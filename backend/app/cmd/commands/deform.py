import math
from types import SimpleNamespace

from app.cmd.commands.surfaces import GROUP, ask_style, guard, handles_of, keep_report
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.solid import surfwork as sw
from app.solid import work

CAGE_MOST = 16
MAX_MOVES = 4096
FLAT_SHARE = 0.05


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


def mm3(value, what, s: float) -> list:
    return [c * s for c in triple(value, what)]


def bodies_of(ctx, args) -> list:
    handles = handles_of(args)
    if not handles:
        raise CommandError("Give the handles of the solids or surfaces to deform.")
    out = []
    for h in dict.fromkeys(handles):
        body = guard(sw.body_of, ctx.d, h)
        if ctx.locked(body):
            raise CommandError("%s is on a locked layer." % (body.name or "The object"))
        out.append(body)
    return out


def common(args) -> dict:
    out = {}
    if args.get("max_points") is not None:
        try:
            out["max_points"] = int(args["max_points"])
        except (TypeError, ValueError):
            raise CommandError("max_points must be a whole number.")
    return out


def deviation_line(rep: dict) -> str:
    dev = rep.get("deviation") or {}
    state = "within" if dev.get("within") else "above"
    return "Deviation from the exact mapping at %d sample points: largest %.3g mm, mean %.3g mm, %s the model tolerance %.3g mm (%d control points on %d faces)." % (
        int(dev.get("samples", 0)), dev.get("max", 0.0), dev.get("mean", 0.0), state, dev.get("limit", 0.0), int(rep.get("poles", 0)), int(rep.get("faces", 0)))


def say_result(ctx, label: str, body, res: dict) -> None:
    rep = res.get("report") or {}
    summary = res.get("summary") or {}
    ctx.say("%s: %s is now a %s." % (label, body.name or "the object", sw.surface_label(summary)))
    ctx.say(deviation_line(rep))
    if not (rep.get("deviation") or {}).get("within"):
        ctx.say("%d surface(s) or edge(s) reached the control point limit before the tolerance; give a larger max_points to refine further." % int(rep.get("capped", 0)))
    if rep.get("closed_before") and not summary.get("closed"):
        ctx.say("The solid is no longer closed.")
    line = sw.audit_line(rep)
    if line:
        ctx.say(line)
    keep_report(ctx, rep)


def outcome(rows: list) -> dict:
    last = rows[-1][1]
    summary = last.get("summary") or {}
    rep = last.get("report") or {}
    dev = rep.get("deviation") or {}
    return {
        "handles": [h for h, _r in rows], "handle": rows[-1][0], "valid": all(bool((r.get("summary") or {}).get("valid")) for _h, r in rows),
        "closed": bool(summary.get("closed")), "deviation": max(float(((r.get("report") or {}).get("deviation") or {}).get("max", 0.0)) for _h, r in rows),
        "within": all(bool(((r.get("report") or {}).get("deviation") or {}).get("within")) for _h, r in rows), "tolerance": dev.get("limit"), "report": rep,
    }


def run_each(ctx, args, method: str, params: dict, op: str, label: str, name: str) -> dict:
    d = ctx.d
    copy = bool(args.get("copy", False))
    rows = []
    for body in bodies_of(ctx, args):
        res = guard(sw.call, d, method, {"id": guard(work.worker_id, d, body), **params, **common(args)})
        if copy:
            made = guard(sw.add_result, ctx, res, "%s %s" % (body.name or "Object", name), op)
        else:
            made = guard(sw.replace_result, ctx, body, res, op)
        say_result(ctx, label, body, res)
        rows.append((made.handle, res))
    return outcome(rows)


def do_bend(ctx, args):
    s = sw.scale(ctx.d)
    if args.get("start") is None or args.get("end") is None:
        raise CommandError("Give the spine as start and end.")
    params = {"start": mm3(args["start"], "The spine start", s), "end": mm3(args["end"], "The spine end", s), "limit": bool(args.get("limit", False))}
    if args.get("through") is not None:
        params["through"] = mm3(args["through"], "The bend point", s)
    if args.get("direction") is not None:
        params["direction"] = triple(args["direction"], "The bend direction")
    if args.get("angle") is not None:
        try:
            deg = float(args["angle"])
        except (TypeError, ValueError):
            raise CommandError("The bend angle is a number of degrees.")
        if not math.isfinite(deg) or abs(deg) < 1e-9 or abs(deg) >= 360.0:
            raise CommandError("The bend angle must not be zero and stays below 360 degrees.")
        params["angle"] = math.radians(deg)
        if "through" not in params and "direction" not in params:
            raise CommandError("With an angle, give the side to bend toward as through (a point) or direction (a vector).")
    elif "through" not in params:
        raise CommandError("Give a point to bend through, or an angle in degrees with a direction.")
    got = run_each(ctx, args, "deform_bend", params, "bend", "BEND", "bent")
    rep = got["report"]
    ctx.say("Bend radius %s, angle %.6g degrees over a spine of %s%s." % (ctx.fd(rep.get("radius", 0.0) / s), math.degrees(rep.get("angle", 0.0)), ctx.fd(rep.get("spine_length", 0.0) / s), ", limited to the spine" if rep.get("limit") else ""))
    return got


def rail_spec(ctx, args, key: str) -> dict:
    d = ctx.d
    s = sw.scale(d)
    line = args.get(key + "_line")
    if line is not None:
        if not isinstance(line, (list, tuple)) or len(line) != 2:
            raise CommandError("Give %s_line as two points." % key)
        return {"kind": "line", "a": mm3(line[0], "The line start", s), "b": mm3(line[1], "The line end", s)}
    if isinstance(args.get(key + "_edge"), dict):
        return guard(sw.edge_curve, d, args[key + "_edge"])
    if args.get(key) is None:
        raise CommandError("Give the %s curve as %s (a curve handle), %s_edge (an edge reference) or %s_line (two points)." % (key, key, key, key))
    return guard(sw.curve_spec, d, guard(sw.entity_of, d, args[key]))


def do_flow(ctx, args):
    s = sw.scale(ctx.d)
    params = {"base": rail_spec(ctx, args, "base"), "target": rail_spec(ctx, args, "target"), "stretch": bool(args.get("stretch", False)), "reverse_base": bool(args.get("reverse_base", False)), "reverse_target": bool(args.get("reverse_target", False))}
    got = run_each(ctx, args, "deform_flow", params, "flow", "FLOW", "flowed")
    rep = got["report"]
    ctx.say("Base curve %s long, target curve %s long, lengths %s." % (ctx.fd(rep.get("base_length", 0.0) / s), ctx.fd(rep.get("target_length", 0.0) / s), "stretched by %.6g" % rep.get("ratio", 1.0) if rep.get("stretch") else "kept"))
    return got


def face_spec(ctx, args, key: str):
    d = ctx.d
    if args.get(key) is None:
        raise CommandError("Give the %s surface as %s (a surface handle)." % (key, key))
    body = guard(sw.body_of, d, args[key])
    ref = {"body": body.handle, "face": args.get(key + "_face"), "face_index": args.get(key + "_face_index")}
    if ref["face"] is None and ref["face_index"] is None:
        if not sw.single_face(body):
            raise CommandError("The %s surface has %d faces; give %s_face or %s_face_index." % (key, len(body.face_ids), key, key))
        ref["face_index"] = 0
    return body, guard(sw.face_ref, d, ref)[1]


def do_flowsrf(ctx, args):
    s = sw.scale(ctx.d)
    moving = set(handles_of(args))
    target_body, target = face_spec(ctx, args, "target")
    plane = args.get("base_plane")
    if plane is not None:
        if not isinstance(plane, (list, tuple)) or len(plane) != 3:
            raise CommandError("Give base_plane as three points: a corner and the ends of the two sides from it.")
        o, x, y = (mm3(q, "A base plane point", s) for q in plane)
        base = {"plane": {"origin": o, "x": [x[k] - o[k] for k in range(3)], "y": [y[k] - o[k] for k in range(3)]}}
    else:
        base_body, face = face_spec(ctx, args, "base")
        if base_body.handle in moving:
            raise CommandError("The base surface cannot be one of the objects to deform.")
        base = {"face": face}
    if target_body.handle in moving:
        raise CommandError("The target surface cannot be one of the objects to deform.")
    params = {"base": base, "target": {"face": target}}
    for key in ("swap_uv", "reverse_u", "reverse_v", "flip"):
        params[key] = bool(args.get(key, False))
    return run_each(ctx, args, "deform_flow_surface", params, "flow_surface", "FLOWSRF", "flowed")


def cage_of(body) -> dict:
    rec = (body.source or {}).get("cage")
    if not isinstance(rec, dict):
        raise CommandError("%s has no cage; run CAGE on it first." % (body.name or "The object"))
    if rec.get("result") != body.blob:
        raise CommandError("%s changed after its cage was made; run CAGE on it again." % (body.name or "The object"))
    return rec


def cage_points(rec: dict, body, s: float) -> list:
    nx, ny, nz = rec["counts"]
    off = [(body.offset[k] - rec["at"][k]) for k in range(3)]
    out = []
    for n, q in enumerate(rec["points"]):
        out.append({"index": [n // (ny * nz), (n // nz) % ny, n % nz], "at": [q[k] / s + off[k] for k in range(3)]})
    return out


def cage_view(rec: dict, body, s: float) -> dict:
    return {"handle": body.handle, "counts": list(rec["counts"]), "degrees": list(rec["degrees"]), "points": cage_points(rec, body, s)}


def cage_counts(args) -> list:
    raw = args.get("counts", [3, 3, 3])
    if isinstance(raw, (int, float)):
        raw = [raw, raw, raw]
    try:
        counts = [int(c) for c in raw]
    except (TypeError, ValueError):
        raise CommandError("counts is three whole numbers.")
    if len(counts) != 3 or any(c < 2 or c > CAGE_MOST for c in counts):
        raise CommandError("A cage has from 2 to %d points in each of its three directions." % CAGE_MOST)
    return counts


def cage_degrees(args, counts: list) -> list:
    raw = args.get("degree", 3)
    if isinstance(raw, (int, float)):
        raw = [raw, raw, raw]
    try:
        wanted = [int(g) for g in raw]
    except (TypeError, ValueError):
        raise CommandError("degree is a whole number, or three of them.")
    if len(wanted) != 3 or any(g < 1 for g in wanted):
        raise CommandError("The cage degree is at least 1 in each direction.")
    return [min(g, c - 1) for g, c in zip(wanted, counts)]


def do_cage(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    handles = handles_of(args)
    if len(handles) != 1:
        raise CommandError("Give the handle of one solid or surface to put in a cage.")
    body = guard(sw.body_of, d, handles[0])
    if ctx.locked(body):
        raise CommandError("%s is on a locked layer." % (body.name or "The object"))
    counts = cage_counts(args)
    degrees = cage_degrees(args, counts)
    box = guard(work.kcall, "shape_summary", {"id": guard(work.worker_id, d, body)})["summary"].get("bbox")
    if not box:
        raise CommandError("The object has no geometry to put in a cage.")
    try:
        margin = float(args.get("margin", 0.0)) * s
    except (TypeError, ValueError):
        raise CommandError("The margin is a number.")
    if not math.isfinite(margin) or margin < 0:
        raise CommandError("The margin must not be negative.")
    lo = [box[k] - margin for k in range(3)]
    hi = [box[k + 3] + margin for k in range(3)]
    least = max(max(hi[k] - lo[k] for k in range(3)) * FLAT_SHARE, 1e-6)
    for k in range(3):
        if hi[k] - lo[k] < least:
            mid = (lo[k] + hi[k]) / 2.0
            lo[k], hi[k] = mid - least / 2.0, mid + least / 2.0
    frame = {"origin": lo, "x": [hi[0] - lo[0], 0.0, 0.0], "y": [0.0, hi[1] - lo[1], 0.0], "z": [0.0, 0.0, hi[2] - lo[2]], "counts": counts, "degrees": degrees}
    rest = guard(work.kcall, "deform_cage_rest", frame)["points"]
    rec = {**frame, "points": rest, "blob": body.blob, "base_offset": list(body.offset), "at": list(body.offset), "result": body.blob, "faces": list(range(len(body.face_ids))), "edges": list(range(len(body.edge_ids)))}
    target = d.modify(body.handle)
    target.source = {**(body.source or {}), "cage": rec}
    ctx.say("CAGE: %s has a cage of %d by %d by %d points, degree %d, %d, %d." % (body.name or "the object", counts[0], counts[1], counts[2], degrees[0], degrees[1], degrees[2]))
    return cage_view(rec, target, s)


def cage_index(row, counts: list) -> int:
    try:
        i, j, k = int(row[0]), int(row[1]), int(row[2])
    except (TypeError, ValueError, IndexError, KeyError):
        raise CommandError("Name a cage point by its three indices.")
    if not (0 <= i < counts[0] and 0 <= j < counts[1] and 0 <= k < counts[2]):
        raise CommandError("Cage point %d, %d, %d is outside the %d by %d by %d cage." % (i, j, k, counts[0], counts[1], counts[2]))
    return (i * counts[1] + j) * counts[2] + k


def do_cageedit(ctx, args):
    d = ctx.d
    s = sw.scale(d)
    handles = handles_of(args)
    if len(handles) != 1:
        raise CommandError("Give the handle of one object that has a cage.")
    body = guard(sw.body_of, d, handles[0])
    rec = cage_of(body)
    counts = rec["counts"]
    moved = [(body.offset[k] - rec["at"][k]) * s for k in range(3)]
    origin = [rec["origin"][k] + moved[k] for k in range(3)]
    points = [[q[k] + moved[k] for k in range(3)] for q in rec["points"]]
    base_offset = [rec["base_offset"][k] + body.offset[k] - rec["at"][k] for k in range(3)]
    frame = {"origin": origin, "x": rec["x"], "y": rec["y"], "z": rec["z"], "counts": counts, "degrees": rec["degrees"]}
    changed = 0
    if args.get("reset"):
        points = guard(work.kcall, "deform_cage_rest", frame)["points"]
        changed = len(points)
    elif args.get("moves"):
        if len(args["moves"]) > MAX_MOVES:
            raise CommandError("At most %d cage points move at once." % MAX_MOVES)
        for m in args["moves"]:
            if not isinstance(m, dict):
                raise CommandError("Each move is {i, j, k, to}.")
            points[cage_index((m.get("i"), m.get("j"), m.get("k")), counts)] = mm3(m.get("to"), "The new position", s)
            changed += 1
    elif args.get("points"):
        delta = mm3(args.get("delta"), "The displacement", s)
        for n in dict.fromkeys(cage_index(row, counts) for row in args["points"]):
            points[n] = [points[n][k] + delta[k] for k in range(3)]
            changed += 1
    else:
        ctx.say("CAGEEDIT: the cage of %s has %d by %d by %d points." % (body.name or "the object", counts[0], counts[1], counts[2]))
        return cage_view(rec, body, s)
    if ctx.locked(body):
        raise CommandError("%s is on a locked layer." % (body.name or "The object"))
    base = SimpleNamespace(blob=rec["blob"], offset=base_offset)
    res = guard(sw.call, d, "deform_cage", {"id": guard(work.worker_id, d, base), **frame, "points": points, **common(args)})
    inputs = (res.get("history") or {}).get("inputs") or []
    parts = None
    faces = edges = None
    if inputs and rec.get("faces") is not None and len(rec["faces"]) == len(inputs[0]["faces"]) and len(rec["edges"]) == len(inputs[0]["edges"]):
        try:
            parts = [([body.face_ids[n] for n in rec["faces"]], [body.edge_ids[n] for n in rec["edges"]], inputs[0])]
            faces = [inputs[0]["faces"][str(n)]["to"][0] for n in range(len(rec["faces"]))]
            edges = [inputs[0]["edges"][str(n)]["to"][0] for n in range(len(rec["edges"]))]
        except (IndexError, KeyError):
            parts, faces, edges = None, None, None
    target = d.modify(body.handle)
    source = {**sw.source_for("cage", res), "from": [body.name]}
    guard(work.apply_result, d, target, res["id"], res["summary"], source, parts, body.lineage)
    new = {**frame, "points": points, "blob": rec["blob"], "base_offset": base_offset, "at": [0.0, 0.0, 0.0], "result": target.blob, "faces": faces, "edges": edges}
    target.source = {**source, "cage": new}
    ctx.say("CAGEEDIT: %d cage point(s) set." % changed)
    say_result(ctx, "CAGEEDIT", body, res)
    got = outcome([(target.handle, res)])
    got["cage"] = cage_view(new, target, s)
    return got


def do_cageoff(ctx, args):
    d = ctx.d
    handles = handles_of(args)
    if len(handles) != 1:
        raise CommandError("Give the handle of one object that has a cage.")
    body = guard(sw.body_of, d, handles[0])
    if not isinstance((body.source or {}).get("cage"), dict):
        raise CommandError("%s has no cage." % (body.name or "The object"))
    target = d.modify(body.handle)
    target.source = {k: v for k, v in (body.source or {}).items() if k != "cage"}
    ctx.say("CAGEOFF: the cage of %s is removed; the shape stays as it is." % (body.name or "the object"))
    return {"handle": target.handle}


def pick_objects(ctx, message):
    sel = yield ctx.select(message)
    if sel.kind != "selection" or not sel.value:
        return None
    return [int(h) for h in sel.value]


def pick_one(ctx, message):
    sel = yield ctx.select(message, pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return None
    return int(sel.value[0])


@command("bend", group=GROUP, label="Bend", description="Bend solids and surfaces along an arc: a spine from start to end, and a point the bent spine passes through or an angle; optionally only along the spine.", menu="Modify > Deform > Bend")
def bend_cmd(ctx):
    handles = yield from pick_objects(ctx, "Select solids or surfaces to bend")
    if not handles:
        return
    a = yield ctx.point("Specify the start of the spine")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify the end of the spine", base=a.value)
    if b.kind != "point":
        return
    q = yield ctx.point("Specify a point to bend through", base=b.value)
    if q.kind != "point":
        return
    word = yield from ask_style(ctx, "Limit the bend to the spine?", ["No", "Yes"], "No")
    if word is None:
        return
    do_bend(ctx, {"handles": handles, "start": list(a.value), "end": list(b.value), "through": list(q.value), "limit": word == "Yes"})


@executes("bend")
def bend_exec(ctx, args):
    return do_bend(ctx, args)


@command("flow", aliases=("flowalongcurve",), group=GROUP, label="Flow along Curve", description="Map solids and surfaces lying along a base curve onto a target curve, keeping lengths or stretching them to the target.", menu="Modify > Deform > Flow along Curve")
def flow_cmd(ctx):
    handles = yield from pick_objects(ctx, "Select solids or surfaces to flow")
    if not handles:
        return
    base = yield from pick_one(ctx, "Select the base curve")
    if base is None:
        return
    target = yield from pick_one(ctx, "Select the target curve")
    if target is None:
        return
    word = yield from ask_style(ctx, "Stretch to the length of the target curve?", ["No", "Yes"], "No")
    if word is None:
        return
    do_flow(ctx, {"handles": handles, "base": base, "target": target, "stretch": word == "Yes"})


@executes("flow")
def flow_exec(ctx, args):
    return do_flow(ctx, args)


@command("flowsrf", aliases=("flowalongsrf",), group=GROUP, label="Flow along Surface", description="Map solids and surfaces from a base surface or plane onto a target surface, keeping their distance from it.", menu="Modify > Deform > Flow along Surface")
def flowsrf_cmd(ctx):
    handles = yield from pick_objects(ctx, "Select solids or surfaces to flow")
    if not handles:
        return
    base = yield from pick_one(ctx, "Select the base surface")
    if base is None:
        return
    target = yield from pick_one(ctx, "Select the target surface")
    if target is None:
        return
    do_flowsrf(ctx, {"handles": handles, "base": base, "target": target})


@executes("flowsrf")
def flowsrf_exec(ctx, args):
    return do_flowsrf(ctx, args)


@command("cage", group=GROUP, label="Cage", description="Wrap a solid or surface in a box of control points, with a chosen number of points in each direction, ready for Cage Edit.", menu="Modify > Deform > Cage")
def cage_cmd(ctx):
    handle = yield from pick_one(ctx, "Select a solid or surface")
    if handle is None:
        return
    counts = []
    for axis in ("X", "Y", "Z"):
        n = yield ctx.number("Specify the number of cage points along %s" % axis, default=3, integer=True, minimum=2, maximum=CAGE_MOST)
        if n.kind != "number":
            return
        counts.append(int(n.value))
    do_cage(ctx, {"handle": handle, "counts": counts})


@executes("cage")
def cage_exec(ctx, args):
    return do_cage(ctx, args)


@command("cageedit", group=GROUP, label="Cage Edit", description="Move points of an object's cage to absolute positions or by a displacement; the object deforms with the cage.", menu="Modify > Deform > Cage Edit")
def cageedit_cmd(ctx):
    handle = yield from pick_one(ctx, "Select an object that has a cage")
    if handle is None:
        return
    body = guard(sw.body_of, ctx.d, handle)
    rec = cage_of(body)
    index = []
    for axis, count in zip(("X", "Y", "Z"), rec["counts"]):
        n = yield ctx.number("Specify the cage point along %s (1 to %d)" % (axis, count), integer=True, minimum=1, maximum=count)
        if n.kind != "number":
            return
        index.append(int(n.value) - 1)
    at = cage_points(rec, body, sw.scale(ctx.d))[cage_index(index, rec["counts"])]["at"]
    ctx.say("The cage point is at %s." % ",".join(ctx.fd(c) for c in at))
    to = yield ctx.point("Specify the new position", base=at)
    if to.kind != "point":
        return
    do_cageedit(ctx, {"handle": handle, "moves": [{"i": index[0], "j": index[1], "k": index[2], "to": list(to.value)}]})


@executes("cageedit")
def cageedit_exec(ctx, args):
    return do_cageedit(ctx, args)


@command("cageoff", group=GROUP, label="Remove Cage", description="Remove the cage of an object and keep its shape.", menu="Modify > Deform > Remove Cage")
def cageoff_cmd(ctx):
    handle = yield from pick_one(ctx, "Select an object that has a cage")
    if handle is None:
        return
    do_cageoff(ctx, {"handle": handle})


@executes("cageoff")
def cageoff_exec(ctx, args):
    return do_cageoff(ctx, args)
