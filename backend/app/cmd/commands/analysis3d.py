import math

from app.analysis import combs, ramps, service as an, spec as spec_mod
from app.cmd.commands.surfaces import ask_style, handles_of
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.solid.work import SolidError

GROUP = "inquiry"
PULL_WORDS = {"z": [0.0, 0.0, 1.0], "-z": [0.0, 0.0, -1.0], "y": [0.0, 1.0, 0.0], "-y": [0.0, -1.0, 0.0], "x": [1.0, 0.0, 0.0], "-x": [-1.0, 0.0, 0.0]}


def guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except spec_mod.SpecError as err:
        raise CommandError(str(err))
    except ramps.RampError as err:
        raise CommandError(str(err))
    except SolidError as err:
        raise CommandError(str(err))


def bump(ctx) -> int:
    ctx.mem["analysis_seq"] = int(ctx.mem.get("analysis_seq", 0)) + 1
    return ctx.mem["analysis_seq"]


def f(v, digits=4):
    return "n/a" if v is None else ("%.*g" % (digits, v))


def show(ctx, label: str, raw: dict) -> dict:
    spec = guard(spec_mod.normalise, ctx.d, raw)
    _payload, meta = guard(an.compute_full, ctx.doc, spec, 1.0)
    st = meta["stats"]
    unit = meta["unit"]
    n = len(meta["bodies"])
    ctx.say("%s: %d surface(s), %s vertices, lowest %s, highest %s, mean %s %s." % (label, n, st.get("count"), f(st.get("min")), f(st.get("max")), f(st.get("mean")), unit))
    ctx.mem["analysis3d"] = spec
    seq = bump(ctx)
    return {"mode": spec["mode"], "seq": seq, "stats": st, "range": meta["range"], "unit": unit, "bodies": [b["handle"] for b in meta["bodies"]], "ramp": meta["ramp_name"]}


def optional_ramp(args):
    out = {}
    if args.get("ramp") is not None:
        out["ramp"] = args["ramp"]
    return out


def pick_surfaces(ctx, message):
    sel = yield ctx.select(message)
    if sel.kind != "selection":
        return None
    return [int(h) for h in sel.value]


@command("zebra", aliases=("zebrastripes",), group=GROUP, label="Zebra Stripes", description="Colour surfaces with reflection stripes (or isophote bands) to judge how smoothly they meet.", menu="Tools > Inquiry > Zebra", undoable=False)
def zebra_cmd(ctx):
    handles = yield from pick_surfaces(ctx, "Select surfaces for stripe analysis or press Enter for all")
    if handles is None:
        return
    style = yield from ask_style(ctx, "Style", ["Zebra", "Isophote"], "Zebra")
    if style is None:
        return
    direction = yield from ask_style(ctx, "Stripe direction", ["Vertical", "Horizontal"], "Vertical")
    if direction is None:
        return
    band = yield ctx.number("Specify the stripe width in degrees <6>", default=6.0)
    if band.kind != "number":
        return
    show(ctx, style.upper(), {"mode": style.lower(), "targets": handles, "direction": direction.lower(), "band": band.value})


@executes("zebra")
def zebra_exec(ctx, args):
    style = str(args.get("style", "zebra")).lower()
    if style not in ("zebra", "isophote"):
        raise CommandError("Style is zebra or isophote.")
    spec = {"mode": style, "targets": handles_of(args, "handles") or handles_of(args, "targets")}
    for key in ("direction", "axis", "view", "light", "band"):
        if args.get(key) is not None:
            spec[key] = args[key]
    if spec.get("axis") is not None and "direction" not in args:
        spec["direction"] = "custom"
    spec.update(optional_ramp(args))
    return show(ctx, style.upper(), spec)


@command("curvatureanalysis", aliases=("curvana", "surfcurvature"), group=GROUP, label="Curvature Analysis", description="Colour surfaces by Gaussian, mean, principal, absolute or rms curvature.", menu="Tools > Inquiry > Curvature Analysis", undoable=False)
def curvature_cmd(ctx):
    handles = yield from pick_surfaces(ctx, "Select surfaces for curvature analysis or press Enter for all")
    if handles is None:
        return
    measure = yield from ask_style(ctx, "Measure", ["Gaussian", "Mean", "Max", "Min", "Absolute", "Rms"], "Gaussian")
    if measure is None:
        return
    show(ctx, "CURVATUREANALYSIS", {"mode": "curvature", "targets": handles, "measure": measure.lower()})


@executes("curvatureanalysis")
def curvature_exec(ctx, args):
    spec = {"mode": "curvature", "targets": handles_of(args, "handles") or handles_of(args, "targets"), "measure": str(args.get("measure", "gaussian")).lower()}
    spec.update(optional_ramp(args))
    return show(ctx, "CURVATUREANALYSIS", spec)


def pull_from(raw):
    if isinstance(raw, str):
        w = raw.strip().lower()
        if w not in PULL_WORDS:
            raise CommandError("The pull direction is x, y, z, -x, -y, -z or three numbers.")
        return PULL_WORDS[w]
    return raw


@command("draftanalysis", aliases=("draftana",), group=GROUP, label="Draft Angle Analysis", description="Colour surfaces by their draft angle against a pull direction, with pass and fail limits.", menu="Tools > Inquiry > Draft Angle", undoable=False)
def draft_cmd(ctx):
    handles = yield from pick_surfaces(ctx, "Select surfaces for draft analysis or press Enter for all")
    if handles is None:
        return
    word = yield from ask_style(ctx, "Pull direction", ["Z", "X", "Y", "Vector"], "Z")
    if word is None:
        return
    if word == "Vector":
        a = yield ctx.point("Specify the start of the pull direction")
        if a.kind != "point":
            return
        b = yield ctx.point("Specify the end of the pull direction", base=a.value)
        if b.kind != "point":
            return
        pull = [b.value[0] - a.value[0], b.value[1] - a.value[1], (b.value[2] if len(b.value) > 2 else 0.0) - (a.value[2] if len(a.value) > 2 else 0.0)]
    else:
        pull = PULL_WORDS[word.lower()]
    lo = yield ctx.number("Specify the lower draft limit in degrees <-3>", default=-3.0)
    if lo.kind != "number":
        return
    hi = yield ctx.number("Specify the upper draft limit in degrees <3>", default=3.0)
    if hi.kind != "number":
        return
    show(ctx, "DRAFTANALYSIS", {"mode": "draft", "targets": handles, "pull": pull, "lower": lo.value, "upper": hi.value})


@executes("draftanalysis")
def draft_exec(ctx, args):
    spec = {"mode": "draft", "targets": handles_of(args, "handles") or handles_of(args, "targets"), "pull": pull_from(args.get("pull", "z"))}
    for key in ("lower", "upper"):
        if args.get(key) is not None:
            spec[key] = args[key]
    spec.update(optional_ramp(args))
    return show(ctx, "DRAFTANALYSIS", spec)


def report_points(ctx, res):
    st = res["stats"]
    ctx.say("DEVIATION: %d point(s), mean %s, median %s, standard deviation %s, largest %s, smallest %s." % (res["count"], f(st["mean"]), f(st["median"]), f(st["std"]), f(st["max"]), f(st["min"])))
    if "within_good" in st or "beyond_bad" in st:
        ctx.say("DEVIATION: %s within the good distance, %s beyond the bad distance." % (st.get("within_good", "n/a"), st.get("beyond_bad", "n/a")))


@command("deviation", aliases=("surfdeviation",), group=GROUP, label="Deviation", description="Distance from a surface (or points) to a target surface, as colours and statistics.", menu="Tools > Inquiry > Deviation", undoable=False)
def deviation_cmd(ctx):
    src = yield from pick_surfaces(ctx, "Select the surfaces to measure")
    if not src:
        return
    sel = yield ctx.select("Select the target surface", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return
    signed = yield from ask_style(ctx, "Distance", ["Unsigned", "Signed"], "Unsigned")
    if signed is None:
        return
    show(ctx, "DEVIATION", {"mode": "deviation", "source": src, "target": int(sel.value[0]), "signed": signed == "Signed"})


@executes("deviation")
def deviation_exec(ctx, args):
    target = args.get("target")
    if target is None:
        raise CommandError("Give the handle of the target surface.")
    faces = [int(v) for v in args.get("faces") or []]
    if args.get("points") is not None:
        res = guard(an.point_deviation, ctx.doc, args["points"], int(target), faces, bool(args.get("signed", False)), args.get("good"), args.get("bad"))
        report_points(ctx, res)
        return res
    spec = {"mode": "deviation", "source": handles_of(args, "source"), "target": int(target), "faces": faces, "signed": bool(args.get("signed", False)), "good": args.get("good"), "bad": args.get("bad")}
    if args.get("max_vertices") is not None:
        spec["max_vertices"] = args["max_vertices"]
    spec.update(optional_ramp(args))
    return show(ctx, "DEVIATION", spec)


def run_comb(ctx, args):
    handles = handles_of(args, "handles")
    edges = list(args.get("edges") or [])
    per_span = int(args.get("density", args.get("per_span", 12)))
    scale = float(args.get("scale", 1.0))
    if not math.isfinite(scale) or scale <= 0 or scale > 1000:
        raise CommandError("The comb scale must be a positive number up to 1000.")
    if not 8 <= per_span <= 64:
        raise CommandError("The comb density is 8 to 64 teeth per span.")
    res = guard(combs.compute, ctx.d, handles, edges, per_span, scale)
    teeth = sum(len(s["points"]) for c in res["curves"] for s in c["segments"])
    infl = sum(len(s["inflections"]) for c in res["curves"] for s in c["segments"])
    ctx.say("CURVATURECOMB: %d curve(s), %d teeth, largest curvature %s, %d inflection(s)." % (len(res["curves"]), teeth, f(res["max_curvature"]), infl))
    ctx.mem["combs3d"] = {"handles": handles, "edges": edges, "per_span": per_span, "scale": scale}
    seq = bump(ctx)
    return {"curves": len(res["curves"]), "teeth": teeth, "max_curvature": res["max_curvature"], "inflections": infl, "seq": seq}


@command("curvaturecomb", aliases=("combs", "curvaturegraph"), group=GROUP, label="Curvature Comb", description="Draw curvature combs on curves: teeth along the normal, long where the curve bends hard.", menu="Tools > Inquiry > Curvature Comb", undoable=False)
def comb_cmd(ctx):
    sel = yield ctx.select("Select curves for curvature combs")
    if sel.kind != "selection" or not sel.value:
        return
    scale = yield ctx.number("Specify the comb height scale <1>", default=1.0, positive=True)
    if scale.kind != "number":
        return
    run_comb(ctx, {"handles": [int(h) for h in sel.value], "scale": scale.value})


@executes("curvaturecomb")
def comb_exec(ctx, args):
    return run_comb(ctx, args)


@command("analysisoff", aliases=("clearanalysis",), group=GROUP, label="Analysis Off", description="Switch off surface analysis colouring and curvature combs.", menu="Tools > Inquiry > Analysis Off", undoable=False)
def off_cmd(ctx):
    off_run(ctx, {})
    yield from ()


def off_run(ctx, args):
    which = str(args.get("which", "all")).lower()
    if which not in ("all", "surface", "comb"):
        raise CommandError("Switch off all, surface or comb.")
    if which in ("all", "surface"):
        ctx.mem.pop("analysis3d", None)
    if which in ("all", "comb"):
        ctx.mem.pop("combs3d", None)
    seq = bump(ctx)
    an.clear_cache()
    ctx.say("ANALYSISOFF: analysis display cleared.")
    return {"seq": seq, "which": which}


@executes("analysisoff")
def off_exec(ctx, args):
    return off_run(ctx, args)


def ramp_run(ctx, args):
    name = str(args.get("name", "")).strip().lower()
    if not name:
        raise CommandError("Give the name of the ramp.")
    if args.get("reset"):
        ramps.reset(ctx.d, name)
        ctx.say("ANALYSISRAMP: %s is back to its default." % name)
        return {"name": name, "reset": True}
    base = ramps.all_ramps(ctx.d).get(name)
    raw = args.get("ramp")
    if raw is None:
        raw = {k: args[k] for k in ("kind", "stops", "min", "max", "center", "symmetric", "limits") if k in args}
    if not raw:
        return {"name": name, "ramp": base}
    merged = {**(base or {"kind": "gradient"}), **raw}
    rec = guard(ramps.put, ctx.d, name, merged)
    ctx.say("ANALYSISRAMP: %s stored in the document." % name)
    return {"name": name, "ramp": rec}


@command("analysisramp", group="tools", label="Analysis Colour Ramp", description="Edit a colour ramp used by surface analysis: stops, limits and centre are stored in the document.", menu="Tools > Inquiry > Analysis Colours")
def ramp_cmd(ctx):
    n = yield ctx.word("Enter the ramp name [%s]" % "/".join(sorted(ramps.all_ramps(ctx.d))), default="diverging")
    if n.kind not in ("text", "keyword"):
        return
    name = str(n.value)
    lo = yield ctx.number("Specify the lower limit or press Enter to keep it", default=None)
    hi = yield ctx.number("Specify the upper limit or press Enter to keep it", default=None)
    args = {"name": name}
    if lo.kind == "number":
        args["min"] = lo.value
    if hi.kind == "number":
        args["max"] = hi.value
    ramp_run(ctx, args)


@executes("analysisramp")
def ramp_exec(ctx, args):
    return ramp_run(ctx, args)
