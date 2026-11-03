import copy
import math

from app.assembly import store as A
from app.joints import contact
from app.joints import store as J
from app.joints.drive import Driver
from app.mates import joint_eq
from app.mates import ops as M
from app.mates import store as S

BISECT_MAX = 40
CHECK_TARGET = 60


def joint_name(d, ref) -> tuple:
    for r in S.records(d):
        if r["kind"] != "joint":
            continue
        if r["id"] == ref or r["name"].casefold() == str(ref).casefold() or str(r["id"]) == str(ref):
            return r["name"], r
    raise J.MotionError("There is no joint %s." % ref)


def clean_tracks(d, tracks, caps) -> list:
    if not isinstance(tracks, list) or len(tracks) > caps["tracks"]:
        raise J.MotionError("A study holds at most %d tracks." % caps["tracks"])
    out = []
    seen = set()
    for tr in tracks:
        if not isinstance(tr, dict):
            raise J.MotionError("A track is an object with joint, coord and keys.")
        name, rec = joint_name(d, tr.get("joint"))
        coord = str(tr.get("coord") or "")
        kind = rec["opt"]["type"]
        if coord not in joint_eq.COORDS[kind]:
            raise J.MotionError("%s (%s) has no coordinate %s; its coordinates are %s." % (name, kind, coord, ", ".join(joint_eq.COORDS[kind]) or "none"))
        if (name, coord) in seen:
            raise J.MotionError("%s %s has two tracks; keep one." % (name, coord))
        seen.add((name, coord))
        keys = tr.get("keys")
        if not isinstance(keys, list) or not keys or len(keys) > caps["keys"]:
            raise J.MotionError("A track needs between 1 and %d keys." % caps["keys"])
        cleaned = []
        for k in keys:
            if not isinstance(k, dict):
                raise J.MotionError("A key is an object with t, v and ease.")
            ease = str(k.get("ease") or "linear")
            if ease not in J.EASES:
                raise J.MotionError("The ease is %s." % ", ".join(J.EASES))
            cleaned.append({"t": J.number(k.get("t"), "A key time", 0.0, caps["duration"]), "v": J.number(k.get("v"), "A key value"), "ease": ease})
        cleaned.sort(key=lambda k: k["t"])
        for a, b in zip(cleaned, cleaned[1:]):
            if b["t"] - a["t"] < 1e-9:
                raise J.MotionError("Two keys of %s %s sit at the same time." % (name, coord))
        out.append({"joint": name, "coord": coord, "keys": cleaned})
    return out


def clean_contact(data, c, caps) -> dict:
    c = c or {}
    mode = str(c.get("mode") or "stop")
    if mode not in J.CONTACT_MODES:
        raise J.MotionError("The contact mode is %s." % ", ".join(J.CONTACT_MODES))
    sets = []
    for k in c.get("sets") or []:
        sets.append(J.contact(data, k)["id"])
    return {"sets": sets, "mode": mode, "stride": int(J.number(c.get("stride", 0), "The stride", 0, 10000))}


def new_study(d, name=None, duration=None, fps=None, caps=None) -> dict:
    data = J.load(d)
    caps = caps or J.limits(False)
    if len(data["studies"]) >= caps["studies"]:
        raise J.MotionError("A document keeps at most %d motion studies." % caps["studies"])
    sid = "S%d" % data["next_study"]
    data["next_study"] += 1
    rec = {
        "id": sid, "name": J.clean_name(name or "Study %d" % (data["next_study"] - 1)), "duration": J.number(duration if duration is not None else 4.0, "The duration", 0.01, caps["duration"]),
        "fps": int(J.number(fps if fps is not None else 30, "The frame rate", 1, caps["fps"])), "tracks": [], "contact": {"sets": [], "mode": "stop", "stride": 0}, "plots": [],
    }
    frame_check(rec, caps)
    data["studies"][sid] = rec
    J.save(d, data)
    return rec


def frame_check(rec: dict, caps: dict) -> None:
    n = int(rec["duration"] * rec["fps"] + 0.5) + 1
    if n > caps["frames"]:
        raise J.MotionError("This study would make %d frames; the limit is %d. Lower the frame rate or the duration." % (n, caps["frames"]))


def edit_study(d, sid, fields: dict, caps=None) -> dict:
    data = J.load(d)
    caps = caps or J.limits(False)
    rec = J.study(data, sid)
    if "name" in fields and fields["name"] is not None:
        rec["name"] = J.clean_name(fields["name"])
    if "duration" in fields and fields["duration"] is not None:
        rec["duration"] = J.number(fields["duration"], "The duration", 0.01, caps["duration"])
    if "fps" in fields and fields["fps"] is not None:
        rec["fps"] = int(J.number(fields["fps"], "The frame rate", 1, caps["fps"]))
    if "tracks" in fields and fields["tracks"] is not None:
        rec["tracks"] = clean_tracks(d, fields["tracks"], caps)
    if "contact" in fields and fields["contact"] is not None:
        merged = dict(rec["contact"])
        merged.update(fields["contact"])
        rec["contact"] = clean_contact(data, merged, caps)
    if "plots" in fields and fields["plots"] is not None:
        plots = []
        for p in fields["plots"]:
            name, jr = joint_name(d, p.get("joint"))
            if str(p.get("coord")) not in joint_eq.COORDS[jr["opt"]["type"]]:
                raise J.MotionError("%s has no coordinate %s." % (name, p.get("coord")))
            plots.append({"joint": name, "coord": str(p["coord"])})
        rec["plots"] = plots
    frame_check(rec, caps)
    J.save(d, data)
    return rec


def delete_study(d, sid) -> dict:
    data = J.load(d)
    rec = J.study(data, sid)
    data["studies"].pop(rec["id"])
    J.save(d, data)
    return {"deleted": rec["id"]}


def ease(kind: str, s: float) -> float:
    if kind == "smooth":
        return s * s * (3.0 - 2.0 * s)
    if kind == "hold":
        return 0.0
    return s


def track_value(keys: list, t: float) -> float:
    if t <= keys[0]["t"]:
        return keys[0]["v"]
    if t >= keys[-1]["t"]:
        return keys[-1]["v"]
    for a, b in zip(keys, keys[1:]):
        if a["t"] <= t <= b["t"]:
            s = (t - a["t"]) / (b["t"] - a["t"])
            return a["v"] + (b["v"] - a["v"]) * ease(a["ease"], s)
    return keys[-1]["v"]


def listing(d) -> dict:
    data = J.load(d)
    return {"studies": list(data["studies"].values()), "contacts": [contact.view(c) for c in data["contacts"].values()], "dynamics": data["dynamics"]}


def prepare(doc, sid, restricted: bool, contact_mode=None, frames=None):
    d = doc.drawing
    data = J.load(d)
    caps = J.limits(restricted)
    st = copy.deepcopy(J.study(data, sid))
    if not st["tracks"]:
        raise J.MotionError("The study %s has no tracks. Add keys to a joint first." % st["name"])
    model = M.Model(d)
    drv = Driver(model)
    tracks = []
    by_name = {model.recs[m.id]["name"]: m for m in model.mates if m.kind == "joint"}
    for tr in st["tracks"]:
        m = by_name.get(tr["joint"])
        if m is None or m.id not in drv.joints:
            raise J.MotionError("%s is missing or suppressed." % tr["joint"])
        tracks.append((m.id, tr["coord"], tr["keys"]))
    n = int(st["duration"] * st["fps"] + 0.5)
    if frames:
        n = min(n, max(1, int(frames) - 1))
    if n + 1 > caps["frames"]:
        raise J.MotionError("This study would make %d frames; the limit is %d%s." % (n + 1, caps["frames"], " for a macro or agent" if restricted else ""))
    mode = contact_mode or st["contact"]["mode"]
    prober = None
    touch = contact.default_touch(d)
    if mode != "off" and st["contact"]["sets"]:
        fixed = {b.id for b in model.net.bodies.values() if b.fixed}
        pairs, touch = contact.component_pairs(d, st["contact"]["sets"], fixed)
        if len(pairs) > caps["pairs"]:
            raise J.MotionError("The contact sets name %d component pairs; the limit is %d%s." % (len(pairs), caps["pairs"], " for a macro or agent" if restricted else ""))
        if pairs:
            prober = contact.Prober(doc, pairs, touch)
    free_ids = [c for c, b in model.net.bodies.items() if not b.fixed]
    names = {m.id: model.recs[m.id]["name"] for m in model.mates if m.kind == "joint"}
    ctx = {"model": model, "drv": drv, "tracks": tracks, "n": n, "dur": float(st["duration"]), "prober": prober, "mode": mode, "touch": touch, "free": free_ids, "names": names, "study": st, "caps": caps, "mmu": model.mmu}
    return lambda job: execute(job, ctx)


def execute(job, ctx) -> dict:
    model, drv, tracks, n, dur = ctx["model"], ctx["drv"], ctx["tracks"], ctx["n"], ctx["dur"]
    prober, mode, names, free = ctx["prober"], ctx["mode"], ctx["names"], ctx["free"]
    st = ctx["study"]
    wanted = {(p["joint"], p["coord"]) for p in st.get("plots") or []}
    stride = int(st["contact"].get("stride") or 0) or max(1, n // CHECK_TARGET)
    stride = max(stride, int(math.ceil(n / max(1, ctx["caps"]["checks"]))))
    frames, states = job.frames, job.states
    log = []
    solve_ms = 0.0
    logged = set()

    def targets_at(t):
        out = {}
        for mid, key, keys in tracks:
            v, _ = drv.clamp(mid, key, joint_eq.to_internal(key, track_value(keys, t)))
            out[(mid, key)] = v
        return out

    def snap_states():
        return {m.id: copy.deepcopy(m.opt.get("state") or {}) for m in model.net.mates if m.kind in joint_eq.KINDS}

    def record(t):
        q = {}
        for mid in drv.joints:
            spec = drv.joints[mid].opt["spec"]
            q[names[mid]] = {k: joint_eq.to_user(k, drv.measured(mid, k)) for k in joint_eq.COORDS[spec["type"]]}
        frames.append({"t": t, "q": q, "poses": M.poses_of(model, free)})
        states.append(snap_states())

    def poses_now():
        return {c: model.net.bodies[c].matrix() for c in free}

    stopped = None
    last_clear = None
    message = ""
    for i in range(n + 1):
        job.check()
        t = dur * i / n
        res = drv.goto(targets_at(t))
        solve_ms += res["ms"]
        if not res["ok"]:
            stopped = {"time": frames[-1]["t"] if frames else 0.0, "reason": "solve", "message": "The mechanism cannot reach the keyed values at %.3f s; it stops there." % t, "pair": None, "gap": None, "joints": frames[-1]["q"] if frames else {}}
            message = stopped["message"]
            break
        record(t)
        if prober is not None and (i % stride == 0 or i == n):
            c = prober.check(poses_now())
            if c["state"] == "clear":
                last_clear = (t, drv.snapshot(), c)
            else:
                key = (c["pair"], c["state"])
                if mode == "report":
                    if key not in logged:
                        logged.add(key)
                        log.append({"t": t, "pair": list(c["pair"]), "gap": c["gap"], "state": c["state"]})
                else:
                    found = refine(job, ctx, drv, c, t, last_clear, targets_at, poses_now)
                    solve_ms += found["ms"]
                    drv.restore(found["snap"])
                    stop_t = found["t"]
                    while frames and frames[-1]["t"] > stop_t + 1e-12:
                        frames.pop()
                        states.pop()
                    if not frames or frames[-1]["t"] < stop_t - 1e-12:
                        record(stop_t)
                    stopped = {"time": stop_t, "reason": "contact", "pair": list(found["c"]["pair"]), "gap": found["c"]["gap"], "gap_mm": None if found["c"]["gap"] is None else found["c"]["gap"] * ctx["mmu"], "joints": frames[-1]["q"], "state": found["c"]["state"], "bisections": found["steps"]}
                    log.append({"t": stop_t, "pair": list(found["c"]["pair"]), "gap": found["c"]["gap"], "state": found["c"]["state"]})
                    message = "Stopped at %.4f s on contact between %s and %s, gap %.5f mm." % (stop_t, stopped["pair"][0], stopped["pair"][1], stopped["gap_mm"] if stopped["gap_mm"] is not None else 0.0)
                    break
        job.report(fraction=(i + 1) / (n + 1), t=t)
    drv.clear()
    plots = []
    for mid in drv.joints:
        spec = drv.joints[mid].opt["spec"]
        for key in joint_eq.COORDS[spec["type"]]:
            if wanted and (names[mid], key) not in wanted:
                continue
            plots.append({"joint": names[mid], "coord": key, "kind": joint_eq.kind_of(key), "unit": "deg" if key in joint_eq.ANGLES else "length", "t": [f["t"] for f in frames], "v": [f["q"][names[mid]][key] for f in frames]})
    if not message:
        message = "Solved %d frames in %.2f s." % (len(frames), solve_ms / 1000.0)
    return {"frames": len(frames), "planned": n + 1, "duration": dur, "stopped": stopped, "plots": plots, "contacts": log, "solve_ms": solve_ms, "checks": 0 if prober is None else prober.calls, "check_ms": 0.0 if prober is None else prober.ms, "touch": ctx["touch"], "message": message}


def refine(job, ctx, drv, hit, hit_t, last_clear, targets_at, poses_now) -> dict:
    prober = ctx["prober"]
    ms = 0.0
    if last_clear is None:
        return {"t": hit_t, "snap": drv.snapshot(), "c": hit, "steps": 0, "ms": 0.0}
    lo_t, lo_snap, lo_c = last_clear
    hi_t = hit_t
    steps = 0
    for _ in range(BISECT_MAX):
        job.check()
        if hi_t - lo_t < 1e-9:
            break
        mid = 0.5 * (lo_t + hi_t)
        steps += 1
        drv.restore(lo_snap)
        res = drv.goto(targets_at(mid))
        ms += res["ms"]
        if not res["ok"]:
            hi_t = mid
            continue
        c = prober.check(poses_now())
        if c["state"] == "clear":
            lo_t, lo_snap, lo_c = mid, drv.snapshot(), c
        elif c["state"] == "contact":
            return {"t": mid, "snap": drv.snapshot(), "c": c, "steps": steps, "ms": ms}
        else:
            hi_t = mid
    return {"t": lo_t, "snap": lo_snap, "c": lo_c, "steps": steps, "ms": ms}


def frames_view(job, start=0, count=200) -> dict:
    start = max(0, int(start))
    count = max(1, min(int(count), 2000))
    return {"frames": job.frames[start:start + count], "total": len(job.frames), "from": start}


def apply(doc, job, t: float) -> dict:
    d = doc.drawing
    if not job.frames:
        raise J.MotionError("This run has no frames.")
    idx = min(range(len(job.frames)), key=lambda i: abs(job.frames[i]["t"] - float(t)))
    frame = job.frames[idx]
    states = job.states[idx] if idx < len(job.states) else None
    moved = []
    for cid, pose in frame["poses"].items():
        rec = A.get(d, cid)
        if rec is None:
            continue
        rec = copy.deepcopy(rec)
        rec["transform"] = list(pose)
        A.put(d, rec)
        moved.append(cid)
    model = M.Model(d)
    for m in model.net.mates:
        if m.kind in joint_eq.KINDS:
            if states is not None and m.id in states:
                m.opt["state"] = copy.deepcopy(states[m.id])
            else:
                m.opt["state"] = {}
    rep = model.net.solve(retries=0)
    for m in model.net.mates:
        if m.kind in joint_eq.KINDS and not m.suppressed:
            model.save_mate(m)
    model.write(model.changed())
    from app.joints import ops as JO

    return {"t": frame["t"], "frame": idx, "moved": moved, "poses": M.poses_of(model, moved), "status": JO.status_view(model), "solved": rep.ok}
