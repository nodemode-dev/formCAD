import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes
from app.doc import curvepath, geom
from app.doc.kinds import array as A
from app.doc.kinds.array import AssocArray

PREVIEW_ENTITIES = 2000
EPS = 1e-9


def _union(ents):
    box = None
    for e in ents:
        box = geom.union_bounds(box, e.bounds())
    return list(box) if box else [0.0, 0.0, 0.0, 0.0]


def _centre(box):
    return [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0, 0.0]


def _limit(ctx) -> int:
    return int(ctx.var("MAXARRAY"))


def _gather(ctx, handles):
    ents = []
    locked = 0
    for h in handles:
        e = ctx.d.get(int(h))
        if e is None:
            continue
        if ctx.locked(e):
            locked += 1
            continue
        ents.append(e)
    if not ents:
        raise CommandError("No objects to array (objects on locked layers are left out).")
    return ents


def ref_point(e) -> list:
    for name in ("center", "position", "start", "base"):
        v = getattr(e, name, None)
        if isinstance(v, list) and len(v) >= 2:
            return [float(v[0]), float(v[1]), 0.0]
    for name in e.POINTS:
        v = getattr(e, name, None)
        if isinstance(v, list) and len(v) >= 2:
            return [float(v[0]), float(v[1]), 0.0]
    for name in e.POINT_LISTS:
        lst = getattr(e, name, None)
        if lst:
            return [float(lst[0][0]), float(lst[0][1]), 0.0]
    for name in e.VERTEX_LISTS:
        lst = getattr(e, name, None)
        if lst:
            return [float(lst[0]["p"][0]), float(lst[0]["p"][1]), 0.0]
    box = e.bounds()
    return _centre(box) if box else [0.0, 0.0, 0.0]


def new_array(ctx, shape, ents, **kw) -> AssocArray:
    box = _union(ents)
    w, h = box[2] - box[0], box[3] - box[1]
    size = max(w, h) or 1.0
    arr = AssocArray(shape=shape)
    arr.source = []
    for e in ents:
        data = e.to_dict()
        data["handle"] = 0
        arr.source.append(data)
    if shape == "rect":
        arr.base = _centre(box)
        arr.column_spacing = 1.5 * (w or size)
        arr.row_spacing = 1.5 * (h or size)
        arr.level_spacing = arr.row_spacing
    elif shape == "polar":
        first = ents[0].bounds()
        arr.base = _centre(first) if first else _centre(box)
        arr.rows = 1
        arr.row_spacing = 1.5 * size
        arr.level_spacing = arr.row_spacing
    else:
        arr.base = ref_point(ents[0])
        arr.rows = 1
        arr.columns = 1
    for k, v in kw.items():
        setattr(arr, k, v)
    return arr


def _preview_items(ctx, arr):
    n = max(1, PREVIEW_ENTITIES // max(len(arr.source), 1))
    try:
        ents = arr.explode_entities(n)
    except Exception:
        return []
    return jig.entity_items(ents, ctx.d)


def _loop_jig(ctx, arr):
    return lambda q: _preview_items(ctx, arr)


def _check_limit(ctx, arr) -> None:
    total = arr.total_objects()
    lim = _limit(ctx)
    if total > A.HARD_LIMIT or total > lim:
        raise CommandError("The array would create %d objects; the limit is %d." % (total, min(lim, A.HARD_LIMIT)))


def _try_set(ctx, arr, **vals) -> bool:
    old = {k: getattr(arr, k) for k in vals}
    for k, v in vals.items():
        setattr(arr, k, v)
    total = arr.total_objects()
    lim = min(_limit(ctx), A.HARD_LIMIT)
    if total > lim:
        for k, v in old.items():
            setattr(arr, k, v)
        ctx.say("The array would create %d objects; the limit is %d. Enter a smaller count." % (total, lim))
        return False
    return True


def _spawn(ctx, arr, ents, associative):
    _check_limit(ctx, arr)
    if arr.shape == "path" and not arr.path.get("entity"):
        raise CommandError("The path has no length.")
    if associative:
        for e in ents:
            ctx.d.erase_entity(e.handle)
        h = ctx.add(arr)
        ctx.say("Associative %s array created: %d items, %d objects." % (arr.shape, arr.count(), arr.total_objects()))
        return {"array": h, "items": arr.count(), "created": 0}
    if arr.levels > 1:
        ctx.say("Levels need an associative array; the copies are made on one level.")
        arr.levels = 1
    made = []
    for key, d, rot, about in arr.frames():
        if max(abs(d[0]), abs(d[1]), abs(d[2])) < EPS and abs(rot) < EPS:
            continue
        for e in ents:
            clone = e.copy_as_new()
            try:
                arr.realize([clone], d, rot, about)
            except Exception:
                raise CommandError("The objects can't be arrayed that way.")
            made.append(ctx.d.add_entity(clone, e.owner))
    ctx.say("%d objects created." % len(made))
    return {"array": None, "items": arr.count(), "created": len(made), "handles": made}


def _ask_count(ctx, arr, msg, field, minimum=1):
    while True:
        r = yield ctx.number(msg, default=int(getattr(arr, field)), integer=True, minimum=minimum, maximum=A.HARD_LIMIT)
        if r.kind != "number":
            return False
        if _try_set(ctx, arr, **{field: int(r.value)}):
            return True


def _distance(ctx, msg, current, base, options=()):
    while True:
        r = yield ctx.distance(msg, list(options), default=current, base=base)
        if r.kind == "number":
            v = r.value
        elif r.kind == "point":
            v = geom.dist(base, r.value)
        elif r.kind == "keyword":
            return "key", r.value
        else:
            return None, None
        if abs(v) < EPS:
            ctx.say("Requires a nonzero distance.")
            continue
        return "value", v


def _total_spacing(ctx, base, count):
    t = yield from _distance(ctx, "Specify total distance", None, base)
    if t[0] != "value":
        return None
    return t[1] / (count - 1) if count > 1 else t[1]


def _ask_yes(ctx, msg, current):
    r = yield ctx.yesno(msg, "Yes" if current else "No")
    if r.kind != "keyword":
        return None
    return r.value == "Yes"


def _ask_angle(ctx, msg, current):
    while True:
        r = yield ctx.angle(msg, default=current, absolute=False)
        if r.kind != "number":
            return None
        if abs(r.value) < 1e-12:
            ctx.say("Requires a nonzero angle.")
            continue
        return r.value


def _flow_base(ctx, arr):
    r = yield ctx.point("Specify base point", ["Key point"], default=list(arr.base))
    if r.kind == "keyword":
        r = yield ctx.point("Specify key point", default=list(arr.base))
    if r.kind == "point":
        arr.base = [r.value[0], r.value[1], 0.0]


def _flow_assoc(ctx, assoc):
    v = yield from _ask_yes(ctx, "Create associative array", assoc)
    return assoc if v is None else v


def _flow_columns(ctx, arr):
    ok = yield from _ask_count(ctx, arr, "Enter number of columns", "columns")
    if not ok:
        return
    k, v = yield from _distance(ctx, "Specify distance between columns", arr.column_spacing, arr.base, ["Total"])
    if k == "value":
        arr.column_spacing = v
    elif k == "key":
        s = yield from _total_spacing(ctx, arr.base, arr.columns)
        if s is not None:
            arr.column_spacing = s


def _flow_rows(ctx, arr, elevation=True):
    ok = yield from _ask_count(ctx, arr, "Enter number of rows", "rows")
    if not ok:
        return
    k, v = yield from _distance(ctx, "Specify distance between rows", arr.row_spacing, arr.base, ["Total"])
    if k == "value":
        arr.row_spacing = v
    elif k == "key":
        s = yield from _total_spacing(ctx, arr.base, arr.rows)
        if s is not None:
            arr.row_spacing = s
    if elevation:
        r = yield ctx.distance("Specify the incrementing elevation between rows", default=arr.row_elevation)
        if r.kind == "number":
            arr.row_elevation = r.value


def _flow_levels(ctx, arr):
    ok = yield from _ask_count(ctx, arr, "Enter number of levels", "levels")
    if not ok:
        return
    k, v = yield from _distance(ctx, "Specify distance between levels", arr.level_spacing, arr.base, ["Total"])
    if k == "value":
        arr.level_spacing = v
    elif k == "key":
        s = yield from _total_spacing(ctx, arr.base, arr.levels)
        if s is not None:
            arr.level_spacing = s


def _flow_count_rect(ctx, arr):
    ok = yield from _ask_count(ctx, arr, "Enter number of columns", "columns")
    if ok:
        yield from _ask_count(ctx, arr, "Enter number of rows", "rows")


def _flow_spacing_rect(ctx, arr):
    k, v = yield from _distance(ctx, "Specify distance between columns", arr.column_spacing, arr.base, ["Unit cell"])
    if k == "value":
        arr.column_spacing = v
        k2, v2 = yield from _distance(ctx, "Specify distance between rows", arr.row_spacing, arr.base)
        if k2 == "value":
            arr.row_spacing = v2
    elif k == "key":
        a = yield ctx.point("Specify first corner")
        if a.kind != "point":
            return
        while True:
            b = yield ctx.point("Specify opposite corner", base=a.value, rect=True)
            if b.kind != "point":
                return
            dx, dy = b.value[0] - a.value[0], b.value[1] - a.value[1]
            if abs(dx) < EPS or abs(dy) < EPS:
                ctx.say("Requires a nonzero distance.")
                continue
            arr.column_spacing, arr.row_spacing = dx, dy
            return


def _flow_items(ctx, arr):
    while True:
        r = yield ctx.number("Enter number of items in array", default=int(arr.items), integer=True, minimum=1, maximum=A.HARD_LIMIT)
        if r.kind != "number":
            return
        if _try_set(ctx, arr, items=int(r.value)):
            return


def _flow_fill(ctx, arr):
    while True:
        v = yield from _ask_angle(ctx, "Specify the angle to fill (+=ccw, -=cw)", arr.fill_angle)
        if v is None:
            return
        if abs(v) > geom.TAU + 1e-9:
            ctx.say("The items would span more than 360 degrees; enter a smaller angle or fewer items.")
            continue
        arr.fill_angle = v
        return


def _flow_between(ctx, arr):
    cur = arr.polar_step()
    while True:
        v = yield from _ask_angle(ctx, "Specify the angle between items", cur)
        if v is None:
            return
        n = max(int(arr.items), 1)
        if abs(abs(v) * n - geom.TAU) < 1e-9:
            arr.fill_angle = math.copysign(geom.TAU, v)
            return
        fill = v * (n - 1) if n > 1 else v
        if abs(fill) > geom.TAU + 1e-9:
            ctx.say("The items would span more than 360 degrees; enter a smaller angle or fewer items.")
            continue
        arr.fill_angle = fill
        return


def _flow_rotate(ctx, arr):
    v = yield from _ask_yes(ctx, "Rotate arrayed items?", arr.rotate_items)
    if v is not None:
        arr.rotate_items = v


def _flow_path_items(ctx, arr):
    while True:
        r = yield ctx.number("Enter number of items along path", default=int(arr.items), integer=True, minimum=1, maximum=A.HARD_LIMIT)
        if r.kind != "number":
            return
        arr.path_method = "count"
        if _try_set(ctx, arr, items=int(r.value)):
            return


def _flow_path_spacing(ctx, arr):
    k, v = yield from _distance(ctx, "Specify the distance between items along path", arr.path_spacing, arr.base)
    if k == "value" and v > 0:
        arr.path_method = "spacing"
        arr.path_spacing = v


def _flow_align(ctx, arr):
    v = yield from _ask_yes(ctx, "Align items to the path?", arr.align)
    if v is not None:
        arr.align = v


RECT_OPTS = ["ASsociative", "Base point", "COUnt", "Spacing", "COLumns", "Rows", "Levels", "eXit"]
POLAR_OPTS = ["ASsociative", "Base point", "Items", "Angle between", "Fill angle", "ROWs", "Levels", "ROTate items", "eXit"]


def _edit_prompt(ctx, arr, options, message="Select grip to edit array"):
    p = ctx.keyword(message, options, "eXit")
    p.jig = _loop_jig(ctx, arr)
    return p


def _rect_flow(ctx, ents, assoc):
    arr = new_array(ctx, "rect", ents)
    while True:
        r = yield _edit_prompt(ctx, arr, RECT_OPTS)
        if r.kind == "point":
            ctx.say("Editing the array with grips is not available yet; choose an option.")
            continue
        if r.kind != "keyword" or r.value == "eXit":
            break
        k = r.value
        if k == "ASsociative":
            assoc = yield from _flow_assoc(ctx, assoc)
        elif k == "Base point":
            yield from _flow_base(ctx, arr)
        elif k == "COUnt":
            yield from _flow_count_rect(ctx, arr)
        elif k == "Spacing":
            yield from _flow_spacing_rect(ctx, arr)
        elif k == "COLumns":
            yield from _flow_columns(ctx, arr)
        elif k == "Rows":
            yield from _flow_rows(ctx, arr)
        elif k == "Levels":
            yield from _flow_levels(ctx, arr)
    return _spawn(ctx, arr, ents, assoc)


def _polar_flow(ctx, ents, assoc):
    arr = new_array(ctx, "polar", ents)
    arr.center = [0.0, 0.0, 0.0]

    def jig_center(q):
        tmp = new_array(ctx, "polar", ents)
        tmp.center = [q[0], q[1], 0.0]
        return _preview_items(ctx, tmp)

    while True:
        p = ctx.point("Specify center point of array", ["Base point", "Axis of rotation"], jig=jig_center)
        r = yield p
        if r.kind == "keyword" and r.value == "Base point":
            yield from _flow_base(ctx, arr)
            continue
        if r.kind == "keyword" and r.value == "Axis of rotation":
            a = yield ctx.point("Specify first point on axis of rotation")
            if a.kind == "point":
                b = yield ctx.point("Specify second point on axis of rotation", base=a.value)
                if b.kind == "point":
                    arr.axis = [[a.value[0], a.value[1], 0.0], [b.value[0], b.value[1], 0.0]]
                    ctx.say("Axis of rotation stored; a flat drawing rotates about the center point.")
            continue
        if r.kind != "point":
            return None
        arr.center = [r.value[0], r.value[1], 0.0]
        break
    while True:
        r = yield _edit_prompt(ctx, arr, POLAR_OPTS)
        if r.kind != "keyword" or r.value == "eXit":
            break
        k = r.value
        if k == "ASsociative":
            assoc = yield from _flow_assoc(ctx, assoc)
        elif k == "Base point":
            yield from _flow_base(ctx, arr)
        elif k == "Items":
            yield from _flow_items(ctx, arr)
        elif k == "Angle between":
            yield from _flow_between(ctx, arr)
        elif k == "Fill angle":
            yield from _flow_fill(ctx, arr)
        elif k == "ROWs":
            yield from _flow_rows(ctx, arr)
        elif k == "Levels":
            yield from _flow_levels(ctx, arr)
        elif k == "ROTate items":
            yield from _flow_rotate(ctx, arr)
    return _spawn(ctx, arr, ents, assoc)


def path_entity(ctx, handle):
    e = ctx.d.get(int(handle)) if handle is not None else None
    if e is None or e.kind not in curvepath.KINDS:
        raise CommandError("Select a line, arc, circle, ellipse, polyline or spline as the path.")
    cur = curvepath.build(e)
    if cur is None or cur.length <= EPS:
        raise CommandError("The path has no length.")
    return e, cur


def set_path(arr, e, cur) -> None:
    data = e.to_dict()
    data["handle"] = 0
    arr.path = {"handle": e.handle, "entity": data, "length": cur.length, "closed": bool(cur.closed)}


def _path_flow(ctx, ents, assoc):
    while True:
        r = yield ctx.entity("Select path curve")
        if r.kind != "entity":
            return None
        try:
            pe, cur = path_entity(ctx, r.value.get("handle"))
        except CommandError as err:
            ctx.say(str(err))
            continue
        break
    ents = [e for e in ents if e.handle != pe.handle]
    if not ents:
        raise CommandError("Select objects to array.")
    arr = new_array(ctx, "path", ents)
    set_path(arr, pe, cur)
    arr.items = 6
    while True:
        p = ctx.number("Enter number of items along path", ["Spacing", "Align items", "Associative"], default=int(arr.items), integer=True, minimum=1, maximum=A.HARD_LIMIT)
        p.jig = _loop_jig(ctx, arr)
        r = yield p
        if r.kind == "number":
            arr.path_method = "count"
            if _try_set(ctx, arr, items=int(r.value)):
                break
            continue
        if r.kind == "keyword" and r.value == "Spacing":
            yield from _flow_path_spacing(ctx, arr)
            break
        if r.kind == "keyword" and r.value == "Align items":
            yield from _flow_align(ctx, arr)
            continue
        if r.kind == "keyword" and r.value == "Associative":
            assoc = yield from _flow_assoc(ctx, assoc)
            continue
        break
    return _spawn(ctx, arr, ents, assoc)


def _assoc_default(ctx) -> bool:
    try:
        return bool(int(ctx.var("ARRAYASSOC")))
    except Exception:
        return True


def _select(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return None
    return _gather(ctx, s.value)


@command("arrayrect", group="modify", label="Rectangular Array", description="Associative rectangular array of rows, columns and levels.", menu="Modify > Array > Rectangular Array")
def arrayrect(ctx):
    ents = yield from _select(ctx)
    if ents:
        yield from _rect_flow(ctx, ents, _assoc_default(ctx))


@command("arraypolar", group="modify", label="Polar Array", description="Associative polar array around a centre point.", menu="Modify > Array > Polar Array")
def arraypolar(ctx):
    ents = yield from _select(ctx)
    if ents:
        yield from _polar_flow(ctx, ents, _assoc_default(ctx))


@command("arraypath", group="modify", label="Path Array", description="Copies of objects distributed along a path curve.", menu="Modify > Array > Path Array")
def arraypath(ctx):
    ents = yield from _select(ctx)
    if ents:
        yield from _path_flow(ctx, ents, True)


@command("array", aliases=("ar",), group="modify", label="Array", description="Create an array: rectangular, polar or path.", menu="")
def array(ctx):
    ents = yield from _select(ctx)
    if not ents:
        return
    t = yield ctx.keyword("Enter array type", ["Rectangular", "PAth", "POlar"], "Rectangular")
    if t.kind != "keyword":
        return
    assoc = _assoc_default(ctx)
    if t.value == "Rectangular":
        yield from _rect_flow(ctx, ents, assoc)
    elif t.value == "POlar":
        yield from _polar_flow(ctx, ents, assoc)
    else:
        yield from _path_flow(ctx, ents, True)


def _classic_rect(ctx, ents):
    rows = yield ctx.number("Enter the number of rows (---)", default=1, integer=True, minimum=1, maximum=A.HARD_LIMIT)
    if rows.kind != "number":
        return None
    cols = yield ctx.number("Enter the number of columns (|||)", default=1, integer=True, minimum=1, maximum=A.HARD_LIMIT)
    if cols.kind != "number":
        return None
    arr = new_array(ctx, "rect", ents, rows=int(rows.value), columns=int(cols.value), levels=1)
    arr.column_spacing, arr.row_spacing = 0.0, 0.0
    cell = False
    if rows.value > 1:
        r = yield Prompt("Enter the distance between rows or specify unit cell (---)", ("distance", "point"), [], None, "", ents and _centre(_union(ents)) or None)
        if r.kind == "number":
            arr.row_spacing = r.value
        elif r.kind == "point":
            o = yield ctx.point("Specify opposite corner of unit cell", base=r.value, rect=True)
            if o.kind != "point":
                return None
            arr.column_spacing = o.value[0] - r.value[0]
            arr.row_spacing = o.value[1] - r.value[1]
            cell = True
        else:
            return None
    if cols.value > 1 and not cell:
        r = yield ctx.distance("Specify the distance between columns (|||)")
        if r.kind == "number":
            arr.column_spacing = r.value
        else:
            return None
    return arr


def _classic_polar(ctx, ents):
    ref = ref_point(ents[-1])
    while True:
        r = yield ctx.point("Specify center point of array", ["Base"])
        if r.kind == "keyword":
            b = yield ctx.point("Specify base point", default=ref)
            if b.kind == "point":
                ref = [b.value[0], b.value[1], 0.0]
            continue
        break
    if r.kind != "point":
        return None
    n = yield ctx.number("Enter the number of items in the array", integer=True, minimum=1, maximum=A.HARD_LIMIT)
    if n.kind != "number":
        return None
    while True:
        a = yield ctx.angle("Specify the angle to fill (+=ccw, -=cw)", default=geom.TAU, absolute=False)
        if a.kind != "number":
            return None
        if abs(a.value) < 1e-12:
            ctx.say("Requires a nonzero angle.")
            continue
        if abs(a.value) > geom.TAU + 1e-9:
            ctx.say("The items would span more than 360 degrees; enter a smaller angle or fewer items.")
            continue
        break
    rot = yield ctx.yesno("Rotate arrayed objects?", "Yes")
    if rot.kind != "keyword":
        return None
    arr = new_array(ctx, "polar", ents, items=int(n.value), fill_angle=a.value, rotate_items=rot.value == "Yes", levels=1, rows=1)
    arr.center = [r.value[0], r.value[1], 0.0]
    arr.base = ref
    return arr


@command("-array", group="modify", label="Array (command line)", description="Classic array that makes separate copies.", menu="")
def array_classic(ctx):
    ents = yield from _select(ctx)
    if not ents:
        return
    last = ctx.mem.get("array_type", "Rectangular")
    t = yield ctx.keyword("Enter the type of array", ["Rectangular", "Polar"], last)
    if t.kind != "keyword":
        return
    ctx.mem["array_type"] = t.value
    if t.value == "Rectangular":
        arr = yield from _classic_rect(ctx, ents)
    else:
        arr = yield from _classic_polar(ctx, ents)
    if arr is not None:
        _spawn(ctx, arr, ents, False)


def _handles(args):
    raw = args.get("objects", args.get("handles"))
    if raw is None:
        raise CommandError("No objects to array.")
    return [int(h) for h in raw]


def _flag(args, name, default):
    v = args.get(name, default)
    return default if v is None else bool(v)


def _pt(v):
    return geom.as_pt(v)


def _vals(arr, args, names):
    for src, dst in names:
        if src in args and args[src] is not None:
            setattr(arr, dst, args[src])


def _rect_args(ctx, ents, args):
    arr = new_array(ctx, "rect", ents)
    arr.rows = int(args.get("rows", 3))
    arr.columns = int(args.get("columns", 4))
    arr.levels = int(args.get("levels", 1))
    arr.row_spacing = float(args.get("row_spacing", 1.0))
    arr.column_spacing = float(args.get("column_spacing", 1.0))
    arr.level_spacing = float(args.get("level_spacing", arr.row_spacing))
    arr.row_elevation = float(args.get("row_elevation", 0.0))
    arr.axis_angle = math.radians(float(args.get("axis_angle", 0.0)))
    if args.get("base_point") is not None:
        arr.base = _pt(args["base_point"])
    if min(arr.rows, arr.columns, arr.levels) < 1:
        raise CommandError("Counts must be at least 1.")
    return arr


def _polar_args(ctx, ents, args):
    arr = new_array(ctx, "polar", ents)
    c = args.get("center", args.get("centre"))
    if c is None:
        raise CommandError("A center point is required.")
    arr.center = _pt(c)
    arr.items = int(args.get("count", 6))
    fill = math.radians(float(args.get("angle", 360.0)))
    if abs(fill) < 1e-12:
        raise CommandError("Requires a nonzero angle.")
    if abs(fill) > geom.TAU + 1e-9:
        raise CommandError("The items would span more than 360 degrees; enter a smaller angle or fewer items.")
    arr.fill_angle = fill
    arr.rotate_items = _flag(args, "rotate", True)
    arr.rows = int(args.get("rows", 1))
    arr.row_spacing = float(args.get("row_spacing", arr.row_spacing))
    arr.row_elevation = float(args.get("row_elevation", 0.0))
    arr.levels = int(args.get("levels", 1))
    arr.level_spacing = float(args.get("level_spacing", arr.row_spacing))
    if args.get("base_point") is not None:
        arr.base = _pt(args["base_point"])
    if min(arr.items, arr.rows, arr.levels) < 1:
        raise CommandError("Counts must be at least 1.")
    return arr


def _path_args(ctx, ents, args):
    pe, cur = path_entity(ctx, args.get("path"))
    ents = [e for e in ents if e.handle != pe.handle]
    if not ents:
        raise CommandError("Select objects to array.")
    arr = new_array(ctx, "path", ents)
    set_path(arr, pe, cur)
    if args.get("spacing") is not None:
        arr.path_method = "spacing"
        arr.path_spacing = float(args["spacing"])
        if arr.path_spacing <= 0:
            raise CommandError("Requires a nonzero distance.")
    else:
        arr.items = int(args.get("count", 6))
        if arr.items < 1:
            raise CommandError("Counts must be at least 1.")
    arr.align = _flag(args, "align", True)
    arr.levels = int(args.get("levels", 1))
    arr.level_spacing = float(args.get("level_spacing", 1.0))
    if args.get("base_point") is not None:
        arr.base = _pt(args["base_point"])
    return arr, ents


def _build_args(ctx, shape, args):
    ents = _gather(ctx, _handles(args))
    if shape == "rect":
        return _rect_args(ctx, ents, args), ents
    if shape == "polar":
        return _polar_args(ctx, ents, args), ents
    return _path_args(ctx, ents, args)


def _run_args(ctx, shape, args, assoc_default):
    arr, ents = _build_args(ctx, shape, args)
    assoc = _flag(args, "associative", assoc_default)
    return _spawn(ctx, arr, ents, assoc)


@executes("arrayrect")
def arrayrect_exec(ctx, args):
    return _run_args(ctx, "rect", args, _assoc_default(ctx))


@executes("arraypolar")
def arraypolar_exec(ctx, args):
    return _run_args(ctx, "polar", args, _assoc_default(ctx))


@executes("arraypath")
def arraypath_exec(ctx, args):
    return _run_args(ctx, "path", args, True)


@executes("array")
def array_exec(ctx, args):
    t = str(args.get("type", "rectangular")).lower()
    if t not in ("rectangular", "rect", "polar", "path"):
        raise CommandError("Array type must be rectangular, polar or path.")
    shape = "rect" if t.startswith("rect") else t
    return _run_args(ctx, shape, args, True if shape == "path" else _assoc_default(ctx))


@executes("-array")
def array_classic_exec(ctx, args):
    t = str(args.get("type", "rectangular")).lower()
    ents = _gather(ctx, _handles(args))
    if t.startswith("rect"):
        rows, cols = int(args.get("rows", 1)), int(args.get("columns", 1))
        sp = args.get("spacing")
        rs = args.get("row_spacing", sp[0] if isinstance(sp, (list, tuple)) else sp)
        cs = args.get("column_spacing", sp[1] if isinstance(sp, (list, tuple)) else sp)
        if rows > 1 and not rs:
            raise CommandError("Requires a nonzero distance.")
        if cols > 1 and not cs:
            raise CommandError("Requires a nonzero distance.")
        arr = new_array(ctx, "rect", ents, rows=rows, columns=cols, levels=1)
        arr.row_spacing = float(rs or 0.0)
        arr.column_spacing = float(cs or 0.0)
    elif t == "polar":
        c = args.get("center", args.get("centre"))
        if c is None:
            raise CommandError("A center point is required.")
        n = int(args.get("count", 6))
        fill = math.radians(float(args.get("angle", 360.0)))
        if abs(fill) < 1e-12:
            raise CommandError("Requires a nonzero angle.")
        arr = new_array(ctx, "polar", ents, items=n, fill_angle=fill, rotate_items=_flag(args, "rotate", True), levels=1, rows=1)
        arr.center = _pt(c)
        arr.base = _pt(args["base"]) if args.get("base") is not None else ref_point(ents[-1])
    else:
        raise CommandError("Array type must be rectangular or polar.")
    return _spawn(ctx, arr, ents, False)


def being_edited(ctx):
    for e in ctx.d.ents.values():
        if e.kind == "assoc_array" and e.editing:
            return e
    return None


def _refuse_editing(arr) -> None:
    if arr.editing:
        raise CommandError("An array's source objects are being edited; enter ARRAYCLOSE first.")


def item_at(arr, point):
    srcs = arr.source_entities()
    base_box = _union(srcs)
    best, bd = None, None
    for key, d, rot, about in arr.frames():
        rep = arr.replacement_for(key)
        box = _union(arr.item_objects(key)) if rep is not None else base_box
        m = A.frame_matrix(d, rot, about)
        corners = [[m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]] for x, y in ((box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3]))]
        if _inside(corners, point):
            cx = sum(p[0] for p in corners) / 4.0
            cy = sum(p[1] for p in corners) / 4.0
            dist = math.hypot(cx - point[0], cy - point[1])
            if bd is None or dist < bd:
                best, bd = key, dist
    return best


def _inside(poly, pt, tol=1e-9) -> bool:
    sign = 0
    for i in range(4):
        a, b = poly[i], poly[(i + 1) % 4]
        cr = (b[0] - a[0]) * (pt[1] - a[1]) - (b[1] - a[1]) * (pt[0] - a[0])
        if abs(cr) <= tol:
            continue
        s = 1 if cr > 0 else -1
        if sign and s != sign:
            return False
        sign = s
    return True


def _pick_array(ctx, prompt_text="Select array"):
    pre = [ctx.d.get(h) for h in ctx.doc.selection if ctx.d.get(h) is not None and ctx.d.get(h).kind == "assoc_array"]
    if len(pre) == 1 and len(ctx.doc.selection) == 1:
        h = pre[0].handle
        ctx.doc.selection = []
        return h
    while True:
        r = yield ctx.entity(prompt_text)
        if r.kind != "entity":
            return None
        e = ctx.d.get(int(r.value.get("handle", 0)))
        if e is None or e.kind != "assoc_array":
            ctx.say("The object is not an associative array.")
            continue
        return e.handle


def _item_prompt(ctx, arr, msg, options=()):
    p = Prompt(msg, ("entity", "text"), list(options))
    return p


def _resolve_item(ctx, arr, r):
    if r.kind == "text":
        try:
            key = A.key_of(r.value)
        except ValueError:
            ctx.say("No array item there; select an item of the array.")
            return None
        if arr.frame_of(key) is None:
            ctx.say("No array item there; select an item of the array.")
            return None
        return key
    if r.kind != "entity":
        return None
    v = r.value
    if int(v.get("handle", 0)) != arr.handle:
        ctx.say("No array item there; select an item of the array.")
        return None
    key = item_at(arr, v.get("point", [0.0, 0.0]))
    if key is None:
        ctx.say("No array item there; select an item of the array.")
    return key


def _replace_objects(ctx, arr, objs, base, key):
    frame_base = arr.base
    shift = [frame_base[0] - base[0], frame_base[1] - base[1], 0.0]
    dicts = []
    for e in objs:
        c = e.copy_as_new()
        c.move_by(shift)
        data = c.to_dict()
        data["handle"] = 0
        dicts.append(data)
    arr.replacements = [r for r in arr.replacements if tuple(r["item"]) != tuple(key)]
    arr.replacements.append({"item": list(key), "base": list(frame_base), "objects": dicts})


def _place_source(ctx, arr, key):
    fr = arr.frame_of(key)
    if fr is None:
        raise CommandError("No array item there; select an item of the array.")
    d, rot, about = fr
    objs = arr.realize(arr.item_objects(key), d, rot, about)
    handles = []
    for e in objs:
        handles.append(ctx.d.add_entity(e, ctx.doc.current_space))
    arr.editing = {"item": list(key), "handles": handles, "frame": {"d": list(d), "rot": rot, "about": list(about) if about else None}}
    ctx.say("Source objects of item %s placed for editing; enter ARRAYCLOSE when done." % A.key_text(key))
    return handles


def _edit_options(arr):
    if arr.shape == "rect":
        return ["Source", "REPlace", "Base point", "Rows", "Columns", "Levels", "RESet", "eXit"]
    if arr.shape == "polar":
        return ["Source", "REPlace", "Base point", "Items", "Angle between", "Fill angle", "Rows", "Levels", "ROTate items", "RESet", "eXit"]
    return ["Source", "REPlace", "Base point", "Items", "Spacing", "Align items", "Levels", "RESet", "eXit"]


def _modify(ctx, handle):
    return ctx.d.modify(handle)


@command("arrayedit", group="modify", label="Edit Array", description="Edit an associative array, replace items or edit the source objects.", menu="Modify > Object > Array")
def arrayedit(ctx):
    h = yield from _pick_array(ctx)
    if h is None:
        return
    arr = _modify(ctx, h)
    _refuse_editing(arr)
    while True:
        r = yield _edit_prompt(ctx, arr, _edit_options(arr), "Enter an option")
        if r.kind != "keyword" or r.value == "eXit":
            break
        k = r.value
        if k == "Source":
            while True:
                it = yield _item_prompt(ctx, arr, "Select item in array")
                if it.kind not in ("entity", "text"):
                    break
                key = _resolve_item(ctx, arr, it)
                if key is None:
                    continue
                _place_source(ctx, arr, key)
                return
        elif k == "REPlace":
            yield from _flow_replace(ctx, arr)
        elif k == "Base point":
            yield from _flow_base(ctx, arr)
        elif k == "Rows":
            yield from _flow_rows(ctx, arr, arr.shape != "path")
        elif k == "Columns":
            yield from _flow_columns(ctx, arr)
        elif k == "Levels":
            yield from _flow_levels(ctx, arr)
        elif k == "Items":
            if arr.shape == "path":
                yield from _flow_path_items(ctx, arr)
            else:
                yield from _flow_items(ctx, arr)
        elif k == "Angle between":
            yield from _flow_between(ctx, arr)
        elif k == "Fill angle":
            yield from _flow_fill(ctx, arr)
        elif k == "ROTate items":
            yield from _flow_rotate(ctx, arr)
        elif k == "Spacing":
            yield from _flow_path_spacing(ctx, arr)
        elif k == "Align items":
            yield from _flow_align(ctx, arr)
        elif k == "RESet":
            arr.replacements = []
            ctx.say("Replacements removed.")


def _flow_replace(ctx, arr):
    while True:
        s = yield ctx.select("Select replacement objects")
        if s.kind != "selection" or not s.value:
            return
        if arr.handle in s.value:
            ctx.say("An array's items can't contain the array itself." if len(s.value) > 1 else "Select objects other than the array.")
            continue
        break
    objs = _gather(ctx, s.value)
    c = _centre(_union(objs))
    b = yield ctx.point("Select base point of replacement objects", default=c)
    base = c if b.kind != "point" else [b.value[0], b.value[1], 0.0]
    consumed = False
    while True:
        r = yield _item_prompt(ctx, arr, "Select an item in array to replace", ["Source objects"])
        if r.kind == "keyword" and r.value == "Source objects":
            arr.replacements = []
            ctx.say("All items now follow the source objects.")
            continue
        if r.kind not in ("entity", "text"):
            break
        key = _resolve_item(ctx, arr, r)
        if key is None:
            continue
        _replace_objects(ctx, arr, objs, base, key)
        if not consumed:
            for e in objs:
                ctx.d.erase_entity(e.handle)
            consumed = True
        ctx.say("Item %s replaced." % A.key_text(key))
    if not consumed:
        return


def _close(ctx, arr, save):
    ed = arr.editing
    handles = [h for h in ed["handles"] if h in ctx.d.ents]
    if save:
        if not handles:
            raise CommandError("The source would have no objects; enter ARRAYCLOSE No to discard the changes, or erase the array.")
        fr = ed["frame"]
        objs = [ctx.d.get(h).copy_as_new() for h in handles]
        objs = arr.unrealize(objs, fr["d"], fr["rot"], fr["about"])
        dicts = []
        for e in objs:
            data = e.to_dict()
            data["handle"] = 0
            dicts.append(data)
        key = tuple(ed["item"])
        rep = arr.replacement_for(key)
        if rep is not None:
            rep["objects"] = dicts
        else:
            arr.source = dicts
    for h in handles:
        ctx.d.erase_entity(h)
    arr.editing = None
    ctx.say("Array source changes saved." if save else "Array source changes discarded.")


@command("arrayclose", group="modify", label="Close Array Editing", description="End array source editing, saving or discarding the changes.", menu="")
def arrayclose(ctx):
    arr = being_edited(ctx)
    if arr is None:
        ctx.say("No array is being edited.")
        return
    r = yield ctx.yesno("Save changes to array?", "Yes")
    if r.kind != "keyword":
        return
    _close(ctx, _modify(ctx, arr.handle), r.value == "Yes")


@executes("arrayclose")
def arrayclose_exec(ctx, args):
    arr = being_edited(ctx)
    if arr is None:
        raise CommandError("No array is being edited.")
    _close(ctx, _modify(ctx, arr.handle), _flag(args, "save", True))
    return {"array": arr.handle}


def _set_pairs(arr, args, pairs):
    for name, attr, conv in pairs:
        if args.get(name) is not None:
            setattr(arr, attr, conv(args[name]))


def _int_min1(v):
    n = int(v)
    if n < 1:
        raise CommandError("Counts must be at least 1.")
    return n


def _nonzero(v):
    f = float(v)
    if abs(f) < EPS:
        raise CommandError("Requires a nonzero distance.")
    return f


@executes("arrayedit")
def arrayedit_exec(ctx, args):
    h = int(args.get("array", args.get("handle", 0)))
    e = ctx.d.get(h)
    if e is None or e.kind != "assoc_array":
        raise CommandError("The object is not an associative array.")
    if not e.source:
        raise CommandError("The array's source block is missing.")
    arr = _modify(ctx, h)
    _refuse_editing(arr)
    keep = {k: getattr(arr, k) for k in ("columns", "rows", "levels", "items", "column_spacing", "row_spacing", "level_spacing", "row_elevation", "axis_angle", "fill_angle", "rotate_items", "center", "base", "path_method", "path_spacing", "align")}
    _set_pairs(arr, args, [("columns", "columns", _int_min1), ("rows", "rows", _int_min1), ("levels", "levels", _int_min1), ("count", "items", _int_min1), ("items", "items", _int_min1), ("column_spacing", "column_spacing", _nonzero), ("row_spacing", "row_spacing", _nonzero), ("level_spacing", "level_spacing", _nonzero), ("row_elevation", "row_elevation", float), ("axis_angle", "axis_angle", lambda v: math.radians(float(v))), ("fill_angle", "fill_angle", lambda v: math.radians(float(v))), ("rotate", "rotate_items", bool), ("center", "center", _pt), ("base_point", "base", _pt), ("align", "align", bool)])
    if args.get("spacing") is not None and arr.shape == "path":
        arr.path_method = "spacing"
        arr.path_spacing = _nonzero(args["spacing"])
    if args.get("count") is not None and arr.shape == "path":
        arr.path_method = "count"
    if args.get("angle_between") is not None:
        v = math.radians(float(args["angle_between"]))
        n = max(int(arr.items), 1)
        if abs(abs(v) * n - geom.TAU) < 1e-9:
            arr.fill_angle = math.copysign(geom.TAU, v)
        else:
            fill = v * (n - 1) if n > 1 else v
            if abs(fill) > geom.TAU + 1e-9:
                raise CommandError("The items would span more than 360 degrees; enter a smaller angle or fewer items.")
            arr.fill_angle = fill
    if abs(arr.fill_angle) > geom.TAU + 1e-9:
        for k, v in keep.items():
            setattr(arr, k, v)
        raise CommandError("The items would span more than 360 degrees; enter a smaller angle or fewer items.")
    if abs(arr.fill_angle) < 1e-12:
        for k, v in keep.items():
            setattr(arr, k, v)
        raise CommandError("Requires a nonzero angle.")
    if args.get("path") is not None and arr.shape == "path":
        pe, cur = path_entity(ctx, args["path"])
        set_path(arr, pe, cur)
    if args.get("reset"):
        arr.replacements = []
    rep = args.get("replace")
    if rep:
        objs = _gather(ctx, [int(x) for x in rep.get("objects", [])])
        if arr.handle in [o.handle for o in objs]:
            raise CommandError("An array's items can't contain the array itself.")
        c = _centre(_union(objs))
        base = _pt(rep["base_point"]) if rep.get("base_point") is not None else c
        items = rep.get("items", [])
        if items == "source":
            arr.replacements = []
        else:
            for it in items:
                key = A.key_of(it)
                if arr.frame_of(key) is None:
                    raise CommandError("No array item there; select an item of the array.")
                _replace_objects(ctx, arr, objs, base, key)
            for o in objs:
                ctx.d.erase_entity(o.handle)
    for ov in args.get("override", []) or []:
        key = A.key_of(ov["item"])
        if arr.frame_of(key) is None:
            raise CommandError("No array item there; select an item of the array.")
        arr.overrides = [x for x in arr.overrides if tuple(x["item"]) != key]
        rec = {"item": list(key)}
        for name in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible"):
            if name in ov:
                rec[name] = ov[name]
        arr.overrides.append(rec)
    if args.get("clear_overrides"):
        arr.overrides = []
    if args.get("source_item") is not None:
        _place_source(ctx, arr, A.key_of(args["source_item"]))
    if arr.total_objects() > min(_limit(ctx), A.HARD_LIMIT):
        for k, v in keep.items():
            setattr(arr, k, v)
        raise CommandError("The array would create %d objects; the limit is %d." % (arr.total_objects(), min(_limit(ctx), A.HARD_LIMIT)))
    return {"array": h, "items": arr.count(), "editing": bool(arr.editing)}
