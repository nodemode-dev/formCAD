import datetime
import math
import re

from app import __version__
from app.ecadout import gerber
from app.ecadout import view as V

EXTENSIONS = (".emn", ".emp")


def q(text) -> str:
    s = re.sub(r"[^\x20-\x7e]", "?", str(text))
    s = s.replace('"', "'")
    return '"%s"' % s if (" " in s or not s) else s


def stamp(view) -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y/%m/%d.%H:%M:%S")


def loop_lines(label, verts, ox, oy):
    pts = [(float(v[0]) - ox, float(v[1]) - oy, float(v[2]) if len(v) > 2 else 0.0) for v in verts]
    flat = V.loop_points({"verts": [list(p) for p in pts]})
    ccw = V.area(flat) > 0
    want_ccw = label == 0
    if ccw != want_ccw:
        n = len(pts)
        pts = [(pts[n - 1 - k][0], pts[n - 1 - k][1], -pts[(n - 2 - k) % n][2]) for k in range(n)]
    n = len(pts)
    out = []
    for i in range(n):
        x, y, _ = pts[i]
        incoming = pts[(i - 1) % n][2] if i > 0 else 0.0
        ang = math.degrees(4.0 * math.atan(incoming)) if i > 0 else 0.0
        out.append("%d %s %s %s" % (label, gerber.dec(x), gerber.dec(y), gerber.dec(ang)))
    x, y, _ = pts[0]
    closing = pts[n - 1][2]
    out.append("%d %s %s %s" % (label, gerber.dec(x), gerber.dec(y), gerber.dec(math.degrees(4.0 * math.atan(closing)))))
    return out


def package_name(c):
    return str(c.get("package") or c.get("footprint") or c.get("name") or "BODY")


def part_number(c):
    return str(c.get("part") or c.get("value") or c.get("package") or "NONE")


def body_loop(c):
    if c.get("outline"):
        return [(float(p[0]), float(p[1])) for p in c["outline"]]
    w, d = float(c.get("w", 1.0)), float(c.get("d", 1.0))
    cx, cy = float(c.get("cx", 0.0)), float(c.get("cy", 0.0))
    return [(cx - w / 2, cy - d / 2), (cx + w / 2, cy - d / 2), (cx + w / 2, cy + d / 2), (cx - w / 2, cy + d / 2)]


def board(view: dict) -> str:
    ox, oy = view["origin"]
    lines = [".HEADER", 'BOARD_FILE 3.0 "FormCAD %s" %s 1' % (__version__, stamp(view)), "%s MM" % q(view["name"]), ".END_HEADER", ".BOARD_OUTLINE UNOWNED", gerber.dec(view["thickness"])]
    outer = [lp for lp in view["outline"]["loops"] if lp["outer"]]
    inner = [lp for lp in view["outline"]["loops"] if not lp["outer"]]
    lines += loop_lines(0, outer[0]["verts"], ox, oy)
    for i, lp in enumerate(inner):
        lines += loop_lines(i + 1, lp["verts"], ox, oy)
    lines.append(".END_BOARD_OUTLINE")
    lines.append(".DRILLED_HOLES")
    for p in view["pads"]:
        if p.get("drill"):
            lines.append("%s %s %s %s %s PIN UNOWNED" % (gerber.dec(float(p["drill"])), gerber.dec(float(p["x"]) - ox), gerber.dec(float(p["y"]) - oy), "PTH" if p.get("plated", True) else "NPTH", q(p.get("ref") or "NOREFDES")))
    for v in view["vias"]:
        lines.append("%s %s %s PTH BOARD VIA UNOWNED" % (gerber.dec(float(v["drill"])), gerber.dec(float(v["x"]) - ox), gerber.dec(float(v["y"]) - oy)))
    for h in view["holes"]:
        lines.append("%s %s %s %s BOARD MTG UNOWNED" % (gerber.dec(float(h["d"])), gerber.dec(float(h["x"]) - ox), gerber.dec(float(h["y"]) - oy), "PTH" if h.get("plated") else "NPTH"))
    lines.append(".END_DRILLED_HOLES")
    lines.append(".PLACEMENT")
    for c in view["components"]:
        side = "BOTTOM" if c.get("side", "top") == "bottom" else "TOP"
        lines.append("%s %s %s" % (q(package_name(c)), q(part_number(c)), q(c.get("ref", "U?"))))
        lines.append("%s %s 0 %s %s PLACED" % (gerber.dec(float(c["x"]) - ox), gerber.dec(float(c["y"]) - oy), gerber.dec(float(c.get("rot", 0.0)) % 360.0), side))
    lines.append(".END_PLACEMENT")
    return "\n".join(lines) + "\n"


def library(view: dict) -> str:
    lines = [".HEADER", 'LIBRARY_FILE 3.0 "FormCAD %s" %s 1' % (__version__, stamp(view)), ".END_HEADER"]
    seen = set()
    for c in view["components"]:
        key = (package_name(c), part_number(c))
        if key in seen:
            continue
        seen.add(key)
        lines.append(".ELECTRICAL")
        lines.append("%s %s MM %s" % (q(key[0]), q(key[1]), gerber.dec(float(c.get("h", 1.0)))))
        pts = body_loop(c)
        if V.area(pts) < 0:
            pts = pts[::-1]
        for p in pts + [pts[0]]:
            lines.append("0 %s %s 0" % (gerber.dec(p[0]), gerber.dec(p[1])))
        lines.append(".END_ELECTRICAL")
    return "\n".join(lines) + "\n"
