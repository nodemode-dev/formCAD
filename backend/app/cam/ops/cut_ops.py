from app.cam import model
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.registry import Field, OpType, register
from app.cutting import layout, records
from app.cutting import plan as P
from app.cutting import shapes as S
from app.cutting.shapes import CutError
from app.turning import emit

_ = emit

TOOL_KINDS = ("laser", "nozzle", "flat", "bull")


def header(ctx, label, proc):
    t = ctx.tool
    return [["comment", "%s T%d %s (%s)" % (label, t.number, t.name, proc["kind"])], T.tool_change(t.number, 0.0, t.name)]


def finish(ctx, res, proc, moves):
    for w in res["warnings"]:
        ctx.warn(w)
    meta = {"cutting": True, "process": proc["kind"], "kerf": proc["kerf"], "stats": res["stats"], "order": [list(o) for o in res["order"][:2000]]}
    return T.Toolpath(moves + res["moves"], meta)


def gen_nest(ctx):
    p = ctx.p
    d = ctx.doc.drawing
    if not p["nest"] or not p["process"]:
        raise CamError("Give the nest and the cutting process.")
    try:
        nest = records.get_nest(d, p["nest"])
        proc = records.process_view(records.get_process(d, p["process"]))
    except CutError as err:
        raise CamError(str(err))
    idx = int(p["sheet"]) - 1
    sheets = nest["result"]["sheets"]
    if not 0 <= idx < len(sheets):
        raise CamError("The nest has %d sheets; sheet %d does not exist." % (len(sheets), p["sheet"]))
    sh = sheets[idx]
    wp = layout.world_parts(nest["parts"], sh)
    ctx.check()
    try:
        res = P.plan_sheet(wp, proc, p["order"], (0.0, 0.0, sh["width"], sh["height"]), (p["home_x"], p["home_y"]))
    except CutError as err:
        raise CamError(str(err))
    return finish(ctx, res, proc, header(ctx, "Cut sheet %d of nest %s" % (p["sheet"], p["nest"]), proc))


def gen_profile(ctx):
    p = ctx.p
    d = ctx.doc.drawing
    if not p["process"]:
        raise CamError("Give the cutting process.")
    try:
        proc = records.process_view(records.get_process(d, p["process"]))
    except CutError as err:
        raise CamError(str(err))
    region = ctx.region()
    raw = [{"pts": [tuple(q) for q in r]} for r in region.rings]
    parts = S.group_loops(raw)
    if not parts:
        raise CamError("The geometry has no closed outline to cut.")
    for q in parts:
        q["name"] = "Outline"
    b = region.bounds()
    bounds = (b[0] - 1e6, b[1] - 1e6, b[2] + 1e6, b[3] + 1e6)
    try:
        res = P.plan_sheet(parts, proc, p["order"], bounds, (p["home_x"], p["home_y"]))
    except CutError as err:
        raise CamError(str(err))
    return finish(ctx, res, proc, header(ctx, "Cut outlines", proc))


COMMON = [Field("process", "text", "", "Cutting process id (P1)", group="Process"), Field("order", "choice", "part", "Cut order", choices=("part", "all-inner-first"), group="Order"), Field("home_x", "number", 0.0, "Start and end X", min=-100000, max=100000, unit="mm", group="Order"), Field("home_y", "number", 0.0, "Start and end Y", min=-100000, max=100000, unit="mm", group="Order")]

register(OpType(kind="cut_nest", label="Cut a nested sheet", group="cutting", generate=gen_nest, tool_kinds=TOOL_KINDS, needs_feeds=False, description="Cutting code for one sheet of a nest: kerf offset, inner contours before outer, lead-ins and lead-outs in the scrap, pierce and cut commands, nearest part order.", fields=[Field("nest", "text", "", "Nest id (N1)", group="Nest"), Field("sheet", "int", 1, "Sheet number", min=1, max=1000, group="Nest"), Field("stamp", "int", 0, "Change counter", min=0, max=1000000000, group="Nest")] + COMMON))
register(OpType(kind="cut_profile", label="Cut outlines", group="cutting", generate=gen_profile, tool_kinds=TOOL_KINDS, needs_feeds=False, description="Cutting code for the closed outlines of the chosen geometry, with the same kerf, lead and order rules.", geometry=("polygons", "rect", "entities", "section"), fields=COMMON))
