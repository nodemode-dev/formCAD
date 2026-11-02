import copy
import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity, pick_point, with_jig
from app.cmd.registry import command, executes
from app.doc import geom, tables as T
from app.doc.kinds import mline as ML
from app.doc.kinds.mline import MLine
from app.sysvars import registry as sv

JUST_NAMES = ("Top", "Zero", "Bottom")
BAD_NAME_CHARS = '<>/\\":;?*|,=`'
MAX_ELEMENTS = 16
TOOLS = ("CC", "OC", "MC", "CT", "OT", "MT", "CJ", "AV", "DV", "CS", "CA", "WA")
TOL = 1e-6


def style_key(name: str) -> str:
    return str(name).strip().upper()


def valid_name(name: str) -> bool:
    n = str(name).strip()
    return 0 < len(n) <= 31 and not any(c in BAD_NAME_CHARS for c in n)


def get_style(ctx, name):
    return ctx.d.table_get("mlinestyles", style_key(name))


def current_style(ctx) -> dict:
    rec = get_style(ctx, str(ctx.var("CMLSTYLE")))
    if rec is None:
        rec = get_style(ctx, "STANDARD")
    return rec


def styles_in_use(ctx) -> set:
    out = set()
    for e in ctx.d.ents.values():
        if e.kind == "mline":
            out.add(style_key(e.style))
    return out


def parse_color_value(value):
    try:
        return sv.parse_color(value)
    except Exception:
        raise CommandError("Invalid colour: %s" % value)


def clean_style(rec: dict, ctx) -> dict:
    els = rec.get("elements") or []
    if not 1 <= len(els) <= MAX_ELEMENTS:
        raise CommandError("A multiline style holds 1 to %d elements." % MAX_ELEMENTS)
    out_els = []
    for e in els:
        off = float(e.get("offset", 0.0))
        if not math.isfinite(off):
            raise CommandError("Invalid element offset.")
        lt = str(e.get("linetype", "BYLAYER") or "BYLAYER")
        if lt.upper() not in ("BYLAYER", "BYBLOCK") and ctx.d.table_get("linetypes", lt) is None:
            raise CommandError("Linetype %s is not loaded." % lt)
        out_els.append({"offset": off, "color": parse_color_value(e.get("color", 256)), "linetype": lt if lt.upper() not in ("BYLAYER", "BYBLOCK") else lt.upper()})
    out_els.sort(key=lambda e: -e["offset"])
    caps = {}
    for key in ("start_cap", "end_cap"):
        c = rec.get(key) or {}
        ang = float(c.get("angle", 90.0))
        if not 10.0 <= ang <= 170.0:
            raise CommandError("The cap angle must be from 10 to 170 degrees.")
        caps[key] = {"line": bool(c.get("line")), "outer_arc": bool(c.get("outer_arc")), "inner_arcs": bool(c.get("inner_arcs")), "angle": ang}
    fill = rec.get("fill")
    fill = None if fill in (None, "", "none", "None") else parse_color_value(fill)
    return {"name": rec["name"], "description": str(rec.get("description", "")), "elements": out_els, "start_cap": caps["start_cap"], "end_cap": caps["end_cap"], "joints": bool(rec.get("joints")), "fill": fill}


def summary(rec: dict) -> str:
    return "%s - %s (%d elements)" % (rec["name"], rec.get("description") or "no description", len(rec["elements"]))


def refuse_unusable(ctx, rec, verb):
    nm = rec["name"]
    if style_key(nm) == "STANDARD":
        raise CommandError("The STANDARD style cannot be %s." % verb)
    if style_key(nm) == style_key(str(ctx.var("CMLSTYLE"))):
        raise CommandError("The current style cannot be %s." % verb)
    if style_key(nm) in styles_in_use(ctx):
        raise CommandError("Style %s is used by existing multilines and cannot be %s." % (nm, verb))


def style_action(ctx, action, a) -> dict:
    d = ctx.d
    if action == "list":
        return {"styles": [r["name"] for r in d.tables["mlinestyles"].values()], "current": str(ctx.var("CMLSTYLE"))}
    name = str(a.get("name", "")).strip()
    if action in ("create", "new"):
        if not valid_name(name):
            raise CommandError("Invalid style name: up to 31 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if get_style(ctx, name) is not None:
            raise CommandError("Style %s already exists." % name)
        base = {"name": style_key(name), "description": a.get("description", ""), "elements": a.get("elements") or T.new_mlinestyle()["elements"], "start_cap": a.get("start_cap"), "end_cap": a.get("end_cap"), "joints": a.get("joints", False), "fill": a.get("fill")}
        rec = clean_style(base, ctx)
        d.table_set("mlinestyles", rec)
        if a.get("current", True):
            ctx.setvar("CMLSTYLE", rec["name"])
        return {"style": rec}
    rec0 = get_style(ctx, name)
    if rec0 is None:
        raise CommandError("Style %s does not exist." % name)
    if action == "current":
        ctx.setvar("CMLSTYLE", rec0["name"])
        return {"style": rec0}
    if action == "modify":
        new = copy.deepcopy(rec0)
        for k in ("description", "joints", "fill", "start_cap", "end_cap"):
            if k in a:
                new[k] = a[k]
        if "elements" in a:
            if style_key(name) in styles_in_use(ctx):
                raise CommandError("Style %s is in use and its elements cannot be changed." % rec0["name"])
            new["elements"] = a["elements"]
        rec = clean_style(new, ctx)
        d.table_set("mlinestyles", rec)
        return {"style": rec}
    if action == "copy":
        to = str(a.get("to", "")).strip()
        if not valid_name(to):
            raise CommandError("Invalid style name: up to 31 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if get_style(ctx, to) is not None:
            raise CommandError("Style %s already exists." % to)
        rec = copy.deepcopy(rec0)
        rec["name"] = style_key(to)
        d.table_set("mlinestyles", rec)
        return {"style": rec}
    if action == "rename":
        to = str(a.get("to", "")).strip()
        refuse_unusable(ctx, rec0, "renamed")
        if not valid_name(to):
            raise CommandError("Invalid style name: up to 31 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if get_style(ctx, to) is not None:
            raise CommandError("Style %s already exists." % to)
        rec = copy.deepcopy(rec0)
        rec["name"] = style_key(to)
        d.table_remove("mlinestyles", rec0["name"])
        d.table_set("mlinestyles", rec)
        return {"style": rec}
    if action == "delete":
        refuse_unusable(ctx, rec0, "deleted")
        d.table_remove("mlinestyles", rec0["name"])
        return {"deleted": rec0["name"]}
    raise CommandError("Unknown MLSTYLE action: %s." % action)


def _ask_name(ctx, msg, default=None):
    r = yield ctx.word(msg, default=default)
    if r.kind == "enter":
        return default
    if r.kind not in ("text",):
        return None
    return str(r.value).strip()


def _ask_yes(ctx, msg, default):
    r = yield ctx.yesno(msg, "Yes" if default else "No")
    if r.kind == "keyword":
        return r.value == "Yes"
    return default


def _ask_cap(ctx, label, cap):
    line = yield from _ask_yes(ctx, "%s cap line?" % label, cap["line"])
    outer = yield from _ask_yes(ctx, "%s cap outer arc?" % label, cap["outer_arc"])
    inner = yield from _ask_yes(ctx, "%s cap inner arcs?" % label, cap["inner_arcs"])
    ang = yield ctx.number("Specify %s cap angle" % label.lower(), default=cap["angle"], minimum=10, maximum=170)
    return {"line": line, "outer_arc": outer, "inner_arcs": inner, "angle": cap["angle"] if ang.kind == "enter" else float(ang.value)}


def _ask_elements(ctx, existing):
    els = []
    while len(els) < MAX_ELEMENTS:
        first = not els
        base = existing[len(els)] if existing and len(els) < len(existing) else None
        o = yield ctx.number("Specify element offset" + ("" if first else " (Enter when done)"), default=base["offset"] if base else None)
        if o.kind == "enter":
            if not first:
                break
            continue
        if o.kind != "number":
            return None
        col = yield ctx.word("Specify element color (index, name or BYLAYER)", default=str(base["color"]) if base else "BYLAYER")
        lt = yield ctx.word("Specify element linetype", default=base["linetype"] if base else "BYLAYER")
        els.append({"offset": float(o.value), "color": col.value if col.kind == "text" else (base["color"] if base else 256), "linetype": lt.value if lt.kind == "text" else (base["linetype"] if base else "BYLAYER")})
    return els


@command("mlstyle", group="format", label="Multiline Style...", description="Create, modify, rename, delete multiline styles.", menu="Format > Multiline Style...")
def mlstyle(ctx):
    r = yield ctx.keyword("Enter an option", ["?", "Current", "New", "Modify", "Copy", "Rename", "Delete"], "?")
    if r.kind == "enter":
        r.value = "?"
    elif r.kind != "keyword":
        return
    act = r.value
    if act == "?":
        for rec in ctx.d.tables["mlinestyles"].values():
            ctx.say(summary(rec) + ("  (current)" if style_key(rec["name"]) == style_key(str(ctx.var("CMLSTYLE"))) else ""))
        return
    if act in ("Current", "Modify", "Copy", "Rename", "Delete"):
        name = yield from _ask_name(ctx, "Enter style name", str(ctx.var("CMLSTYLE")))
        if not name:
            return
        if get_style(ctx, name) is None:
            raise CommandError("Style %s does not exist." % name)
        if act == "Current":
            style_action(ctx, "current", {"name": name})
            return
        if act in ("Copy", "Rename"):
            to = yield from _ask_name(ctx, "Enter new style name")
            if not to:
                return
            style_action(ctx, act.lower(), {"name": name, "to": to})
            return
        if act == "Delete":
            style_action(ctx, "delete", {"name": name})
            return
        rec = copy.deepcopy(get_style(ctx, name))
        used = style_key(name) in styles_in_use(ctx)
    else:
        name = yield from _ask_name(ctx, "Enter name for new style")
        if not name:
            return
        if not valid_name(name):
            raise CommandError("Invalid style name: up to 31 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if get_style(ctx, name) is not None:
            raise CommandError("Style %s already exists." % name)
        rec = T.new_mlinestyle(style_key(name))
        used = False
    desc = yield from _ask_name(ctx, "Enter description", rec.get("description", ""))
    args = {"name": name, "description": desc if desc is not None else ""}
    change = True
    if act == "Modify":
        change = yield from _ask_yes(ctx, "Change elements?", False)
        if change and used:
            raise CommandError("Style %s is in use and its elements cannot be changed." % rec["name"])
    if change:
        els = yield from _ask_elements(ctx, rec["elements"] if act == "Modify" else None)
        if els is None:
            return
        args["elements"] = els
    args["start_cap"] = yield from _ask_cap(ctx, "Start", rec["start_cap"])
    args["end_cap"] = yield from _ask_cap(ctx, "End", rec["end_cap"])
    args["joints"] = yield from _ask_yes(ctx, "Display joints?", rec["joints"])
    fl = yield from _ask_name(ctx, "Specify fill color (None for no fill)", "None" if rec["fill"] is None else str(rec["fill"]))
    args["fill"] = fl
    style_action(ctx, "modify" if act == "Modify" else "create", args)
    ctx.say("Multiline style %s %s." % (style_key(name), "modified" if act == "Modify" else "created and made current"))


@executes("mlstyle")
def mlstyle_exec(ctx, args):
    return style_action(ctx, str(args.get("action", "list")).lower(), args)


def mline_shapes(ent) -> list:
    out = []
    for runs in ML.element_runs(ent):
        for run in runs:
            if len(run["pts"]) >= 2:
                out.append(jig.poly([[p[0], p[1], 0.0] for p in run["pts"]], run["closed"]))
    for kind, a, b, sign in ML.cap_shapes(ent):
        out.append(jig.poly([[a[0], a[1], sign if kind == "arc" else 0.0], [b[0], b[1], 0.0]]))
    for a, b in ML.joint_lines(ent):
        out.append(jig.line(a, b))
    return out


def new_mline(ctx, pts, closed, scale, just, style_name) -> MLine:
    rec = get_style(ctx, style_name)
    if rec is None:
        raise CommandError("Style %s does not exist." % style_name)
    clean = []
    for p in pts:
        if not clean or geom.dist(p, clean[-1]) > ctx.d.tolerances["absolute"]:
            clean.append([float(p[0]), float(p[1])])
    if len(clean) < 2:
        raise CommandError("A multiline needs at least two distinct points.")
    if closed and len(clean) < 3:
        raise CommandError("A closed multiline needs at least three points.")
    if closed and geom.dist(clean[0], clean[-1]) <= ctx.d.tolerances["absolute"]:
        clean.pop()
    if scale == 0 or not math.isfinite(scale):
        raise CommandError("The multiline scale must not be zero.")
    return MLine(style=rec["name"], style_def=copy.deepcopy(rec), scale=float(scale), justification=int(just), closed=bool(closed), vertices=[{"p": p, "cuts": []} for p in clean])


def _preview_mline(ctx, pts, closed, scale, just, style):
    try:
        return mline_shapes(new_mline(ctx, pts, closed, scale, just, style))
    except CommandError:
        return [jig.line(pts[-2], pts[-1])] if len(pts) >= 2 else []


@command("mline", aliases=("ml",), group="draw", label="Multiline", description="Multiline with justification, scale, style.", menu="Draw > Multiline")
def mline(ctx):
    while True:
        just = int(ctx.var("CMLJUST"))
        scale = float(ctx.var("CMLSCALE"))
        style = current_style(ctx)["name"]
        ctx.say("Current settings: Justification = %s, Scale = %s, Style = %s" % (JUST_NAMES[just], ctx.fd(scale), style))
        r = yield ctx.point("Specify start point", ["Justification", "Scale", "STyle"])
        if r.kind == "keyword":
            if r.value == "Justification":
                j = yield ctx.keyword("Enter justification type", list(JUST_NAMES), JUST_NAMES[just])
                if j.kind == "keyword":
                    ctx.setvar("CMLJUST", JUST_NAMES.index(j.value))
            elif r.value == "Scale":
                s = yield ctx.number("Enter mline scale", default=scale)
                if s.kind == "number":
                    if s.value == 0:
                        ctx.say("The multiline scale must not be zero.")
                    else:
                        ctx.setvar("CMLSCALE", float(s.value))
            else:
                n = yield ctx.word("Enter mline style name", ["?"], style)
                if n.kind == "keyword" or (n.kind == "text" and str(n.value).strip() == "?"):
                    for rec in ctx.d.tables["mlinestyles"].values():
                        ctx.say(summary(rec))
                elif n.kind == "text":
                    rec = get_style(ctx, n.value)
                    if rec is None:
                        ctx.say("Style %s does not exist." % str(n.value).strip().upper())
                    else:
                        ctx.setvar("CMLSTYLE", rec["name"])
            continue
        if r.kind != "point":
            return
        break
    pts = [list(r.value)]
    closed = False
    while True:
        opts = ["Undo"]
        if len(pts) >= 3:
            opts.append("Close")
        n = yield ctx.point("Specify next point", opts, base=pts[-1], jig=lambda p: _preview_mline(ctx, pts + [list(p)], False, scale, just, style))
        if n.kind == "enter":
            break
        if n.kind == "keyword":
            if n.value == "Undo" and len(pts) > 1:
                pts.pop()
            if n.value == "Close":
                closed = True
                break
            continue
        if n.kind != "point":
            return
        if not ctx.same(n.value, pts[-1]):
            pts.append(list(n.value))
    if len(pts) < 2:
        return
    ctx.add(new_mline(ctx, pts, closed, scale, just, style))


def _just_value(v):
    if isinstance(v, str):
        low = v.lower()
        for i, nm in enumerate(JUST_NAMES):
            if nm.lower() == low or (low == "middle" and i == 1):
                return i
        raise CommandError("Justification must be top, zero or bottom.")
    if int(v) not in (0, 1, 2):
        raise CommandError("Justification must be top, zero or bottom.")
    return int(v)


@executes("mline")
def mline_exec(ctx, args):
    pts = [geom.as_pt(p) for p in args.get("points", [])]
    scale = float(args.get("scale", ctx.var("CMLSCALE")))
    just = _just_value(args.get("justification", ctx.var("CMLJUST")))
    style = args.get("style") or current_style(ctx)["name"]
    return {"handle": ctx.add(new_mline(ctx, pts, bool(args.get("closed")), scale, just, style))}


def _frame(ent, seg_index):
    dx, dy, length = ML.seg_dirs(ent)[seg_index]
    a = ent.vertices[seg_index]["p"]
    return a, (dx, dy), (-dy, dx), length


def _band(ent):
    lats = [ML.lateral(ent, k) for k in range(len(ent.elements()))]
    return min(lats), max(lats)


def crossing(ent_a, seg_a, ent_b, seg_b):
    a0, da, na, la = _frame(ent_a, seg_a)
    b0, db, nb, lb = _frame(ent_b, seg_b)
    den = da[0] * db[1] - da[1] * db[0]
    if abs(den) < 1e-9:
        raise CommandError("The multilines are parallel.")
    wx, wy = b0[0] - a0[0], b0[1] - a0[1]
    ta = (wx * db[1] - wy * db[0]) / den
    tb = (wx * da[1] - wy * da[0]) / den
    return ta, tb, [a0[0] + da[0] * ta, a0[1] + da[1] * ta]


def band_interval(ent_a, seg_a, ent_b, seg_b, k, ta):
    a0, da, na, la = _frame(ent_a, seg_a)
    b0, db, nb, lb = _frame(ent_b, seg_b)
    lo, hi = _band(ent_b)
    s = da[0] * nb[0] + da[1] * nb[1]
    c = na[0] * nb[0] + na[1] * nb[1]
    lat = ML.lateral(ent_a, k)
    t1 = (lo - lat * c) / s
    t2 = (hi - lat * c) / s
    if t1 > t2:
        t1, t2 = t2, t1
    return max(0.0, ta + t1), min(la, ta + t2)


def add_cut(ent, seg, k, s0, s1):
    if s1 - s0 <= 1e-9:
        return
    cuts = ent.vertices[seg].setdefault("cuts", [])
    if len(cuts) >= ML.MAX_CUTS:
        raise CommandError("Too many cuts on one segment.")
    cuts.append({"element": int(k), "start": float(s0), "end": float(s1)})


def cut_across(ent_a, seg_a, ent_b, seg_b, ta, elements):
    for k in elements:
        s0, s1 = band_interval(ent_a, seg_a, ent_b, seg_b, k, ta)
        add_cut(ent_a, seg_a, k, s0, s1)


def outer_elements(ent):
    n = len(ent.elements())
    return sorted({0, n - 1})


def tool_cross(ctx, tool, ha, pa, hb, pb):
    A, B = _mline(ctx, ha), _mline(ctx, hb)
    if A.handle == B.handle:
        raise CommandError("Select two different multilines.")
    sa = ML.locate(A, pa)[1]
    sb = ML.locate(B, pb)[1]
    ta, tb, X = crossing(A, sa, B, sb)
    la = ML.seg_dirs(A)[sa][2]
    lb = ML.seg_dirs(B)[sb][2]
    if ta < -TOL or ta > la + TOL or tb < -TOL or tb > lb + TOL:
        raise CommandError("The multilines do not cross.")
    a = ctx.d.modify(A.handle)
    b = ctx.d.modify(B.handle)
    all_a = range(len(a.elements()))
    if tool == "CC":
        cut_across(a, sa, b, sb, ta, all_a)
    elif tool == "OC":
        cut_across(a, sa, b, sb, ta, all_a)
        cut_across(b, sb, a, sa, tb, outer_elements(b))
    else:
        cut_across(a, sa, b, sb, ta, outer_elements(a))
        cut_across(b, sb, a, sa, tb, outer_elements(b))
    return [a.handle, b.handle]


def _end_vertex(ent, pt):
    n = len(ent.vertices)
    d0 = geom.dist(ent.vertices[0]["p"], pt)
    d1 = geom.dist(ent.vertices[-1]["p"], pt)
    return (0, 0) if d0 <= d1 else (n - 1, n - 2)


def tool_tee(ctx, tool, ha, pa, hb, pb):
    A, B = _mline(ctx, ha), _mline(ctx, hb)
    if A.handle == B.handle:
        raise CommandError("Select two different multilines.")
    if A.closed:
        raise CommandError("The first multiline must be open.")
    vi, oi = _end_vertex(A, pa)
    seg_a = 0 if vi == 0 else len(A.vertices) - 2
    sb = ML.locate(B, pb)[1]
    ta, tb, X = crossing(A, seg_a, B, sb)
    a0, da, na, la = _frame(A, seg_a)
    b0, db, nb, lb = _frame(B, sb)
    if tb < -TOL or tb > lb + TOL:
        raise CommandError("The multilines do not meet.")
    body = A.vertices[oi]["p"]
    side = (body[0] - X[0]) * nb[0] + (body[1] - X[1]) * nb[1]
    lo, hi = _band(B)
    edge = hi if side > 0 else lo
    s = da[0] * nb[0] + da[1] * nb[1]
    t_edge = 0.0 if tool == "MT" else edge / s
    new_end = [X[0] + da[0] * t_edge, X[1] + da[1] * t_edge]
    a = ctx.d.modify(A.handle)
    a.vertices[vi]["p"] = new_end
    a.vertices[seg_a]["cuts"] = []
    b = ctx.d.modify(B.handle)
    if tool in ("OT", "MT"):
        lats = [ML.lateral(b, k) for k in range(len(b.elements()))]
        near = max(range(len(lats)), key=lambda k: lats[k] if side > 0 else -lats[k])
        s0, s1 = band_interval(b, sb, a, seg_a, near, tb)
        add_cut(b, sb, near, s0, s1)
    return [a.handle, b.handle]


def tool_corner(ctx, ha, pa, hb, pb):
    A, B = _mline(ctx, ha), _mline(ctx, hb)
    if A.handle == B.handle:
        raise CommandError("Select two different multilines.")
    if A.closed or B.closed:
        raise CommandError("Corner joints need open multilines.")
    va, _ = _end_vertex(A, pa)
    vb, _ = _end_vertex(B, pb)
    sa = 0 if va == 0 else len(A.vertices) - 2
    sb = 0 if vb == 0 else len(B.vertices) - 2
    ta, tb, X = crossing(A, sa, B, sb)
    ctx.d.modify(A.handle).vertices[va]["p"] = [X[0], X[1]]
    ctx.d.modify(B.handle).vertices[vb]["p"] = [X[0], X[1]]
    return [A.handle, B.handle]


def tool_add_vertex(ctx, h, pt):
    M = _mline(ctx, h)
    d, seg, tc, q, pos = ML.locate(M, pt)
    length = ML.seg_dirs(M)[seg][2]
    if tc <= max(1e-9, 1e-6 * length) or tc >= length - max(1e-9, 1e-6 * length):
        raise CommandError("A vertex already exists there.")
    m = ctx.d.modify(h)
    old = m.vertices[seg]
    keep, move = [], []
    for c in old.get("cuts", []):
        s0, s1 = float(c["start"]), float(c["end"])
        if s0 < tc:
            keep.append({"element": c["element"], "start": s0, "end": min(s1, tc)})
        if s1 > tc:
            move.append({"element": c["element"], "start": max(s0, tc) - tc, "end": s1 - tc})
    old["cuts"] = keep
    m.vertices.insert(seg + 1, {"p": [q[0], q[1]], "cuts": move})
    return [h]


def tool_delete_vertex(ctx, h, pt):
    M = _mline(ctx, h)
    n = len(M.vertices)
    if n <= 2 or (M.closed and n <= 3):
        raise CommandError("The multiline has too few vertices to delete one.")
    best = min(range(n), key=lambda i: geom.dist(M.vertices[i]["p"], pt))
    m = ctx.d.modify(h)
    segs = m.segment_count()
    for s in (best, (best - 1) % segs if (m.closed or best > 0) else None):
        if s is not None and s < len(m.vertices):
            m.vertices[s]["cuts"] = []
    m.vertices.pop(best)
    return [h]


def _span_cuts(M, s_a, s_b):
    out = []
    pos = 0.0
    for i, (dx, dy, length) in enumerate(ML.seg_dirs(M)):
        lo, hi = max(s_a, pos), min(s_b, pos + length)
        if hi - lo > 1e-9:
            out.append((i, lo - pos, hi - pos))
        pos += length
    return out


def tool_cut(ctx, tool, h, p1, p2):
    M = _mline(ctx, h)
    l1, l2 = ML.locate(M, p1), ML.locate(M, p2)
    if abs(l1[4] - l2[4]) <= 1e-9:
        raise CommandError("The two points coincide.")
    s_a, s_b = sorted((l1[4], l2[4]))
    m = ctx.d.modify(h)
    elements = range(len(m.elements()))
    if tool == "CS":
        _, seg, tc, q, _pos = l1
        a, d, n, length = _frame(m, seg)
        lat = (p1[0] - q[0]) * n[0] + (p1[1] - q[1]) * n[1]
        elements = [min(elements, key=lambda k: abs(ML.lateral(m, k) - lat))]
    for seg, c0, c1 in _span_cuts(m, s_a, s_b):
        for k in elements:
            add_cut(m, seg, k, c0, c1)
    return [h]


def tool_weld(ctx, h, p1, p2):
    M = _mline(ctx, h)
    l1, l2 = ML.locate(M, p1), ML.locate(M, p2)
    m = ctx.d.modify(h)
    s_a, s_b = sorted((l1[4], l2[4]))
    spans = {seg: (c0, c1) for seg, c0, c1 in _span_cuts(m, s_a, s_b)}
    for seg, (c0, c1) in spans.items():
        out = []
        for c in m.vertices[seg].get("cuts", []):
            s0, s1 = float(c["start"]), float(c["end"])
            if s1 <= c0 or s0 >= c1:
                out.append(c)
                continue
            if s0 < c0:
                out.append({"element": c["element"], "start": s0, "end": c0})
            if s1 > c1:
                out.append({"element": c["element"], "start": c1, "end": s1})
        m.vertices[seg]["cuts"] = out
    return [h]


def _mline(ctx, handle):
    e = ctx.d.get(int(handle)) if handle is not None else None
    if e is None or e.kind != "mline":
        raise CommandError("Select a multiline.")
    return e


def run_tool(ctx, tool, a) -> list:
    tool = tool.upper()
    if tool in ("CC", "OC", "MC"):
        return tool_cross(ctx, tool, a["first"]["handle"], a["first"]["point"], a["second"]["handle"], a["second"]["point"])
    if tool in ("CT", "OT", "MT"):
        return tool_tee(ctx, tool, a["first"]["handle"], a["first"]["point"], a["second"]["handle"], a["second"]["point"])
    if tool == "CJ":
        return tool_corner(ctx, a["first"]["handle"], a["first"]["point"], a["second"]["handle"], a["second"]["point"])
    if tool == "AV":
        return tool_add_vertex(ctx, a["mline"], a["point"])
    if tool == "DV":
        return tool_delete_vertex(ctx, a["mline"], a["point"])
    if tool in ("CS", "CA"):
        return tool_cut(ctx, tool, a["mline"], a["p1"], a["p2"])
    if tool == "WA":
        return tool_weld(ctx, a["mline"], a["p1"], a["p2"])
    raise CommandError("Unknown multiline editing tool: %s." % tool)


def mledit_exec(ctx, args):
    tool = str(args.get("tool", "")).upper()
    if tool not in TOOLS:
        raise CommandError("Unknown multiline editing tool: %s." % tool)
    a = dict(args)
    for key in ("first", "second"):
        if key in a and isinstance(a[key], dict):
            a[key] = {"handle": a[key].get("handle"), "point": geom.as_pt(a[key].get("point", [0, 0]))}
    for key in ("point", "p1", "p2"):
        if key in a:
            a[key] = geom.as_pt(a[key])
    return {"handles": run_tool(ctx, tool, a)}


def _nearest_mline(ctx, p):
    best, bd = None, None
    for e in ctx.visible_entities():
        if e.kind != "mline":
            continue
        d = ML.locate(e, p)[0]
        if bd is None or d < bd:
            best, bd = e, d
    return best


def _outline_jig(ctx):
    def fn(p):
        e = _nearest_mline(ctx, p)
        return mline_shapes(e) if e is not None else []

    return fn


def _pick_mline(ctx, msg, undo=False):
    while True:
        r = yield with_jig(ctx.entity(msg, ["Undo"] if undo else []), _outline_jig(ctx))
        if r.kind == "keyword":
            return "undo"
        if r.kind != "entity":
            return None
        ent = pick_entity(ctx, r.value)
        if ent is None or ent.kind != "mline":
            ctx.say("Select a multiline.")
            continue
        return {"handle": ent.handle, "point": pick_point(r.value)}


@command("mledit", aliases=("-mledit",), group="modify", label="Multiline...", description="Edit multilines: crosses, tees, corners, vertices, cuts, welds.", menu="Modify > Object > Multiline...")
def mledit(ctx):
    while True:
        r = yield ctx.keyword("Enter mline editing option", list(TOOLS))
        if r.kind != "keyword":
            return
        tool = r.value
        a = {}
        if tool in ("CC", "OC", "MC", "CT", "OT", "MT", "CJ"):
            while True:
                f = yield from _pick_mline(ctx, "Select first mline")
                if f is None:
                    return
                if f == "undo":
                    continue
                s = yield from _pick_mline(ctx, "Select second mline", True)
                if s is None:
                    return
                if s == "undo":
                    continue
                a["first"], a["second"] = f, s
                break
        else:
            f = yield from _pick_mline(ctx, "Select mline")
            if f is None:
                return
            a["mline"], a["point"] = f["handle"], f["point"]
            if tool in ("CS", "CA", "WA"):
                a["p1"] = f["point"]
                M = ctx.d.get(f["handle"])

                def shape(p, M=M, p1=f["point"]):
                    return [jig.line(p1, p)] + mline_shapes(M)

                s = yield ctx.point("Select second point", base=a["p1"], jig=shape)
                if s.kind != "point":
                    return
                a["p2"] = s.value
        try:
            run_tool(ctx, tool, a)
        except CommandError as err:
            ctx.say(str(err))


executes("mledit")(mledit_exec)
