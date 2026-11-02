import math
import re

from app.cmd import edit_ledger as L, grips, jig, snaps
from app.cmd.commands.modify_corner import menu
from app.cmd.context import CommandError
from app.cmd.draw_support import inherit, pick_entity, pick_point
from app.cmd.registry import command, executes
from app.doc import blockxf, curvepath, geom
from app.doc.entities import Arc, Insert, Line, LwPolyline, Polyline3d, Spline, Text
from app.doc.model import SPACE_MODEL, layout_space

LOCKED = "The object is on a locked layer."
MAX_OPS = 1000
MAX_ITEMS = 100000
LINE_STEP = 5.0 / 3.0


def _props_from(src, dst, thick=True):
    inherit(src, dst)
    if thick and hasattr(dst, "thickness"):
        dst.thickness = src.thickness


def _elev(e):
    return float(getattr(e, "elevation", 0.0) or 0.0)


def _segments(verts, closed, z, src):
    out = []
    n = len(verts)
    for i in range(n if closed else n - 1):
        a, b = verts[i], verts[(i + 1) % n]
        arc = geom.bulge_to_arc(a["p"], b["p"], a.get("bulge", 0.0) or 0.0)
        if arc is None:
            seg = Line(start=[a["p"][0], a["p"][1], z], end=[b["p"][0], b["p"][1], z])
        else:
            c, r, a0, a1, _ccw = arc
            seg = Arc(center=[c[0], c[1], z], radius=r, start_angle=a0, end_angle=a1)
        _props_from(src, seg)
        out.append(seg)
    return out


def _plain(contents):
    s = contents.replace("\\P", "\n").replace("\\p", "\n")
    s = re.sub(r"\\[ACcFfHhQqTtWwLlOoKk][^;\\]*;", "", s)
    s = re.sub(r"\\[LlOoKk]", "", s)
    s = s.replace("\\~", " ").replace("\\\\", "\\").replace("{", "").replace("}", "")
    return s.split("\n")


def _mtext_lines(e):
    lines = _plain(e.contents) or [""]
    n = len(lines)
    step = LINE_STEP * e.height
    total = (n - 1) * step + e.height
    col = (e.attachment - 1) % 3
    row = (e.attachment - 1) // 3
    top = 0.0 if row == 0 else (total / 2.0 if row == 1 else total)
    c, s = math.cos(e.rotation), math.sin(e.rotation)
    out = []
    for i, text in enumerate(lines):
        dy = top - e.height - i * step
        pos = [e.position[0] + dy * -s, e.position[1] + dy * c, e.position[2] if len(e.position) > 2 else 0.0]
        t = Text(position=list(pos), height=e.height, text=text, rotation=e.rotation, style=e.style)
        if col:
            t.halign = col
            t.align_point = list(pos)
        _props_from(e, t, False)
        out.append(t)
    return out


def _resolve_block_props(ref, ent):
    if ent.layer == "0":
        ent.layer = ref.layer
    if ent.color == 0:
        ent.color = ref.color
    if str(ent.linetype).lower() == "byblock":
        ent.linetype = ref.linetype
    if ent.lineweight == -2:
        ent.lineweight = ref.lineweight
    return ent


def block_world(ctx, ins):
    rec = ctx.d.table_get("blocks", ins.block)
    if rec is None:
        return []
    if rec.get("explodable") is False or rec.get("xref"):
        return None
    out = []
    space = "block:" + rec["name"]
    for m in blockxf.insert_matrices(ins, rec):
        for child in list(ctx.d.entities(space)):
            c = blockxf.clone_through(child, m)
            if c is None:
                continue
            c.handle = 0
            c.owner = ins.owner
            out.append((child, _resolve_block_props(ins, c)))
            if len(out) >= blockxf.MAX_COPIES:
                return out
    return out


def _mline_parts(e):
    from app.doc.kinds import mline as ML

    out = []
    els = e.elements()
    for k, runs in enumerate(ML.element_runs(e)):
        spec = els[k]
        for run in runs:
            pts = run["pts"]
            pairs = list(zip(pts, pts[1:]))
            if run.get("closed") and len(pts) > 2:
                pairs.append((pts[-1], pts[0]))
            for a, b in pairs:
                if geom.dist(a, b) < geom.EPS:
                    continue
                ln = Line(start=[a[0], a[1], 0.0], end=[b[0], b[1], 0.0])
                _props_from(e, ln)
                col = spec.get("color", 256)
                if col not in (256, 0):
                    ln.color = col
                lt = str(spec.get("linetype", "BYLAYER"))
                if lt.upper() not in ("BYLAYER", "BYBLOCK"):
                    ln.linetype = lt
                out.append(ln)
    return out


def _region_parts(e):
    out = []
    for loop in e.loops:
        verts = loop.get("vertices", [])
        out.extend(_segments([{"p": v["p"], "bulge": v.get("bulge", 0.0)} for v in verts], True, 0.0, e))
    return out


def explode_parts(ctx, e):
    k = e.kind
    if k == "lwpolyline":
        return _segments(e.vertices, e.closed, _elev(e), e)
    if k == "polyline3d":
        pts = e.points
        pairs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if e.closed and len(pts) > 2 else [])
        out = []
        for a, b in pairs:
            ln = Line(start=list(a), end=list(b))
            _props_from(e, ln)
            out.append(ln)
        return out
    if k == "mtext":
        return _mtext_lines(e)
    if k == "mline":
        return _mline_parts(e)
    if k == "region":
        return _region_parts(e)
    if k == "helix":
        sp = Spline(degree=e.degree, knots=list(e.knots), control_points=[list(p) for p in e.control_points], weights=[], fit_points=[], closed=False)
        _props_from(e, sp, False)
        return [sp]
    if k == "assoc_array":
        return e.explode_entities(blockxf.MAX_COPIES)
    if k == "insert":
        res = block_world(ctx, e)
        if res is None:
            return None
        return [c for _child, c in res]
    if k == "dimension":
        rec = ctx.d.table_get("blocks", e.block) if e.block else None
        if rec is None:
            from app.dim import explode as dim_explode

            return dim_explode.parts(ctx.doc, e)
        out = []
        for child in list(ctx.d.entities("block:" + rec["name"])):
            c = type(child).from_dict(child.to_dict())
            c.handle = 0
            c.owner = e.owner
            out.append(_resolve_block_props(e, c))
        return out
    return None


def _explode(ctx, handles):
    made = []
    done = 0
    for e in ctx.editable(handles):
        parts = explode_parts(ctx, e)
        if not parts:
            continue
        space = e.owner
        ctx.d.erase_entity(e.handle)
        for p in parts:
            p.handle = 0
            made.append(ctx.d.add_entity(p, space))
        done += 1
    return done, made


@command("explode", aliases=("x",), group="modify", label="Explode", description="Break compound objects into component objects.", menu="Modify > Explode")
def explode(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    done, made = _explode(ctx, s.value)
    ctx.say("%d object%s exploded, %d object%s created." % (done, "" if done == 1 else "s", len(made), "" if len(made) == 1 else "s"))


@executes("explode")
def explode_exec(ctx, args):
    if args.get("all"):
        handles = [e.handle for e in ctx.visible_entities()]
    else:
        handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
    done, made = _explode(ctx, handles)
    return {"exploded": done, "created": made}


def _approach(e, p, aperture):
    if snaps.pieces(e):
        q = snaps.nearest_on(e, p)
        if q is not None:
            return geom.dist(q, p)
    box = e.bounds()
    if box is None:
        return None
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    return geom.dist([cx, cy], p)


def pick_nested(ctx, ins, pt):
    nested = block_world(ctx, ins)
    if nested is None:
        raise CommandError("The block cannot be exploded.")
    if not nested:
        raise CommandError("The block reference has no nested objects.")
    aperture = float(ctx.doc.view.get("height", 100.0)) * 0.03
    best = None
    for child, c in nested:
        d = _approach(c, pt, aperture)
        if d is not None and d <= aperture and (best is None or d < best[0]):
            best = (d, c)
    if best is None:
        raise CommandError("Nothing nested there.")
    return best[1]


def _shifted_clones(clones, vec):
    out = []
    for c in clones:
        k = type(c).from_dict(c.to_dict())
        k.move_by(vec)
        out.append(k)
    return out


def _add_copies(ctx, clones, vec, space, led=None):
    made = []
    for c in _shifted_clones(clones, vec):
        c.handle = 0
        h = ctx.d.add_entity(c, space)
        made.append(L.made(led, h) if led is not None else h)
    return made


@command("ncopy", group="modify", label="Copy Nested Objects", description="Copy objects nested inside a block reference.", menu="Modify > Copy Nested Objects")
def ncopy(ctx):
    clones = None
    while clones is None:
        r = yield ctx.entity("Select nested objects to copy", ["Settings"])
        if r.kind == "keyword":
            ctx.say("Nested objects are copied to the current space at their world position.")
            continue
        if r.kind != "entity":
            return
        ins = pick_entity(ctx, r.value)
        pt = pick_point(r.value)
        if not isinstance(ins, Insert):
            ctx.say("Select a block reference.")
            continue
        try:
            clones = [pick_nested(ctx, ins, pt)]
        except CommandError as err:
            ctx.say(str(err))
    space = ctx.doc.current_space
    multiple = False
    while True:
        b = yield ctx.point("Specify base point or displacement", ["Displacement", "Multiple"])
        if b.kind == "keyword" and b.value == "Multiple":
            multiple = True
            continue
        break
    if b.kind == "keyword":
        d = yield ctx.point("Specify displacement", default=[0.0, 0.0, 0.0], jig=lambda q: jig.entity_items(_shifted_clones(clones, [q[0], q[1], 0.0]), ctx.d))
        if d.kind == "point":
            _add_copies(ctx, clones, [d.value[0], d.value[1], 0.0], space)
        return
    if b.kind != "point":
        return
    base = b.value
    while True:
        p = yield ctx.point("Specify second point", base=base, default_text="use first point as displacement", jig=lambda q: jig.entity_items(_shifted_clones(clones, [q[0] - base[0], q[1] - base[1], 0.0]), ctx.d))
        if p.kind == "point":
            _add_copies(ctx, clones, [p.value[0] - base[0], p.value[1] - base[1], 0.0], space)
            if not multiple:
                return
            continue
        if p.kind == "enter" and not multiple:
            _add_copies(ctx, clones, [base[0], base[1], 0.0], space)
        return


@executes("ncopy")
def ncopy_exec(ctx, args):
    ins = ctx.d.get(int(args.get("handle", 0)))
    if not isinstance(ins, Insert):
        raise CommandError("Select a block reference.")
    nested = block_world(ctx, ins)
    if nested is None:
        raise CommandError("The block cannot be exploded.")
    if not nested:
        raise CommandError("The block reference has no nested objects.")
    if args.get("point") is not None:
        clones = [pick_nested(ctx, ins, geom.as_pt(args["point"]))]
    else:
        clones = [c for _child, c in nested]
    if "delta" in args:
        vec = geom.as_pt(args["delta"])
    elif "from" in args and "to" in args:
        a, b = geom.as_pt(args["from"]), geom.as_pt(args["to"])
        vec = [b[0] - a[0], b[1] - a[1], 0.0]
    else:
        vec = [0.0, 0.0, 0.0]
    return {"created": _add_copies(ctx, clones, vec, ctx.doc.current_space)}


def _clone_xf(e, xf):
    c = type(e).from_dict(e.to_dict())
    grips.transform(c, xf)
    return c


def _items_xf(ctx, handles, xf):
    out = []
    for h in handles:
        e = ctx.d.get(h)
        if e is None:
            continue
        try:
            out.append(_clone_xf(e, xf))
        except grips.GripError:
            continue
    return jig.entity_items(out, ctx.d)


def _op_move(ctx, led, handles, vec):
    for e in ctx.editable(handles):
        L.touch(ctx, led, e)
        e.move_by(vec)


def _op_copy(ctx, led, handles, vec):
    made = []
    for h in handles:
        e = ctx.d.get(h)
        if e is None:
            continue
        c = e.copy_as_new()
        c.move_by(vec)
        made.append(L.made(led, ctx.d.add_entity(c, e.owner)))
    return made


def _op_xf(ctx, led, handles, xf):
    skipped = 0
    for e in ctx.editable(handles):
        try:
            probe = _clone_xf(e, xf)
        except grips.GripError:
            skipped += 1
            continue
        L.touch(ctx, led, e)
        ctx.d.ents[e.handle] = probe
    return skipped


def _vec(a, b):
    return [b[0] - a[0], b[1] - a[1], 0.0]


def _angle_value(inp, base):
    if inp.kind == "number":
        return inp.value
    if inp.kind == "point":
        return geom.angle_of(base, inp.value)
    return None


def _scale_value(inp, base):
    if inp.kind == "number":
        return inp.value
    if inp.kind == "point":
        return geom.dist(base, inp.value)
    return None


@command("mocoro", group="modify", label="Move/Copy/Rotate", description="Move, copy, rotate, scale in one command with a shared base point.", menu="Tools > Express Tools > Move/Copy/Rotate")
def mocoro(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    b = yield ctx.point("Specify base point")
    if b.kind != "point":
        return
    st = {"base": [b.value[0], b.value[1], 0.0]}
    stack = []
    while True:
        base = st["base"]
        r = yield menu(ctx, "Enter an option", ["Move", "Copy", "Rotate", "Scale", "Base", "Undo", "eXit"], "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return
        w = r.value
        if w == "Undo":
            if stack:
                led, prev = stack.pop()
                L.rollback(ctx, led)
                st["base"] = prev
            else:
                ctx.say("Nothing to undo.")
            continue
        led = L.new()
        if w in ("Move", "Copy"):
            p = yield ctx.point("Specify second point", base=base, jig=lambda q, base=base: jig.moved_items(ctx.d, handles, _vec(base, q)))
            if p.kind != "point":
                continue
            vec = _vec(base, p.value)
            if w == "Move":
                _op_move(ctx, led, handles, vec)
                st["base"] = [p.value[0], p.value[1], 0.0]
            else:
                _op_copy(ctx, led, handles, vec)
        elif w == "Rotate":
            a = yield ctx.angle("Specify rotation angle", base=base, absolute=False, jig=lambda q, base=base: _items_xf(ctx, handles, grips.Xf("rotate", base, geom.angle_of(base, q))))
            ang = _angle_value(a, base)
            if ang is None:
                continue
            _op_xf(ctx, led, handles, grips.Xf("rotate", base, ang))
        elif w == "Scale":
            k = yield ctx.distance("Specify scale factor", base=base, positive=True, jig=lambda q, base=base: _items_xf(ctx, handles, grips.Xf("scale", base, k=max(geom.dist(base, q), 1e-9))))
            val = _scale_value(k, base)
            if val is None or val <= 0:
                continue
            _op_xf(ctx, led, handles, grips.Xf("scale", base, k=val))
        elif w == "Base":
            nb = yield ctx.point("Specify base point")
            if nb.kind != "point":
                continue
            stack.append((led, list(base)))
            if len(stack) > MAX_OPS:
                stack.pop(0)
            st["base"] = [nb.value[0], nb.value[1], 0.0]
            continue
        stack.append((led, list(base)))
        if len(stack) > MAX_OPS:
            stack.pop(0)


@executes("mocoro")
def mocoro_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
    if not handles:
        raise CommandError("Select objects.")
    ops = args.get("ops", [])
    if not isinstance(ops, list) or len(ops) > MAX_OPS:
        raise CommandError("At most %d operations are allowed." % MAX_OPS)
    base = geom.as_pt(args["base"]) if "base" in args else None
    if base is None:
        raise CommandError("Give the base point.")
    plan = []
    cur = list(base)
    for op in ops:
        keys = [k for k in ("move", "copy", "rotate", "scale", "base") if k in op]
        if len(keys) != 1:
            raise CommandError("Each operation must have exactly one of move, copy, rotate, scale, base.")
        key = keys[0]
        if key in ("move", "copy", "base"):
            tgt = geom.as_pt(op[key])
            plan.append((key, tgt))
        elif key == "rotate":
            plan.append((key, math.radians(float(op[key]))))
        else:
            k = float(op[key])
            if k <= 0:
                raise CommandError("Value must be positive and nonzero.")
            plan.append((key, k))
    led = L.new()
    made = []
    for key, val in plan:
        if key == "move":
            _op_move(ctx, led, handles, _vec(cur, val))
            cur = list(val)
        elif key == "copy":
            made.extend(_op_copy(ctx, led, handles, _vec(cur, val)))
        elif key == "rotate":
            _op_xf(ctx, led, handles, grips.Xf("rotate", cur, val))
        elif key == "scale":
            _op_xf(ctx, led, handles, grips.Xf("scale", cur, k=val))
        else:
            cur = list(val)
    return {"created": made, "base": cur}


def _layout_names(ctx):
    recs = sorted(ctx.d.tables["layouts"].values(), key=lambda r: r.get("tab_order", 0))
    return [r["name"] for r in recs]


def _viewports(ctx, space):
    return [e for e in ctx.d.entities(space) if e.kind == "viewport"]


def change_space(ctx, handles, layout=None, viewport=None):
    names = _layout_names(ctx)
    cur = ctx.doc.current_space
    to_paper = cur == SPACE_MODEL
    if to_paper:
        if layout is None:
            if not names:
                raise CommandError("No layout to move objects to.")
            layout = names[0]
        match = [n for n in names if n.lower() == layout.lower()]
        if not match:
            raise CommandError('Layout "%s" not found.' % layout)
        layout = match[0]
    else:
        layout = cur[len("layout:"):] if cur.startswith("layout:") else cur
    target = layout_space(layout) if to_paper else SPACE_MODEL
    paper_space = layout_space(layout)
    vps = _viewports(ctx, paper_space)
    vp = None
    if viewport is not None:
        vp = ctx.d.get(int(viewport))
        if vp is None or vp.kind != "viewport":
            raise CommandError("Select a viewport.")
    elif len(vps) >= 1:
        vp = vps[0]
    if vp is None:
        raise CommandError("There is no viewport on the layout.")
    changed = 0
    for e in ctx.editable(handles):
        if e.kind == "viewport" or e.owner == target:
            continue
        c = type(e).from_dict(e.to_dict())
        vc = vp.view_center
        try:
            if to_paper:
                grips.transform(c, grips.Xf("scale", vc, k=1.0 / vp.scale))
                c.move_by([vp.center[0] - vc[0], vp.center[1] - vc[1], 0.0])
            else:
                grips.transform(c, grips.Xf("scale", vp.center, k=vp.scale))
                c.move_by([vc[0] - vp.center[0], vc[1] - vp.center[1], 0.0])
        except grips.GripError:
            continue
        h = e.handle
        ctx.d.erase_entity(h)
        c.handle = 0
        ctx.d.add_entity(c, target, h)
        changed += 1
    return changed, layout, to_paper


@command("chspace", group="modify", label="Change Space", description="Move objects between model space and a layout through a viewport.", menu="Modify > Change Space")
def chspace(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    layout = None
    names = _layout_names(ctx)
    if ctx.doc.current_space == SPACE_MODEL and len(names) > 1:
        r = yield ctx.word("Enter layout name", default=names[0])
        if r.kind == "text" and r.value:
            layout = str(r.value)
        elif r.kind != "enter":
            return
    viewport = None
    if ctx.doc.current_space == SPACE_MODEL:
        probe_layout = layout or (names[0] if names else None)
        vps = _viewports(ctx, layout_space(probe_layout)) if probe_layout else []
    else:
        vps = _viewports(ctx, ctx.doc.current_space)
    if len(vps) > 1:
        r = yield ctx.entity("Select viewport")
        if r.kind != "entity":
            return
        v = pick_entity(ctx, r.value)
        if v is None or v.kind != "viewport":
            ctx.say("Select a viewport.")
            return
        viewport = v.handle
    n, layout, to_paper = change_space(ctx, s.value, layout, viewport)
    ctx.say("%d object%s changed from %s to %s." % (n, "" if n == 1 else "s", "model space" if to_paper else "paper space", "paper space" if to_paper else "model space"))


@executes("chspace")
def chspace_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
    n, layout, to_paper = change_space(ctx, handles, args.get("layout"), args.get("viewport"))
    return {"changed": n, "layout": layout, "toPaper": to_paper}


def _flat_z(p):
    if p is not None and len(p) > 2:
        p[2] = 0.0


def flatten_entity(ctx, e):
    if isinstance(e, Polyline3d):
        new = LwPolyline.from_points([[p[0], p[1]] for p in e.points], closed=e.closed)
        for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "plot_style", "handle", "owner"):
            setattr(new, name, getattr(e, name))
        ctx.d.ents[e.handle] = new
        return True
    if e.kind == "helix":
        new = Spline(degree=e.degree, knots=list(e.knots), control_points=[[p[0], p[1], 0.0] for p in e.control_points], weights=[], fit_points=[], closed=False)
        for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "plot_style", "handle", "owner"):
            setattr(new, name, getattr(e, name))
        ctx.d.ents[e.handle] = new
        return True
    for name in e.POINTS:
        _flat_z(getattr(e, name, None))
    for name in e.POINT_LISTS:
        for p in getattr(e, name, []):
            _flat_z(p)
    for name in e.VERTEX_LISTS:
        for v in getattr(e, name, []):
            _flat_z(v["p"])
    if hasattr(e, "elevation"):
        e.elevation = 0.0
    if hasattr(e, "thickness"):
        e.thickness = 0.0
    for name in ("major", "start_tangent", "end_tangent", "direction"):
        _flat_z(getattr(e, name, None))
    if e.kind == "hatch":
        e.elevation = 0.0
    if hasattr(e, "loops"):
        for loop in e.loops:
            for v in loop.get("vertices", []):
                _flat_z(v["p"])
    return True


def _flatten(ctx, handles):
    n = 0
    for e in ctx.editable(handles):
        ctx.d.modify(e.handle)
        if flatten_entity(ctx, e):
            n += 1
    return n


@command("flatten", group="modify", label="Flatten Objects", description="Set Z to zero and flatten 3D polylines.", menu="Modify > Flatten Objects")
def flatten(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    n = _flatten(ctx, s.value)
    ctx.say("%d object%s flattened." % (n, "" if n == 1 else "s"))


@executes("flatten")
def flatten_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
    return {"flattened": _flatten(ctx, handles)}


def _source_box(ents):
    box = None
    for e in ents:
        box = geom.union_bounds(box, e.bounds())
    return box


def path_array(ctx, handles, path_handle, count=None, spacing=None, align=True):
    path_ent = ctx.d.get(path_handle)
    if path_ent is None or path_ent.kind not in curvepath.KINDS:
        raise CommandError("Select a path curve.")
    path = curvepath.build(path_ent)
    if path is None or path.length <= geom.EPS:
        raise CommandError("The path has no length.")
    src = [ctx.d.get(h) for h in handles if h != path_handle and ctx.d.get(h) is not None]
    if not src:
        raise CommandError("Select objects to array.")
    if spacing is not None:
        if spacing <= 0:
            raise CommandError("Value must be positive and nonzero.")
        n = int(math.floor(path.length / spacing + 1e-9)) + 1
        step = spacing
    else:
        n = int(count if count is not None else 6)
        if n < 1:
            raise CommandError("Requires an integer of at least 1.")
        step = path.length / n if path.closed else (path.length / (n - 1) if n > 1 else 0.0)
    if n * len(src) > MAX_ITEMS:
        raise CommandError("Too many items.")
    box = _source_box(src)
    base = [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0] if box else [0.0, 0.0]
    p0, t0 = path.at(0.0)
    made = []
    for k in range(n):
        s = min(k * step, path.length)
        p, t = path.at(s)
        for e in src:
            c = type(e).from_dict(e.to_dict())
            c.handle = 0
            if align and abs(t - t0) > 1e-12:
                try:
                    grips.transform(c, grips.Xf("rotate", base, t - t0))
                except grips.GripError:
                    pass
            c.move_by([p[0] - base[0], p[1] - base[1], 0.0])
            made.append(ctx.d.add_entity(c, e.owner))
    return made, n, path.length


@command("arraypath.simple", group="modify", label="Path Array", description="Non-associative copies of objects distributed along a path curve.", menu="Modify > Array > Path Array")
def arraypath_simple(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    path = None
    while path is None:
        r = yield ctx.entity("Select path curve")
        if r.kind != "entity":
            return
        cand = pick_entity(ctx, r.value)
        if cand is None or cand.kind not in curvepath.KINDS:
            ctx.say("Select a path curve.")
            continue
        path = cand
    if not [h for h in handles if h != path.handle]:
        ctx.say("Select objects to array.")
        return
    count = spacing = None
    while True:
        n = yield ctx.number("Enter number of items along path", ["Distance"], default=6, integer=True, minimum=1, default_text="6")
        if n.kind == "keyword":
            d = yield ctx.distance("Specify distance between items along path", positive=True)
            if d.kind == "number":
                spacing = d.value
                break
            continue
        if n.kind == "number":
            count = int(n.value)
            break
        return
    a = yield ctx.yesno("Align items to path?", "Yes")
    align = not (a.kind == "keyword" and a.value == "No")
    try:
        made, n, length = path_array(ctx, handles, path.handle, count, spacing, align)
    except CommandError as err:
        ctx.say(str(err))
        return
    ctx.say("%d items created along a path of length %s." % (n, ctx.fd(length)))


@executes("arraypath.simple")
def arraypath_simple_exec(ctx, args):
    handles = [int(h) for h in args.get("handles", [])] or list(ctx.doc.selection)
    made, n, length = path_array(ctx, handles, int(args.get("path", 0)), args.get("count"), args.get("spacing"), bool(args.get("align", True)))
    return {"created": made, "items": n}
