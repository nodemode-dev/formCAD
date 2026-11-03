import json

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.core.outputs import OutputRefused
from app.pipe import fittings, service, store
from app.pipe.limits import PipeError
from app.schem import numbering
from app.schem import service as sservice
from app.schem import store as sstore
from app.schem.errors import SchemError
from app.solid.work import SolidError

GROUP = "solids"
ERRORS = (PipeError, SchemError, OutputRefused, SolidError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ERRORS as err:
        raise CommandError(str(err))


def ask_json(ctx, message, default=""):
    t = yield ctx.text(message, default)
    if t.kind != "text" or not str(t.value).strip():
        return None
    try:
        value = json.loads(str(t.value))
    except ValueError:
        raise CommandError("That is not valid JSON.")
    if not isinstance(value, dict):
        raise CommandError("Give a JSON object.")
    return value


def do_spec(ctx, args):
    return run(lambda: store.add(ctx.d, "spec", "S", store.clean_spec(args)))


def do_route(ctx, args):
    def go():
        row = store.clean_run(args)
        if row["spec"]:
            store.need(ctx.d, row["spec"], "spec")
        rec = store.add(ctx.d, "run", "R", row)
        res = service.solve(ctx.d, rec)
        ctx.say("PIPEROUTE: %s, developed length %.4g, %d bends or fittings, %d warnings." % (rec["id"], res["total"], len(res["arcs"]) or len(res["fittings"]), len(res["violations"])))
        return {"run": rec["id"], "total": res["total"], "violations": res["violations"]}

    return run(go)


@command("pipespec", group=GROUP, label="Tube Spec", description="Add a tube or pipe spec: outside diameter, wall, minimum bend radius factor and springback, all user entered.", menu="Manufacture > Pipes and Tubing > Tube Spec")
def pipespec_cmd(ctx):
    v = yield from ask_json(ctx, 'Spec as JSON, for example {"od": 20, "wall": 2}')
    if v is None:
        return None
    return do_spec(ctx, v)


@executes("pipespec")
def pipespec_exec(ctx, args):
    return do_spec(ctx, args)


@command("piperoute", aliases=("tuberoute",), group=GROUP, label="Pipe or Tube Route", description="Route a bent tube or a fitted pipe run through 3D points or assembly anchors, with centreline radii, taps, reducers and end flanges; reports developed length and flags tight bends.", menu="Manufacture > Pipes and Tubing > Route")
def piperoute_cmd(ctx):
    v = yield from ask_json(ctx, 'Run as JSON: {"spec": "S1", "style": "tube", "points": [[0,0,0],[200,0,0],[200,100,0]], "clr": 40}')
    if v is None:
        return None
    return do_route(ctx, v)


@executes("piperoute")
def piperoute_exec(ctx, args):
    return do_route(ctx, args)


def do_cutlist(ctx, args):
    def go():
        rows = service.cutlist(ctx.d, args.get("run"))
        bom = service.fitting_bom(ctx.d)
        ctx.say("PIPECUTLIST: %d rows, %d fitting kinds." % (len(rows), len(bom)))
        return {"rows": rows, "fittings": bom}

    return run(go)


@command("pipecutlist", aliases=("tubecutlist",), group=GROUP, label="Pipe Cut List", description="List every piece of every pipe and tube run with developed length, bends and bender data, and the fitting count.", menu="Manufacture > Pipes and Tubing > Cut List")
def pipecutlist_cmd(ctx):
    return do_cutlist(ctx, {})


@executes("pipecutlist")
def pipecutlist_exec(ctx, args):
    return do_cutlist(ctx, args)


def do_bender(ctx, args):
    def go():
        t = service.bender_table(ctx.d, store.need(ctx.d, args.get("run"), "run"))
        ctx.say("PIPEBENDER: %d bends, total %.4g." % (t["bends"], t["total"]))
        return t

    return run(go)


@command("pipebender", aliases=("tubebender",), group=GROUP, label="Tube Bender Table", description="Length, rotation and angle for each bend of a bent tube run.", menu="Manufacture > Pipes and Tubing > Bender Table")
def pipebender_cmd(ctx):
    t = yield ctx.text("Run to tabulate", "R1")
    if t.kind != "text":
        return None
    return do_bender(ctx, {"run": str(t.value).strip()})


@executes("pipebender")
def pipebender_exec(ctx, args):
    return do_bender(ctx, args)


def do_fitting(ctx, args):
    def go():
        kind = str(args.get("type") or "")
        h, p, summary = fittings.make(ctx.d, kind, args.get("params"), str(args.get("name") or kind.capitalize()))
        ctx.say("PIPEFITTING: %s body %d." % (kind, h))
        return {"handle": h, "params": p, "summary": summary}

    return run(go)


@command("pipefitting", group=GROUP, label="Pipe Fitting", description="Generate a parametric elbow, tee, reducer or flange body from its outside diameter, wall and proportions.", menu="Manufacture > Pipes and Tubing > Fitting")
def pipefitting_cmd(ctx):
    k = yield ctx.keyword("Fitting", ["elbow", "tee", "reducer", "flange"], "elbow")
    if k.kind != "keyword":
        return None
    v = yield from ask_json(ctx, "Parameters as JSON, or Enter for the example sizes", "{}")
    return do_fitting(ctx, {"type": str(k.value).lower(), "params": v or {}})


@executes("pipefitting")
def pipefitting_exec(ctx, args):
    return do_fitting(ctx, args)


def do_export(ctx, args):
    return run(service.export, ctx.d, args.get("path"), str(args.get("kind") or "cutlist"), args.get("run"))


@command("pipeexport", group=GROUP, label="Export Pipe Cut List", description="Write the pipe cut list or a bender table to a CSV file.", menu="Manufacture > Pipes and Tubing > Export")
def pipeexport_cmd(ctx):
    t = yield ctx.text("CSV file to write", "")
    if t.kind != "text" or not str(t.value).strip():
        return None
    return do_export(ctx, {"path": str(t.value).strip(), "kind": "cutlist"})


@executes("pipeexport")
def pipeexport_exec(ctx, args):
    return do_export(ctx, args)


def do_device(ctx, args):
    return run(lambda: sstore.add_device(ctx.d, args))


@command("schemdevice", group=GROUP, label="Schematic Device", description="Place a device symbol on a schematic sheet with its reference and pins.", menu="Draw > Electrical > Device")
def schemdevice_cmd(ctx):
    v = yield from ask_json(ctx, 'Device as JSON: {"type": "coil", "x": 50, "y": 100}')
    if v is None:
        return None
    return do_device(ctx, v)


@executes("schemdevice")
def schemdevice_exec(ctx, args):
    return do_device(ctx, args)


def do_wire(ctx, args):
    return run(lambda: sstore.add_wire(ctx.d, args))


@command("schemwire", group=GROUP, label="Schematic Wire", description="Connect two device pins with a wire carrying a name, gauge, colour and signal class.", menu="Draw > Electrical > Wire")
def schemwire_cmd(ctx):
    v = yield from ask_json(ctx, 'Wire as JSON: {"from": {"device": "K1", "pin": "A2"}, "to": {"device": "S1", "pin": "1"}}')
    if v is None:
        return None
    return do_wire(ctx, v)


@executes("schemwire")
def schemwire_exec(ctx, args):
    return do_wire(ctx, args)


def do_number(ctx, args):
    def go():
        out = numbering.renumber(ctx.d, args.get("template"), args.get("prefix"), bool(args.get("keep_manual", True)))
        ctx.say("SCHEMNUMBER: %d nodes, %d wires, %d changed." % (out["nodes"], out["wires"], out["changed"]))
        return out

    return run(go)


@command("schemnumber", aliases=("wirenumber",), group=GROUP, label="Number Wires", description="Number every electrical node once, by sheet and sequence with a template; manually fixed numbers are kept.", menu="Draw > Electrical > Number Wires")
def schemnumber_cmd(ctx):
    return do_number(ctx, {})


@executes("schemnumber")
def schemnumber_exec(ctx, args):
    return do_number(ctx, args)


def do_draw(ctx, args):
    def go():
        out = sservice.draw(ctx.d)
        ctx.say("SCHEMDRAW: %d entities on %d sheets." % (out["entities"], len(out["sheets"])))
        return out

    return run(go)


@command("schemdraw", group=GROUP, label="Draw Schematic", description="Regenerate the 2D drawing entities of the electrical schematic: frames, symbols, orthogonal wires and labels.", menu="Draw > Electrical > Draw Schematic")
def schemdraw_cmd(ctx):
    return do_draw(ctx, {})


@executes("schemdraw")
def schemdraw_exec(ctx, args):
    return do_draw(ctx, args)


def do_wirelist(ctx, args):
    def go():
        rows = sservice.wirelist(ctx.d)
        chk = sservice.check(ctx.d)
        ctx.say("SCHEMWIRELIST: %d wires, %d problems." % (len(rows), len(chk["problems"])))
        return {"rows": rows, "problems": chk["problems"]}

    return run(go)


@command("schemwirelist", aliases=("wirelist",), group=GROUP, label="Schematic Wire List", description="List the wires of the electrical schematic by name with from and to pins, and report open pins and number problems.", menu="Draw > Electrical > Wire List")
def schemwirelist_cmd(ctx):
    return do_wirelist(ctx, {})


@executes("schemwirelist")
def schemwirelist_exec(ctx, args):
    return do_wirelist(ctx, args)


def do_schem_export(ctx, args):
    return run(lambda: sservice.write_csv(args.get("path"), sservice.wirelist(ctx.d)))


@command("schemexport", group=GROUP, label="Export Wire List", description="Write the schematic wire list to a CSV file.", menu="Draw > Electrical > Export Wire List")
def schemexport_cmd(ctx):
    t = yield ctx.text("CSV file to write", "")
    if t.kind != "text" or not str(t.value).strip():
        return None
    return do_schem_export(ctx, {"path": str(t.value).strip()})


@executes("schemexport")
def schemexport_exec(ctx, args):
    return do_schem_export(ctx, args)
