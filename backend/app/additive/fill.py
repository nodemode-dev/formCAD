import math

import numpy as np

from app.additive import regions as rg

MAX_CELLS = 600_000
TABLE_A = np.full((2, 16, 2), -1, dtype=np.int64)
TABLE_B = np.full((2, 16, 2), -1, dtype=np.int64)


def _fill_tables():
    plain = {1: [(3, 0)], 2: [(0, 1)], 3: [(3, 1)], 4: [(1, 2)], 6: [(0, 2)], 7: [(3, 2)], 8: [(2, 3)], 9: [(0, 2)], 11: [(1, 2)], 12: [(1, 3)], 13: [(0, 1)], 14: [(3, 0)]}
    for centre in (0, 1):
        for case, segs in plain.items():
            for k, (a, b) in enumerate(segs):
                TABLE_A[centre, case, k] = a
                TABLE_B[centre, case, k] = b
    saddle = {5: ([(3, 0), (1, 2)], [(0, 1), (3, 2)]), 10: ([(0, 1), (2, 3)], [(3, 0), (1, 2)])}
    for case, (low, high) in saddle.items():
        for centre, segs in ((0, low), (1, high)):
            for k, (a, b) in enumerate(segs):
                TABLE_A[centre, case, k] = a
                TABLE_B[centre, case, k] = b


_fill_tables()


def bbox_mm(region):
    arr = np.concatenate([np.asarray(p, dtype=np.float64).reshape(-1, 2) for p in region]) / rg.S
    return float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 0].max()), float(arr[:, 1].max())


def lines(region, spacing: float, angle_deg: float, offset: float = 0.0) -> list:
    if not region or spacing <= 1e-6:
        return []
    x0, y0, x1, y1 = bbox_mm(region)
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    corners = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    u = corners[:, 0] * ca + corners[:, 1] * sa
    v = -corners[:, 0] * sa + corners[:, 1] * ca
    k0 = math.floor((v.min() - offset) / spacing)
    k1 = math.ceil((v.max() - offset) / spacing)
    vs = offset + np.arange(k0, k1 + 1) * spacing
    if len(vs) > 200_000:
        return []
    ua, ub = u.min() - 1.0, u.max() + 1.0
    p0 = np.stack([ua * ca - vs * sa, ua * sa + vs * ca], axis=1)
    p1 = np.stack([ub * ca - vs * sa, ub * sa + vs * ca], axis=1)
    raw = [[a_, b_] for a_, b_ in zip(rg.ints(p0), rg.ints(p1))]
    return rg.clip_lines(raw, region)


def grid(region, spacing: float, angle_deg: float) -> list:
    return lines(region, spacing * 2.0, angle_deg) + lines(region, spacing * 2.0, angle_deg + 90.0)


def waves(region, period: float, spacing: float, z: float, layer: int) -> list:
    if not region or spacing <= 1e-6:
        return []
    x0, y0, x1, y1 = bbox_mm(region)
    amp = period * 0.18
    out = []
    vertical = (int(z / max(period * 0.5, 1e-6)) % 2) == 1
    phase = 2.0 * math.pi * z / period
    if not vertical:
        ys = np.arange(math.floor(y0 / spacing) * spacing, y1 + spacing, spacing)
        xs = np.arange(x0 - 1.0, x1 + 1.0, period / 10.0)
        for y in ys:
            if len(xs) * len(ys) > 800_000:
                break
            out.append(rg.ints(np.stack([xs, y + amp * np.sin(2.0 * math.pi * xs / period + phase)], axis=1)))
    else:
        xs = np.arange(math.floor(x0 / spacing) * spacing, x1 + spacing, spacing)
        ys = np.arange(y0 - 1.0, y1 + 1.0, period / 10.0)
        for x in xs:
            if len(xs) * len(ys) > 800_000:
                break
            out.append(rg.ints(np.stack([x + amp * np.sin(2.0 * math.pi * ys / period + phase), ys], axis=1)))
    return rg.clip_lines(out, region)


def gyroid_period(width_eff: float, density_pct: float) -> float:
    d = max(density_pct, 1.0) / 100.0
    return max(1.0, 2.43 * width_eff / d)


def gyroid_polylines(bbox, z: float, period: float, cell_factor: int = 12) -> list:
    x0, y0, x1, y1 = bbox
    pad = 0.6
    x0, y0, x1, y1 = x0 - pad, y0 - pad, x1 + pad, y1 + pad
    cell = period / cell_factor
    nx = int(math.ceil((x1 - x0) / cell)) + 1
    ny = int(math.ceil((y1 - y0) / cell)) + 1
    while nx * ny > MAX_CELLS:
        cell *= 1.25
        nx = int(math.ceil((x1 - x0) / cell)) + 1
        ny = int(math.ceil((y1 - y0) / cell)) + 1
    k = 2.0 * math.pi / period
    xs = np.arange(nx) * cell + x0
    ys = np.arange(ny) * cell + y0
    sx, cx = np.sin(k * xs), np.cos(k * xs)
    sy, cy = np.sin(k * ys), np.cos(k * ys)
    sz, cz = math.sin(k * z), math.cos(k * z)
    F = sx[None, :] * cy[:, None] + (sy * cz)[:, None] + sz * cx[None, :]
    pos = F > 0.0
    c0 = pos[:-1, :-1]
    c1 = pos[:-1, 1:]
    c2 = pos[1:, 1:]
    c3 = pos[1:, :-1]
    case = c0.astype(np.int64) + 2 * c1 + 4 * c2 + 8 * c3
    centre = ((F[:-1, :-1] + F[:-1, 1:] + F[1:, 1:] + F[1:, :-1]) > 0).astype(np.int64)
    ci, cj = np.nonzero((case != 0) & (case != 15))
    if not len(ci):
        return []
    cs = case[ci, cj]
    ce = centre[ci, cj]
    hcount = ny * (nx - 1)
    segs_a, segs_b = [], []
    for k_ in (0, 1):
        ea = TABLE_A[ce, cs, k_]
        eb = TABLE_B[ce, cs, k_]
        ok = ea >= 0
        segs_a.append(np.stack([ci[ok], cj[ok], ea[ok]], axis=1))
        segs_b.append(np.stack([ci[ok], cj[ok], eb[ok]], axis=1))
    A = np.concatenate(segs_a)
    B = np.concatenate(segs_b)

    def point(sg):
        i, j, e = sg[:, 0], sg[:, 1], sg[:, 2]
        r1 = np.where(e == 0, i, np.where(e == 2, i + 1, i))
        c1_ = np.where(e == 0, j, np.where(e == 2, j, np.where(e == 3, j, j + 1)))
        r2 = np.where(e == 0, i, np.where(e == 2, i + 1, np.where(e == 3, i + 1, i + 1)))
        c2_ = np.where(e == 0, j + 1, np.where(e == 2, j + 1, np.where(e == 3, j, j + 1)))
        f1 = F[r1, c1_]
        f2 = F[r2, c2_]
        den = f1 - f2
        den = np.where(np.abs(den) < 1e-15, 1e-15, den)
        t = f1 / den
        xx = xs[c1_] + t * (xs[c2_] - xs[c1_])
        yy = ys[r1] + t * (ys[r2] - ys[r1])
        horizontal = (e == 0) | (e == 2)
        row = np.where(e == 2, i + 1, i)
        col = np.where(e == 1, j + 1, j)
        eid = np.where(horizontal, row * (nx - 1) + j, hcount + row * nx + col)
        return eid.astype(np.int64), np.stack([xx, yy], axis=1)

    ida, pa = point(A)
    idb, pb = point(B)
    m = len(ida)
    ids = np.concatenate([ida, idb])
    seg = np.concatenate([np.arange(m), np.arange(m)])
    order = np.argsort(ids, kind="stable")
    ids_s, seg_s = ids[order], seg[order]
    same = ids_s[1:] == ids_s[:-1]
    link = [[] for _ in range(m)]
    for a, b in zip(seg_s[:-1][same].tolist(), seg_s[1:][same].tolist()):
        if a != b:
            link[a].append(b)
            link[b].append(a)
    used = np.zeros(m, dtype=bool)
    polylines = []
    pts_a = pa
    pts_b = pb
    ends_a = ida.tolist()
    ends_b = idb.tolist()

    def walk(start, first_id):
        chain_pts = [pts_a[start] if ends_a[start] == first_id else pts_b[start]]
        cur_id = ends_b[start] if ends_a[start] == first_id else ends_a[start]
        chain_pts.append(pts_a[start] if ends_a[start] == cur_id else pts_b[start])
        used[start] = True
        cur = start
        while True:
            nxt = None
            for s in link[cur]:
                if not used[s] and (ends_a[s] == cur_id or ends_b[s] == cur_id):
                    nxt = s
                    break
            if nxt is None:
                break
            used[nxt] = True
            cur_id = ends_b[nxt] if ends_a[nxt] == cur_id else ends_a[nxt]
            chain_pts.append(pts_a[nxt] if ends_a[nxt] == cur_id else pts_b[nxt])
            cur = nxt
        return chain_pts

    deg = [len(x) for x in link]
    for s in range(m):
        if not used[s] and deg[s] < 2:
            first_id = ends_a[s] if len(link[s]) == 0 or not any(ends_a[o] == ends_a[s] or ends_b[o] == ends_a[s] for o in link[s]) else ends_b[s]
            polylines.append(np.asarray(walk(s, first_id)))
    for s in range(m):
        if not used[s]:
            polylines.append(np.asarray(walk(s, ends_a[s])))
    return polylines


def gyroid(region, z: float, period: float) -> list:
    if not region:
        return []
    box = bbox_mm(region)
    pl = gyroid_polylines(box, z, period)
    paths = [rg.ints(p) for p in pl if len(p) >= 2]
    return rg.clip_lines(paths, region)
