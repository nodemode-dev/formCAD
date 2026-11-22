import math

from app.cmd.commands.surfaces import guard, keep_report
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.solid import surfwork as sw
from app.solid import work

GROUP = "solids"
MAX_MOVES = 4000


def net_of(d, body) -> dict:
    res = sw.kcall("surf_net", {"id": work.worker_id(d, body)}, work.LONG)
    k = 1.0 / sw.scale(d)
    res["poles"] = [[c * k for c in q] for q in res["poles"]]
    return res


def triple(value, what) -> list:
    try:
        out = [float(c) for c in value]
    except (TypeError, ValueError):
        raise CommandError("%s needs three numbers." % what)
    if len(out) == 2:
        out.append(0.0)
    if len(out) != 3 or not all(math.isfinite(c) for c in out):
        raise CommandError("%s needs three finite numbers." % what)
    return out


def index_pair(row, nu: int, nv: int) -> tuple:
    try:
        i, j = int(row[0]), int(row[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise CommandError("Name a control point by its row and column.")
    if not (0 <= i < nu and 0 <= j < nv):
        raise CommandError("Control point %d, %d is outside the %d by %d net." % (i, j, nu, nv))
    return i, j


def do_points(ctx, args):
    d = ctx.d
    if args.get("handle") is None:
        raise CommandError("Give the handle of a surface.")
    body = guard(sw.body_of, d, args["handle"])
    if ctx.locked(body):
        raise CommandError("The surface is on a locked layer.")
    s = sw.scale(d)
    moves = {}
    if args.get("moves"):
        for m in args["moves"]:
            if not isinstance(m, dict):
                raise CommandError("Each move is {i, j, to}.")
            moves[(int(m.get("i", -1)), int(m.get("j", -1)))] = triple(m.get("to"), "The new position")
    elif args.get("points"):
        delta = triple(args.get("delta"), "The displacement")
        net = guard(net_of, d, body)
        nu, nv = net["count"]
        for row in args["points"]:
            i, j = index_pair(row, nu, nv)
            at = net["poles"][i * nv + j]
            moves[(i, j)] = [at[k] + delta[k] for k in range(3)]
    if not moves:
        raise CommandError("Give moves as a list of {i, j, to}, or points and a delta.")
    if len(moves) > MAX_MOVES:
        raise CommandError("At most %d control points move at once." % MAX_MOVES)
    payload = [{"i": i, "j": j, "to": [c * s for c in to]} for (i, j), to in moves.items()]
    res = guard(sw.call, d, "surf_set_poles", {"id": work.worker_id(d, body), "moves": payload})
    target = guard(sw.replace_result, ctx, body, res, "points")
    rep = res.get("report") or {}
    ctx.say("SRFPOINTS: moved %d control point(s) of %s, the largest by %s." % (len(moves), body.name or "the surface", ctx.fd(float(rep.get("largest_move", 0.0)) / s)))
    line = sw.audit_line(rep)
    if line:
        ctx.say(line)
    keep_report(ctx, rep)
    return {"handle": target.handle, "moved": len(moves), "poles": rep.get("poles"), "trimmed": bool(rep.get("trimmed")), "valid": bool((res.get("summary") or {}).get("valid"))}


@command("srfpoints", aliases=("surfpoints",), group=GROUP, label="Move Surface Points", description="Move control points of a single surface; in the 3D view, show the control points of a selected surface and drag them.", menu="Modify > 3D Operations > Move Surface Points")
def srfpoints_cmd(ctx):
    sel = yield ctx.select("Select a surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    body = guard(sw.body_of, ctx.d, int(sel.value[0]))
    net = guard(net_of, ctx.d, body)
    nu, nv = net["count"]
    ctx.say("The surface has a %d by %d control net." % (nu, nv))
    row = yield ctx.number("Specify the row of the control point (1 to %d)" % nu, integer=True, minimum=1, maximum=nu)
    if row.kind != "number":
        return
    col = yield ctx.number("Specify the column of the control point (1 to %d)" % nv, integer=True, minimum=1, maximum=nv)
    if col.kind != "number":
        return
    i, j = int(row.value) - 1, int(col.value) - 1
    at = net["poles"][i * nv + j]
    ctx.say("The control point is at %s." % ",".join(ctx.fd(c) for c in at))
    to = yield ctx.point("Specify the new position", base=at)
    if to.kind != "point":
        return
    do_points(ctx, {"handle": body.handle, "moves": [{"i": i, "j": j, "to": list(to.value)}]})


@executes("srfpoints")
def srfpoints_exec(ctx, args):
    return do_points(ctx, args)
