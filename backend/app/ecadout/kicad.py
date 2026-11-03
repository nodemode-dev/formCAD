import math
import re

from app import __version__
from app.ecadout import view as V

MAX_BYTES = 8 * 1024 * 1024
MAX_NODES = 600000
MAX_DEPTH = 64
MAX_EDGE = 4000
ESCAPE = re.compile(r"\\(.)", re.S)
TOKEN = re.compile(r'\s*(\(|\)|"(?:[^"\\]|\\.)*"|[^\s()"]+)')


class KicadError(ValueError):
    pass


def parse(text: str):
    if len(text) > MAX_BYTES:
        raise KicadError("The file is larger than %d MB." % (MAX_BYTES // (1024 * 1024)))
    stack = [[]]
    count = 0
    for m in TOKEN.finditer(text):
        tok = m.group(1)
        count += 1
        if count > MAX_NODES:
            raise KicadError("The file holds more than %d tokens." % MAX_NODES)
        if tok == "(":
            if len(stack) > MAX_DEPTH:
                raise KicadError("The file nests deeper than %d levels." % MAX_DEPTH)
            stack.append([])
        elif tok == ")":
            if len(stack) < 2:
                raise KicadError("The file has an unmatched closing bracket.")
            done = stack.pop()
            stack[-1].append(done)
        elif tok.startswith('"'):
            stack[-1].append(ESCAPE.sub(lambda e: {"n": "\n", "t": "\t"}.get(e.group(1), e.group(1)), tok[1:-1]) if "\\" in tok else tok[1:-1])
        else:
            stack[-1].append(tok)
    if len(stack) != 1:
        raise KicadError("The file has an unclosed bracket.")
    return stack[0]


def q(text) -> str:
    return '"%s"' % str(text).replace("\\", "\\\\").replace('"', '\\"')


def n(v) -> str:
    s = ("%.6f" % v).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def find(node, head):
    return [c for c in node if isinstance(c, list) and c and c[0] == head]


def first(node, head):
    got = find(node, head)
    return got[0] if got else None


def write_board(view: dict) -> str:
    nets = {}

    def net_id(name):
        if not name:
            return 0
        return nets.setdefault(name, len(nets) + 1)

    body = []
    layer_names = view["layers"]
    for lp in view["outline"]["loops"]:
        verts = lp["verts"]
        for i, a in enumerate(verts):
            b = verts[(i + 1) % len(verts)]
            bulge = a[2] if len(a) > 2 else 0.0
            arc = V.bulge_arc((a[0], a[1]), (b[0], b[1]), bulge) if abs(bulge) > 1e-12 else None
            if arc:
                cx, cy, r, sweep = arc
                ang = math.atan2(a[1] - cy, a[0] - cx) + sweep / 2.0
                mx, my = cx + r * math.cos(ang), cy + r * math.sin(ang)
                body.append("(gr_arc (start %s %s) (mid %s %s) (end %s %s) (stroke (width 0.1) (type default)) (layer \"Edge.Cuts\"))" % (n(a[0]), n(-a[1]), n(mx), n(-my), n(b[0]), n(-b[1])))
            else:
                body.append("(gr_line (start %s %s) (end %s %s) (stroke (width 0.1) (type default)) (layer \"Edge.Cuts\"))" % (n(a[0]), n(-a[1]), n(b[0]), n(-b[1])))
    for t in view["tracks"]:
        pts = t["pts"]
        for i in range(len(pts) - 1):
            body.append("(segment (start %s %s) (end %s %s) (width %s) (layer %s) (net %d))" % (n(pts[i][0]), n(-pts[i][1]), n(pts[i + 1][0]), n(-pts[i + 1][1]), n(t["width"]), q(t["layer"]), net_id(t.get("net"))))
    for v in view["vias"]:
        body.append("(via (at %s %s) (size %s) (drill %s) (layers %s %s) (net %d))" % (n(v["x"]), n(-v["y"]), n(v["dia"]), n(v["drill"]), q(v.get("from", "F.Cu")), q(v.get("to", "B.Cu")), net_id(v.get("net"))))
    by_ref = {}
    for p in view["pads"]:
        by_ref.setdefault(p.get("ref") or "", []).append(p)
    for ref, pads in by_ref.items():
        if not ref:
            continue
        bottom = pads[0].get("side") == "bottom" and not pads[0].get("drill")
        lines = ["(footprint %s (layer %s) (at 0 0) (property \"Reference\" %s (at 0 0) (layer \"F.SilkS\") (effects (font (size 1 1) (thickness 0.15))))" % (q(ref), q("B.Cu" if bottom else "F.Cu"), q(ref))]
        for p in pads:
            kind = "thru_hole" if p.get("drill") else "smd"
            shape = {"circle": "circle", "rect": "rect", "roundrect": "roundrect", "oval": "oval"}.get(p.get("shape"), "rect")
            ls = " ".join(q(x) for x in (p["layers"] + (["B.Mask"] if bottom else ["F.Mask"])))
            if p.get("drill"):
                ls = "\"*.Cu\" \"*.Mask\""
            drill = " (drill %s)" % n(p["drill"]) if p.get("drill") else ""
            lines.append("(pad %s %s %s (at %s %s %s) (size %s %s)%s (layers %s) (net %d %s))" % (q(p.get("num", "")), kind if p.get("plated", True) or not p.get("drill") else "np_thru_hole", shape, n(p["x"]), n(-p["y"]), n(p.get("rot", 0.0)), n(p["w"]), n(p["h"]), drill, ls, net_id(p.get("net")), q(p.get("net", ""))))
        body.append("\n".join(lines) + ")")
    head = ["(kicad_pcb (version 20240108) (generator \"formcad\") (generator_version %s)" % q(__version__), "(general (thickness %s))" % n(view["thickness"]), "(paper \"A3\")"]
    layers = ["(0 \"F.Cu\" signal)"] + ["(%d \"%s\" signal)" % (i, nm) for i, nm in enumerate(layer_names[1:-1], start=1)] + ["(31 \"B.Cu\" signal)", "(44 \"Edge.Cuts\" user)"]
    head.append("(layers %s)" % " ".join(layers))
    head.append("(net 0 \"\")")
    for name, i in nets.items():
        head.append("(net %d %s)" % (i, q(name)))
    return "\n".join(head + body) + ")\n"


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        raise KicadError("A coordinate is not a number.")


def xy(node):
    return num(node[1]), -num(node[2])


def read_board(text: str) -> dict:
    try:
        return read_tree(text)
    except (TypeError, IndexError, ValueError, OverflowError, AttributeError) as err:
        if isinstance(err, KicadError):
            raise
        raise KicadError("The board file is malformed: a node is missing or holds a bad value.")


def read_tree(text: str) -> dict:
    root = parse(text)
    if not root or not isinstance(root[0], list) or not root[0] or root[0][0] != "kicad_pcb":
        raise KicadError("This is not a board file in the .kicad_pcb format.")
    pcb = root[0]
    nets = {0: ""}
    for nd in find(pcb, "net"):
        if len(nd) >= 3:
            nets[int(num(nd[1]))] = str(nd[2])
    segs = []
    for nd in find(pcb, "gr_line") + find(pcb, "gr_arc") + find(pcb, "gr_rect") + find(pcb, "gr_circle") + find(pcb, "gr_poly"):
        lyr = first(nd, "layer")
        if not lyr or lyr[1] != "Edge.Cuts":
            continue
        if nd[0] == "gr_line":
            segs.append(("line", xy(first(nd, "start")), xy(first(nd, "end"))))
        elif nd[0] == "gr_arc":
            segs.append(("arc", xy(first(nd, "start")), xy(first(nd, "mid")), xy(first(nd, "end"))))
        elif nd[0] == "gr_rect":
            a, b = xy(first(nd, "start")), xy(first(nd, "end"))
            pts = [a, (b[0], a[1]), b, (a[0], b[1])]
            for i in range(4):
                segs.append(("line", pts[i], pts[(i + 1) % 4]))
        elif nd[0] == "gr_circle":
            c, e = xy(first(nd, "center")), xy(first(nd, "end"))
            r = math.hypot(e[0] - c[0], e[1] - c[1])
            segs.append(("circle", c, r))
        elif nd[0] == "gr_poly":
            pts = [xy(p) for p in find(first(nd, "pts"), "xy")]
            for i in range(len(pts)):
                segs.append(("line", pts[i], pts[(i + 1) % len(pts)]))
    if len(segs) > MAX_EDGE:
        raise KicadError("The board edge has %d segments; the limit is %d." % (len(segs), MAX_EDGE))
    tracks = []
    for nd in find(pcb, "segment"):
        tracks.append({"net": nets.get(int(num(first(nd, "net")[1])), ""), "layer": first(nd, "layer")[1], "width": num(first(nd, "width")[1]), "a": list(xy(first(nd, "start"))), "b": list(xy(first(nd, "end")))})
    vias = []
    for nd in find(pcb, "via"):
        at = xy(first(nd, "at"))
        ls = first(nd, "layers")
        vias.append({"net": nets.get(int(num(first(nd, "net")[1])), ""), "x": at[0], "y": at[1], "dia": num(first(nd, "size")[1]), "drill": num(first(nd, "drill")[1]), "from": ls[1] if ls and len(ls) > 1 else "F.Cu", "to": ls[2] if ls and len(ls) > 2 else "B.Cu"})
    return {"edge": segs, "tracks": tracks, "vias": vias, "footprints": len(find(pcb, "footprint"))}


def chain(segs):
    loops = []
    circles = []
    pool = [s for s in segs if s[0] != "circle"]
    circles = [s for s in segs if s[0] == "circle"]
    eps = 1e-3

    def ends(s):
        return (s[1], s[-1])

    used = [False] * len(pool)
    index = {}
    for j, s in enumerate(pool):
        for end, flag in ((ends(s)[0], False), (ends(s)[1], True)):
            index.setdefault((round(end[0] / eps), round(end[1] / eps)), []).append((j, flag))

    def find_next(cur):
        kx, ky = round(cur[0] / eps), round(cur[1] / eps)
        best = None
        for gx in (kx - 1, kx, kx + 1):
            for gy in (ky - 1, ky, ky + 1):
                for j, flag in index.get((gx, gy), ()):
                    if used[j]:
                        continue
                    e = ends(pool[j])[1 if flag else 0]
                    if math.hypot(e[0] - cur[0], e[1] - cur[1]) <= eps and (best is None or (j, flag) < (best[0], best[2])):
                        best = (j, pool[j], flag)
        return best

    for i0 in range(len(pool)):
        if used[i0]:
            continue
        used[i0] = True
        run = [pool[i0]]
        start = ends(pool[i0])[0]
        cur = ends(pool[i0])[1]
        guard = 0
        while math.hypot(cur[0] - start[0], cur[1] - start[1]) > eps and guard < len(pool) + 2:
            guard += 1
            hit = find_next(cur)
            if hit is None:
                raise KicadError("The board edge is not a closed loop.")
            used[hit[0]] = True
            s = hit[1]
            if hit[2]:
                s = (s[0],) + tuple(reversed(s[1:])) if s[0] == "line" else ("arc", s[3], s[2], s[1])
            run.append(s)
            cur = ends(s)[1]
        loops.append(run)
    return loops, circles


def loops_to_verts(run):
    verts = []
    for s in run:
        if s[0] == "line":
            verts.append([s[1][0], s[1][1], 0.0])
        else:
            geo = V.arc_through(s[1], s[2], s[3])
            if geo is None:
                verts.append([s[1][0], s[1][1], 0.0])
                continue
            cx, cy, r, ccw = geo
            a0 = math.atan2(s[1][1] - cy, s[1][0] - cx)
            a1 = math.atan2(s[3][1] - cy, s[3][0] - cx)
            sweep = (a1 - a0) % (2 * math.pi) if ccw else -((a0 - a1) % (2 * math.pi))
            verts.append([s[1][0], s[1][1], math.tan(sweep / 4.0)])
    return verts
