import json

from app.bodies import configs, massprops, materials, multibody, refgeo
from app.cmd import barred
from app.cmd.commands.solids import bodies_of, xyz
from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.param import ops
from app.param import store as S
from app.solid.work import SolidError

FAILURES = (multibody.BodyError, configs.ConfigError, refgeo.RefError, materials.MaterialError, massprops.MassError, S.ParamError, SolidError, ValueError, KeyError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ops.Refused as err:
        raise CommandError(err.message)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def handles_arg(args, key="handles"):
    raw = args.get(key)
    if raw is None and args.get("handle") is not None:
        raw = [args["handle"]]
    if not isinstance(raw, list) or not raw:
        raise CommandError("Give %s as a list of body handles." % key)
    try:
        return [int(h) for h in raw]
    except (TypeError, ValueError):
        raise CommandError("%s must be whole numbers." % key)


def pick_bodies(ctx, message, one=False):
    sel = yield ctx.select(message, pick_one=one)
    if sel.kind != "selection":
        return []
    return [b.handle for b in bodies_of(ctx, sel.value)]


@command("combine", aliases=("combinebodies",), group="solids", label="Combine Bodies", description="Add, subtract or intersect solid bodies.", menu="Modify > 3D Operations > Combine")
def combine_cmd(ctx):
    k = yield ctx.keyword("Combine [Add/Subtract/Common]", ["Add", "Subtract", "Common"], "Add")
    op = (k.value if k.kind == "keyword" else "Add").lower()
    main = yield from pick_bodies(ctx, "Select the main body", True)
    if not main:
        ctx.say("Select a solid.")
        return
    rest = yield from pick_bodies(ctx, "Select the other bodies")
    rest = [h for h in rest if h != main[0]]
    if not rest:
        ctx.say("Select at least one more solid.")
        return
    res = run(multibody.combine, ctx.d, op, main + rest)
    ctx.say("COMBINE: " + res["message"])


@executes("combine")
def combine_exec(ctx, args):
    op = str(args.get("op") or "add").lower()
    return run(multibody.combine, ctx.d, op, handles_arg(args), bool(args.get("keep_tools", False)), args.get("fuzzy"), bool(args.get("force", False)), bool(args.get("retry", True)))


@command("splitbody", aliases=("splitsolid",), group="solids", label="Split Body", description="Cut a solid body into pieces with a plane or a surface body.", menu="Modify > 3D Operations > Split Body")
def split_cmd(ctx):
    body = yield from pick_bodies(ctx, "Select the body to split", True)
    if not body:
        ctx.say("Select a solid.")
        return
    k = yield ctx.keyword("Cut with [Points/Reference/Surface]", ["Points", "Reference", "Surface"], "Points")
    mode = k.value if k.kind == "keyword" else "Points"
    planes, tools = [], []
    if mode == "Points":
        pts = []
        for msg in ("Specify first point on the plane", "Specify second point", "Specify third point"):
            r = yield ctx.point(msg)
            if r.kind != "point":
                return
            pts.append(xyz(r.value))
        from app.solid import planes as P

        try:
            pl = P.through_points(*pts)
        except P.PlaneError as err:
            raise CommandError(str(err))
        planes.append({"origin": pl["origin"], "normal": pl["z"]})
    elif mode == "Reference":
        t = yield ctx.text("Enter the name of a reference plane")
        if t.kind != "text":
            return
        planes.append({"ref": str(t.value)})
    else:
        tools = yield from pick_bodies(ctx, "Select the surface body")
        if not tools:
            return
    res = run(multibody.split, ctx.d, body[0], planes, tools)
    ctx.say("SPLITBODY: " + res["message"])


@executes("splitbody")
def split_exec(ctx, args):
    h = args.get("handle")
    if h is None:
        h = handles_arg(args)[0]
    return run(multibody.split, ctx.d, int(h), args.get("planes") or [], [int(t) for t in args.get("tools") or []], bool(args.get("keep_tools", True)), args.get("fuzzy"), bool(args.get("force", False)))


def pick_motion(ctx, copy):
    k = yield ctx.keyword("Motion [Translate/Rotate]", ["Translate", "Rotate"], "Translate")
    if k.kind != "keyword" or k.value == "Translate":
        base = yield ctx.point("Specify base point")
        if base.kind != "point":
            return None
        to = yield ctx.point("Specify second point", base=base.value)
        if to.kind != "point":
            return None
        b, t = xyz(base.value), xyz(to.value)
        return {"translate": [t[0] - b[0], t[1] - b[1], t[2] - b[2]], "rotate": None}
    c = yield ctx.point("Specify point on the rotation axis")
    if c.kind != "point":
        return None
    ang = yield ctx.number("Specify rotation angle in degrees")
    if ang.kind != "number":
        return None
    return {"translate": None, "rotate": {"origin": xyz(c.value), "axis": [0.0, 0.0, 1.0], "degrees": float(ang.value)}}


@command("movecopybody", aliases=("mcb", "copybody"), group="solids", label="Move or Copy Body", description="Move solid bodies, or copy them into new bodies.", menu="Modify > 3D Operations > Move/Copy Body")
def movecopy_cmd(ctx):
    found = yield from pick_bodies(ctx, "Select bodies")
    if not found:
        ctx.say("Select solids.")
        return
    k = yield ctx.keyword("Action [Move/Copy]", ["Move", "Copy"], "Move")
    copy = k.kind == "keyword" and k.value == "Copy"
    motion = yield from pick_motion(ctx, copy)
    if motion is None:
        return
    count = 1
    if copy:
        n = yield ctx.number("Number of copies", default=1, integer=True, positive=True)
        count = int(n.value) if n.kind == "number" else 1
    res = run(multibody.copy_bodies, ctx.d, found, motion, count) if copy else run(multibody.move, ctx.d, found, motion)
    ctx.say("MOVECOPYBODY: " + res["message"])


@executes("movecopybody")
def movecopy_exec(ctx, args):
    motion = {"translate": args.get("translate"), "rotate": args.get("rotate")}
    handles = handles_arg(args)
    if args.get("copy"):
        return run(multibody.copy_bodies, ctx.d, handles, motion, args.get("count", 1))
    return run(multibody.move, ctx.d, handles, motion)


@command("refgeo", aliases=("refplane", "refaxis", "refpoint", "refcs"), group="solids", label="Reference Geometry", description="Planes, axes, points and coordinate systems used as references.", menu="Insert > Reference Geometry")
def refgeo_cmd(ctx):
    k = yield ctx.keyword("Make [Plane/Axis/Point/Cs]", ["Plane", "Axis", "Point", "Cs"], "Plane")
    kind = (k.value if k.kind == "keyword" else "Plane").lower()
    need = {"plane": 3, "axis": 2, "point": 1, "cs": 3}[kind]
    labels = {"cs": ("Specify origin", "Specify a point on the x axis", "Specify a point in the xy plane")}.get(kind, ("Specify first point", "Specify second point", "Specify third point"))
    pts = []
    for i in range(need):
        r = yield ctx.point(labels[i])
        if r.kind != "point":
            return
        pts.append(xyz(r.value))
    if kind == "plane":
        item = run(refgeo.create, ctx.d, "plane", "three_points", {"points": pts})
    elif kind == "axis":
        item = run(refgeo.create, ctx.d, "axis", "two_points", {"points": pts})
    elif kind == "point":
        item = run(refgeo.create, ctx.d, "point", "coordinates", {"xyz": pts[0]})
    else:
        item = run(refgeo.create, ctx.d, "cs", "three_points", {"origin": pts[0], "x_point": pts[1], "y_point": pts[2]})
    ctx.say("REFGEO: %s created." % item["name"])


@executes("refgeo")
def refgeo_exec(ctx, args):
    action = str(args.get("action") or "create").lower()
    d = ctx.d
    if action == "create":
        params = args.get("params")
        if not isinstance(params, dict):
            raise CommandError("Give params as an object.")
        return run(refgeo.create, d, str(args.get("kind", "")).lower(), str(args.get("method", "")).lower(), params, args.get("name"))
    if action == "edit":
        return run(refgeo.update, d, str(args.get("name", "")), args.get("params"), args.get("new_name"), args.get("visible"))
    if action == "delete":
        return run(refgeo.delete, d, str(args.get("name", "")))
    if action == "rebuild":
        return run(refgeo.rebuild, d)
    if action == "list":
        return {"items": refgeo.describe(d)}
    raise CommandError("action is create, edit, delete, rebuild or list.")


@command("config", aliases=("configurations",), group="solids", label="Configurations", description="Switch, add or remove configurations.", menu="Tools > Configurations")
def config_cmd(ctx):
    k = yield ctx.keyword("Configuration [Activate/New/Delete/List]", ["Activate", "New", "Delete", "List"], "Activate")
    action = (k.value if k.kind == "keyword" else "Activate").lower()
    if action == "list":
        info = run(configs.listing, ctx.d)
        for rec in info["configs"]:
            ctx.say("%s%s" % (rec["name"], " (active)" if rec["name"] == info["active"] else ""))
        return
    t = yield ctx.text("Enter configuration name")
    if t.kind != "text":
        return
    name = str(t.value)
    if action == "new":
        run(configs.create, ctx.d, name)
    elif action == "delete":
        run(configs.delete, ctx.d, name)
    else:
        run(configs.activate, ctx.d, name)
    ctx.say("CONFIG: %s done." % action)


@executes("config")
def config_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    d = ctx.d
    name = str(args.get("name") or "")
    if action == "list":
        return run(configs.listing, d)
    if action == "create":
        return run(configs.create, d, name, args.get("description", ""), args.get("values"), args.get("suppress"), args.get("materials"), args.get("copy_from"))
    if action == "edit":
        return run(configs.update, d, name, args.get("description"), args.get("values"), args.get("suppress"), args.get("materials"), args.get("new_name"))
    if action == "delete":
        return run(configs.delete, d, name)
    if action == "activate":
        return run(configs.activate, d, name)
    raise CommandError("action is list, create, edit, delete or activate.")


@command("designtable", aliases=("dtable",), group="solids", label="Design Table", description="Export or import the table of configurations against parameters as CSV.", menu="Tools > Design Table")
def designtable_cmd(ctx):
    k = yield ctx.keyword("Design table [Export/Import/Show]", ["Export", "Import", "Show"], "Show")
    action = (k.value if k.kind == "keyword" else "Show").lower()
    if action == "show":
        g = run(configs.grid, ctx.d)
        ctx.say("%d rows, %d columns." % (len(g["rows"]), len(g["columns"])))
        return
    t = yield ctx.text("Enter the table file name")
    if t.kind != "text":
        return
    refused = barred.args_refusal(ctx.runner, COMMANDS["designtable"], {"path": str(t.value)})
    if refused:
        raise CommandError(refused)
    res = run(configs.export_file if action == "export" else configs.import_file, ctx.d, str(t.value))
    ctx.say("DESIGNTABLE: %s done." % action)
    return res


@executes("designtable")
def designtable_exec(ctx, args):
    action = str(args.get("action") or "show").lower()
    if action == "show":
        return run(configs.grid, ctx.d)
    if action == "set":
        return run(configs.apply_grid, ctx.d, {"rows": args.get("rows")})
    if action not in ("export", "import"):
        raise CommandError("action is show, set, export or import.")
    path = args.get("path")
    if not path:
        raise CommandError("Give path.")
    return run(configs.export_file if action == "export" else configs.import_file, ctx.d, str(path))


@command("material", aliases=("setmaterial",), group="solids", label="Apply Material", description="Give solid bodies a material from the library.", menu="Edit > Appearance > Material")
def material_cmd(ctx):
    found = yield from pick_bodies(ctx, "Select bodies")
    if not found:
        ctx.say("Select solids.")
        return
    t = yield ctx.text("Enter material name (empty to clear)")
    if t.kind not in ("text", "enter"):
        return
    name = str(t.value or "") if t.kind == "text" else ""
    for h in found:
        run(materials.assign, ctx.d, multibody.solid(ctx.d, h), name)
    ctx.say("MATERIAL: set on %d body(ies)." % len(found))


@executes("material")
def material_exec(ctx, args):
    name = str(args.get("material") or "")
    out = [run(materials.assign, ctx.d, multibody.solid(ctx.d, h), name, bool(args.get("refresh", False))) for h in handles_arg(args)]
    return {"assigned": out}


@command("materiallib", group="settings", label="Materials Library", description="Add, change or remove materials in your own library.", menu="Tools > Materials Library", undoable=False)
def materiallib_cmd(ctx):
    info = materials.library()
    for row in info["materials"]:
        ctx.say("%s: density %g kg/m3, E %g GPa, nu %g (%s)" % (row["name"], row["density"], row["youngs_modulus"], row["poissons_ratio"], row["origin"]))


@executes("materiallib")
def materiallib_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    row = args.get("material") if isinstance(args.get("material"), dict) else {}
    if action == "list":
        return materials.library()
    if action == "add":
        return run(materials.add_user, row)
    if action == "edit":
        return run(materials.update_user, str(args.get("name", "")), row)
    if action == "delete":
        return run(materials.delete_user, str(args.get("name", "")))
    raise CommandError("action is list, add, edit or delete.")


@command("bodymass", aliases=("massprops3d",), group="inquiry", label="Mass Properties of Bodies", description="Mass, volume, area, centre of mass and inertia of solid bodies, about the centre of mass and a chosen coordinate system.", menu="Tools > Inquiry > Mass Properties", undoable=False)
def bodymass_cmd(ctx):
    found = yield from pick_bodies(ctx, "Select bodies (Enter for all)")
    res = run(massprops.compute, ctx.d, found)
    report_mass(ctx, res)


def report_mass(ctx, res):
    if res.get("volume") is None:
        ctx.say(res.get("note", "No volume."))
        return
    ctx.say("Volume: %g mm3" % res["volume"])
    ctx.say("Surface area: %g mm2" % res["area"])
    if res.get("mass") is not None:
        ctx.say("Mass: %g kg" % res["mass"])
    c = res["centroid"]
    ctx.say("Centre of mass: %g, %g, %g mm" % (c[0], c[1], c[2]))


@executes("bodymass")
def bodymass_exec(ctx, args):
    handles = [int(h) for h in args.get("handles") or []]
    res = run(massprops.compute, ctx.d, handles, args.get("cs"), args.get("density"))
    report_mass(ctx, res)
    return json.loads(json.dumps(res))
