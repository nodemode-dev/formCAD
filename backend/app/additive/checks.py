import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from app.additive import placement, slicing
from app.additive import regions as rg
from app.additive.jobs import QUIET

FLAT_DOWN_AREA = 50.0
SAMPLE_LAYERS = 14


def edge_report(v: np.ndarray, t: np.ndarray) -> dict:
    nv, nt = slicing.weld(v, t)
    if not len(nt):
        return {"open": 0, "nonmanifold": 0, "components": 0, "cavities": 0}
    a = np.concatenate([nt[:, 0], nt[:, 1], nt[:, 2]])
    b = np.concatenate([nt[:, 1], nt[:, 2], nt[:, 0]])
    lo, hi = np.minimum(a, b), np.maximum(a, b)
    key = lo * len(nv) + hi
    _u, counts = np.unique(key, return_counts=True)
    n = len(nv)
    ij = np.concatenate([nt[:, 0], nt[:, 1], nt[:, 2]]), np.concatenate([nt[:, 1], nt[:, 2], nt[:, 0]])
    graph = coo_matrix((np.ones(len(ij[0])), ij), shape=(n, n))
    count, label = connected_components(graph, directed=False)
    cavities = 0
    for c in range(count):
        tris = nt[label[nt[:, 0]] == c]
        if len(tris) >= 4 and slicing.signed_volume(nv, tris) < -1e-6:
            cavities += 1
    return {"open": int((counts == 1).sum()), "nonmanifold": int((counts > 2).sum()), "components": int(count), "cavities": cavities}


def run(parts: list, items: list, s: dict, bed, metal: bool, min_wall=None) -> list:
    out = []
    wall = float(min_wall) if min_wall else (0.6 if metal else 0.8 * s["nozzle"])
    all_v, all_t, off = [], [], 0
    for k, (body, item) in enumerate(zip(parts, items)):
        v, _m = placement.transform(body.v, item)
        rep = edge_report(v, body.t)
        where = {"body": body.handle, "item": k}
        if rep["open"]:
            out.append({"kind": "open_edges", "severity": "error", "message": "%s has %d open edges; it is not a closed solid." % (body.name, rep["open"]), "where": where})
        if rep["nonmanifold"]:
            out.append({"kind": "non_manifold", "severity": "error", "message": "%s has %d edges shared by more than two triangles." % (body.name, rep["nonmanifold"]), "where": where})
        if rep["cavities"]:
            why = "traps unfused powder and cannot be cleared" if metal else "is a closed hollow volume with no way in"
            out.append({"kind": "closed_cavity", "severity": "warning", "message": "%s has %d closed internal void%s; it %s." % (body.name, rep["cavities"], "" if rep["cavities"] == 1 else "s", why), "where": where})
        lo, hi = v.min(axis=0), v.max(axis=0)
        if lo[0] < -1e-6 or lo[1] < -1e-6 or hi[0] > bed[0] + 1e-6 or hi[1] > bed[1] + 1e-6:
            out.append({"kind": "off_plate", "severity": "error", "message": "%s sits partly outside the %g by %g mm plate." % (body.name, bed[0], bed[1]), "where": where})
        if hi[2] - lo[2] > s["max_height"] + 1e-6:
            out.append({"kind": "too_tall", "severity": "error", "message": "%s is %.1f mm tall; the profile allows %.1f mm." % (body.name, hi[2] - lo[2], s["max_height"]), "where": where})
        nv, nt = slicing.weld(v, body.t)
        if len(nt):
            a, b, c = nv[nt[:, 0]], nv[nt[:, 1]], nv[nt[:, 2]]
            cr = np.cross(b - a, c - a)
            area = np.linalg.norm(cr, axis=1) / 2.0
            nz = np.where(area > 1e-12, cr[:, 2] / np.maximum(2.0 * area, 1e-30), 0.0)
            cz = ((a + b + c) / 3.0)[:, 2] - lo[2]
            flat = (nz < -0.99) & (cz > 0.05)
            fa = float(area[flat].sum())
            if fa > FLAT_DOWN_AREA:
                out.append({"kind": "flat_downskin", "severity": "warning", "message": "%s has %.0f mm2 of flat down-facing surface that is not on the plate; it needs support%s." % (body.name, fa, " and will be rough or may curl" if metal else ""), "where": where})
        all_v.append(nv)
        all_t.append(nt + off)
        off += len(nv)
    if all_v:
        v = np.vstack(all_v)
        t = np.vstack(all_t)
        zmin, zmax = float(v[:, 2].min()), float(v[:, 2].max())
        if zmax - zmin > 0.2:
            zs = np.linspace(zmin + 0.1, zmax - 0.1, SAMPLE_LAYERS)
            loops = slicing.slice_planes(v, t, zs, QUIET, slicing.MAX_PAIRS, {})
            regions = slicing.to_regions(loops)
            worst = {}
            for z, R in zip(zs, regions):
                if not R:
                    continue
                opened = rg.offset(rg.offset(R, -wall / 2.0), wall / 2.0)
                thin = rg.diff(R, rg.offset(opened, 0.01)) if opened else R
                a = rg.area(thin)
                if a > 0.5:
                    worst[round(float(z - zmin), 2)] = a
            if worst:
                z0 = min(worst)
                out.append({"kind": "thin_walls", "severity": "warning", "message": "Features thinner than %.2f mm at %d of %d sample heights (first at z %.2f mm, %.1f mm2)." % (wall, len(worst), SAMPLE_LAYERS, z0, worst[z0]), "where": {"z": z0}})
    return out
