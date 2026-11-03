import math

import numpy as np

from app.solid import surfwork as sw
from app.solid import work
from app.solid.work import SolidError

CURVE_KINDS = ("line", "circle", "arc", "ellipse", "lwpolyline", "polyline3d", "spline", "nurbscurve")
MAX_CURVES = 64


def refs_of(d, handles: list, edges: list) -> list:
    out = []
    for h in handles or []:
        ent = d.get(int(h))
        if ent is None:
            raise SolidError("Object %s does not exist." % h)
        if ent.kind not in CURVE_KINDS:
            raise SolidError("A %s has no curvature comb; choose a curve." % ent.kind)
        out.append({"ref": {"handle": ent.handle}, "spec": sw.curve_spec(d, ent)})
    for r in edges or []:
        body, edge = sw.edge_ref(d, r)
        out.append({"ref": {"body": body.handle, "edge": body.edge_ids[edge["index"]] if edge["index"] < len(body.edge_ids) else None}, "spec": {"kind": "shape_edge", **edge}})
    if not out:
        raise SolidError("Choose curves or edges for the comb.")
    if len(out) > MAX_CURVES:
        raise SolidError("A comb takes up to %d curves at a time." % MAX_CURVES)
    return out


def planar_normal(points: np.ndarray):
    if len(points) < 3:
        return None
    c = points.mean(axis=0)
    u, s, vt = np.linalg.svd(points - c, full_matrices=False)
    if s[0] < 1e-12 or s[-1] > 1e-6 * s[0]:
        return None
    n = vt[-1]
    for axis in (np.array([0.0, 0.0, 1.0]), np.array([0.0, 1.0, 0.0]), np.array([1.0, 0.0, 0.0])):
        if abs(float(np.dot(n, axis))) > 1e-9:
            return n if float(np.dot(n, axis)) > 0 else -n
    return n


def compute(d, handles: list, edges: list, per_span: int = 12, scale: float = 1.0, density: int | None = None) -> dict:
    items = refs_of(d, handles, edges)
    s = work.mm(d)
    res = work.kcall("an_comb", {"curves": [i["spec"] for i in items], "per_span": int(density or per_span)}, work.LONG)
    diag = 0.0
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    curves = []
    kmax = 0.0
    for item, got in zip(items, res["curves"]):
        segs = []
        for e in got["edges"]:
            pts = np.asarray(e["points"], dtype=np.float64)
            k = np.asarray(e["curvature"], dtype=np.float64)
            nor = np.asarray(e["normal"], dtype=np.float64)
            tan = np.asarray(e["tangent"], dtype=np.float64)
            segs.append({"pts": pts, "k": k, "n": nor, "t": tan, "type": e["type"]})
            if len(pts):
                lo = np.minimum(lo, pts.min(axis=0))
                hi = np.maximum(hi, pts.max(axis=0))
            if len(k):
                kmax = max(kmax, float(k.max()))
        curves.append((item["ref"], segs))
    if np.all(np.isfinite(lo)):
        diag = float(np.linalg.norm(hi - lo))
    height = max(diag * 0.1 * float(scale), 1e-9)
    factor = height / kmax if kmax > 1e-12 else 0.0
    out = []
    for ref, segs in curves:
        allpts = np.concatenate([g["pts"] for g in segs]) if segs else np.zeros((0, 3))
        w = planar_normal(allpts)
        rows = []
        for g in segs:
            tips = g["pts"] - g["n"] * (g["k"] * factor)[:, None]
            kk = g["k"].copy()
            if w is not None:
                b = np.cross(g["t"], g["n"])
                sign = np.where(b @ w >= 0, 1.0, -1.0)
                kk = kk * sign
            infl = [int(i) for i in range(1, len(kk)) if kk[i - 1] * kk[i] < 0] if w is not None else []
            rows.append({
                "points": (g["pts"] / s).tolist(), "tips": (tips / s).tolist(), "curvature": (kk * s).tolist(),
                "radius": [None if abs(x) < 1e-12 else float(1.0 / (abs(x) * s)) for x in kk], "inflections": infl, "type": g["type"],
            })
        out.append({"ref": ref, "planar": w is not None, "segments": rows})
    return {"curves": out, "max_curvature": kmax * s, "height": height / s, "scale": float(scale), "mm_per_unit": s, "unit": "1/unit"}
