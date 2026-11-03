import copy
import math

import numpy as np

from app.mates import rig

KINDS = ("joint", "jointlink")
TYPES = ("rigid", "revolute", "slider", "cylindrical", "pinslot", "planar", "ball")
COORDS = {
    "rigid": [], "revolute": ["rz"], "slider": ["tz"], "cylindrical": ["rz", "tz"], "pinslot": ["rz", "tx"],
    "planar": ["tx", "ty", "rz"], "ball": ["rx", "ry", "rz"],
}
ROWS = {
    "rigid": [0, 1, 2, 3, 4, 5], "revolute": [0, 1, 2, 3, 4], "slider": [0, 1, 3, 4, 5], "cylindrical": [0, 1, 3, 4],
    "pinslot": [1, 2, 3, 4], "planar": [2, 3, 4], "ball": [0, 1, 2],
}
ANGLES = ("rx", "ry", "rz")
ALIASES = {"fixed": "rigid", "hinge": "revolute", "pin": "revolute", "prismatic": "slider", "pin-slot": "pinslot", "pin_slot": "pinslot", "ballsocket": "ball", "spherical": "ball"}
NAMES = {"rx": "x rotation", "ry": "y rotation", "rz": "rotation", "tx": "x travel", "ty": "y travel", "tz": "travel"}


class JointError(ValueError):
    pass


def type_of(word) -> str:
    key = str(word or "").strip().lower().replace(" ", "")
    key = ALIASES.get(key, key)
    if key not in TYPES:
        raise JointError("%s is not a joint type; use %s." % (word, ", ".join(TYPES)))
    return key


def kind_of(key: str) -> str:
    return "angle" if key in ANGLES else "length"


def to_user(key: str, v: float) -> float:
    return math.degrees(v) if key in ANGLES else v


def to_internal(key: str, v: float) -> float:
    return math.radians(v) if key in ANGLES else v


def default_x(z) -> np.ndarray:
    z = rig.unit(z)
    a = np.array([1.0, 0.0, 0.0]) if abs(float(z[0])) < 0.9 else np.array([0.0, 1.0, 0.0])
    return rig.unit(a - float(a @ z) * z)


def frame_matrix(f: dict) -> tuple:
    z = rig.unit(f["z"])
    x = np.asarray(f.get("x") if f.get("x") is not None else default_x(z), dtype=float)
    x = x - float(x @ z) * z
    if float(np.linalg.norm(x)) < 1e-9:
        x = default_x(z)
    x = rig.unit(x)
    y = np.cross(z, x)
    return np.column_stack([x, y, z]), np.asarray(f["o"], dtype=float)


def compose(kind: str, q: dict) -> tuple:
    t = np.zeros(3)
    r = np.eye(3)
    if kind == "ball":
        r = rig.expm([q.get("rx", 0.0), q.get("ry", 0.0), q.get("rz", 0.0)])
        return r, t
    for i, k in enumerate(("tx", "ty", "tz")):
        if k in COORDS[kind]:
            t[i] = q.get(k, 0.0)
    if "rz" in COORDS[kind]:
        r = rig.expm([0.0, 0.0, q.get("rz", 0.0)])
    return r, t


def runtime_spec(opt: dict) -> dict:
    kind = opt["type"]
    spec = {"type": kind, "fa": frame_matrix(opt["fa"]), "fb": frame_matrix(opt["fb"])}
    spec["rel0"] = (np.asarray(opt["rel0"]["r"], dtype=float).reshape(3, 3), np.asarray(opt["rel0"]["t"], dtype=float).reshape(3))
    lim = {}
    cone = None
    for key, v in (opt.get("limits") or {}).items():
        if key == "cone":
            if v and v.get("max") is not None:
                cone = math.radians(float(v["max"]))
            continue
        if key not in COORDS[kind]:
            continue
        lo, hi = v.get("min"), v.get("max")
        if lo is None and hi is None:
            continue
        lim[key] = (None if lo is None else to_internal(key, float(lo)), None if hi is None else to_internal(key, float(hi)))
    spec["lim"] = lim
    spec["cone"] = cone if kind == "ball" else None
    return spec


def relative(spec: dict, wa: dict, wb: dict) -> tuple:
    fa, oa = spec["fa"]
    fb, ob = spec["fb"]
    ra = wa["R"] @ fa
    ta = wa["R"] @ oa + wa["t"]
    rb = wb["R"] @ fb
    tb = wb["R"] @ ob + wb["t"]
    r = ra.T @ rb
    t = ra.T @ (tb - ta)
    r0, t0 = spec["rel0"]
    return r0.T @ (t - t0), r0.T @ r


TILT = ("revolute", "cylindrical", "pinslot", "planar")


def rot_parts(kind: str, dr: np.ndarray) -> tuple:
    if kind in TILT:
        return (float(dr[0, 2]), float(dr[1, 2]), math.atan2(float(dr[1, 0]), float(dr[0, 0])))
    w = rig.logm(dr)
    return (float(w[0]), float(w[1]), float(w[2]))


def unwrap(v: float, prev) -> float:
    if prev is None:
        return v
    return v + 2.0 * math.pi * round((float(prev) - v) / (2.0 * math.pi))


def coord_map(kind: str, dt, dr, prev=None) -> dict:
    prev = prev or {}
    a, b, c = rot_parts(kind, dr)
    out = {"tx": float(dt[0]), "ty": float(dt[1]), "tz": float(dt[2]), "rx": 0.0 if kind in TILT else a, "ry": 0.0 if kind in TILT else b, "rz": c}
    out["rz"] = unwrap(out["rz"], prev.get("rz"))
    return out


def values_of(spec: dict, wa: dict, wb: dict, prev=None) -> dict:
    dt, dr = relative(spec, wa, wb)
    return coord_map(spec["type"], dt, dr, prev)


def res_joint(m, W) -> np.ndarray:
    spec = m.opt["spec"]
    kind = spec["type"]
    dt, dr = relative(spec, W[0], W[1])
    a, b, c = rot_parts(kind, dr)
    full = (float(dt[0]), float(dt[1]), float(dt[2]), a, b, c)
    rows = [full[i] for i in ROWS[kind]]
    prev = (m.opt.get("state") or {}).get("q")
    vals = coord_map(kind, dt, dr, prev)
    for key in COORDS[kind]:
        if key in spec["lim"]:
            lo, hi = spec["lim"][key]
            q = vals[key]
            c = q
            if lo is not None:
                c = max(c, lo)
            if hi is not None:
                c = min(c, hi)
            rows.append(q - c)
    if spec["cone"] is not None:
        rows.append(max(0.0, float(np.linalg.norm(rig.logm(dr))) - spec["cone"]))
    for key, target in (m.opt.get("drive") or {}).items():
        rows.append(vals[key] - float(target))
    return np.array(rows, dtype=float)


def res_link(m, W) -> np.ndarray:
    o = m.opt
    st = o.get("state") or {}
    v1 = values_of(o["spec1"], W[0], W[1], {"rz": st.get("q1")})[o["c1"]]
    v2 = values_of(o["spec2"], W[2], W[3], {"rz": st.get("q2")})[o["c2"]]
    return np.array([(v2 - o["q20"]) - o["k"] * (v1 - o["q10"])])


def update_state(m, W) -> None:
    st = m.opt.setdefault("state", {})
    if m.kind == "joint":
        spec = m.opt["spec"]
        vals = values_of(spec, W[0], W[1], st.get("q"))
        st["q"] = {k: vals[k] for k in COORDS[spec["type"]]}
    elif m.kind == "jointlink":
        o = m.opt
        st["q1"] = values_of(o["spec1"], W[0], W[1], {"rz": st.get("q1")})[o["c1"]]
        st["q2"] = values_of(o["spec2"], W[2], W[3], {"rz": st.get("q2")})[o["c2"]]


def runtime(rec: dict) -> dict:
    opt = copy.deepcopy(rec.get("opt") or {})
    out = {"state": copy.deepcopy(opt.get("state") or {})}
    if rec["kind"] == "joint":
        out["spec"] = runtime_spec(opt)
    else:
        out["spec1"] = runtime_spec(opt["j1"])
        out["spec2"] = runtime_spec(opt["j2"])
        out["c1"], out["c2"] = opt["c1"], opt["c2"]
        out["q10"], out["q20"] = float(opt["q10"]), float(opt["q20"])
        out["k"] = float(opt["k"])
    return out


def persist(m, rec: dict) -> dict:
    out = copy.deepcopy(rec.get("opt") or {})
    st = copy.deepcopy(m.opt.get("state") or {})
    out["state"] = plain(st)
    return out


def plain(v):
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    if isinstance(v, np.ndarray):
        return [float(x) for x in v.reshape(-1)]
    if isinstance(v, np.floating):
        return float(v)
    return v
