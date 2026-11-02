import re

from app.calc import CalcError, NeedsPick, engine, service
from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.cmd.registry import command, executes

ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*(.+)$")
PICK_OPTS = ["Point", "Distance", "Angle", "Intersection"]
PICK_NEED = {"Point": 1, "Distance": 2, "Angle": 2, "Intersection": 4}


def _vars(ctx) -> dict:
    return ctx.mem.setdefault("cal_vars", {})


def _store(ctx, name, res) -> None:
    _vars(ctx)[name.lower()] = res["value"]


def _eval(ctx, text):
    m = ASSIGN.match(text)
    name, expr = (m.group(1), m.group(2)) if m else (None, text)
    picks = []
    while True:
        it = iter(picks)

        def picker(mode, it=it):
            try:
                p = next(it)
            except StopIteration:
                raise NeedsPick(mode or "cur")
            return p

        try:
            res = engine.run(expr, _vars(ctx), picker)
            break
        except NeedsPick as need:
            mode = need.mode
            p = yield ctx.point("Select point for %s" % mode)
            if p.kind != "point":
                return
            picks.append([p.value[0], p.value[1]])
        except CalcError as err:
            ctx.say("CAL: %s" % err)
            return
    ctx.say(res["text"])
    _store(ctx, "ans", res)
    if name:
        _store(ctx, name, res)


@command("cal", aliases=("quickcalc", "qc"), group="inquiry", label="QuickCalc", description="Expression calculator with points, functions, unit conversion and drawing picks.", menu="Tools > Inquiry > Quick", transparent=True, undoable=False, repeatable=False)
def cal(ctx):
    r = yield Prompt(">> Expression", ("text",), [], None, "", free_text=True)
    if r.kind != "text":
        return
    yield from _eval(ctx, r.value)


@executes("cal")
def cal_exec(ctx, args):
    body = dict(args)
    variables = dict(_vars(ctx))
    variables.update(args.get("variables") or {})
    body["variables"] = variables
    out = service.handle(body, ctx.doc)
    if not out.get("ok"):
        raise CommandError(out["error"])
    if out.get("kind") and "expression" in args:
        _vars(ctx)["ans"] = out["value"] if out["kind"] == "number" else engine.Vec(*out["value"])
    return out


@command("quickcalc.pick", group="inquiry", label="QuickCalc Pick", description="Get a point, distance, angle or intersection from the drawing.", menu="", transparent=True, undoable=False, repeatable=False)
def quickcalc_pick(ctx):
    r = yield ctx.keyword("Get from the drawing", PICK_OPTS)
    if r.kind != "keyword":
        return
    pts = []
    for i in range(PICK_NEED[r.value]):
        p = yield ctx.point("Specify point %d" % (i + 1), base=pts[-1] if pts else None)
        if p.kind != "point":
            return
        pts.append([p.value[0], p.value[1]])
    res = engine.pick_helper(r.value, pts)
    ctx.say(res["text"])
    _store(ctx, "ans", res)


@executes("quickcalc.pick")
def quickcalc_pick_exec(ctx, args):
    out = service.handle({"pick": {"mode": args.get("mode"), "points": args.get("points", [])}}, ctx.doc)
    if not out.get("ok"):
        raise CommandError(out["error"])
    return out
