import math

import numpy as np

from app.mates import joint_eq, rig

PL, AX, PT, CV = "plane", "axis", "point", "curve"
KINDS = ("coincident", "concentric", "distance", "angle", "parallel", "perpendicular", "tangent", "lock", "gear", "rackpinion", "screw", "limitdistance", "limitangle", "symmetric", "width", "path", "slot", "cam", "joint", "jointlink")
CURVE_KINDS = ("path", "cam")
MAX_CURVE_POINTS = 4096
MECHANICAL = ("gear", "rackpinion", "screw")
VALUED = ("distance", "angle", "limitdistance", "limitangle")
ALIGNS = ("any", "aligned", "anti", "auto")
NEAR = 1e-9


class MateError(ValueError):
    pass


class Side:
    __slots__ = ("comp", "k", "p", "d", "r", "pts", "closed")

    def __init__(self, comp, k, p, d=None, r=None, pts=None, closed=False):
        if k not in (PL, AX, PT, CV):
            raise MateError("A mate reference must be a plane, an axis, a point or a curve.")
        self.comp = comp
        self.k = k
        self.r = None if r is None else float(r)
        self.pts = None
        self.closed = bool(closed)
        if k == CV:
            pts = np.asarray(pts if pts is not None else [], dtype=float)
            if pts.ndim != 2 or pts.shape[1] != 3 or not 2 <= pts.shape[0] <= MAX_CURVE_POINTS:
                raise MateError("A curve reference needs 2 to %d points of x, y and z." % MAX_CURVE_POINTS)
            self.pts = pts
            self.p = pts[0].copy()
            self.d = _plane_normal(pts)
            return
        self.p = np.asarray(p, dtype=float).reshape(3)
        self.d = rig.unit(d) if (d is not None and k != PT) else (np.array([0.0, 0.0, 1.0]) if k != PT else np.zeros(3))

    def to_dict(self) -> dict:
        out = {"comp": self.comp, "kind": self.k, "p": [float(v) for v in self.p]}
        if self.k == CV:
            out["pts"] = [[float(v) for v in q] for q in self.pts]
            out["closed"] = self.closed
        elif self.k != PT:
            out["d"] = [float(v) for v in self.d]
        if self.r is not None:
            out["r"] = self.r
        return out

    @staticmethod
    def from_dict(rec: dict) -> "Side":
        return Side(rec.get("comp"), rec["kind"], rec["p"], rec.get("d"), rec.get("r"), rec.get("pts"), rec.get("closed", False))


def _plane_normal(pts) -> np.ndarray:
    c = pts.mean(axis=0)
    _, s, vt = np.linalg.svd(pts - c)
    span = float(np.max(np.linalg.norm(pts - c, axis=1)))
    if pts.shape[0] < 3 or span < 1e-12 or s.size < 2 or s[1] < 1e-9 * max(span, 1.0):
        return np.zeros(3)
    if s.size > 2 and s[2] > 1e-6 * max(span, 1.0):
        return np.zeros(3)
    return rig.unit(vt[2])


class Mate:
    def __init__(self, mid, kind, sides, value=None, opt=None, name="", suppressed=False):
        if kind not in KINDS:
            raise MateError("Unknown mate kind %s." % kind)
        self.id = mid
        self.kind = kind
        self.sides = sides
        self.value = value
        self.opt = dict(opt or {})
        self.name = name or "%s%d" % (kind, mid)
        self.suppressed = suppressed

    def comps(self) -> list:
        return [s.comp for s in self.sides if s.comp is not None]


def world(side: Side, pose) -> dict:
    r, t = pose
    out = {"k": side.k, "p": r @ side.p + t, "d": r @ side.d, "r": side.r, "R": r, "t": t}
    if side.pts is not None:
        out["pts"] = side.pts @ r.T + t
        out["closed"] = side.closed
    return out


def _vec(e):
    return e["d"]


def _cross_rows(a, b, sign):
    if sign == "any":
        return np.cross(a, b)
    s = 1.0 if sign == "anti" else -1.0
    return a + s * b


def _pair(m, W):
    a, b = W[0], W[1]
    ka, kb = a["k"], b["k"]
    return a, b, ka, kb


def _order(a, b):
    rank = {PL: 0, AX: 1, PT: 2}
    return rank[a["k"]] <= rank[b["k"]]


def _line_dist_vec(p, ax):
    return np.cross(p - ax["p"], ax["d"])


def _plane_off(pl, p):
    return float((p - pl["p"]) @ pl["d"])


def _need_r(e, what):
    if e["r"] is None:
        raise MateError("%s needs a cylinder, cone, circle or sphere with a radius." % what)
    return e["r"]


def _angle_between(a, b, about=None):
    if about is not None:
        return rig.signed_angle(a, b, about)
    return math.atan2(float(np.linalg.norm(np.cross(a, b))), float(a @ b))


def res_coincident(m, W):
    a, b = W[0], W[1]
    sw = not _order(a, b)
    if sw:
        a, b = b, a
    ka, kb = a["k"], b["k"]
    al = m.opt.get("align", "any")
    if ka == PL and kb == PL:
        return np.concatenate([_cross_rows(a["d"], b["d"], al if al != "auto" else "anti"), [float((b["p"] - a["p"]) @ a["d"])]])
    if ka == PL and kb == AX:
        return np.array([float(a["d"] @ b["d"]), _plane_off(a, b["p"])])
    if ka == PL and kb == PT:
        return np.array([_plane_off(a, b["p"])])
    if ka == AX and kb == AX:
        return np.concatenate([_cross_rows(a["d"], b["d"], al if al != "auto" else "any"), np.cross(b["p"] - a["p"], a["d"])])
    if ka == AX and kb == PT:
        return _line_dist_vec(b["p"], a)
    if ka == PT and kb == PT:
        return b["p"] - a["p"]
    raise MateError("These references cannot be made coincident.")


def res_concentric(m, W):
    a, b = W[0], W[1]
    if a["k"] == PL or b["k"] == PL:
        raise MateError("Concentric needs axes or centre points.")
    return res_coincident(m, W)


def _side(m, a, b):
    return float(m.opt.get("side", 1.0))


def res_distance(m, W):
    a, b = W[0], W[1]
    v = float(m.value)
    if not _order(a, b):
        a, b = b, a
    ka, kb = a["k"], b["k"]
    sd = _side(m, a, b)
    al = m.opt.get("align", "anti")
    if ka == PL and kb == PL:
        return np.concatenate([_cross_rows(a["d"], b["d"], al if al != "auto" else "anti"), [sd * float((b["p"] - a["p"]) @ a["d"]) - v]])
    if ka == PL and kb == AX:
        return np.array([float(a["d"] @ b["d"]), sd * _plane_off(a, b["p"]) - v])
    if ka == PL and kb == PT:
        return np.array([sd * _plane_off(a, b["p"]) - v])
    if ka == AX and kb == AX:
        return np.concatenate([np.cross(a["d"], b["d"]), [float(np.linalg.norm(np.cross(b["p"] - a["p"], a["d"]))) - v]])
    if ka == AX and kb == PT:
        return np.array([float(np.linalg.norm(_line_dist_vec(b["p"], a))) - v])
    if ka == PT and kb == PT:
        return np.array([float(np.linalg.norm(b["p"] - a["p"])) - v])
    raise MateError("These references have no distance mate.")


def _angle_vectors(m, W):
    a, b = W[0], W[1]
    if a["k"] == PT or b["k"] == PT:
        raise MateError("An angle needs planes or axes.")
    va, vb = a["d"], b["d"]
    if m.opt.get("flip"):
        vb = -vb
    return va, vb


def res_angle(m, W):
    va, vb = _angle_vectors(m, W)
    v = float(m.value)
    about = W[2]["d"] if len(W) > 2 else None
    if about is not None:
        pa = va - (va @ about) * about
        pb = vb - (vb @ about) * about
        na, nb = float(np.linalg.norm(pa)), float(np.linalg.norm(pb))
        if na < 1e-9 or nb < 1e-9:
            raise MateError("The references lie along the rotation axis, so the angle is undefined.")
        pa, pb = pa / na, pb / nb
        s = float(about @ np.cross(pa, pb))
        c = float(pa @ pb)
        return np.array([math.atan2(s * math.cos(v) - c * math.sin(v), c * math.cos(v) + s * math.sin(v))])
    if v < 1e-9 or math.pi - v < 1e-9:
        return np.cross(va, vb) if v < 1e-9 else np.cross(va, vb)
    return np.array([float(va @ vb) - math.cos(v)])


def res_parallel(m, W):
    a, b = W[0], W[1]
    if a["k"] == PT or b["k"] == PT:
        raise MateError("Parallel needs planes or axes.")
    al = m.opt.get("align", "any")
    if (a["k"] == PL) == (b["k"] == PL):
        return _cross_rows(a["d"], b["d"], al if al != "auto" else "any")
    return np.array([float(a["d"] @ b["d"])])


def res_perpendicular(m, W):
    a, b = W[0], W[1]
    if a["k"] == PT or b["k"] == PT:
        raise MateError("Perpendicular needs planes or axes.")
    if (a["k"] == PL) != (b["k"] == PL):
        return np.cross(a["d"], b["d"])
    return np.array([float(a["d"] @ b["d"])])


def res_tangent(m, W):
    a, b = W[0], W[1]
    if not _order(a, b):
        a, b = b, a
    ka, kb = a["k"], b["k"]
    sd = _side(m, a, b)
    mode = m.opt.get("mode", "external")
    if ka == PL and kb == AX:
        r = _need_r(b, "Tangent")
        return np.array([float(a["d"] @ b["d"]), sd * _plane_off(a, b["p"]) - r])
    if ka == PL and kb == PT:
        r = _need_r(b, "Tangent")
        return np.array([sd * _plane_off(a, b["p"]) - r])
    if ka == AX and kb == AX:
        ra, rb = _need_r(a, "Tangent"), _need_r(b, "Tangent")
        want = ra + rb if mode == "external" else abs(ra - rb)
        return np.concatenate([np.cross(a["d"], b["d"]), [float(np.linalg.norm(np.cross(b["p"] - a["p"], a["d"]))) - want]])
    if ka == AX and kb == PT:
        ra, rb = _need_r(a, "Tangent"), _need_r(b, "Tangent")
        want = ra + rb if mode == "external" else abs(ra - rb)
        return np.array([float(np.linalg.norm(_line_dist_vec(b["p"], a))) - want])
    if ka == PT and kb == PT:
        ra, rb = _need_r(a, "Tangent"), _need_r(b, "Tangent")
        want = ra + rb if mode == "external" else abs(ra - rb)
        return np.array([float(np.linalg.norm(b["p"] - a["p"])) - want])
    raise MateError("Tangent works between planes, cylinders and spheres.")


def res_lock(m, W):
    ra, ta = W[0]["R"], W[0]["t"]
    rb, tb = W[1]["R"], W[1]["t"]
    rel_r = np.asarray(m.opt["rel_r"], dtype=float)
    rel_t = np.asarray(m.opt["rel_t"], dtype=float)
    return np.concatenate([ra.T @ (tb - ta) - rel_t, rig.logm(rel_r.T @ (ra.T @ rb))])


def _turn(m, key, wrapped):
    last = m.opt.get("state", {}).get(key)
    if last is None:
        return wrapped
    return wrapped + 2.0 * math.pi * round((last - wrapped) / (2.0 * math.pi))


def phi_of(m, which, e, R):
    u = R @ np.asarray(m.opt["u" + which], dtype=float)
    u0 = np.asarray(m.opt["u0" + which], dtype=float)
    return rig.signed_angle(u0, u, e["d"])


def res_gear(m, W):
    pa = phi_of(m, "a", W[0], W[0]["R"])
    pb = phi_of(m, "b", W[1], W[1]["R"])
    pa, pb = _turn(m, "a", pa), _turn(m, "b", pb)
    ratio = float(m.value)
    sg = 1.0 if m.opt.get("reverse", True) else -1.0
    return np.array([pb + sg * ratio * pa])


def res_rackpinion(m, W):
    pa = _turn(m, "a", phi_of(m, "a", W[0], W[0]["R"]))
    k = W[1]["d"]
    s = float(k @ (W[1]["p"] - W[0]["p"]))
    sg = 1.0 if m.opt.get("reverse", False) else -1.0
    return np.array([(s - float(m.opt["s0"])) + sg * float(m.value) * pa])


def res_screw(m, W):
    pa = phi_of(m, "a", W[0], W[0]["R"])
    pb = phi_of(m, "b", W[1], W[1]["R"])
    rel = _turn(m, "a", wrap_pair(pa, pb))
    k = W[0]["d"]
    s = float(k @ (W[1]["p"] - W[0]["p"]))
    hand = 1.0 if m.opt.get("right", True) else -1.0
    return np.array([(s - float(m.opt["s0"])) - hand * float(m.value) * rel / (2.0 * math.pi)])


def wrap_pair(pa, pb):
    return rig.wrap(pb - pa)


def res_limitdistance(m, W):
    a, b = W[0], W[1]
    if not _order(a, b):
        a, b = b, a
    sd = _side(m, a, b)
    if a["k"] == PL and b["k"] in (PT, AX):
        o = sd * _plane_off(a, b["p"])
    elif a["k"] == PL and b["k"] == PL:
        o = sd * float((b["p"] - a["p"]) @ a["d"])
    elif a["k"] == AX and b["k"] in (AX, PT):
        o = float(np.linalg.norm(_line_dist_vec(b["p"], a)))
    elif a["k"] == PT and b["k"] == PT:
        o = float(np.linalg.norm(b["p"] - a["p"]))
    else:
        raise MateError("These references have no distance limit.")
    lo, hi = float(m.opt["min"]), float(m.opt["max"])
    return np.array([o - min(max(o, lo), hi)])


def res_limitangle(m, W):
    va, vb = _angle_vectors(m, W)
    th = _angle_between(va, vb, W[2]["d"] if len(W) > 2 else None)
    lo, hi = float(m.opt["min"]), float(m.opt["max"])
    return np.array([th - min(max(th, lo), hi)])


def _mirror_p(x, pl):
    return x - 2.0 * float((x - pl["p"]) @ pl["d"]) * pl["d"]


def _mirror_d(v, pl):
    return v - 2.0 * float(v @ pl["d"]) * pl["d"]


def res_symmetric(m, W):
    a, b, s = W[0], W[1], W[2]
    if s["k"] != PL:
        raise MateError("Symmetric needs a symmetry plane as the third reference.")
    if a["k"] != b["k"] or a["k"] == CV:
        raise MateError("Symmetric needs two references of the same type: two points, two planes or two axes.")
    pa = _mirror_p(a["p"], s)
    if a["k"] == PT:
        return pa - b["p"]
    da = _mirror_d(a["d"], s)
    if a["k"] == PL:
        return np.concatenate([_cross_rows(da, b["d"], m.opt.get("align", "aligned")), [float((b["p"] - pa) @ b["d"])]])
    return np.concatenate([np.cross(da, b["d"]), np.cross(b["p"] - pa, da)])


def res_width(m, W):
    if len(W) != 4 or any(e["k"] != PL for e in W):
        raise MateError("Width needs four planes: two faces of the tab, then two faces of the groove.")
    t1, t2, g1, g2 = W
    ng = g1["d"]
    off = float((0.5 * (t1["p"] + t2["p"]) - 0.5 * (g1["p"] + g2["p"])) @ ng)
    return np.concatenate([np.cross(t1["d"], ng), [off]])


def _poly_closest(pts, closed, x):
    a = pts if closed else pts[:-1]
    b = np.roll(pts, -1, axis=0) if closed else pts[1:]
    ab = b - a
    l2 = np.maximum(np.einsum("ij,ij->i", ab, ab), 1e-300)
    t = np.clip(np.einsum("ij,ij->i", x - a, ab) / l2, 0.0, 1.0)
    c = a + t[:, None] * ab
    return c[int(np.argmin(np.einsum("ij,ij->i", c - x, c - x)))]


def _circle_closest(e, x):
    w = (x - e["p"]) - float((x - e["p"]) @ e["d"]) * e["d"]
    n = float(np.linalg.norm(w))
    u = w / n if n > 1e-12 else rig.perp(e["d"])
    return e["p"] + e["r"] * u


def _curve_closest(e, x):
    if e["k"] == CV:
        return _poly_closest(e["pts"], e["closed"], x)
    if e["r"] is not None:
        return _circle_closest(e, x)
    return e["p"] + float((x - e["p"]) @ e["d"]) * e["d"]


def res_path(m, W):
    a, b = W[0], W[1]
    if a["k"] != PT:
        raise MateError("Path needs a point on the first component.")
    if b["k"] not in (AX, CV):
        raise MateError("Path needs a curve, a straight edge or a circle on the second component.")
    return a["p"] - _curve_closest(b, a["p"])


def res_slot(m, W):
    f, s = W[0], W[1]
    if f["k"] not in (PT, AX) or s["k"] != AX:
        raise MateError("Slot needs a point or a pin axis on the first component and the slot centre line on the second.")
    ds = s["d"]
    dlt = f["p"] - s["p"]
    if f["k"] == PT:
        rows = np.cross(dlt, ds)
    else:
        n = s["R"] @ np.asarray(m.opt["n"], dtype=float)
        rows = np.concatenate([np.cross(f["d"], n), [float(dlt @ np.cross(ds, n))]])
    u = float(dlt @ ds)
    if m.opt.get("position", "free") in ("centre", "center"):
        return np.concatenate([rows, [u]])
    h = 0.5 * float(m.value)
    return np.concatenate([rows, [u - min(max(u, -h), h)]])


def res_cam(m, W):
    f, c = W[0], W[1]
    if f["k"] == AX and f["r"] is None:
        raise MateError("A cylinder follower needs a radius.")
    if f["k"] not in (PT, AX):
        raise MateError("Cam needs a point, sphere or cylinder follower on the first component.")
    if not ((c["k"] == AX and c["r"] is not None) or c["k"] == CV):
        raise MateError("Cam needs a profile curve or a circle on the second component.")
    n = c["d"]
    if float(n @ n) < 0.25:
        raise MateError("The cam profile is a straight line or is not flat, so it has no plane.")
    h = float((f["p"] - c["p"]) @ n)
    q = f["p"] - h * n
    head = np.cross(f["d"], n) if f["k"] == AX else np.array([h])
    v = q - _curve_closest(c, q)
    rf = f["r"] or 0.0
    if rf > 0.0:
        return np.concatenate([head, [float(np.linalg.norm(v)) - rf]])
    return np.concatenate([head, v])


RES = {
    "coincident": res_coincident, "concentric": res_concentric, "distance": res_distance, "angle": res_angle, "parallel": res_parallel,
    "perpendicular": res_perpendicular, "tangent": res_tangent, "lock": res_lock, "gear": res_gear, "rackpinion": res_rackpinion,
    "screw": res_screw, "limitdistance": res_limitdistance, "limitangle": res_limitangle,
    "symmetric": res_symmetric, "width": res_width, "path": res_path, "slot": res_slot, "cam": res_cam,
    "joint": joint_eq.res_joint, "jointlink": joint_eq.res_link,
}


def residual(m: Mate, W: list) -> np.ndarray:
    return np.asarray(RES[m.kind](m, W), dtype=float).reshape(-1)


def resolve(m: Mate, W: list) -> None:
    a, b = W[0], W[1]
    k = m.kind
    if k not in CURVE_KINDS and any(e["k"] == CV for e in W):
        raise MateError("Only path and cam mates take a curve reference.")
    if k in ("symmetric", "width", "path", "slot", "cam"):
        _resolve_shape(m, W)
    if k in ("coincident", "distance", "parallel", "concentric", "limitdistance"):
        if m.opt.get("align", "auto") == "auto":
            if k in ("parallel", "concentric"):
                m.opt["align"] = "any"
            elif a["k"] == PL and b["k"] == PL:
                m.opt["align"] = "aligned" if float(a["d"] @ b["d"]) > 0 else "anti"
            else:
                m.opt["align"] = "any"
        if k == "coincident" and a["k"] == PL and b["k"] == PL and m.opt["align"] == "any":
            m.opt["align"] = "any"
    if k in ("distance", "limitdistance", "tangent"):
        x, y = (a, b) if _order(a, b) else (b, a)
        if "side" not in m.opt:
            m.opt["side"] = 1.0
            if x["k"] == PL and not (y["k"] == PL and m.opt.get("align") == "anti"):
                m.opt["side"] = 1.0 if _plane_off(x, y["p"]) >= 0 else -1.0
            if m.opt.get("flip"):
                m.opt["side"] = -m.opt["side"]
    if k == "tangent" and "mode" not in m.opt:
        x, y = (a, b) if _order(a, b) else (b, a)
        if x["k"] != PL and x["r"] is not None and y["r"] is not None:
            if x["k"] == AX and y["k"] == AX:
                dist = float(np.linalg.norm(np.cross(y["p"] - x["p"], x["d"])))
            elif x["k"] == AX:
                dist = float(np.linalg.norm(_line_dist_vec(y["p"], x)))
            else:
                dist = float(np.linalg.norm(y["p"] - x["p"]))
            ext, inn = x["r"] + y["r"], abs(x["r"] - y["r"])
            m.opt["mode"] = "external" if abs(dist - ext) <= abs(dist - inn) else "internal"
        else:
            m.opt["mode"] = "external"
    if k == "lock":
        ra, ta = a["R"], a["t"]
        rb, tb = b["R"], b["t"]
        m.opt["rel_r"] = (ra.T @ rb).tolist()
        m.opt["rel_t"] = (ra.T @ (tb - ta)).tolist()
    if k in ("gear", "rackpinion", "screw"):
        for which, e in (("a", a), ("b", b)):
            if which == "b" and k == "rackpinion":
                continue
            Rw = e["R"]
            u_local = rig.perp(Rw.T @ e["d"])
            m.opt["u" + which] = u_local.tolist()
            m.opt["u0" + which] = (Rw @ u_local).tolist()
        m.opt["state"] = {}
        if k == "rackpinion":
            m.opt["s0"] = float(b["d"] @ (b["p"] - a["p"]))
        if k == "screw":
            m.opt["s0"] = float(a["d"] @ (b["p"] - a["p"]))
    if k in ("limitdistance", "limitangle"):
        if "min" not in m.opt or "max" not in m.opt:
            raise MateError("A limit mate needs a minimum and a maximum.")
        if float(m.opt["min"]) > float(m.opt["max"]):
            raise MateError("The minimum of a limit is above its maximum.")
    if k in ("gear", "rackpinion", "screw"):
        if m.value is None or abs(float(m.value)) < 1e-12:
            raise MateError("This mate needs a ratio or pitch other than zero.")
        if a["k"] == PL or b["k"] == PL or a["k"] == PT or b["k"] == PT:
            raise MateError("This mate needs axes on both components.")
    if k in VALUED and k not in ("limitdistance", "limitangle") and m.value is None:
        raise MateError("This mate needs a value.")


def _parallel(a, b) -> bool:
    return float(np.linalg.norm(np.cross(a["d"], b["d"]))) < 1e-6


def _resolve_shape(m: Mate, W: list) -> None:
    k = m.kind
    a, b = W[0], W[1]
    if k == "symmetric":
        if len(W) != 3:
            raise MateError("Symmetric needs three references: two entities and the symmetry plane.")
        res_symmetric(m, W)
        if a["k"] == PL and m.opt.get("align", "auto") == "auto":
            m.opt["align"] = "aligned" if float(_mirror_d(a["d"], W[2]) @ b["d"]) >= 0 else "anti"
    elif k == "width":
        res_width(m, W)
        t1, t2, g1, g2 = W
        if not _parallel(t1, t2):
            raise MateError("The two tab faces are not parallel, so they have no mid-plane.")
        if not _parallel(g1, g2):
            raise MateError("The two groove faces are not parallel, so they have no mid-plane.")
        if m.sides[0].comp != m.sides[1].comp or m.sides[2].comp != m.sides[3].comp:
            raise MateError("Both tab faces must be on one component and both groove faces on one component.")
        if m.sides[0].comp == m.sides[2].comp:
            raise MateError("The tab and the groove must be on different components.")
    elif k == "path":
        res_path(m, W)
    elif k == "slot":
        if str(m.opt.get("position", "free")).lower() in ("center", "centred", "centered", "centre"):
            m.opt["position"] = "centre"
        if m.opt.get("position", "free") not in ("free", "centre"):
            raise MateError("A slot position is free or centre.")
        if m.opt.get("position", "free") == "free" and (m.value is None or float(m.value) <= 0.0):
            raise MateError("A slot mate needs the slot length: the travel between the two end centres.")
        if a["k"] == AX and b["k"] == AX:
            w = a["d"] - float(a["d"] @ b["d"]) * b["d"]
            if float(np.linalg.norm(w)) < 1e-6:
                raise MateError("The pin axis runs along the slot; it must cross the slot.")
            m.opt["n"] = (b["R"].T @ rig.unit(w)).tolist()
        res_slot(m, W)
    elif k == "cam":
        res_cam(m, W)


def update_state(m: Mate, W: list) -> None:
    st = m.opt.setdefault("state", {})
    if m.kind in joint_eq.KINDS:
        joint_eq.update_state(m, W)
    elif m.kind == "gear":
        st["a"] = _turn(m, "a", phi_of(m, "a", W[0], W[0]["R"]))
        st["b"] = _turn(m, "b", phi_of(m, "b", W[1], W[1]["R"]))
    elif m.kind == "rackpinion":
        st["a"] = _turn(m, "a", phi_of(m, "a", W[0], W[0]["R"]))
    elif m.kind == "screw":
        pa = phi_of(m, "a", W[0], W[0]["R"])
        pb = phi_of(m, "b", W[1], W[1]["R"])
        st["a"] = _turn(m, "a", wrap_pair(pa, pb))
