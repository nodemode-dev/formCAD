import json

from app.additive import jobs, service, store
from app.additive import settings as cfg
from app.additive.jobs import AdditiveError
from app.additive.placement import PlacementError
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.core.outputs import OutputRefused

GROUP = "solids"
ERRORS = (AdditiveError, store.AdditiveRecordError, cfg.SettingError, PlacementError, OutputRefused)
PRESET_WORDS = ["Balanced", "Quality", "Speed", "Strength", "Metal"]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ERRORS as err:
        raise CommandError(str(err))


def plate_of(ctx, args):
    h = store.header(ctx.d)
    wanted = args.get("plate")
    if wanted in (None, ""):
        if not h["plates"]:
            service_default_plate(ctx)
            h = store.header(ctx.d)
        return h["plates"][0]["id"]
    return store.need(h, "plates", str(wanted))["id"]


def service_default_plate(ctx):
    items = service.default_items(ctx.doc, None)
    if not store.header(ctx.d)["profiles"]:
        store.add_profile(ctx.d, {"name": "Standard", "preset": "standard"})
    h = store.header(ctx.d)
    items, _report = service.arrange_items(ctx.doc, items, h["profiles"][0]["settings"]["bed"], 4.0, None, jobs.QUIET, ctx.runner)
    store.add_plate(ctx.d, {"name": "Plate 1"}, items)


def ask_plate(ctx):
    t = yield ctx.text("Plate to use (Enter for the first plate)", "")
    return str(t.value).strip() if t.kind == "text" and t.value else ""


def do_slice(ctx, tid):
    res, last = run(service.do_slice, ctx.doc, tid, ctx.runner)
    store.set_last(ctx.d, tid, last)
    s = res.summary
    ctx.say("SLICE: %d layers, %.1f m of filament, about %s, support %.0f mm3, %d warning%s." % (s["layers"], s["filament_mm"] / 1000.0, s["print_time"], s["support_volume_mm3"], len(res.warnings), "" if len(res.warnings) == 1 else "s"))
    return {"plate": tid, "summary": s, "warnings": res.warnings, "hash": res.hash}


@command("slice", aliases=("sliceplate",), group=GROUP, label="Slice Plate", description="Slice the bodies of a build plate into layers, walls, infill, skins, supports and bridges, and estimate the filament and time.", menu="Manufacture > Additive > Slice Plate")
def slice_cmd(ctx):
    pid = yield from ask_plate(ctx)
    tid = run(plate_of, ctx, {"plate": pid})
    return do_slice(ctx, tid)


@executes("slice")
def slice_exec(ctx, args):
    return do_slice(ctx, run(plate_of, ctx, args))


@command("orientstudy", aliases=("orientation",), group=GROUP, label="Orientation Study", description="Rank build orientations of the bodies by support volume, height, surface steps and bed contact.", menu="Manufacture > Additive > Orientation Study")
def orient_cmd(ctx):
    k = yield ctx.keyword("Preset", PRESET_WORDS, "Balanced")
    if k.kind != "keyword":
        return
    handles = [r["handle"] for r in service.bodies.listing(ctx.doc)]
    return orient_run(ctx, {"bodies": handles, "preset": str(k.value).lower()})


def orient_run(ctx, args):
    rows = service.bodies.listing(ctx.doc)
    handles = args.get("bodies")
    if handles is None:
        handles = [r["handle"] for r in rows]
    try:
        handles = [int(h) for h in handles]
    except (TypeError, ValueError):
        raise CommandError("bodies must be handles (whole numbers).")
    if not handles:
        raise CommandError("There are no solid or mesh bodies to study.")
    preset = str(args.get("preset") or "balanced").lower()
    angle = float(args.get("angle", 45.0))
    if not 10.0 <= angle <= 80.0:
        raise CommandError("The angle is between 10 and 80 degrees.")
    h = store.header(ctx.d)
    layer_h = h["profiles"][0]["settings"]["layer_height"] if h["profiles"] else 0.2
    out = run(service.do_orient, ctx.doc, handles, preset, angle, max(1, min(int(args.get("top", 5)), 20)), layer_h, ctx.runner)
    best = out["candidates"][0]
    ctx.say("ORIENTSTUDY: best is %s, support volume %.0f mm3, height %.1f mm (%d orientations tried)." % (best["label"].lower(), best["terms"]["support_volume_mm3"], best["terms"]["height_mm"], out["evaluated"]))
    rank = args.get("apply")
    if rank not in (None, "", 0, False):
        tid = plate_of(ctx, args)
        plate = json.loads(json.dumps(store.need(store.header(ctx.d), "plates", tid)))
        try:
            pick = out["candidates"][int(rank) - 1]
        except (ValueError, IndexError):
            raise CommandError("apply is the rank of a listed candidate.")
        run(service.orient_item, plate, handles, pick["rotation"])
        items, _r = run(service.arrange_items, ctx.doc, plate["items"], plate["bed"], plate["spacing"], None, jobs.QUIET, ctx.runner)
        run(store.edit_plate, ctx.d, tid, {"items": items})
        out["applied"] = {"plate": tid, "rank": int(rank)}
    return out


@executes("orientstudy")
def orient_exec(ctx, args):
    return orient_run(ctx, args)


def arrange_run(ctx, args):
    tid = run(plate_of, ctx, args)
    plate = store.need(store.header(ctx.d), "plates", tid)
    spacing = float(args.get("spacing", plate["spacing"]))
    if not 0.0 <= spacing <= 100.0:
        raise CommandError("Spacing is between 0 and 100 mm.")
    items, report = run(service.arrange_items, ctx.doc, plate["items"], plate["bed"], spacing, args.get("rotations"), jobs.QUIET, ctx.runner)
    run(store.edit_plate, ctx.d, tid, {"items": items, "spacing": spacing})
    ctx.say("ARRANGEPLATE: %d placed, %d did not fit, %.0f percent of the plate used." % (report["placed"], len(report["unplaced"]), report["utilisation"] * 100.0))
    return {"plate": tid, "report": report}


@command("arrangeplate", aliases=("arrange",), group=GROUP, label="Arrange Plate", description="Place the parts of a build plate without overlap, keeping the spacing between them.", menu="Manufacture > Additive > Arrange Plate")
def arrange_cmd(ctx):
    pid = yield from ask_plate(ctx)
    sp = yield ctx.number("Spacing between parts in millimetres", default=4.0, minimum=0.0, maximum=100.0)
    if sp.kind != "number":
        return
    return arrange_run(ctx, {"plate": pid, "spacing": float(sp.value)})


@executes("arrangeplate")
def arrange_exec(ctx, args):
    return arrange_run(ctx, args)


def export_run(ctx, args):
    path = args.get("file") or args.get("path")
    if not path:
        raise CommandError("Give file, the output file name.")
    kind = str(args.get("kind") or "gcode").lower()
    tid = run(plate_of, ctx, args)
    plate = json.loads(json.dumps(store.need(store.header(ctx.d), "plates", tid)))
    if kind == "3mf":
        out = run(service.export_3mf, ctx.doc, plate, str(path))
    elif kind == "gcode":
        res = service.result_for(ctx.doc.id, tid)
        if res is None or res.hash != service.fingerprint(ctx.doc, plate, store.need(store.header(ctx.d), "profiles", plate["profile"])):
            res, last = run(service.do_slice, ctx.doc, tid, ctx.runner)
            store.set_last(ctx.d, tid, last)
        out = run(service.export_gcode, res, str(path))
    else:
        raise CommandError("kind is gcode or 3mf.")
    ctx.say("ADDITIVEEXPORT: wrote %s (%d bytes)." % (out["path"], out["bytes"]))
    return out


@command("additiveexport", aliases=("exportgcode",), group="additive", label="Export Plate", description="Write the sliced plate as Marlin G-code or the build plate as a 3MF file.", menu="Manufacture > Additive > Export Plate")
def export_cmd(ctx):
    pid = yield from ask_plate(ctx)
    k = yield ctx.keyword("Kind", ["Gcode", "3mf"], "Gcode")
    if k.kind != "keyword":
        return
    t = yield ctx.text("Enter the output file name")
    if t.kind != "text" or not t.value:
        return
    return export_run(ctx, {"plate": pid, "kind": str(k.value).lower(), "file": str(t.value)})


@executes("additiveexport")
def export_exec(ctx, args):
    return export_run(ctx, args)
