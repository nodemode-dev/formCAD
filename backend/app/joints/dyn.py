import copy
import heapq
import math
import time

import numpy as np

from app.joints import proxy
from app.joints import store as J
from app.mates import joint_eq
from app.mates import ops as M

PRIORITY = {"slider": 0, "cylindrical": 1, "pinslot": 1, "planar": 1, "rigid": 2, "ball": 3, "revolute": 4}
CHUNK = 25
WORLD = "world"


def quat_of(r: np.ndarray) -> list:
    t = float(np.trace(r))
    if t > 0:
        s = math.sqrt(t + 1.0) * 2.0
        q = [0.25 * s, (r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s]
    elif r[0, 0] > r[1, 1] and r[0, 0] > r[2, 2]:
        s = math.sqrt(1.0 + r[0, 0] - r[1, 1] - r[2, 2]) * 2.0
        q = [(r[2, 1] - r[1, 2]) / s, 0.25 * s, (r[0, 1] + r[1, 0]) / s, (r[0, 2] + r[2, 0]) / s]
    elif r[1, 1] > r[2, 2]:
        s = math.sqrt(1.0 + r[1, 1] - r[0, 0] - r[2, 2]) * 2.0
        q = [(r[0, 2] - r[2, 0]) / s, (r[0, 1] + r[1, 0]) / s, 0.25 * s, (r[1, 2] + r[2, 1]) / s]
    else:
        s = math.sqrt(1.0 + r[2, 2] - r[0, 0] - r[1, 1]) * 2.0
        q = [(r[1, 0] - r[0, 1]) / s, (r[0, 2] + r[2, 0]) / s, (r[1, 2] + r[2, 1]) / s, 0.25 * s]
    n = math.sqrt(sum(v * v for v in q))
    return [v / n for v in q]


class Edge:
    def __init__(self, mate, a, b):
        self.mate = mate
        self.a = a
        self.b = b
        self.kind = mate.opt["spec"]["type"]


def plan(model, free: list, roots: set) -> tuple:
    edges = []
    for m in model.mates:
        if m.kind != "joint" or m.suppressed:
            continue
        rec = model.recs[m.id]
        a = rec["refs"][0]["comp"] or WORLD
        b = rec["refs"][1]["comp"] or WORLD
        edges.append(Edge(m, a, b))
    visited = {WORLD} | set(roots)
    tree = []
    used = set()

    def grow(start_nodes):
        heap = []
        count = 0
        for e in edges:
            if id(e) in used:
                continue
            if (e.a in start_nodes and e.b not in start_nodes) or (e.b in start_nodes and e.a not in start_nodes):
                heapq.heappush(heap, (PRIORITY[e.kind], count, id(e), e))
                count += 1
        while heap:
            _, _, _, e = heapq.heappop(heap)
            if id(e) in used:
                continue
            if e.a in visited and e.b in visited:
                continue
            parent, child, forward = (e.a, e.b, True) if e.a in visited else (e.b, e.a, False)
            used.add(id(e))
            visited.add(child)
            tree.append((e, parent, child, forward))
            for o in edges:
                if id(o) in used:
                    continue
                if (o.a in visited) != (o.b in visited):
                    heapq.heappush(heap, (PRIORITY[o.kind], count, id(o), o))
                    count += 1

    grow(visited)
    floating = [c for c in model.net.bodies if c not in visited]
    roots_free = []
    for c in floating:
        if c in visited:
            continue
        if c in free:
            visited.add(c)
            roots_free.append(c)
            grow(visited)
    loose = [c for c in model.net.bodies if c not in visited]
    closures = [e for e in edges if id(e) not in used]
    return tree, closures, roots_free, loose


def build(model, proxies: dict, study, dyn: dict, free: list, pair_comps: list, timestep: float, tracks: list):
    import mujoco

    mmu = model.mmu
    unit = mmu * 1e-3
    spec = mujoco.MjSpec()
    spec.compiler.degree = False
    spec.option.timestep = timestep
    spec.option.gravity = list(dyn["gravity"])
    roots = {c for c, b in model.net.bodies.items() if b.fixed}
    tree, closures, free_roots, loose = plan(model, free, roots)
    poses = {c: (b.R.copy(), b.t.copy() * unit) for c, b in model.net.bodies.items()}
    poses[WORLD] = (np.eye(3), np.zeros(3))
    bodies = {WORLD: spec.worldbody}
    names = {}
    jmap = {}
    warnings = []

    def make_body(cid, parent):
        pr, pt = poses[parent]
        cr, ct = poses[cid]
        body = bodies[parent].add_body(name=cid, pos=list(pr.T @ (ct - pt)), quat=quat_of(pr.T @ cr))
        bodies[cid] = body
        names[cid] = cid
        p = proxies.get(cid)
        if p is None:
            return body
        for k, pts in enumerate(p["pieces"]):
            mesh = spec.add_mesh(name="%s_m%d" % (cid, k))
            mesh.uservert = pts.reshape(-1).tolist()
            g = body.add_geom(name="%s_g%d" % (cid, k), type=mujoco.mjtGeom.mjGEOM_MESH, meshname=mesh.name, contype=0, conaffinity=0, group=1)
            g.friction = [dyn["friction"], 0.005, 0.0001]
        body.mass = float(p["mass"])
        body.ipos = list(p["com"])
        i = p["inertia"]
        body.fullinertia = [float(i[0, 0]), float(i[1, 1]), float(i[2, 2]), float(i[0, 1]), float(i[0, 2]), float(i[1, 2])]
        body.explicitinertial = True
        return body

    for c, b in model.net.bodies.items():
        if b.fixed:
            make_body(c, WORLD)
    for c in free_roots:
        body = make_body(c, WORLD)
        body.add_freejoint()
    for c in loose:
        make_body(c, WORLD)
        warnings.append("Component %s has no joint to the ground and is not marked free, so it stays where it is." % c)
    for edge, parent, child, forward in tree:
        body = make_body(child, parent)
        add_joint(spec, mujoco, model, edge, parent, child, forward, body, poses, unit, jmap, max(dyn["contact_time"], 2.5 * timestep))
    scale = model.L * unit
    for k, edge in enumerate(closures):
        if edge.kind not in ("revolute", "ball"):
            raise J.MotionError("%s (%s) closes a loop, and dynamics can only close a loop with a revolute or ball joint." % (model.recs[edge.mate.id]["name"], edge.kind))
        o_w, axis_w = joint_point_axis(model, edge, unit)
        ar, at = poses[edge.a]
        pts = [o_w] if edge.kind == "ball" else [o_w, o_w + axis_w * (0.5 * scale)]
        for p in pts:
            eq = spec.add_equality()
            eq.type = mujoco.mjtEq.mjEQ_CONNECT
            eq.name1, eq.name2 = edge.a, edge.b
            eq.objtype = mujoco.mjtObj.mjOBJ_BODY
            eq.data = np.array(list(ar.T @ (p - at)) + [0.0] * 9)
            eq.solref = [max(dyn["solref_loop"], 2.5 * timestep), 1.0]
    for a, b in pair_comps:
        ga = [g.name for g in bodies[a].geoms] if a in bodies else []
        gb = [g.name for g in bodies[b].geoms] if b in bodies else []
        for x in ga:
            for y in gb:
                pair = spec.add_pair()
                pair.geomname1, pair.geomname2 = x, y
                pair.friction = [dyn["friction"], dyn["friction"], 0.005, 0.0001, 0.0001]
                pair.solref = [max(dyn["contact_time"], 2.5 * timestep), 1.0]
    acts = []
    for mid, key, keys in tracks:
        entry = jmap.get((mid, key))
        if entry is None:
            warnings.append("The track on %s %s has no moving joint in the simulation; it is ignored." % (model.recs[mid]["name"], key))
            continue
        act = spec.add_actuator(name="drive_%d_%s" % (mid, key), target=entry["name"], trntype=mujoco.mjtTrn.mjTRN_JOINT)
        act.gaintype = mujoco.mjtGain.mjGAIN_FIXED
        act.biastype = mujoco.mjtBias.mjBIAS_AFFINE
        act.gainprm[0] = 1.0
        act.biasprm[1] = -1.0
        acts.append((mid, key, keys, entry))
    mj = spec.compile()
    return mj, {"bodies": bodies, "jmap": jmap, "acts": acts, "warnings": warnings, "closures": len(closures), "tree": len(tree), "unit": unit, "free": free_roots}


def joint_point_axis(model, edge, unit) -> tuple:
    m = edge.mate
    spec = m.opt["spec"]
    w = model.net.worlds(m)
    fa, oa = spec["fa"]
    ra = w[0]["R"] @ fa
    o = (w[0]["R"] @ oa + w[0]["t"]) * unit
    r0 = spec["rel0"][0]
    axis = ra @ r0 @ np.array([0.0, 0.0, 1.0])
    return o, axis / np.linalg.norm(axis)


def world_axes(model, edge) -> np.ndarray:
    m = edge.mate
    spec = m.opt["spec"]
    w = model.net.worlds(m)
    fa, _ = spec["fa"]
    return w[0]["R"] @ fa @ spec["rel0"][0]


def add_joint(spec, mujoco, model, edge, parent, child, forward, body, poses, unit, jmap, soft):
    kind = edge.kind
    mate = edge.mate
    rec = model.recs[mate.id]
    name = rec["name"]
    if kind == "rigid":
        return
    o_w, _ = joint_point_axis(model, edge, unit)
    cr, ct = poses[child]
    axes = world_axes(model, edge)
    pos = list(cr.T @ (o_w - ct))
    sign = 1.0 if forward else -1.0
    if not forward and kind in ("pinslot", "planar"):
        raise J.MotionError("%s (%s) is attached the other way round; make the moving component the second one of the joint." % (name, kind))
    w = model.net.worlds(mate)
    cur = joint_eq.values_of(mate.opt["spec"], w[0], w[1], (mate.opt.get("state") or {}).get("q"))
    lim = mate.opt["spec"]["lim"]

    def local(v):
        return list(cr.T @ (sign * v))

    def add(jtype, jname, axis_w, key):
        j = body.add_joint(name="%s_%s" % (name, jname), type=jtype, pos=pos, axis=local(axis_w) if jtype != mujoco.mjtJoint.mjJNT_BALL else [0, 0, 1])
        if key in lim:
            lo, hi = lim[key]
            q0 = cur[key]
            lo_m = -1e6 if lo is None else lo - q0
            hi_m = 1e6 if hi is None else hi - q0
            if not forward:
                lo_m, hi_m = -hi_m, -lo_m
            if jtype == mujoco.mjtJoint.mjJNT_SLIDE:
                lo_m, hi_m = lo_m * (1.0 if key in joint_eq.ANGLES else unit), hi_m * (1.0 if key in joint_eq.ANGLES else unit)
            j.limited = mujoco.mjtLimited.mjLIMITED_TRUE
            j.range = [lo_m, hi_m]
            j.solref_limit = [soft, 1.0]
        scale = 1.0 if key in joint_eq.ANGLES else unit
        jmap[(mate.id, key)] = {"name": j.name, "sign": sign, "q0": cur[key], "scale": scale, "kind": jtype}
        return j

    hinge, slide, ball = mujoco.mjtJoint.mjJNT_HINGE, mujoco.mjtJoint.mjJNT_SLIDE, mujoco.mjtJoint.mjJNT_BALL
    ex, ey, ez = axes[:, 0], axes[:, 1], axes[:, 2]
    if kind == "revolute":
        add(hinge, "rz", ez, "rz")
    elif kind == "slider":
        add(slide, "tz", ez, "tz")
    elif kind == "cylindrical":
        add(slide, "tz", ez, "tz")
        add(hinge, "rz", ez, "rz")
    elif kind == "pinslot":
        add(slide, "tx", ex, "tx")
        add(hinge, "rz", ez, "rz")
    elif kind == "planar":
        add(slide, "tx", ex, "tx")
        add(slide, "ty", ey, "ty")
        add(hinge, "rz", ez, "rz")
    elif kind == "ball":
        j = body.add_joint(name="%s_ball" % name, type=ball, pos=pos)
        cone = mate.opt["spec"]["cone"]
        if cone is not None:
            j.limited = mujoco.mjtLimited.mjLIMITED_TRUE
            j.range = [0.0, cone]
            j.solref_limit = [soft, 1.0]
        jmap[(mate.id, "ball")] = {"name": j.name, "sign": sign, "q0": 0.0, "scale": 1.0, "kind": ball}


def prepare(doc, spec_in: dict, restricted: bool):
    try:
        __import__("mujoco")
    except ImportError:
        raise J.MotionError("Dynamics runs need MuJoCo, which is not installed here. It has no wheel for an Intel Mac; motion studies and joints work without it.")

    d = doc.drawing
    data = J.load(d)
    caps = J.limits(restricted)
    dyn = copy.deepcopy(data["dynamics"])
    duration = J.number(spec_in.get("duration"), "The duration", 0.001, caps["dyn_duration"])
    timestep = J.number(spec_in.get("timestep", dyn["timestep"]), "The time step", 1e-5, 0.05)
    nsteps = int(math.ceil(duration / timestep))
    if nsteps > caps["dyn_steps"]:
        raise J.MotionError("This run needs %d steps; the limit is %d%s. Lower the duration or raise the time step." % (nsteps, caps["dyn_steps"], " for a macro or agent" if restricted else ""))
    fps = J.number(spec_in.get("record_fps", 60), "The record rate", 1, caps["dyn_record_fps"])
    nframes = int(duration * fps) + 2
    if nframes > caps["dyn_frames"]:
        raise J.MotionError("This run would record %d frames; the limit is %d. Lower the record rate or the duration." % (nframes, caps["dyn_frames"]))
    model = M.Model(d)
    if len(model.net.bodies) > caps["dyn_bodies"]:
        raise J.MotionError("Dynamics runs take at most %d components." % caps["dyn_bodies"])
    study = None
    tracks = []
    if spec_in.get("study"):
        study = J.study(data, spec_in["study"])
        by_name = {model.recs[m.id]["name"]: m for m in model.mates if m.kind == "joint"}
        for tr in study["tracks"]:
            m = by_name.get(tr["joint"])
            if m is not None and not m.suppressed:
                tracks.append((m.id, tr["coord"], tr["keys"]))
    free = [str(c) for c in (spec_in.get("free") or [])]
    for c in free:
        if c not in model.net.bodies:
            raise J.MotionError("There is no component %s to let fall." % c)
    kids = spec_in.get("contacts")
    if kids is None:
        kids = list(data["contacts"].keys())
    from app.joints import contact

    fixed = {c for c, b in model.net.bodies.items() if b.fixed}
    pairs = contact.component_pairs(d, [J.contact(data, k)["id"] for k in kids], fixed)[0] if kids else []
    if len(pairs) > caps["pairs"]:
        raise J.MotionError("The contact sets name %d component pairs; the limit is %d%s." % (len(pairs), caps["pairs"], " for a macro or agent" if restricted else ""))
    cids = list(model.net.bodies)
    prox = proxy.fetch(doc, cids, float(dyn["density"]), 48)
    mj, info = build(model, prox, study, dyn, free, pairs, timestep, tracks)
    stop_on_contact = bool(spec_in.get("stop_on_contact"))
    ctx = {"mj": mj, "info": info, "model": model, "dyn": dyn, "duration": duration, "timestep": timestep, "nsteps": nsteps, "fps": fps, "pairs": pairs, "stop": stop_on_contact, "tracks": tracks, "prox": prox, "names": {m.id: model.recs[m.id]["name"] for m in model.mates if m.kind == "joint"}, "caps": caps, "mmu": model.mmu}
    return lambda job: execute(job, ctx)


def track_at(keys, t):
    from app.joints.study import track_value

    return track_value(keys, t)


def execute(job, ctx) -> dict:
    import mujoco

    mj, info, model = ctx["mj"], ctx["info"], ctx["model"]
    data = mujoco.MjData(mj)
    unit = info["unit"]
    dt = ctx["timestep"]
    jmap = info["jmap"]
    acts = info["acts"]
    for i, (mid, key, keys, entry) in enumerate(acts):
        jid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_JOINT, entry["name"])
        adr = mj.jnt_dofadr[jid]
        inv = float(mj.dof_invweight0[adr])
        eff = 1.0 / inv if inv > 1e-12 else 1.0
        wn = 2.0 * math.pi * ctx["dyn"]["servo_hz"]
        kp = eff * wn * wn
        kv = 2.0 * ctx["dyn"]["damping_ratio"] * eff * wn
        aid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_ACTUATOR, "drive_%d_%s" % (mid, key))
        mj.actuator_gainprm[aid, 0] = kp
        mj.actuator_biasprm[aid, 1] = -kp
        mj.actuator_biasprm[aid, 2] = -kv
    cids = [c for c, b in model.net.bodies.items() if not b.fixed]
    bids = {c: mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_BODY, c) for c in model.net.bodies}
    jids = {k: mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_JOINT, v["name"]) for k, v in jmap.items()}
    geom_owner = {}
    for c, bid in bids.items():
        for g in range(mj.ngeom):
            if mj.geom_bodyid[g] == bid:
                geom_owner[g] = c
    frames, states = job.frames, job.states
    plots_keys = [(k, v) for k, v in jmap.items() if k[1] != "ball"]
    ball_keys = [(k, v) for k, v in jmap.items() if k[1] == "ball"]
    contacts = []
    seen = set()
    stopped = None
    next_rec = 0.0
    rec_dt = 1.0 / ctx["fps"]
    steps = 0
    t0 = time.perf_counter()
    peak = {}

    def record():
        t = float(data.time)
        poses = {}
        for c in cids:
            b = bids[c]
            m = np.eye(4)
            m[:3, :3] = data.xmat[b].reshape(3, 3)
            m[:3, 3] = data.xpos[b] / unit
            poses[c] = [float(v) for v in m.reshape(-1)]
        q = {}
        for (mid, key), v in plots_keys:
            adr = mj.jnt_qposadr[jids[(mid, key)]]
            val = v["q0"] + v["sign"] * float(data.qpos[adr]) / v["scale"]
            q.setdefault(ctx["names"][mid], {})[key] = joint_eq.to_user(key, val)
        for (mid, key), v in ball_keys:
            adr = mj.jnt_qposadr[jids[(mid, key)]]
            quat = np.array(data.qpos[adr:adr + 4])
            vec = np.zeros(3)
            mujoco.mju_quat2Vel(vec, quat, 1.0)
            vec = vec * v["sign"]
            q.setdefault(ctx["names"][mid], {}).update({"rx": math.degrees(vec[0]), "ry": math.degrees(vec[1]), "rz": math.degrees(vec[2])})
        frames.append({"t": t, "q": q, "poses": poses})
        states.append(None)

    def watch():
        nonlocal stopped
        for i in range(data.ncon):
            c = data.contact[i]
            a, b = geom_owner.get(int(c.geom1)), geom_owner.get(int(c.geom2))
            if a is None or b is None:
                continue
            force = np.zeros(6)
            mujoco.mj_contactForce(mj, data, i, force)
            key = tuple(sorted((a, b)))
            peak[key] = max(peak.get(key, 0.0), float(force[0]))
            if key not in seen:
                seen.add(key)
                contacts.append({"t": float(data.time), "pair": list(key), "gap": float(c.dist) / unit, "gap_mm": float(c.dist) * 1000.0, "force": float(force[0])})
                if ctx["stop"] and stopped is None:
                    stopped = {"time": float(data.time), "reason": "contact", "pair": list(key), "gap": float(c.dist) / unit, "gap_mm": float(c.dist) * 1000.0, "force": float(force[0])}
        return stopped is not None

    mujoco.mj_forward(mj, data)
    record()
    next_rec = rec_dt
    total = ctx["nsteps"]
    while steps < total and stopped is None:
        job.check()
        n = min(CHUNK, total - steps)
        for _ in range(n):
            for mid, key, keys, entry in acts:
                aid = mujoco.mj_name2id(mj, mujoco.mjtObj.mjOBJ_ACTUATOR, "drive_%d_%s" % (mid, key))
                target = joint_eq.to_internal(key, track_at(keys, float(data.time)))
                data.ctrl[aid] = entry["sign"] * (target - entry["q0"]) * entry["scale"]
            mujoco.mj_step(mj, data)
            steps += 1
            if data.ncon and watch():
                break
            if data.time >= next_rec - 1e-12:
                record()
                next_rec += rec_dt
            if not np.all(np.isfinite(data.qpos)):
                raise J.MotionError("The simulation became unstable (non-finite positions). Lower the time step or the servo frequency.")
        if len(frames) > ctx["caps"]["dyn_frames"]:
            raise J.MotionError("The run recorded more frames than allowed.")
        job.report(fraction=steps / total, t=float(data.time), steps=steps)
    if stopped is not None and (not frames or frames[-1]["t"] < stopped["time"] - 1e-12):
        record()
    plots = []
    for (mid, key), v in plots_keys:
        name = ctx["names"][mid]
        plots.append({"joint": name, "coord": key, "kind": joint_eq.kind_of(key), "unit": "deg" if key in joint_eq.ANGLES else "length", "t": [f["t"] for f in frames], "v": [f["q"][name][key] for f in frames]})
    for (mid, key), v in ball_keys:
        name = ctx["names"][mid]
        for axis in ("rx", "ry", "rz"):
            plots.append({"joint": name, "coord": axis, "kind": "angle", "unit": "deg", "t": [f["t"] for f in frames], "v": [f["q"][name][axis] for f in frames]})
    elapsed = time.perf_counter() - t0
    msg = "Simulated %.3f s in %d steps (%.2f s of computing, %d frames)." % (float(data.time), steps, elapsed, len(frames))
    if stopped is not None:
        msg = "Stopped at %.4f s on contact between %s and %s. %s" % (stopped["time"], stopped["pair"][0], stopped["pair"][1], msg)
    return {"frames": len(frames), "planned": int(ctx["duration"] * ctx["fps"]) + 1, "duration": float(data.time), "steps": steps, "stopped": stopped, "plots": plots, "contacts": contacts, "peak_force": {"%s-%s" % k: v for k, v in peak.items()}, "solve_ms": elapsed * 1000.0, "checks": 0, "warnings": info["warnings"], "bodies": {c: {"mass": float(ctx["prox"][c]["mass"]), "source": ctx["prox"][c]["source"]} for c in ctx["prox"]}, "message": msg, "timestep": dt, "tree_joints": info["tree"], "closures": info["closures"]}
