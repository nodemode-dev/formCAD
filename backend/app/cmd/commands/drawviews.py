from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import layouts
from app.solid.work import SolidError
from app.views import hook, model, ops
from app.views.model import ViewError

FAILURES = (ViewError, layouts.LayoutError, SolidError, ValueError, KeyError, TypeError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def guard_source(ctx, args):
    src = args.get("source") or {}
    if isinstance(src, dict) and src.get("doc") and barred.caller(getattr(ctx, "runner", None)):
        raise CommandError("A macro or outside agent cannot point a view at another file.")


def done(ctx, h, what):
    d = ctx.doc.drawing
    v = ops.get(d, h)
    msg = "%s %s: %s." % (what, v.name, v.state.get("status", ""))
    ctx.say(msg)
    return {"handle": h, "name": v.name, "message": msg, "state": v.state, "bounds": list(v.bounds())}


def local_of(ctx, view, p):
    return model.to_local(view, view.unit_mm or 1.0, p)


@command("viewbase", group="layout", label="Base View", description="Place a base drawing view of the model on the current layout.", menu="Draw > Drawing View > Base View")
def viewbase(ctx):
    dr = yield ctx.word("Direction [front/back/left/right/top/bottom/iso]", ["front", "back", "left", "right", "top", "bottom", "iso"], "front")
    if dr.kind not in ("keyword", "text"):
        return
    sc = yield ctx.text("Scale (for example 1:2)", "1:1")
    if sc.kind != "text":
        return
    p = yield ctx.point("Place the view")
    if p.kind != "point":
        return
    h = run(ops.create_base, ctx.doc, {"direction": str(dr.value), "scale": sc.value, "position": [p.value[0], p.value[1]]})
    done(ctx, h, "Base view")


@executes("viewbase")
def viewbase_exec(ctx, args):
    guard_source(ctx, args)
    return done(ctx, run(ops.create_base, ctx.doc, args), "Base view")


@command("viewprojected", group="layout", label="Projected View", description="Add a view projected from an existing view.", menu="Draw > Drawing View > Projected View")
def viewprojected(ctx):
    pn = yield ctx.text("Parent view name", None)
    if pn.kind != "text":
        return
    rel = yield ctx.word("Side [top/bottom/left/right]", ["top", "bottom", "left", "right"], "right")
    if rel.kind not in ("keyword", "text"):
        return
    h = run(ops.create_projected, ctx.doc, {"parent": pn.value, "rel": str(rel.value)})
    done(ctx, h, "Projected view")


@executes("viewprojected")
def viewprojected_exec(ctx, args):
    return done(ctx, run(ops.create_projected, ctx.doc, args), "Projected view")


@command("viewaux", group="layout", label="Auxiliary View", description="Add a view looking square onto a picked straight edge of a view.", menu="Draw > Drawing View > Auxiliary View")
def viewaux(ctx):
    pn = yield ctx.text("Parent view name", None)
    if pn.kind != "text":
        return
    a = yield ctx.point("First end of the reference edge")
    if a.kind != "point":
        return
    b = yield ctx.point("Second end of the reference edge", base=a.value)
    if b.kind != "point":
        return
    parent = run(ops.find, ctx.doc.drawing, pn.value)
    line = [local_of(ctx, parent, a.value), local_of(ctx, parent, b.value)]
    h = run(ops.create_aux, ctx.doc, {"parent": pn.value, "edge": {"line": line}})
    done(ctx, h, "Auxiliary view")


@executes("viewaux")
def viewaux_exec(ctx, args):
    return done(ctx, run(ops.create_aux, ctx.doc, args), "Auxiliary view")


@command("viewsection", group="layout", label="Section View", description="Add a full, half, offset or aligned section from a section line drawn on a view.", menu="Draw > Drawing View > Section View")
def viewsection(ctx):
    pn = yield ctx.text("Parent view name", None)
    if pn.kind != "text":
        return
    kind = yield ctx.word("Kind [full/half/offset/aligned]", ["full", "half", "offset", "aligned"], "full")
    if kind.kind not in ("keyword", "text"):
        return
    parent = run(ops.find, ctx.doc.drawing, pn.value)
    pts = []
    need = {"full": 2, "half": 2, "aligned": 3}.get(str(kind.value), 3)
    while True:
        p = yield ctx.point("Next point of the section line" if pts else "First point of the section line", base=pts[-1] if pts else None)
        if p.kind != "point":
            break
        pts.append([p.value[0], p.value[1]])
        if str(kind.value) != "offset" and len(pts) == need:
            break
    if len(pts) < 2:
        return
    h = run(ops.create_section, ctx.doc, {"parent": pn.value, "kind": str(kind.value), "line": [local_of(ctx, parent, q) for q in pts]})
    done(ctx, h, "Section view")


@executes("viewsection")
def viewsection_exec(ctx, args):
    return done(ctx, run(ops.create_section, ctx.doc, args), "Section view")


@command("viewdetail", group="layout", label="Detail View", description="Add an enlarged circular detail of a view.", menu="Draw > Drawing View > Detail View")
def viewdetail(ctx):
    pn = yield ctx.text("Parent view name", None)
    if pn.kind != "text":
        return
    c = yield ctx.point("Centre of the detail circle")
    if c.kind != "point":
        return
    r = yield ctx.distance("Radius of the detail circle", positive=True, base=c.value)
    if r.kind != "value":
        return
    parent = run(ops.find, ctx.doc.drawing, pn.value)
    k = float(parent.scale) / (parent.unit_mm or 1.0)
    h = run(ops.create_detail, ctx.doc, {"parent": pn.value, "center": local_of(ctx, parent, c.value), "radius": r.value / k})
    done(ctx, h, "Detail view")


@executes("viewdetail")
def viewdetail_exec(ctx, args):
    return done(ctx, run(ops.create_detail, ctx.doc, args), "Detail view")


@command("viewbroken", group="layout", label="Broken View", description="Shorten a long view with break lines.", menu="Draw > Drawing View > Broken View")
def viewbroken(ctx):
    vn = yield ctx.text("View name", None)
    if vn.kind != "text":
        return
    ax = yield ctx.word("Direction of the break [x/y]", ["x", "y"], "x")
    if ax.kind not in ("keyword", "text"):
        return
    a = yield ctx.point("First break line")
    if a.kind != "point":
        return
    b = yield ctx.point("Second break line", base=a.value)
    if b.kind != "point":
        return
    v = run(ops.find, ctx.doc.drawing, vn.value)
    la, lb = local_of(ctx, v, a.value), local_of(ctx, v, b.value)
    i = 0 if str(ax.value) == "x" else 1
    lo, hi = sorted([la[i], lb[i]])
    h = run(ops.set_breaks, ctx.doc, v.handle, [{"axis": str(ax.value), "lo": lo, "hi": hi, "gap": min(5.0 / (v.scale or 1.0), (hi - lo) / 2.0), "style": "zigzag"}])
    done(ctx, h, "Broken view")


@executes("viewbroken")
def viewbroken_exec(ctx, args):
    v = run(ops.find, ctx.doc.drawing, args.get("view"))
    h = run(ops.set_breaks, ctx.doc, v.handle, args.get("breaks") or [], bool(args.get("clear")))
    return done(ctx, h, "Broken view")


@command("viewcrop", group="layout", label="Crop View", description="Hide everything outside a closed outline in a view.", menu="Draw > Drawing View > Crop View")
def viewcrop(ctx):
    vn = yield ctx.text("View name", None)
    if vn.kind != "text":
        return
    v = run(ops.find, ctx.doc.drawing, vn.value)
    pts = []
    while True:
        p = yield ctx.point("Next corner of the crop outline" if pts else "First corner of the crop outline", base=pts[-1] if pts else None)
        if p.kind != "point":
            break
        pts.append(local_of(ctx, v, p.value))
    if len(pts) < 3:
        return
    done(ctx, run(ops.set_crop, ctx.doc, v.handle, pts), "Cropped view")


@executes("viewcrop")
def viewcrop_exec(ctx, args):
    v = run(ops.find, ctx.doc.drawing, args.get("view"))
    h = run(ops.set_crop, ctx.doc, v.handle, args.get("polygon"), bool(args.get("clear")))
    return done(ctx, h, "Cropped view")


@command("viewupdate", group="layout", label="Update Views", description="Rebuild the views that are out of date.", menu="Draw > Drawing View > Update Views")
def viewupdate(ctx):
    got = run(ops.update_all, ctx.doc, True)
    ctx.say("%d view(s) updated." % len(got))


@executes("viewupdate")
def viewupdate_exec(ctx, args):
    if args.get("view") not in (None, ""):
        v = run(ops.find, ctx.doc.drawing, args["view"])
        run(ops.update, ctx.doc, v.handle)
        return done(ctx, v.handle, "Updated")
    got = run(ops.update_all, ctx.doc, not args.get("all"))
    return {"updated": got, "message": "%d view(s) updated." % len(got)}


@command("viewedit", group="layout", label="Edit View", description="Change a view: scale, label, edge classes, hidden lines, mode.", menu="Draw > Drawing View > Edit View")
def viewedit(ctx):
    vn = yield ctx.text("View name", None)
    if vn.kind != "text":
        return
    sc = yield ctx.text("New scale (Enter keeps it)", "")
    if sc.kind != "text":
        return
    if str(sc.value).strip():
        v = run(ops.find, ctx.doc.drawing, vn.value)
        run(ops.edit, ctx.doc, v.handle, {"scale": sc.value})
        ctx.say("View %s rescaled." % v.name)


@executes("viewedit")
def viewedit_exec(ctx, args):
    guard_source(ctx, {"source": (args.get("changes") or args).get("source")})
    v = run(ops.find, ctx.doc.drawing, args.get("view"))
    changes = args.get("changes")
    if changes is None:
        changes = {k: val for k, val in args.items() if k != "view"}
    run(ops.edit, ctx.doc, v.handle, changes)
    return done(ctx, v.handle, "Edited")


@command("viewdelete", group="layout", label="Delete View", description="Delete a drawing view.", menu="Draw > Drawing View > Delete View")
def viewdelete(ctx):
    vn = yield ctx.text("View name", None)
    if vn.kind != "text":
        return
    v = run(ops.find, ctx.doc.drawing, vn.value)
    gone = run(ops.delete, ctx.doc, v.handle, True)
    ctx.say("%d view(s) deleted." % len(gone))


@executes("viewdelete")
def viewdelete_exec(ctx, args):
    v = run(ops.find, ctx.doc.drawing, args.get("view"))
    gone = run(ops.delete, ctx.doc, v.handle, bool(args.get("cascade")))
    return {"deleted": gone, "message": "%d view(s) deleted." % len(gone)}


@command("viewprojection", group="layout", label="Projection Angle", description="Set the sheet's projection system to first or third angle.", menu="Draw > Drawing View > Projection Angle")
def viewprojection(ctx):
    kw = yield ctx.word("Projection [first/third]", ["first", "third"], "third")
    if kw.kind not in ("keyword", "text"):
        return
    layout = str(ctx.doc.tab)[7:] if str(ctx.doc.tab).startswith("layout:") else ""
    run(model.set_projection, ctx.doc.drawing, layout, str(kw.value))
    ctx.say("%s angle projection." % str(kw.value).capitalize())


@executes("viewprojection")
def viewprojection_exec(ctx, args):
    layout = args.get("layout") or (str(ctx.doc.tab)[7:] if str(ctx.doc.tab).startswith("layout:") else "")
    sys = run(model.set_projection, ctx.doc.drawing, layout, args.get("system") or args.get("angle"))
    return {"layout": layout, "projection": sys, "message": "%s angle projection." % sys.capitalize()}
