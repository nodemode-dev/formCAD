import base64
import math
import types

import numpy as np

from app.cam import toolpath as T
from app.cam3d import dropcutter
from app.cam3d.cutters import Cutter
from app.cam3d.dexel import BIG, DexelStock, Underside
from app.cam3d.paths3d import POINT
from app.cam3d.segments import Segments, from_moves
from app.cam3d.surface import CamError, Surface

MAX_EVENTS = 400
CHUNK_SAMPLES = 120_000
SNAP_CELLS = 300


def tool_obj(rec: dict):
    return types.SimpleNamespace(kind=rec.get("kind", "flat"), diameter=float(rec.get("diameter", 6) or 6), corner_radius=float(rec.get("corner_radius", 0) or 0), flute_length=float(rec.get("flute_length", 0) or 0), tip_angle=float(rec.get("tip_angle", 118) or 118), tip_diameter=float(rec.get("tip_diameter", 0) or 0))


def b64(a) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


class Events:
    def __init__(self):
        self.rows = []
        self.min_gap = {}
        self.at = {}
        self.seen = set()

    def record(self, kind, k, gap, P, ids, tol=1e-6, extra=None):
        if len(gap) == 0:
            return
        j = int(np.argmin(gap))
        g = float(gap[j])
        if kind not in self.min_gap or g < self.min_gap[kind]:
            self.min_gap[kind] = g
            self.at[kind] = [float(v) for v in P[k[j]]]
        bad = np.nonzero(gap < -tol)[0]
        for b in bad[:6]:
            idx = int(ids[k[b]])
            key = (kind, idx)
            if key in self.seen or len(self.rows) >= MAX_EVENTS:
                continue
            self.seen.add(key)
            self.rows.append({"op_move": idx, "kind": kind, "at": [float(v) for v in P[k[b]]], "distance_mm": float(gap[b])})


def ring_mask(rings, X, Y):
    out = np.zeros(X.shape, dtype=bool)
    for r in rings:
        a = np.asarray(r, dtype=float)
        x, y = X.ravel(), Y.ravel()
        inside = np.zeros(len(x), dtype=bool)
        n = len(a)
        j = n - 1
        for i in range(n):
            xi, yi, xj, yj = a[i, 0], a[i, 1], a[j, 0], a[j, 1]
            cond = ((yi > y) != (yj > y)) & (x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi)
            inside ^= cond
            j = i
        out ^= inside.reshape(X.shape)
    return out


def run(inp: dict, cancel=None, progress=None, phase=None) -> dict:
    cell = float(inp["cell"])
    bmin, bmax = inp["stock"]["min"], inp["stock"]["max"]
    rings = inp["stock"].get("polygon")
    inside = None
    if rings and len(rings) and inp["stock"].get("kind") in ("cylinder", "tube"):
        inside = lambda X, Y: ring_mask(rings, X, Y)
    cells = max(int(math.ceil((bmax[0] - bmin[0]) / cell)), 1) * max(int(math.ceil((bmax[1] - bmin[1]) / cell)), 1)
    if cells > inp["limits"]["sim_cells"]:
        raise CamError("The simulation grid has %d cells, more than the limit of %d; use a larger cell." % (cells, inp["limits"]["sim_cells"]))
    dx = DexelStock(bmin, bmax, cell, inside)
    warnings = []
    if phase:
        phase("design")
    model = Surface(inp["tris"])
    dz = dropcutter.drop(model, POINT, np.stack(np.meshgrid(dx.xc, dx.yc, indexing="ij"), axis=-1).reshape(-1, 2), cancel).reshape(dx.nx, dx.ny)
    dx.set_design(dz)
    if inp.get("fixtures") is not None:
        fx = Surface(inp["fixtures"])
        fz = dropcutter.drop(fx, POINT, np.stack(np.meshgrid(dx.xc, dx.yc, indexing="ij"), axis=-1).reshape(-1, 2), cancel).reshape(dx.nx, dx.ny)
        dx.set_fixture(fz)
    ev = Events()
    stock_volume = dx.volume()
    total_len = 0.0
    n_ops = len(inp["ops"])
    per_op = []
    total_time = 0.0
    total_simple = 0.0
    snaps = []
    pose_log = []
    nsnap = int(inp.get("snapshots", 0))
    est_total = max(sum(len(o["moves"]) for o in inp["ops"]), 1)
    done_moves = 0
    sub = max(1, int(math.ceil(max(dx.nx, dx.ny) / SNAP_CELLS)))

    def snap(label_pose):
        snaps.append((dx.top[::sub, ::sub].astype(np.float32).copy(), dx.bot[::sub, ::sub].astype(np.float32).copy(), (dx.gouge_depth.reshape(dx.nx, dx.ny)[::sub, ::sub] > 0).astype(np.uint8).copy()))
        pose_log.append(label_pose)

    if nsnap:
        snap(None)
    next_snap = 1
    last_pose = None
    for oi, op in enumerate(inp["ops"]):
        if phase:
            phase("op %s" % op["id"])
        rec = op["tool"]
        cu = Cutter.from_tool(tool_obj(rec))
        holder = (rec.get("holder") or {}).get("profile") or []
        stick = float(rec.get("stickout") or 0.0)
        h_under = Underside([(r, z + stick) for r, z in holder]) if holder and stick > 0 else None
        shank_r = float(rec.get("shank_diameter") or 0.0) / 2.0
        flute = float(rec.get("flute_length") or 0.0)
        s_under = Underside([(0.0, flute), (shank_r, flute), (shank_r, max(stick, flute) + 1.0)]) if shank_r > 0 and flute > 0 and 0 < flute < 1e5 else None
        seg = Segments()
        pos, cur_tool = from_moves(seg, op["moves"], oi, arc_tol=cell * 0.25, limit=inp["limits"]["sim_moves"])
        v0 = dx.volume()
        clear0 = dx.min_clear
        if seg.count:
            a = seg.arrays()
            ln = np.linalg.norm(a["p1"] - a["p0"], axis=1)
            ns = np.maximum(np.ceil(ln / (cell * 0.5)).astype(np.int64), 1)
            total_len += float(ln.sum())
            if int(ns.sum()) > inp["limits"]["sim_samples"]:
                raise CamError("%s needs %d simulation samples, more than the limit of %d; use a larger cell." % (op["id"], int(ns.sum()), inp["limits"]["sim_samples"]))
            cs = np.cumsum(ns)
            s0 = 0
            nseg = seg.count
            while s0 < nseg:
                if cancel:
                    cancel()
                s1 = int(np.searchsorted(cs, (cs[s0 - 1] if s0 else 0) + CHUNK_SAMPLES, side="right"))
                s1 = max(s1, s0 + 1)
                s1 = min(s1, nseg)
                cnt = ns[s0:s1]
                tot = int(cnt.sum())
                sid = np.repeat(np.arange(s0, s1), cnt)
                first = np.cumsum(cnt) - cnt
                local = np.arange(tot) - np.repeat(first, cnt)
                t = (local + 1.0) / np.repeat(cnt, cnt)
                P = a["p0"][sid] + (a["p1"][sid] - a["p0"][sid]) * t[:, None]
                ids = (np.int64(oi) << 32) | a["move"][sid]
                rap = a["rapid"][sid]
                feed = ~rap
                if feed.any():
                    Pf = P[feed]
                    idf = ids[feed]
                    if s_under is not None:
                        dx.clearance_body(Pf, s_under, s_under.rmax, idf, "shank", ev.record, max(1, int(round(s_under.rmax / 6.0 / cell))))
                    if h_under is not None:
                        dx.clearance_body(Pf, h_under, h_under.rmax, idf, "holder", ev.record, max(1, int(round(h_under.rmax / 8.0 / cell))))
                    dx.cut(Pf, cu, inp["gouge_tol"], idf, True)
                if rap.any():
                    Pr = P[rap]
                    hit = dx.cut(Pr, cu, inp["gouge_tol"], ids[rap], False)
                    if hit.any():
                        kk = np.nonzero(hit)[0]
                        ev.record("rapid_in_stock", kk, np.full(len(kk), -1.0), Pr, ids[rap])
                last_pose = (P[-1].tolist(), oi, int(a["move"][s1 - 1]))
                done_moves += int(cnt.sum() / max(1, 1))
                s0 = s1
                frac = min(1.0, (done_moves) / max(est_total, 1))
                if progress:
                    progress((oi + min(1.0, s0 / nseg)) / n_ops)
                while nsnap and next_snap <= nsnap and (oi + s0 / nseg) / n_ops >= next_snap / nsnap:
                    snap(last_pose)
                    next_snap += 1
        v1 = dx.volume()
        ct = T.cycle_time(op["moves"], op.get("machine") or {})
        total_time += ct["trapezoid_s"]
        total_simple += ct["simple_s"]
        per_op.append({"op": op["id"], "removed_mm3": round(v0 - v1, 3), "time_s": round(ct["trapezoid_s"], 2), "min_distance_mm": None if not math.isfinite(dx.min_clear) else round(dx.min_clear, 4)})
    while nsnap and next_snap <= nsnap:
        snap(last_pose)
        next_snap += 1
    gd = dx.gouge_depth
    bad = np.nonzero(gd > 0)[0]
    gouge = {"cells": int(len(bad)), "max_depth_mm": float(gd.max()) if len(bad) else 0.0, "area_mm2": float(len(bad) * cell * cell), "first": []}
    if len(bad):
        worst = bad[np.argsort(-gd[bad])[:20]]
        gouge["first"] = [[round(float(v), 3) for v in dx.gouge_tool[i]] + [round(float(gd[i]), 4)] for i in worst]
        gouge["first_move"] = int(dx.gouge_first[bad].min())
    valid = np.isfinite(dx.design_chk)
    margin = float(np.min((dx.top - dx.design_chk)[valid])) if valid.any() else None
    collisions = list(ev.rows)
    closest = {"holder_mm": ev.min_gap.get("holder_stock"), "tool_mm": ev.min_gap.get("shank_stock"), "holder_at": ev.at.get("holder_stock"), "tool_at": ev.at.get("shank_stock"), "holder_fixture_mm": ev.min_gap.get("holder_fixture"), "tool_fixture_mm": ev.min_gap.get("shank_fixture")}
    result = {
        "mode": "dexel", "stock_volume_mm3": round(stock_volume, 3), "removed_mm3": round(stock_volume - dx.volume(), 3), "final_volume_mm3": round(dx.volume(), 3),
        "min_distance_mm": None if not math.isfinite(dx.min_clear) else round(dx.min_clear, 5), "min_distance_at": dx.min_clear_at, "final_surface_margin_mm": None if margin is None else round(margin, 5),
        "gouge": gouge, "collisions": collisions, "closest": closest, "time_s": round(total_time, 2), "time_simple_s": round(total_simple, 2), "path_length_mm": round(total_len, 2),
        "per_op": per_op, "grid": {"nx": dx.nx, "ny": dx.ny, "cell": cell, "origin": [dx.x0, dx.y0]}, "snapshots": len(snaps) - 1 if snaps else 0, "warnings": warnings,
    }
    state = {"snaps": snaps, "poses": pose_log, "sub": sub, "grid": result["grid"], "dx": dx}
    return {"result": result, "state": state}
