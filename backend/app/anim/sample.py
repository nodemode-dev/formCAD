import math

import numpy as np

from app.anim import board as B
from app.assembly import xform
from app.mates import explode, ops
from app.mates import store as S

MAX_CHUNK = 240
MAX_CHUNK_AGENT = 60


def _mate_resolve(d, target):
    rec = S.get(d, target)
    if rec is None:
        raise B.BoardRefused("There is no mate %s to drive." % target)
    return rec["name"], float(rec["value"] if rec.get("value") is not None else 0.0)


def _mate_drive(doc, key, values):
    res = ops.drive(doc, key, values=values, commit=False, report=True)
    if not res["ok"]:
        raise B.BoardRefused(res["message"] or "The drive could not be solved.")
    return [smp["poses"] for smp in res["samples"]], res["ms"]


RESOLVERS = {"mate": _mate_resolve}
DRIVERS = {"mate": _mate_drive}


def register_driver(kind: str, resolve, drive) -> None:
    RESOLVERS[kind] = resolve
    DRIVERS[kind] = drive
    if kind not in B.DRIVER_KINDS:
        B.DRIVER_KINDS.append(kind)


def ease(kind: str, u: float) -> float:
    u = max(0.0, min(1.0, u))
    if kind == "linear":
        return u
    if kind == "ease_in":
        return u * u
    if kind == "ease_out":
        return 1.0 - (1.0 - u) * (1.0 - u)
    if kind == "hold":
        return 1.0 if u >= 1.0 else 0.0
    return u * u * (3.0 - 2.0 * u)


def mix_camera(a: dict, b: dict, k: float) -> dict:
    pa, ta = np.asarray(a["position"], float), np.asarray(a["target"], float)
    pb, tb = np.asarray(b["position"], float), np.asarray(b["target"], float)
    da, db = pa - ta, pb - tb
    la, lb = float(np.linalg.norm(da)), float(np.linalg.norm(db))
    ua, ub = da / la, db / lb
    dot = float(np.clip(ua @ ub, -1.0, 1.0))
    ang = math.acos(dot)
    if ang < 1e-6:
        u = ua
    elif abs(math.pi - ang) < 1e-6:
        side = np.cross(ua, [0.0, 0.0, 1.0])
        if np.linalg.norm(side) < 1e-6:
            side = np.cross(ua, [0.0, 1.0, 0.0])
        side = side / np.linalg.norm(side)
        u = ua * math.cos(math.pi * k) + side * math.sin(math.pi * k)
    else:
        u = (ua * math.sin((1 - k) * ang) + ub * math.sin(k * ang)) / math.sin(ang)
    tgt = ta + (tb - ta) * k
    dist = math.exp(math.log(la) + (math.log(lb) - math.log(la)) * k)
    height = math.exp(math.log(a["height"]) + (math.log(b["height"]) - math.log(a["height"])) * k)
    return {"position": (tgt + u * dist).tolist(), "target": tgt.tolist(), "up": [0.0, 0.0, 1.0], "projection": a["projection"], "fov": a["fov"], "height": height}


def orbit_camera(cam: dict, deg: float) -> dict:
    t = np.asarray(cam["target"], float)
    p = np.asarray(cam["position"], float) - t
    r = math.radians(deg)
    c, s = math.cos(r), math.sin(r)
    q = np.array([p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]])
    return {**cam, "position": (t + q).tolist()}


def camera_at(keys: list, carried, orbit, u: float, ez: float):
    path = [(k["at"], k["camera"]) for k in keys]
    if carried is not None and (not path or path[0][0] > 0.0):
        path.insert(0, (0.0, carried))
    if not path:
        return None
    if u <= path[0][0]:
        base = path[0][1]
    elif u >= path[-1][0]:
        base = path[-1][1]
    else:
        base = path[-1][1]
        for (t0, c0), (t1, c1) in zip(path, path[1:]):
            if t0 <= u <= t1:
                k = 0.0 if t1 <= t0 else (u - t0) / (t1 - t0)
                base = mix_camera(c0, c1, ease("ease", k) if len(path) > 2 else ez)
                break
    if orbit:
        start = path[0][1]
        base = orbit_camera(base if len(path) > 1 else start, orbit * ez)
    return base


def shot_state(d, board: dict) -> list:
    out = []
    carried_t = {}
    carried_drive = {}
    carried_cam = None
    for s in board["shots"]:
        item = {"shot": s}
        ex = s.get("explode")
        if ex:
            start = float(ex.get("from", carried_t.get(ex["view"], 0.0)))
            end = float(ex.get("to", start))
            item["explode"] = (ex["view"], start, end)
            carried_t = {ex["view"]: end}
        elif carried_t:
            view, held_t = next(iter(carried_t.items()))
            item["explode"] = (view, held_t, held_t)
        dr = s.get("drive")
        if dr:
            kind = dr.get("kind", "mate")
            key, committed = RESOLVERS[kind](d, dr["mate"])
            start = float(dr.get("from", carried_drive.get(key, committed)))
            item["drive"] = (key, start, float(dr["to"]))
            item["drive_kind"] = kind
            carried_drive[key] = float(dr["to"])
        cam = s.get("camera")
        item["cam_in"] = carried_cam
        if cam:
            ks = cam.get("keys") or []
            if ks:
                carried_cam = ks[-1]["camera"]
            if cam.get("orbit") and carried_cam is not None:
                carried_cam = orbit_camera(carried_cam, float(cam["orbit"]))
        item["carry_drive"] = dict(carried_drive)
        item["cam_keys"] = (cam or {}).get("keys") or []
        item["cam_orbit"] = (cam or {}).get("orbit")
        out.append(item)
    return out


def params(d, board: dict, first: int, count: int) -> list:
    plan = B.plan_of(board)
    states = shot_state(d, board)
    rows = []
    cur_drive = next((st["drive"][1] for st in states if "drive" in st), None)
    for sp, st in zip(plan["spans"], states):
        s = st["shot"]
        n = sp["frames"]
        for j in range(n):
            gi = sp["first"] + j
            if gi < first or gi >= first + count:
                continue
            loop = bool(s.get("loop"))
            u = j / n if loop else (j + 1) / n
            if gi == 0:
                u = 0.0
            e = ease(s["ease"], u)
            row = {"i": gi, "shot": s["id"], "u": u, "style": s.get("style")}
            if "explode" in st:
                view, a, b = st["explode"]
                row["explode"] = {"view": view, "t": a + (b - a) * e}
            if "drive" in st:
                key, a, b = st["drive"]
                row["drive"] = {"mate": key, "value": a + (b - a) * e}
                row["_drive"] = row["drive"]["value"]
            else:
                row["_drive"] = cur_drive
            cam = camera_at(st["cam_keys"], st["cam_in"], st["cam_orbit"], u, e)
            row["camera"] = cam
            rows.append(row)
        if "drive" in st:
            cur_drive = st["drive"][2]
    return rows


def run(doc, name: str, first: int, count: int) -> dict:
    d = doc.drawing
    board = B.get(d, name)
    lim = B.limits()
    cap = MAX_CHUNK_AGENT if lim is B.AGENT_LIMITS else MAX_CHUNK
    plan = B.plan_of(board)
    first = max(0, int(first))
    count = max(0, min(int(count), cap, plan["frames"] - first))
    rows = params(d, board, first, count)
    held = {(st["drive_kind"], st["drive"][0]) for st in shot_state(d, board) if "drive" in st}
    if len(held) > 1:
        raise B.BoardRefused("A storyboard drives one mate or joint; this one drives %d." % len(held))
    driven = {}
    if held:
        kind, mate = next(iter(held))
        vals = [r["_drive"] for r in rows]
        if vals:
            uniq = []
            for x in vals:
                if not uniq or abs(uniq[-1] - x) > 1e-12:
                    uniq.append(x)
            poses, ms = DRIVERS[kind](doc, mate, uniq)
            at = {}
            for x, pose in zip(uniq, poses):
                at[round(x, 9)] = pose
            driven = {"mate": mate, "poses": at, "ms": ms}
    frames = []
    cache = {}
    for row in rows:
        mats = {}
        offsets = {}
        if "explode" in row:
            ck = (row["explode"]["view"], round(row["explode"]["t"], 9))
            if ck not in cache:
                cache[ck] = explode.pose(d, row["explode"]["view"], row["explode"]["t"])
            pose = cache[ck]
            offsets = pose["offsets"]
            mats = dict(pose["matrices"])
        if driven:
            base = driven["poses"].get(round(row["_drive"], 9))
            if base is not None:
                mats = {}
                for c, m in base.items():
                    off = offsets.get(c)
                    if off is None:
                        mats[c] = m
                    else:
                        a = xform.as_matrix(m).copy()
                        a[:3, 3] += np.asarray(off, float)
                        mats[c] = xform.to_list(a)
        out = {"i": row["i"], "shot": row["shot"], "u": row["u"], "camera": row["camera"], "style": row["style"], "matrices": mats}
        if "explode" in row:
            out["explode"] = row["explode"]
        if "drive" in row:
            out["drive"] = row["drive"]
        frames.append(out)
    return {"name": name, "first": first, "count": len(frames), "total": plan["frames"], "fps": board["fps"], "frames": frames, "drive_ms": driven.get("ms", 0.0) if driven else 0.0}
