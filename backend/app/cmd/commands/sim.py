from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.core.outputs import OutputRefused
from app.services.mesher import MesherError
from app.sim import display, materials, records, registry, report, study
from app.sim.fem import SimError
from app.sim.records import SimRecordError
from app.solid.work import SolidError

GROUP = "solids"
ERRORS = (SimError, SimRecordError, MesherError, SolidError, OutputRefused, KeyError)
LOAD_WORDS = ["Force", "Pressure", "Gravity", "Heat_flux", "Convection", "Heat_load", "Temperature_field", "Reference_load"]
FIXTURE_WORDS = ["Fixed", "Roller", "Symmetry", "Displacement", "Temperature"]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ERRORS as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def parse_select(text: str) -> dict:
    parts = str(text).replace(",", " ").split()
    if not parts:
        raise CommandError("Name the faces: x 200, y 0, z 10, face 3 or all.")
    head = parts[0].lower()
    if head in ("x", "y", "z") and len(parts) == 2:
        return {"plane": {"axis": head, "value": float(parts[1])}}
    if head in ("face", "faces"):
        return {"faces": [int(p) for p in parts[1:]]}
    if head == "all":
        return {"all": True}
    raise CommandError("Name the faces: x 200, y 0, z 10, face 3 or all.")


def first_body(ctx) -> int:
    for e in ctx.d.ordered_entities():
        if e.kind == "solidbody":
            return e.handle
    raise CommandError("The drawing has no solid body to analyse.")


def lib_words() -> list:
    return [m["id"] for m in materials.library()["materials"]]


def material_run(ctx, args):
    raw = dict(args)
    kind = "material"
    row = run(records.create, ctx.d, kind, raw)
    ctx.say("SIMMATERIAL: created %s (%s)." % (row["id"], row["label"]))
    return {"record": row}


@command("simmaterial", aliases=("simulationmaterial",), group=GROUP, label="Study Material", description="Add a material for studies, from the cited library or with your own values and sources.", menu="Simulate > Material")
def material_cmd(ctx):
    k = yield ctx.keyword("Library material", lib_words() + ["Custom"], lib_words()[0])
    if k.kind != "keyword":
        return
    if str(k.value).lower() != "custom":
        return material_run(ctx, {"library": str(k.value).lower()})
    vals = {}
    for key, msg in (("rho", "Density in kg/m3"), ("E", "Young's modulus in Pa"), ("nu", "Poisson's ratio")):
        n = yield ctx.number(msg, positive=True)
        if n.kind != "number":
            return
        vals[key] = n.value
    src = yield ctx.text("Source of these values (organisation, title)")
    if src.kind != "text" or not str(src.value).strip():
        return
    vals["sources"] = [{"field": "all", "org": str(src.value), "title": str(src.value)}]
    vals["name"] = "Custom material"
    return material_run(ctx, vals)


@executes("simmaterial")
def material_exec(ctx, args):
    return material_run(ctx, args)


def load_run(ctx, args):
    raw = dict(args)
    if isinstance(raw.get("select"), str):
        raw["select"] = run(parse_select, raw["select"])
    row = run(records.create, ctx.d, "load", raw)
    ctx.say("SIMLOAD: created %s (%s)." % (row["id"], row["type"]))
    return {"record": row}


@command("simload", aliases=("studyload",), group=GROUP, label="Study Load", description="Add a force, pressure, gravity, heat or convection load on faces for a study.", menu="Simulate > Load")
def load_cmd(ctx):
    k = yield ctx.keyword("Load type", LOAD_WORDS, "Force")
    if k.kind != "keyword":
        return
    kind = str(k.value).lower()
    raw = {"type": kind}
    if kind not in ("gravity", "temperature_field", "heat_load"):
        t = yield ctx.text("Faces (x 200, y 0, z 10, face 3 or all)")
        if t.kind != "text":
            return
        raw["select"] = str(t.value)
    if kind in ("force", "reference_load"):
        d = yield ctx.text("Direction x y z", "0 0 -1")
        if d.kind != "text":
            return
        raw["direction"] = [float(v) for v in str(d.value).replace(",", " ").split()]
    if kind == "convection":
        h = yield ctx.number("Film coefficient h in W/m2K", positive=True)
        t0 = yield ctx.number("Ambient temperature in K", default=293.15, positive=True)
        if h.kind != "number" or t0.kind != "number":
            return
        raw["h"], raw["t_inf"] = h.value, t0.value
    else:
        v = yield ctx.number("Value (N, Pa, m/s2, W/m2, W or K)", default=9.81 if kind == "gravity" else None)
        if v.kind != "number":
            return
        raw["value"] = v.value
    return load_run(ctx, raw)


@executes("simload")
def load_exec(ctx, args):
    return load_run(ctx, args)


def fixture_run(ctx, args):
    raw = dict(args)
    if isinstance(raw.get("select"), str):
        raw["select"] = run(parse_select, raw["select"])
    row = run(records.create, ctx.d, "fixture", raw)
    ctx.say("SIMFIXTURE: created %s (%s)." % (row["id"], row["type"]))
    return {"record": row}


@command("simfixture", aliases=("studyfixture",), group=GROUP, label="Study Fixture", description="Hold faces for a study: fixed, roller, symmetry, prescribed displacement or temperature.", menu="Simulate > Fixture")
def fixture_cmd(ctx):
    k = yield ctx.keyword("Fixture type", FIXTURE_WORDS, "Fixed")
    if k.kind != "keyword":
        return
    kind = str(k.value).lower()
    t = yield ctx.text("Faces (x 200, y 0, z 10, face 3 or all)")
    if t.kind != "text":
        return
    raw = {"type": kind, "select": str(t.value)}
    if kind == "temperature":
        v = yield ctx.number("Temperature in K", positive=True)
        if v.kind != "number":
            return
        raw["value"] = v.value
    elif kind == "symmetry":
        a = yield ctx.number("Axis normal to the symmetry plane (0 x, 1 y, 2 z)", integer=True, minimum=0, maximum=2)
        if a.kind != "int":
            return
        raw["axis"] = a.value
    elif kind == "roller":
        a = yield ctx.number("Axis the faces may slide along (0 x, 1 y, 2 z)", integer=True, minimum=0, maximum=2)
        if a.kind != "int":
            return
        raw["axes"] = [a.value]
    return fixture_run(ctx, raw)


@executes("simfixture")
def fixture_exec(ctx, args):
    return fixture_run(ctx, args)


def study_run(ctx, args):
    raw = dict(args)
    sid = raw.pop("id", None) or raw.pop("study", None)
    if raw.get("maxh") not in (None, ""):
        raw["mesh"] = {**(raw.get("mesh") or {}), "maxh_mm": raw.pop("maxh")}
    if "body" in raw and "geometry" not in raw:
        raw["geometry"] = {"body": int(raw.pop("body"))}
    if "geometry" not in raw and not sid:
        raw["geometry"] = {"body": first_body(ctx)}
    if sid:
        row = run(records.update, ctx.d, str(sid), raw)
        ctx.say("SIMSTUDY: updated %s." % row["id"])
    else:
        row = run(records.create, ctx.d, "study", raw)
        ctx.say("SIMSTUDY: created %s (%s)." % (row["id"], row["type"]))
    return {"record": row}


@command("simstudy", aliases=("studynew",), group=GROUP, label="New Study", description="Create or edit a study: the solid, its material, loads, fixtures and mesh size.", menu="Simulate > Study")
def study_cmd(ctx):
    registry.load()
    types = [s["type"] for s in registry.listing()]
    k = yield ctx.keyword("Study type", [t.capitalize() for t in types], types[0].capitalize())
    if k.kind != "keyword":
        return
    mats = [m["id"] for m in records.of_kind(ctx.d, "material")]
    loads = [m["id"] for m in records.of_kind(ctx.d, "load")]
    fixes = [m["id"] for m in records.of_kind(ctx.d, "fixture")]
    raw = {"type": str(k.value).lower(), "loads": loads, "fixtures": fixes}
    if mats:
        raw["material"] = mats[-1]
    return study_run(ctx, raw)


@executes("simstudy")
def study_exec(ctx, args):
    return study_run(ctx, args)


def last_study(ctx) -> str:
    rows = records.of_kind(ctx.d, "study")
    if not rows:
        raise CommandError("The drawing has no study; create one with SIMSTUDY.")
    return rows[-1]["id"]


def run_study(ctx, args):
    sid = str(args.get("study") or last_study(ctx))
    mode = str(args.get("mode") or "run")
    if mode not in ("run", "mesh"):
        raise CommandError("mode is run or mesh.")
    restrict = study.restricted(ctx.runner)
    parts = run(study.compute, ctx.doc, sid, mode, study.Inline(restrict), restrict)
    out = run(study.store, ctx.d, parts)
    s = out["summary"]
    if mode == "mesh":
        m = s["mesh"]
        ctx.say("SIMRUN: meshed %s, %d nodes, %d tets, element size %.3g mm." % (sid, m["nodes"], m["tets"], m["maxh_mm"]))
    else:
        ctx.say("SIMRUN: solved %s (%s): %s" % (sid, parts["type"], headline(s)))
    return out


def headline(s: dict) -> str:
    bits = []
    if "max_displacement_m" in s:
        bits.append("max displacement %.4g mm" % (s["max_displacement_m"] * 1e3))
    if "max_von_mises_pa" in s:
        bits.append("max von Mises %.4g MPa" % (s["max_von_mises_pa"] * 1e-6))
    if "frequencies_hz" in s:
        bits.append("first frequency %.5g Hz" % s["frequencies_hz"][0])
    if "critical_load_n" in s:
        bits.append("critical load %.5g N" % s["critical_load_n"])
    if "max_temperature_k" in s:
        bits.append("temperature %.5g to %.5g K" % (s["min_temperature_k"], s["max_temperature_k"]))
    return ", ".join(bits)


@command("simrun", aliases=("studyrun", "solve3d"), group=GROUP, label="Run Study", description="Mesh the solid and solve a study; the result is stored in the drawing.", menu="Simulate > Run Study")
def run_cmd(ctx):
    t = yield ctx.text("Study (Enter for the last one)", "")
    if t.kind != "text":
        return
    return run_study(ctx, {"study": str(t.value).strip() or None})


@executes("simrun")
def run_exec(ctx, args):
    return run_study(ctx, args)


def report_run(ctx, args):
    sid = str(args.get("study") or last_study(ctx))
    path = args.get("path") or args.get("file")
    if not path:
        raise CommandError("A report needs an output file name.")
    out = run(report.write, ctx.doc, sid, str(path), str(args.get("format") or "html"), args.get("title"))
    ctx.say("SIMREPORT: wrote %s (%d bytes)." % (out["path"], out["bytes"]))
    return out


@command("simreport", aliases=("studyreport",), group=GROUP, label="Study Report", description="Write the results of a study as an HTML or PDF report file.", menu="Simulate > Report")
def report_cmd(ctx):
    k = yield ctx.keyword("Format", ["Html", "Pdf"], "Html")
    if k.kind != "keyword":
        return
    t = yield ctx.text("Enter the output file name")
    if t.kind != "text" or not t.value:
        return
    return report_run(ctx, {"format": str(k.value).lower(), "path": str(t.value)})


@executes("simreport")
def report_exec(ctx, args):
    return report_run(ctx, args)


def probe_run(ctx, args):
    sid = str(args.get("study") or last_study(ctx))
    pts = args.get("points") or ([args["point"]] if args.get("point") else None)
    if not pts:
        raise CommandError("Give one or more points in millimetres.")
    return run(display.probe, ctx.doc, sid, pts, int(args.get("mode") or 0))


@command("simprobe", aliases=("studyprobe",), group=GROUP, label="Probe Result", description="Read the displacement, temperature or stress of a study result at a point.", menu="Simulate > Probe")
def probe_cmd(ctx):
    t = yield ctx.text("Point x y z in millimetres")
    if t.kind != "text":
        return
    p = [float(v) for v in str(t.value).replace(",", " ").split()]
    if len(p) != 3:
        raise CommandError("A point is three numbers.")
    out = probe_run(ctx, {"point": p})
    for item in out["probes"]:
        ctx.say("SIMPROBE: %s" % ({k: v for k, v in item.items() if k != "point"} if item["inside"] else "outside the part"))
    return out


@executes("simprobe")
def probe_exec(ctx, args):
    return probe_run(ctx, args)
