import itertools
import time

from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepExtrema import BRepExtrema_DistShapeShape, BRepExtrema_ShapeProximity
from OCP.BRepGProp import BRepGProp
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.TopLoc import TopLoc_Location
from OCP.collections import List_TopoDS_Shape as ShapeList
from OCP.gp import gp_Trsf

import kernel_store as store

MAX_ITEMS = 400
MAX_PAIRS = 20000
AXES = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]]


def failed(maker) -> bool:
    if not maker.IsDone():
        return True
    probe = getattr(maker, "HasErrors", None)
    return bool(probe()) if callable(probe) else False


def listed(shape):
    out = ShapeList()
    out.Append(shape)
    return out


def trsf_of(m):
    vals = [float(v) for v in m]
    if len(vals) == 16:
        vals = vals[:12]
    if len(vals) != 12:
        raise RuntimeError("A placement needs 12 or 16 numbers.")
    t = gp_Trsf()
    t.SetValues(*vals)
    return t


def moved(shape, m):
    return shape.Moved(TopLoc_Location(trsf_of(m)))


def local_box(shape):
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box, False)
    if box.IsVoid():
        return None
    lo, hi = box.CornerMin(), box.CornerMax()
    return [lo.X(), lo.Y(), lo.Z(), hi.X(), hi.Y(), hi.Z()]


def world_box(lb, m):
    r = [float(v) for v in m]
    if len(r) == 16:
        r = r[:12]
    lo = [1e300] * 3
    hi = [-1e300] * 3
    for x in (lb[0], lb[3]):
        for y in (lb[1], lb[4]):
            for z in (lb[2], lb[5]):
                p = [r[0] * x + r[1] * y + r[2] * z + r[3], r[4] * x + r[5] * y + r[6] * z + r[7], r[8] * x + r[9] * y + r[10] * z + r[11]]
                for k in range(3):
                    lo[k] = min(lo[k], p[k])
                    hi[k] = max(hi[k], p[k])
    return lo, hi


def boxes_meet(a, b, pad):
    return all(a[0][k] - pad <= b[1][k] and b[0][k] - pad <= a[1][k] for k in range(3))


def volume_of(shape):
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props, False, False, False)
    c = props.CentreOfMass()
    return props.Mass(), [c.X(), c.Y(), c.Z()]


def pair_list(keys, wanted, skip):
    skipped = {frozenset(p) for p in (skip or [])}
    if wanted:
        out = [tuple(p) for p in wanted if frozenset(p) not in skipped]
    else:
        out = [p for p in itertools.combinations(keys, 2) if frozenset(p) not in skipped]
    if len(out) > MAX_PAIRS:
        raise RuntimeError("More than %d pairs would be checked; limit the components." % MAX_PAIRS)
    return out


def prepare(p):
    items = p.get("items") or []
    if len(items) > MAX_ITEMS:
        raise RuntimeError("More than %d components cannot be checked in one call." % MAX_ITEMS)
    seen = {}
    for it in items:
        key = str(it["key"])
        if key in seen:
            raise RuntimeError("The key %s appears twice." % key)
        base = store.shape_of(it["id"])
        lb = local_box(base)
        seen[key] = {"base": base, "matrix": it["matrix"], "lb": lb, "wb": world_box(lb, it["matrix"]) if lb else None, "id": it["id"]}
    return seen


def mesh_all(seen, linear):
    for e in seen.values():
        BRepMesh_IncrementalMesh(e["base"], linear, False, 0.5, True)


def interference(p):
    t0 = time.perf_counter()
    seen = prepare(p)
    fuzzy = float(p.get("fuzzy", 1e-4))
    min_vol = float(p.get("min_volume", 1e-3))
    clearance = p.get("clearance")
    clearance = None if clearance is None else float(clearance)
    pad = max(fuzzy, clearance or 0.0)
    pairs = pair_list(list(seen), p.get("pairs"), p.get("skip"))
    stats = {"pairs": len(pairs), "box_hits": 0, "proximity_hits": 0, "common_runs": 0, "distance_runs": 0}
    near = []
    for a, b in pairs:
        ea, eb = seen[a], seen[b]
        if ea["wb"] is None or eb["wb"] is None:
            continue
        if boxes_meet(ea["wb"], eb["wb"], pad):
            near.append((a, b))
    stats["box_hits"] = len(near)
    diag = max((max(h[k] - l[k] for k in range(3)) for e in seen.values() if e["wb"] for l, h in [e["wb"]]), default=1.0)
    linear = float(p.get("linear") or max(diag * 0.002, 0.01))
    mesh_all(seen, linear)
    interfering, cleared = [], []
    errors = []
    for a, b in near:
        ea, eb = seen[a], seen[b]
        sa, sb = moved(ea["base"], ea["matrix"]), moved(eb["base"], eb["matrix"])
        prox = BRepExtrema_ShapeProximity(linear + fuzzy)
        prox.LoadShape1(sa)
        prox.LoadShape2(sb)
        prox.Perform()
        hit = bool(prox.IsDone() and (prox.OverlapSubShapes1().Size() > 0 if hasattr(prox.OverlapSubShapes1(), "Size") else len(prox.OverlapSubShapes1()) > 0))
        if hit:
            stats["proximity_hits"] += 1
            stats["common_runs"] += 1
            maker = BRepAlgoAPI_Common()
            maker.SetArguments(listed(sa))
            maker.SetTools(listed(sb))
            maker.SetFuzzyValue(fuzzy)
            maker.SetRunParallel(True)
            maker.Build()
            if failed(maker):
                errors.append({"a": a, "b": b, "message": "The common volume could not be built."})
            else:
                vol, centre = volume_of(maker.Shape())
                if vol > min_vol:
                    box = local_box(maker.Shape())
                    interfering.append({"a": a, "b": b, "volume": vol, "centre": centre, "box": box})
                    continue
        if clearance is not None:
            stats["distance_runs"] += 1
            dist = BRepExtrema_DistShapeShape()
            dist.LoadS1(sa)
            dist.LoadS2(sb)
            dist.SetMultiThread(True)
            dist.Perform()
            if dist.IsDone() and dist.NbSolution() > 0:
                d = dist.Value()
                if d <= clearance:
                    pa, pb = dist.PointOnShape1(1), dist.PointOnShape2(1)
                    cleared.append({"a": a, "b": b, "distance": d, "contact": d <= max(fuzzy, 1e-6), "point_a": [pa.X(), pa.Y(), pa.Z()], "point_b": [pb.X(), pb.Y(), pb.Z()]})
    interfering.sort(key=lambda r: -r["volume"])
    cleared.sort(key=lambda r: r["distance"])
    return {"interferences": interfering, "clearances": cleared, "errors": errors, "stats": stats, "linear": linear, "fuzzy": fuzzy, "ms": (time.perf_counter() - t0) * 1000.0}


def blocking(p):
    t0 = time.perf_counter()
    seen = prepare(p)
    dirs = p.get("directions") or AXES
    keys = list(seen)
    diag = max((max(h[k] - l[k] for k in range(3)) for e in seen.values() if e["wb"] for l, h in [e["wb"]]), default=1.0)
    total = [[1e300, 1e300, 1e300], [-1e300, -1e300, -1e300]]
    for e in seen.values():
        if e["wb"]:
            for k in range(3):
                total[0][k] = min(total[0][k], e["wb"][0][k])
                total[1][k] = max(total[1][k], e["wb"][1][k])
    reach = float(p.get("distance") or max(total[1][k] - total[0][k] for k in range(3)) + diag)
    eps = float(p.get("min_volume", 1e-3))
    out = {}
    for a in keys:
        ea = seen[a]
        res = []
        for d in dirs:
            blockers = []
            lo, hi = [ea["wb"][0][k] + min(0.0, d[k] * reach) for k in range(3)], [ea["wb"][1][k] + max(0.0, d[k] * reach) for k in range(3)]
            for b in keys:
                if b == a or seen[b]["wb"] is None:
                    continue
                eb = seen[b]
                if not boxes_meet((lo, hi), eb["wb"], 0.0):
                    continue
                size = min([ea["wb"][1][k] - ea["wb"][0][k] for k in range(3)] + [eb["wb"][1][k] - eb["wb"][0][k] for k in range(3)])
                step = min(max(size / 2.0, reach / 60.0), reach / 6.0)
                tool = moved(eb["base"], eb["matrix"])
                hit = False
                t = step
                while t <= reach + 1e-9 and not hit:
                    shifted = [float(v) for v in ea["matrix"]][:12]
                    for k in range(3):
                        shifted[4 * k + 3] += d[k] * t
                    wb = world_box(ea["lb"], shifted)
                    if boxes_meet(wb, eb["wb"], 0.0):
                        maker = BRepAlgoAPI_Common()
                        maker.SetArguments(listed(moved(ea["base"], shifted)))
                        maker.SetTools(listed(tool))
                        maker.SetFuzzyValue(float(p.get("fuzzy", 1e-4)))
                        maker.Build()
                        if failed(maker):
                            hit = True
                        else:
                            vol, _ = volume_of(maker.Shape())
                            hit = vol > eps
                    t += step
                if hit:
                    blockers.append(b)
            res.append({"dir": list(d), "blockers": blockers})
        out[a] = res
    return {"blocking": out, "reach": reach, "ms": (time.perf_counter() - t0) * 1000.0}


METHODS = {"asm_interference": interference, "asm_blocking": blocking}
