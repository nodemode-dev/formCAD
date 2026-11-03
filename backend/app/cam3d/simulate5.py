import math
import types

import numpy as np
from scipy import ndimage

from app.cam import toolpath as T
from app.cam3d import kinematics, voxel
from app.cam3d.cutters import Cutter
from app.cam3d.segments import Segments, from_moves
from app.cam3d.simulate import b64, tool_obj
from app.cam3d.surface import CamError

SPACING_CAP = 60000


def pose_samples(a, i, step_feed, step_rapid):
    p0, p1 = a["p0"][i], a["p1"][i]
    ln = float(np.linalg.norm(p1 - p0))
    k0 = a["ax"][i] if a["ax"] is not None else np.array([0.0, 0.0, 1.0])
    k1 = a["ax_end"][i] if a.get("ax_end") is not None else k0
    step = step_rapid if a["rapid"][i] else step_feed
    ang = math.degrees(math.acos(min(max(float(np.dot(k0, k1)), -1.0), 1.0)))
    n = max(int(math.ceil(ln / step)), int(math.ceil(ang / 1.0)), 1)
    t = (np.arange(n) + 1.0) / n
    P = p0[None, :] + (p1 - p0)[None, :] * t[:, None]
    K = k0[None, :] * (1 - t[:, None]) + k1[None, :] * t[:, None]
    K = K / np.linalg.norm(K, axis=1, keepdims=True)
    return P, K, ln


def build_axes(seg: Segments):
    n = seg.count
    a = seg.arrays()
    ax = a["ax"]
    if ax is None:
        ax = np.tile(np.array([0.0, 0.0, 1.0]), (n, 1))
    ax = ax / np.linalg.norm(ax, axis=1, keepdims=True)
    a["ax_end"] = ax
    start = np.vstack([ax[:1], ax[:-1]]) if n else ax
    a["ax"] = start
    return a


def surface_tree(tri_sets, spacing, cap=2_500_000):
    from scipy.spatial import cKDTree

    pts = []
    nrm = []
    total = 0
    for tris in tri_sets:
        t = np.asarray(tris, dtype=float)
        area = 0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1)
        k = np.maximum(np.ceil(np.sqrt(np.maximum(area, 1e-12)) / spacing).astype(np.int64) + 1, 2)
        for kv in np.unique(k):
            sel = t[k == kv]
            kv = int(kv)
            ij = [(i, j) for i in range(kv + 1) for j in range(kv + 1 - i)]
            u = np.array([i / kv for i, j in ij])
            v = np.array([j / kv for i, j in ij])
            w = 1.0 - u - v
            p = sel[:, 0, None, :] * w[None, :, None] + sel[:, 1, None, :] * u[None, :, None] + sel[:, 2, None, :] * v[None, :, None]
            pts.append(p.reshape(-1, 3))
            nn = np.cross(sel[:, 1] - sel[:, 0], sel[:, 2] - sel[:, 0])
            nn = nn / np.maximum(np.linalg.norm(nn, axis=1, keepdims=True), 1e-12)
            nrm.append(np.repeat(nn, p.shape[1], axis=0))
            total += p.shape[0] * p.shape[1]
            if total > cap:
                raise CamError("The model surface needs more than %d sample points for the distance check; use a larger cell." % cap)
    if not pts:
        return None
    allp = np.concatenate(pts)
    tree = cKDTree(allp)
    return types.SimpleNamespace(query=tree.query, sample_points=allp, sample_normals=np.concatenate(nrm))


def run(inp: dict, cancel=None, progress=None, phase=None) -> dict:
    lim = inp["limits"]
    machine = kinematics.TableTable(inp.get("machine") or {})
    stock = inp["stock"]
    bmin = np.array(stock["min"], dtype=float)
    bmax = np.array(stock["max"], dtype=float)
    for tris in (inp["tris"], inp.get("fixtures")):
        if tris is not None:
            bmin = np.minimum(bmin, tris.reshape(-1, 3).min(axis=0))
            bmax = np.maximum(bmax, tris.reshape(-1, 3).max(axis=0))
    cell = float(inp["cell"])
    vol = float(np.prod(bmax - bmin))
    auto = (vol / max(lim["sim_voxels"], 1)) ** (1.0 / 3.0)
    if cell < auto:
        cell = auto * 1.02
    warnings = []
    if abs(cell - float(inp["cell"])) > 1e-9:
        warnings.append("The voxel cell was raised to %.3f mm to stay within the limit of %d voxels." % (cell, lim["sim_voxels"]))
    pad = 2.0 * cell
    g = voxel.Grid(bmin - pad, bmax + pad, cell)
    if g.count > lim["sim_voxels"] * 1.2:
        raise CamError("The simulation volume has %d voxels, more than the limit of %d; use a larger cell." % (g.count, lim["sim_voxels"]))
    if phase:
        phase("voxelize")
    S = voxel.box_mask(g, stock["min"], stock["max"], stock.get("polygon") if stock.get("kind") in ("cylinder", "tube") else None)
    M = voxel.voxelize(inp["tris"], g)
    F = voxel.voxelize(inp["fixtures"], g) if inp.get("fixtures") is not None else np.zeros_like(M)
    S &= ~F
    sim = voxel.VoxelSim(g, S, M, F)
    sim.prepare_static()
    tol = float(inp["gouge_tol"])
    tree = surface_tree([inp["tris"]] + ([inp["fixtures"]] if inp.get("fixtures") is not None else []), min(cell * 0.25, 0.15))
    inside_depth = ndimage.distance_transform_edt(M, sampling=cell)
    core = M & (inside_depth > tol + cell * 0.5)
    stock_volume = sim.volume()
    table_top = inp.get("table_top")
    if table_top is None:
        zs = [stock["min"][2]]
        if inp.get("fixtures") is not None:
            zs.append(float(inp["fixtures"].reshape(-1, 3)[:, 2].min()))
        table_top = min(zs)
    tr = float(machine.rec["table"]["radius"])
    per_op = []
    total_t = 0.0
    total_simple = 0.0
    total_len = 0.0
    n_ops = len(inp["ops"])
    min_gap = {}
    min_at = {}
    snaps = []
    poses_log = []
    nsnap = int(inp.get("snapshots", 0))
    max_step = 0.0
    prev_ac = None
    a_seen = [math.inf, -math.inf]
    c_seen = [math.inf, -math.inf]
    axis_events = 0

    def keep(kind, v, where):
        if kind not in min_gap or v < min_gap[kind]:
            min_gap[kind] = float(v)
            min_at[kind] = [float(x) for x in where]

    def snap(pose):
        edge = sim.S & ~ndimage.binary_erosion(sim.S)
        idx = np.argwhere(edge)
        if len(idx) > 40000:
            idx = idx[:: int(math.ceil(len(idx) / 40000))]
        pts = (g.o[None, :] + (idx + 0.5) * cell).astype(np.float32)
        snaps.append(pts)
        poses_log.append(pose)

    if nsnap:
        snap(None)
    next_snap = 1
    sp_c = max(cell * 1.5, 0.3)
    for oi, op in enumerate(inp["ops"]):
        if phase:
            phase("op %s" % op["id"])
        rec = op["tool"]
        cu = Cutter.from_tool(tool_obj(rec))
        flute = float(rec.get("flute_length") or 0.0)
        flute = flute if 0 < flute < 1e5 else cu.R * 6.0
        stick = float(rec.get("stickout") or 0.0)
        stick = stick if stick > flute else flute + 10.0
        shank_r = float(rec.get("shank_diameter") or 0.0) / 2.0 or cu.R
        holder = (rec.get("holder") or {}).get("profile") or [[shank_r * 2.0, 0.0], [shank_r * 2.0, 40.0]]
        sp_h = max(sp_c * 1.5, 0.5)
        cut_pts = voxel.surface_points(cu, flute, sp_c)
        body_pts = np.vstack([voxel.revolve_points([(shank_r, flute), (shank_r, stick)], sp_h), voxel.revolve_points([(r, z) for r, z in holder], sp_h, stick)])
        if len(body_pts) > SPACING_CAP:
            body_pts = body_pts[:: int(math.ceil(len(body_pts) / SPACING_CAP))]
        seg = Segments()
        from_moves(seg, op["moves"], oi, arc_tol=cell * 0.25, limit=lim["sim_moves"])
        v0 = sim.volume()
        sim.dist_body = ndimage.distance_transform_edt(~(sim.S | sim.P), sampling=cell).astype(np.float32)
        if seg.count:
            a = build_axes(seg)
            ln_all = np.linalg.norm(a["p1"] - a["p0"], axis=1)
            total_len += float(ln_all.sum())
            est = int(np.ceil(ln_all / (cell * 0.7)).sum())
            if est > lim["sim_samples"]:
                raise CamError("%s needs about %d poses, more than the limit of %d; use a larger cell." % (op["id"], est, lim["sim_samples"]))
            done = 0
            since = 0
            for si in range(seg.count):
                if cancel and si % 8 == 0:
                    cancel()
                Pp, Kk, ln = pose_samples(a, si, cell * 0.7, cell * 3.0)
                rapid = bool(a["rapid"][si])
                tag = (oi << 32) | int(a["move"][si])
                for pi in range(len(Pp)):
                    p, k = Pp[pi], Kk[pi]
                    e1, e2 = voxel.frame_of(k)
                    if not rapid or pi == len(Pp) - 1:
                        try:
                            sol = machine.solve(p, k, prev_ac)
                        except kinematics.Reach as err:
                            axis_events += 1
                            sim.event("axis_limit", tag, p, 0.0)
                            sol = None
                        if sol is not None:
                            m = (sol["x"], sol["y"], sol["z"])
                            bad = machine.in_travel(m)
                            if bad:
                                sim.event("travel", tag, p, 0.0, (sol["a"], 0.0, sol["c"]))
                            if prev_ac is not None:
                                max_step = max(max_step, abs(sol["a"] - prev_ac["a"]), abs(sol["c"] - prev_ac["c"]))
                            prev_ac = {"a": sol["a"], "c": sol["c"]}
                            a_seen = [min(a_seen[0], sol["a"]), max(a_seen[1], sol["a"])]
                            c_seen = [min(c_seen[0], sol["c"]), max(c_seen[1], sol["c"])]
                    since += 1
                    check = since % 2 == 0 or pi == len(Pp) - 1
                    if check:
                        R3 = np.stack([e1, e2, k], axis=1)
                        wb = p[None, :] + body_pts @ R3.T
                        idx = g.index(wb)
                        inb = ((idx >= 0) & (idx < g.n)).all(axis=1)
                        ii = idx[inb]
                        occ = np.zeros(len(wb), dtype=bool)
                        occ[inb] = sim.S[ii[:, 0], ii[:, 1], ii[:, 2]] | sim.P[ii[:, 0], ii[:, 1], ii[:, 2]]
                        dist = np.full(len(wb), 1e6, dtype=np.float32)
                        dist[inb] = sim.dist_body[ii[:, 0], ii[:, 1], ii[:, 2]]
                        j = int(np.argmin(dist))
                        keep("holder", dist[j], wb[j])
                        if occ.any():
                            jj = int(np.nonzero(occ)[0][0])
                            sk = "holder_fixture" if sim.F[tuple(idx[jj])] else "holder_stock"
                            sim.event(sk, tag, wb[jj], 0.0)
                        low = wb[:, 2] < table_top - 1e-6
                        if low.any():
                            rr = np.hypot(wb[low, 0], wb[low, 1])
                            if (rr <= tr).any():
                                w = wb[low][np.argmax(rr <= tr)]
                                sim.event("holder_table", tag, w, 0.0)
                        wc = p[None, :] + cut_pts @ R3.T
                        sdv, inbc = sim.lookup(wc, sim.sd_tool, 1e6)
                        near_c = np.nonzero(sdv < 1.5 * cell)[0]
                        if len(near_c) and tree is not None:
                            dd, ni = tree.query(wc[near_c])
                            side = ((wc[near_c] - tree.sample_points[ni]) * tree.sample_normals[ni]).sum(axis=1)
                            sg = np.where(side < 0, -dd, dd)
                            jn = int(np.argmin(sg))
                            jc, dval = int(near_c[jn]), float(sg[jn])
                        else:
                            jc = int(np.argmin(sdv))
                            dval = float(sdv[jc])
                        if dval < 0 and sdv[jc] >= cell * 0.5:
                            dval = -dval
                        keep("tool", dval, wc[jc])
                        if dval < -tol and sdv[jc] < cell * 0.5:
                            sk = "tool_fixture" if sim.F[tuple(g.index(wc[jc:jc + 1])[0])] else "tool_model"
                            sim.event(sk, tag, wc[jc], dval)
                        lowc = wc[:, 2] < table_top - 1e-6
                        if lowc.any() and (np.hypot(wc[lowc, 0], wc[lowc, 1]) <= tr).any():
                            sim.event("tool_table", tag, wc[lowc][0], 0.0)
                    if rapid:
                        if check:
                            n_in = sim.cut_pose_test(p, k, cu, flute)
                            if n_in > 0:
                                sim.event("rapid_in_stock", tag, p, -1.0)
                    else:
                        sim.cut_pose(p, k, cu, flute)
                    done += 1
                if progress and si % 16 == 0:
                    progress((oi + si / seg.count) / n_ops)
                while nsnap and next_snap <= nsnap and (oi + (si + 1) / seg.count) / n_ops >= next_snap / nsnap:
                    snap({"tip": p.tolist(), "axis": k.tolist(), "op": oi})
                    next_snap += 1
                if done > 20000:
                    sim.dist_body = ndimage.distance_transform_edt(~(sim.S | sim.P), sampling=cell).astype(np.float32)
                    done = 0
        v1 = sim.volume()
        ct = T.cycle_time(op["moves"], op.get("machine") or {})
        total_t += ct["trapezoid_s"]
        total_simple += ct["simple_s"]
        per_op.append({"op": op["id"], "removed_mm3": round(v0 - v1, 3), "time_s": round(ct["trapezoid_s"], 2), "min_distance_mm": None})
    while nsnap and next_snap <= nsnap:
        snap(None)
        next_snap += 1
    removed_core = core & ~sim.S
    ncore = int(removed_core.sum())
    gouge = {"cells": ncore, "max_depth_mm": 0.0, "area_mm2": 0.0, "first": []}
    if ncore:
        dep = inside_depth[removed_core]
        gouge["max_depth_mm"] = float(dep.max())
        gouge["area_mm2"] = float(ncore * cell * cell)
        idx = np.argwhere(removed_core)
        worst = np.argsort(-dep)[:20]
        gouge["first"] = [[round(float(v), 3) for v in (g.o + (idx[i] + 0.5) * cell)] + [round(float(dep[i]), 4)] for i in worst]
    closest = {"holder_mm": min_gap.get("holder"), "tool_mm": min_gap.get("tool"), "holder_at": min_at.get("holder"), "tool_at": min_at.get("tool")}
    result = {
        "mode": "voxel", "stock_volume_mm3": round(stock_volume, 3), "removed_mm3": round(stock_volume - sim.volume(), 3), "final_volume_mm3": round(sim.volume(), 3),
        "min_distance_mm": None if "tool" not in min_gap else round(min_gap["tool"], 4), "min_distance_at": min_at.get("tool"), "gouge": gouge, "collisions": list(sim.events), "closest": closest,
        "time_s": round(total_t, 2), "time_simple_s": round(total_simple, 2), "path_length_mm": round(total_len, 2), "per_op": per_op,
        "grid": {"nx": int(g.n[0]), "ny": int(g.n[1]), "nz": int(g.n[2]), "cell": cell, "origin": [float(v) for v in g.o]},
        "rotary": {"a_range": None if a_seen[0] == math.inf else [round(a_seen[0], 3), round(a_seen[1], 3)], "c_range": None if c_seen[0] == math.inf else [round(c_seen[0], 3), round(c_seen[1], 3)], "max_step_deg": round(max_step, 3), "axis_limit_events": axis_events},
        "snapshots": len(snaps) - 1 if snaps else 0, "warnings": warnings,
    }
    return {"result": result, "state": {"snaps": snaps, "poses": poses_log, "grid": result["grid"]}}
