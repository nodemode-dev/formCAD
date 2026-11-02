from app.cmd.commands.settings import _make_toggle, _var_toggle
from app.cmd.context import CommandError
from app.cmd.registry import command, executes

PLANES = ("Left", "Top", "Right")

_g, _p = _var_toggle("TRANSPARENCYDISPLAY")
_make_toggle("transparencydisplay", "Transparencydisplay", _g, _p, description="Show object transparency on screen.")
_g, _p = _var_toggle("QPMODE")
_make_toggle("qpmode", "Qpmode", _g, _p, description="Show the quick properties palette when objects are selected.")
_g, _p = _var_toggle("SELECTIONCYCLING")
_make_toggle("selectioncycling", "Selectioncycling", _g, _p, description="Cycle through overlapping objects when picking.")


def draft_state(ctx) -> str:
    if not int(ctx.var("SNAPSTYL")):
        return "Orthographic"
    return PLANES[int(ctx.var("SNAPISOPAIR"))]


def set_draft(ctx, mode: str) -> dict:
    m = (mode or "").strip().lower()
    if m in ("orthographic", "ortho", "o", "off"):
        ctx.setvar("SNAPSTYL", 0)
        ctx.say("<Isodraft off>")
        return {"mode": "Orthographic"}
    for i, name in enumerate(PLANES):
        if m and name.lower().startswith(m):
            ctx.setvar("SNAPSTYL", 1)
            ctx.setvar("SNAPISOPAIR", i)
            ctx.say("<Isodraft %s>" % name)
            return {"mode": name}
    raise CommandError("Drafting mode is Orthographic, Left, Top or Right.")


@command("isodraft", group="settings", label="Isometric Drafting", description="Choose orthographic or isometric drafting and the isometric plane.", transparent=True, undoable=False, repeatable=False)
def isodraft_cmd(ctx):
    cur = draft_state(ctx)
    default = "Orthographic" if cur != "Orthographic" else "Top"
    r = yield ctx.keyword("Drafting mode", ["Orthographic", "Left", "Top", "Right"], default)
    if r.kind in ("keyword", "enter"):
        set_draft(ctx, r.value if r.kind == "keyword" else default)


@executes("isodraft")
def isodraft_exec(ctx, args):
    return set_draft(ctx, str(args.get("mode", "")))


def set_plane(ctx, name: str) -> dict:
    m = (name or "").strip().lower()
    for i, p in enumerate(PLANES):
        if m and p.lower().startswith(m):
            ctx.setvar("SNAPISOPAIR", i)
            ctx.say("Current isoplane is %s." % p)
            return {"plane": p}
    raise CommandError("Isometric plane is Left, Top or Right.")


@command("isoplane", group="settings", label="Isometric Plane", description="Choose the isometric plane for drafting.", transparent=True, undoable=False, repeatable=False)
def isoplane_cmd(ctx):
    nxt = PLANES[(int(ctx.var("SNAPISOPAIR")) + 1) % 3]
    r = yield ctx.keyword("Isometric plane", list(PLANES), nxt)
    if r.kind in ("keyword", "enter"):
        set_plane(ctx, r.value if r.kind == "keyword" else nxt)


@executes("isoplane")
def isoplane_exec(ctx, args):
    if args.get("plane"):
        return set_plane(ctx, str(args["plane"]))
    return set_plane(ctx, PLANES[(int(ctx.var("SNAPISOPAIR")) + 1) % 3])


def apply_settings(ctx, args: dict) -> dict:
    out = {}
    for key, var in (("snap", "SNAPUNIT"), ("grid", "GRIDUNIT")):
        if key in args:
            v = args[key]
            pair = [float(v), float(v)] if isinstance(v, (int, float)) else [float(v[0]), float(v[1])]
            out[key] = ctx.setvar(var, pair)
    if "polar" in args:
        out["polar"] = ctx.setvar("POLARANG", float(args["polar"]))
    if "major" in args:
        out["major"] = ctx.setvar("GRIDMAJOR", int(args["major"]))
    if not out:
        return {"snap": ctx.var("SNAPUNIT"), "grid": ctx.var("GRIDUNIT"), "polar": ctx.var("POLARANG"), "major": ctx.var("GRIDMAJOR")}
    return out


@command("dsettings", aliases=("ds", "se"), group="settings", label="Drafting Settings", description="Snap and grid spacing, polar angle increment and major grid interval.", menu="Tools > Drafting Settings...", undoable=False, repeatable=False)
def dsettings_cmd(ctx):
    while True:
        r = yield ctx.keyword("Drafting setting", ["Snap", "Grid", "Polar", "Major", "Done"], "Done")
        if r.kind != "keyword" or r.value == "Done":
            return
        if r.value in ("Snap", "Grid"):
            cur = ctx.var("SNAPUNIT" if r.value == "Snap" else "GRIDUNIT")
            v = yield ctx.distance("%s spacing" % r.value, default=cur[0], positive=True)
            if v.kind == "number":
                apply_settings(ctx, {r.value.lower(): v.value})
        elif r.value == "Polar":
            v = yield ctx.number("Polar angle increment", default=ctx.var("POLARANG"), positive=True)
            if v.kind == "number":
                apply_settings(ctx, {"polar": v.value})
        else:
            v = yield ctx.number("Major grid interval", default=ctx.var("GRIDMAJOR"), integer=True, minimum=1, maximum=100)
            if v.kind == "number":
                apply_settings(ctx, {"major": v.value})


@executes("dsettings")
def dsettings_exec(ctx, args):
    try:
        return apply_settings(ctx, args)
    except (TypeError, ValueError, IndexError) as err:
        raise CommandError("Invalid drafting setting: %s" % err)
