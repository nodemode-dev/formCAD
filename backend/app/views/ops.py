import copy
import math
import re

from app.doc import layouts
from app.doc.kinds.drawview import DrawView
from app.views import build, model, sources
from app.views.model import ViewError

MAX_VIEWS = 2000
GAP_MM = 15.0
CHILD_TYPES = ("projected", "auxiliary", "section")
REBUILD_KEYS = {"vnormal", "vup", "mode", "source", "section", "detail", "crop", "broken", "origin"}


def views_of(d, layout: str = "") -> list:
    out = [e for e in d.ents.values() if e.kind == "drawview"]
    if layout:
        space = "layout:" + layout
        out = [e for e in out if e.owner == space]
    return out


def get(d, handle) -> DrawView:
    try:
        e = d.ents.get(int(handle))
    except (TypeError, ValueError):
        e = None
    if e is None or e.kind != "drawview":
        raise ViewError("There is no drawing view with handle %s." % handle)
    return e


def find(d, ident) -> DrawView:
    text = str(ident).strip()
    if text.isdigit() and int(text) in d.ents:
        return get(d, text)
    for e in views_of(d):
        if e.name.casefold() == text.casefold():
            return e
    raise ViewError("There is no drawing view %s." % text)


def children(d, handle: int) -> list:
    return [e for e in views_of(d) if e.parent == handle]


def next_name(d) -> str:
    used = {e.name.casefold() for e in views_of(d)}
    i = 1
    while ("v%d" % i) in used:
        i += 1
    return "V%d" % i


def layout_rec(d, layout: str):
    rec = layouts.find(d, layout)
    if rec is None:
        raise ViewError('Layout "%s" not found.' % layout)
    return rec


def layout_unit(d, layout: str) -> float:
    rec = layout_rec(d, layout)
    return layouts.unit_mm(d, layouts.normalize(d, rec.get("page_setup")))


def printable_centre(d, layout: str) -> list:
    rec = layout_rec(d, layout)
    ps = layouts.normalize(d, rec.get("page_setup"))
    box = layouts.printable_units(d, ps)
    return [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0]


def parse_scale(value, fallback: float):
    if value in (None, ""):
        return fallback, layouts.scale_text_of(fallback)
    try:
        v = layouts.parse_plot_scale(value)
    except layouts.LayoutError as err:
        raise ViewError(str(err))
    text = str(value).strip() if isinstance(value, str) else layouts.scale_text_of(v)
    return v, text


def centre_of(view) -> list:
    b = view.bounds()
    return [(b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0]


def set_centre(view, centre) -> None:
    c = centre_of(view)
    view.position = [view.position[0] + centre[0] - c[0], view.position[1] + centre[1] - c[1]]


def clean_show(show) -> dict:
    out = dict(model.DEFAULT_SHOW)
    for k, v in (show or {}).items():
        if k not in model.DEFAULT_SHOW:
            raise ViewError("Unknown view option %s." % k)
        out[k] = bool(v)
    return out


def clean_style(style) -> dict:
    out = {}
    for cls, spec in (style or {}).items():
        if cls not in model.CLASSES:
            raise ViewError("Unknown edge class %s." % cls)
        row = {}
        for k in ("layer", "linetype", "lineweight", "color"):
            if spec.get(k) not in (None, ""):
                row[k] = spec[k]
        if row:
            out[cls] = row
    return out


def clean_mode(mode) -> str:
    m = str(mode or "auto").lower()
    if m not in model.MODES:
        raise ViewError("The hidden line mode is exact, draft or auto.")
    return m


def clean_label(text) -> str:
    return re.sub(r"[\x00-\x1f]", " ", str(text or "")).strip()[:120]


def direction_of(args: dict):
    if args.get("vnormal") is not None:
        return model.unit(args["vnormal"]), model.unit(args.get("vup") or [0, 0, 1])
    return model.standard_direction(args.get("direction") or "front")


def add_view(doc, layout: str, view: DrawView) -> int:
    d = doc.drawing
    if len(views_of(d)) >= MAX_VIEWS:
        raise ViewError("The drawing already has %d views." % MAX_VIEWS)
    model.ensure_layers(d)
    view.layer = model.LAYER_VIEWS
    view.name = view.name or next_name(d)
    view.unit_mm = layout_unit(d, layout)
    return d.add_entity(view, "layout:" + layout)


def create_base(doc, args: dict) -> int:
    d = doc.drawing
    layout = str(args.get("layout") or "")
    if not layout and str(doc.tab).startswith("layout:"):
        layout = str(doc.tab)[7:]
    if not layout:
        raise ViewError("Say which layout the view goes on.")
    layout_rec(d, layout)
    flat = bool(args.get("flat", False))
    normal, up = ([0.0, 0.0, 1.0], [0.0, 1.0, 0.0]) if flat else direction_of(args)
    scale, text = parse_scale(args.get("scale"), 1.0)
    src = {"doc": str((args.get("source") or {}).get("doc", "")), "component": str((args.get("source") or {}).get("component", "")), "config": str((args.get("source") or {}).get("config", ""))}
    if args.get("component") not in (None, ""):
        src["component"] = str(args["component"])
    view = DrawView(vtype="base", source=src, vnormal=normal, vup=up, scale=scale, scale_text=text, mode=clean_mode(args.get("mode")), show=clean_show(args.get("show")), style=clean_style(args.get("style")), label=clean_label(args.get("label")), auto=bool(args.get("auto", True)), flat=flat)
    if args.get("origin") and not flat:
        view.origin = [float(c) for c in args["origin"]]
    h = add_view(doc, layout, view)
    build.rebuild(doc, h, first=True)
    v = d.ents[h]
    pos = args.get("position")
    if pos:
        v.position = [float(pos[0]), float(pos[1])]
    else:
        set_centre(v, printable_centre(d, layout))
    return h


def parent_unit(d, parent) -> float:
    return parent.unit_mm or 1.0


def place_relative(d, parent, view, u, gap_mm=None) -> None:
    unit = parent.unit_mm or 1.0
    gap = (GAP_MM if gap_mm is None else float(gap_mm)) / unit
    pc, ph = centre_of(parent), parent.half_size()
    nh = view.half_size()
    ax, ay = abs(u[0]), abs(u[1])
    dist = gap + ax * (ph[0] + nh[0]) + ay * (ph[1] + nh[1])
    set_centre(view, [pc[0] + u[0] * dist, pc[1] + u[1] * dist])


def inherit(parent, view) -> None:
    view.source = copy.deepcopy(parent.source)
    view.origin = list(parent.origin)
    view.mode = parent.mode
    view.show = dict(parent.show)
    view.style = copy.deepcopy(parent.style)
    view.parent = parent.handle


def create_projected(doc, args: dict) -> int:
    d = doc.drawing
    parent = find(d, args.get("parent"))
    rel = str(args.get("rel") or args.get("direction") or "right").lower()
    layout = parent.owner[7:]
    normal, up = model.derived_direction(parent, rel)
    scale, text = parse_scale(args.get("scale"), parent.scale)
    view = DrawView(vtype="projected", vnormal=normal, vup=up, scale=scale, scale_text=text, label=clean_label(args.get("label")), auto=bool(args.get("auto", parent.auto)))
    inherit(parent, view)
    view.crop, view.broken = {}, {}
    h = add_view(doc, layout, view)
    build.rebuild(doc, h)
    v = d.ents[h]
    angle = model.projection_of(d, layout)
    v.align = "x" if rel in ("left", "right") else "y"
    if args.get("position"):
        v.position = [float(args["position"][0]), float(args["position"][1])]
    else:
        gap = (float(args["gap"]) if args.get("gap") is not None else GAP_MM) / (v.unit_mm or 1.0)
        pc, ph = centre_of(parent), parent.half_size()
        want = model.placement(angle, rel, pc, ph, v.half_size(), gap)
        set_centre(v, want)
    return h


def line_of_edge(d, parent, edge: dict):
    if edge.get("line"):
        a, b = edge["line"]
        return [float(a[0]), float(a[1])], [float(b[0]), float(b[1])]
    classes = (parent.cache or {}).get("classes") or {}
    rec = None
    if edge.get("pid") is not None:
        for recs in classes.values():
            for r in recs:
                if r.get("pid") == int(edge["pid"]) and r["t"] == "line":
                    rec = r
                    break
            if rec:
                break
    elif edge.get("class") is not None:
        lst = classes.get(edge["class"]) or []
        i = int(edge.get("index", -1))
        if 0 <= i < len(lst):
            rec = lst[i]
    if rec is None or rec["t"] != "line":
        raise ViewError("Pick a straight edge in the parent view.")
    return list(rec["a"]), list(rec["b"])


def create_aux(doc, args: dict) -> int:
    d = doc.drawing
    parent = find(d, args.get("parent"))
    layout = parent.owner[7:]
    a, b = line_of_edge(d, parent, args.get("edge") or {})
    dx, dy = b[0] - a[0], b[1] - a[1]
    n2 = math.hypot(dx, dy)
    if n2 < 1e-9:
        raise ViewError("The picked edge has no length.")
    dx, dy = dx / n2, dy / n2
    sign = -1.0 if args.get("flip") else 1.0
    px, py = -dy * sign, dx * sign
    x, y, n = model.view_frame(parent)
    normal = model.unit([x[i] * px + y[i] * py for i in range(3)])
    up = list(n)
    scale, text = parse_scale(args.get("scale"), parent.scale)
    view = DrawView(vtype="auxiliary", vnormal=normal, vup=up, scale=scale, scale_text=text, label=clean_label(args.get("label") or "AUX"), auto=bool(args.get("auto", parent.auto)))
    inherit(parent, view)
    view.crop, view.broken = {}, {}
    h = add_view(doc, layout, view)
    build.rebuild(doc, h)
    v = d.ents[h]
    angle = model.projection_of(d, layout)
    u = [px, py] if angle == "third" else [-px, -py]
    v.align = [u[0], u[1]]
    if args.get("position"):
        v.position = [float(args["position"][0]), float(args["position"][1])]
    else:
        place_relative(d, parent, v, u, args.get("gap"))
    return h


SECTION_KINDS = ("full", "half", "offset", "aligned")


def section_geometry(parent, kind: str, line: list, flip: bool) -> dict:
    kind = str(kind or "full").lower()
    if kind not in SECTION_KINDS:
        raise ViewError("A section is full, half, offset or aligned.")
    pts = [[float(p[0]), float(p[1])] for p in line or []]
    need = {"full": 2, "half": 2, "offset": 3, "aligned": 3}[kind]
    if len(pts) < need or (kind in ("full", "half", "aligned") and len(pts) != need and kind != "offset"):
        raise ViewError("A %s section line needs %s points." % (kind, "at least 3" if kind == "offset" else need))
    x, y, n = model.view_frame(parent)
    pts3 = [model.lift(parent, p) for p in pts]
    d1 = model.unit([pts3[1][i] - pts3[0][i] for i in range(3)])
    a = model.unit(model.cross(n, d1))
    if flip:
        a = model.neg(a)
    return {"kind": kind, "line": pts, "points": pts3, "pnormal": list(n), "keep": a, "flip": bool(flip)}, model.neg(a), list(n)


def create_section(doc, args: dict) -> int:
    d = doc.drawing
    parent = find(d, args.get("parent"))
    layout = parent.owner[7:]
    sec, normal, up = section_geometry(parent, args.get("kind"), args.get("line"), bool(args.get("flip")))
    letter = clean_label(args.get("letter")) or next_letter(d, layout)
    sec["letter"] = letter
    scale, text = parse_scale(args.get("scale"), parent.scale)
    view = DrawView(vtype="section", vnormal=normal, vup=up, scale=scale, scale_text=text, label=clean_label(args.get("label")) or "SECTION %s-%s" % (letter, letter), section=sec, auto=bool(args.get("auto", parent.auto)))
    inherit(parent, view)
    view.crop, view.broken = {}, {}
    h = add_view(doc, layout, view)
    build.rebuild(doc, h)
    v = d.ents[h]
    x, y, n = model.view_frame(parent)
    a = sec["keep"]
    local_a = [model.dot(a, x), model.dot(a, y)]
    ln = math.hypot(local_a[0], local_a[1]) or 1.0
    angle = model.projection_of(d, layout)
    u = [-local_a[0] / ln, -local_a[1] / ln] if angle == "third" else [local_a[0] / ln, local_a[1] / ln]
    v.align = [u[0], u[1]]
    if args.get("position"):
        v.position = [float(args["position"][0]), float(args["position"][1])]
    else:
        place_relative(d, parent, v, u, args.get("gap"))
    return h


def next_letter(d, layout: str) -> str:
    used = set()
    for e in views_of(d, layout):
        if e.section.get("letter"):
            used.add(e.section["letter"])
        if e.detail.get("letter"):
            used.add(e.detail["letter"])
    for c in "ABCDEFGHJKLMNPQRSTUVWXYZ":
        if c not in used:
            return c
    return "A"


def create_detail(doc, args: dict) -> int:
    d = doc.drawing
    parent = find(d, args.get("parent"))
    layout = parent.owner[7:]
    centre = args.get("center")
    radius = float(args.get("radius") or 0.0)
    if not centre or radius <= 0.0:
        raise ViewError("A detail needs a centre and a radius in the parent view.")
    letter = clean_label(args.get("letter")) or next_letter(d, layout)
    scale, text = parse_scale(args.get("scale"), parent.scale * 2.0)
    view = DrawView(vtype="detail", vnormal=list(parent.vnormal), vup=list(parent.vup), scale=scale, scale_text=text, label=clean_label(args.get("label")) or "DETAIL %s" % letter, auto=bool(args.get("auto", parent.auto)))
    inherit(parent, view)
    view.origin = model.lift(parent, [float(centre[0]), float(centre[1])])
    view.detail = {"center": [float(centre[0]), float(centre[1])], "radius": radius, "letter": letter, "shape": "circle"}
    if parent.section.get("points"):
        view.section = dict(copy.deepcopy(parent.section), inherit=True)
    h = add_view(doc, layout, view)
    build.rebuild(doc, h)
    v = d.ents[h]
    if args.get("position"):
        v.position = [float(args["position"][0]), float(args["position"][1])]
    else:
        place_relative(d, parent, v, [1.0, 0.0], args.get("gap"))
    return h


def set_breaks(doc, handle, breaks: list, clear: bool = False) -> int:
    d = doc.drawing
    v = get(d, handle)
    rows = []
    for b in breaks or []:
        axis = str(b.get("axis", "x")).lower()
        if axis not in ("x", "y"):
            raise ViewError("A break runs along x or y.")
        lo, hi = float(b["lo"]), float(b["hi"])
        if hi <= lo:
            raise ViewError("A break needs the second position above the first.")
        gap = float(b.get("gap", 0.0))
        if gap < 0 or gap >= hi - lo:
            raise ViewError("The gap must be smaller than the removed length.")
        style = str(b.get("style", "zigzag")).lower()
        if style not in ("zigzag", "straight"):
            raise ViewError("A break line is zigzag or straight.")
        rows.append({"axis": axis, "lo": lo, "hi": hi, "gap": gap, "style": style})
    ent = d.modify(v.handle)
    ent.broken = {"breaks": rows} if rows and not clear else {}
    if ent.vtype in ("base", "projected") and ent.broken:
        ent.vtype = "broken"
    build.rebuild(doc, v.handle)
    touch_children(d, v.handle)
    return v.handle


def set_crop(doc, handle, polygon, clear: bool = False) -> int:
    d = doc.drawing
    v = get(d, handle)
    ent = d.modify(v.handle)
    if clear or not polygon:
        ent.crop = {}
    else:
        pts = [[float(p[0]), float(p[1])] for p in polygon]
        if len(pts) < 3:
            raise ViewError("A crop outline needs at least three points.")
        ent.crop = {"polygon": pts}
        if ent.vtype in ("base", "projected"):
            ent.vtype = "crop"
    build.rebuild(doc, v.handle)
    touch_children(d, v.handle)
    return v.handle


def touch_children(d, handle: int) -> None:
    for c in children(d, handle):
        d.modify(c.handle)


def update(doc, handle) -> dict:
    v = get(doc.drawing, handle)
    st = build.rebuild(doc, v.handle)
    touch_children(doc.drawing, v.handle)
    return st


def update_all(doc, only_stale: bool = True) -> list:
    d = doc.drawing
    done = []
    for v in sorted(views_of(d), key=lambda e: e.handle):
        if only_stale and v.state.get("status") not in ("stale", "error", "empty"):
            continue
        try:
            build.rebuild(doc, v.handle)
            done.append(v.handle)
        except ViewError:
            continue
    return done


def delete(doc, handle, cascade: bool = False) -> list:
    d = doc.drawing
    v = get(d, handle)
    kids = children(d, v.handle)
    if kids and not cascade:
        raise ViewError("%s has %d dependent views; delete them too or pass cascade." % (v.name, len(kids)))
    gone = []
    stack = [v]
    while stack:
        cur = stack.pop()
        stack.extend(children(d, cur.handle))
        d.erase_entity(cur.handle)
        gone.append(cur.handle)
    return gone


def move(doc, handle, position=None, delta=None) -> None:
    d = doc.drawing
    v = get(d, handle)
    if position is not None:
        dx, dy = float(position[0]) - v.position[0], float(position[1]) - v.position[1]
    else:
        dx, dy = float(delta[0]), float(delta[1])
    if v.parent and v.align:
        if v.align == "x":
            dy = 0.0
        elif v.align == "y":
            dx = 0.0
        elif isinstance(v.align, list):
            k = dx * v.align[0] + dy * v.align[1]
            dx, dy = k * v.align[0], k * v.align[1]
    ent = d.modify(v.handle)
    ent.position = [ent.position[0] + dx, ent.position[1] + dy]
    for c in children(d, v.handle):
        if c.vtype in CHILD_TYPES:
            ce = d.modify(c.handle)
            ce.position = [ce.position[0] + dx, ce.position[1] + dy]
        else:
            d.modify(c.handle)


def edit(doc, handle, changes: dict) -> dict:
    d = doc.drawing
    v = get(d, handle)
    ent = d.modify(v.handle)
    redo = False
    ch = dict(changes or {})
    if "label" in ch:
        ent.label = clean_label(ch["label"])
    if "scale" in ch:
        ent.scale, ent.scale_text = parse_scale(ch["scale"], ent.scale)
    if "show" in ch:
        ent.show = clean_show({**ent.show, **(ch["show"] or {})})
    if "style" in ch:
        merged = copy.deepcopy(ent.style)
        for cls, spec in clean_style(ch["style"]).items():
            merged.setdefault(cls, {}).update(spec)
        ent.style = merged
    if "mode" in ch:
        ent.mode = clean_mode(ch["mode"])
        redo = True
    if "auto" in ch:
        ent.auto = bool(ch["auto"])
    if "flat" in ch and ent.vtype == "base":
        ent.flat = bool(ch["flat"])
        if ent.flat:
            ent.vnormal, ent.vup = [0.0, 0.0, 1.0], [0.0, 1.0, 0.0]
        redo = True
    if ch.get("direction") or ch.get("vnormal") is not None:
        ent.vnormal, ent.vup = direction_of(ch)
        redo = True
    if "source" in ch:
        s = ch["source"] or {}
        ent.source = {"doc": str(s.get("doc", "")), "component": str(s.get("component", "")), "config": str(s.get("config", ""))}
        redo = True
    if ch.get("section") and ent.section:
        parent = get(d, ent.parent)
        sec = ch["section"]
        geo, normal, up = section_geometry(parent, sec.get("kind", ent.section.get("kind")), sec.get("line", ent.section.get("line")), bool(sec.get("flip", ent.section.get("flip"))))
        geo["letter"] = ent.section.get("letter", "")
        ent.section = geo
        ent.vnormal, ent.vup = normal, up
        redo = True
    if ch.get("detail") and ent.detail:
        parent = get(d, ent.parent)
        det = dict(ent.detail)
        det.update({k: ch["detail"][k] for k in ("center", "radius", "letter") if k in ch["detail"]})
        ent.detail = det
        ent.origin = model.lift(parent, det["center"])
        redo = True
    if "position" in ch and ch["position"] is not None:
        move(doc, v.handle, position=ch["position"])
    if redo:
        build.rebuild(doc, v.handle)
    touch_children(d, v.handle)
    return d.ents[v.handle].state


def info(d, v, cache: bool = False) -> dict:
    out = {
        "handle": v.handle, "name": v.name, "label": v.label, "vtype": v.vtype, "layout": v.owner[7:], "source": v.source, "vnormal": v.vnormal, "vup": v.vup,
        "scale": v.scale, "scaleText": v.scale_text, "position": v.position, "origin": v.origin, "parent": v.parent, "align": v.align, "section": v.section,
        "detail": v.detail, "broken": v.broken, "crop": v.crop, "show": v.show, "style": v.style, "mode": v.mode, "auto": v.auto, "flat": v.flat, "state": v.state,
        "bounds": list(v.bounds()), "counts": (v.cache or {}).get("counts", {}), "unitMm": v.unit_mm,
    }
    if cache:
        out["cache"] = v.cache
    return out
