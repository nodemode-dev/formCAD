import time

import numpy as np
from OCP.BRep import BRep_Tool
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_FACE
from OCP.TopExp import TopExp_Explorer
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS

import kernel_store as store

MAX_ITEMS = 400
MAX_VERTICES = 64
MAX_PIECES = 8
SPLIT_RATIO = 1.25


def triangles_of(shape, linear):
    BRepMesh_IncrementalMesh(shape, linear, False, 0.5, True)
    pts, tris = [], []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            base = len(pts)
            for i in range(1, tri.NbNodes() + 1):
                p = tri.Node(i).Transformed(trsf)
                pts.append((p.X(), p.Y(), p.Z()))
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                tris.append((base + a - 1, base + b - 1, base + c - 1))
        exp.Next()
    return np.array(pts, dtype=float).reshape(-1, 3), np.array(tris, dtype=int).reshape(-1, 3)


def hull(points):
    from scipy.spatial import ConvexHull, QhullError

    pts = np.unique(np.round(points, 9), axis=0)
    if len(pts) < 4:
        return None, 0.0
    try:
        h = ConvexHull(pts)
    except QhullError:
        return None, 0.0
    return pts[h.vertices], float(h.volume)


def reduce(points, limit):
    if len(points) <= limit:
        return points
    chosen = [int(np.argmax(points[:, 0])), int(np.argmin(points[:, 0]))]
    dist = np.minimum(np.linalg.norm(points - points[chosen[0]], axis=1), np.linalg.norm(points - points[chosen[1]], axis=1))
    while len(chosen) < limit:
        k = int(np.argmax(dist))
        chosen.append(k)
        dist = np.minimum(dist, np.linalg.norm(points - points[k], axis=1))
    sub = points[chosen]
    h, _ = hull(sub)
    return sub if h is None else h


def split(points, tris, volume, depth, pieces, limit):
    h, hv = hull(points[np.unique(tris.reshape(-1))] if len(tris) else points)
    if h is None:
        return
    if depth >= 3 or len(tris) < 8 or len(pieces) >= MAX_PIECES or hv <= volume * SPLIT_RATIO:
        pieces.append((h, hv, len(tris)))
        return
    cen = points[tris].mean(axis=1)
    c = cen.mean(axis=0)
    _, _, vt = np.linalg.svd(cen - c, full_matrices=False)
    side = (cen - c) @ vt[0] > 0
    if side.all() or (~side).all():
        pieces.append((h, hv, len(tris)))
        return
    for m in (side, ~side):
        split(points, tris[m], volume * float(m.sum()) / len(tris), depth + 1, pieces, limit)


def proxy(p):
    t0 = time.perf_counter()
    items = p.get("items") or []
    if len(items) > MAX_ITEMS:
        raise RuntimeError("More than %d bodies cannot get collision proxies in one call." % MAX_ITEMS)
    limit = max(8, min(int(p.get("max_vertices", MAX_VERTICES)), 256))
    out = {}
    for it in items:
        shape = store.shape_of(it["id"])
        box = Bnd_Box()
        BRepBndLib.Add_s(shape, box, False)
        if box.IsVoid():
            out[str(it["key"])] = {"error": "The body has no extent."}
            continue
        lo, hi = box.CornerMin(), box.CornerMax()
        diag = max(hi.X() - lo.X(), hi.Y() - lo.Y(), hi.Z() - lo.Z(), 1e-6)
        linear = float(p.get("linear") or diag * 0.01)
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props, False, False, False)
        volume = props.Mass()
        com = props.CentreOfMass()
        m = props.MatrixOfInertia()
        inertia = [[m.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)]
        pts, tris = triangles_of(shape, linear)
        pieces = []
        if len(pts):
            split(pts, tris, volume, 0, pieces, limit)
        budget = max(8, limit // max(1, len(pieces)))
        out[str(it["key"])] = {
            "volume": volume, "centroid": [com.X(), com.Y(), com.Z()], "inertia": inertia,
            "box": [lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()],
            "pieces": [reduce(h, budget).tolist() for h, _, _ in pieces],
            "hull_volume": float(sum(v for _, v, _ in pieces)),
        }
    return {"proxies": out, "ms": (time.perf_counter() - t0) * 1000.0}


METHODS = {"asm_proxy": proxy}
