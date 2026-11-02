import math

import numpy as np

from app.doc import planar as P

STEPS = 64
MAX_FAMILIES = 1024
MAX_RUNS = 1_000_000
DISPLAY_RUNS = 150_000
MAX_LINES_PER_FAMILY = 20000
MAX_DASH_STEPS = 50_000_000
MAX_GRADIENT_TRIANGLES = 200_000
DOT_FRACTION = 0.1
ORIGIN_MODES = ("current", "bottom left", "bottom right", "top right", "top left", "center")
GRADIENT_NAMES = ("LINEAR", "CYLINDER", "CURVED", "SPHERICAL", "HEMISPHERICAL", "INVLINEAR", "INVCYLINDER", "INVCURVED", "INVSPHERICAL", "INVHEMISPHERICAL")


def rings_of(loops, step=0.05):
    out = []
    for loop in loops:
        verts = loop.get("vertices", [])
        if len(verts) >= 2:
            ring = P.flatten_loop(verts, step)
            if len(ring) >= 3:
                out.append(ring)
    return out


def bbox_of(rings):
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def resolve_origin(origin, mode, rings):
    box = bbox_of(rings)
    if mode in (None, "current", 0) or box is None:
        return [float(origin[0]), float(origin[1])]
    if isinstance(mode, int):
        mode = ORIGIN_MODES[mode] if 0 <= mode < len(ORIGIN_MODES) else "current"
    x0, y0, x1, y1 = box
    table = {"bottom left": (x0, y0), "bottom right": (x1, y0), "top right": (x1, y1), "top left": (x0, y1), "center": ((x0 + x1) / 2.0, (y0 + y1) / 2.0)}
    p = table.get(mode)
    return [p[0], p[1]] if p else [float(origin[0]), float(origin[1])]


def slabs(rings, extra=(), swap=False):
    edges = []
    levels = set(extra)
    for ring in rings:
        n = len(ring)
        for i in range(n):
            a = ring[i]
            b = ring[(i + 1) % n]
            if swap:
                ax, ay, bx, by = a[1], a[0], b[1], b[0]
            else:
                ax, ay, bx, by = a[0], a[1], b[0], b[1]
            levels.add(ay)
            if ay == by:
                continue
            if ay > by:
                ax, ay, bx, by = bx, by, ax, ay
            edges.append((ay, by, ax, (bx - ax) / (by - ay)))
    ys = sorted(levels)
    edges.sort()
    out = []
    active = []
    k = 0
    ne = len(edges)
    for i in range(len(ys) - 1):
        ya, yb = ys[i], ys[i + 1]
        if yb - ya <= 0.0:
            continue
        while k < ne and edges[k][0] <= ya:
            active.append(edges[k])
            k += 1
        active = [e for e in active if e[1] > ya]
        if len(active) < 2:
            continue
        _cut(active, ya, yb, out, 0)
    return out


def _x_at(e, y):
    return e[2] + (y - e[0]) * e[3]


def _cut(active, ya, yb, out, depth):
    xs = sorted(((_x_at(e, ya), _x_at(e, yb), e) for e in active), key=lambda t: (t[0], t[1]))
    crossing = []
    for i in range(len(xs) - 1):
        a, b = xs[i], xs[i + 1]
        if a[1] > b[1] + 1e-12 * (1.0 + abs(a[1])):
            ea, eb = a[2], b[2]
            den = ea[3] - eb[3]
            if abs(den) > 1e-300:
                y = (eb[2] - eb[0] * eb[3] - (ea[2] - ea[0] * ea[3])) / den
                if ya < y < yb:
                    crossing.append(y)
    if crossing and depth < 24:
        cuts = [ya] + sorted(set(crossing)) + [yb]
        for i in range(len(cuts) - 1):
            if cuts[i + 1] - cuts[i] > 0.0:
                _cut(active, cuts[i], cuts[i + 1], out, depth + 1)
        return
    for i in range(0, len(xs) - 1, 2):
        l, r = xs[i], xs[i + 1]
        if r[0] - l[0] <= 0.0 and r[1] - l[1] <= 0.0:
            continue
        out.append((ya, yb, l[0], r[0], l[1], r[1]))


def trapezoid_triangles(traps, swap=False):
    out = []
    for ya, yb, la, ra, lb, rb in traps:
        if swap:
            out.extend((ya, la, ya, ra, yb, rb, ya, la, yb, rb, yb, lb))
        else:
            out.extend((la, ya, ra, ya, rb, yb, la, ya, rb, yb, lb, yb))
    return out


def fill_triangles(rings):
    return trapezoid_triangles(slabs(rings))


def lerp_color(c1, c2, t):
    return [int(round(c1[i] + (c2[i] - c1[i]) * t)) for i in range(3)]


def tinted(c1, tint):
    t = max(-1.0, min(1.0, tint))
    if t >= 0:
        return lerp_color(c1, (255, 255, 255), t)
    return lerp_color(c1, (0, 0, 0), -t)


def profile(name, s, centered):
    base = name[3:] if name.startswith("INV") else name
    if base == "LINEAR":
        t = s
    elif base == "CURVED":
        t = math.sin(s * math.pi / 2.0)
    else:
        f = 0.5 if centered else 0.3
        k = math.log(0.5) / math.log(f)
        w = max(0.0, min(1.0, s)) ** k
        t = math.sin(w * math.pi)
    return 1.0 - t if name.startswith("INV") else t


def step_index(t):
    return max(0, min(STEPS - 1, int(t * STEPS)))


def gradient_groups(rings, name, angle, centered):
    name = name.upper()
    base = name[3:] if name.startswith("INV") else name
    inv = name.startswith("INV")
    box = bbox_of(rings)
    if box is None:
        return {}
    mx, my = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    ca, sa = math.cos(angle), math.sin(angle)
    rot = [[((p[0] - mx) * ca + (p[1] - my) * sa, -(p[0] - mx) * sa + (p[1] - my) * ca) for p in r] for r in rings]
    xs = [p[0] for r in rot for p in r]
    ys = [p[1] for r in rot for p in r]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    groups = {}

    def back(x, y):
        return (mx + x * ca - y * sa, my + x * sa + y * ca)

    if base in ("LINEAR", "CYLINDER", "CURVED"):
        n = STEPS if base == "LINEAR" else 128
        lw = x1 - x0
        if lw <= 0:
            return {}
        levels = [x0 + lw * i / n for i in range(n + 1)]
        traps = slabs(rot, levels, swap=True)
        for tr in traps:
            xa, xb = tr[0], tr[1]
            s = ((xa + xb) / 2.0 - x0) / lw
            idx = step_index(profile(name, s, centered))
            tri = trapezoid_triangles([tr], swap=True)
            pts = groups.setdefault(idx, [])
            for i in range(0, len(tri), 2):
                bx, by = back(tri[i], tri[i + 1])
                pts.extend((bx, by))
        return groups
    if base == "SPHERICAL":
        cx = (x0 + x1) / 2.0 - (0.0 if centered else 0.25 * (x1 - x0))
        cy = (y0 + y1) / 2.0 + (0.0 if centered else 0.25 * (y1 - y0))
    else:
        cx = (x0 + x1) / 2.0 - (0.0 if centered else 0.25 * (x1 - x0))
        cy = y0
    radius = max(math.hypot(px - cx, py - cy) for px in (x0, x1) for py in (y0, y1)) or 1.0
    tris = trapezoid_triangles(slabs(rot))
    limit = max(x1 - x0, y1 - y0) / STEPS
    stack = [tuple(tris[i:i + 6]) for i in range(0, len(tris), 6)]
    total = 0
    while stack:
        t = stack.pop()
        ax, ay, bx, by, cx2, cy2 = t
        edges = ((ax, ay, bx, by, 2), (bx, by, cx2, cy2, 0), (cx2, cy2, ax, ay, 1))
        longest = max(edges, key=lambda e: math.hypot(e[2] - e[0], e[3] - e[1]))
        ln = math.hypot(longest[2] - longest[0], longest[3] - longest[1])
        if ln > limit and total < MAX_GRADIENT_TRIANGLES:
            mxp, myp = (longest[0] + longest[2]) / 2.0, (longest[1] + longest[3]) / 2.0
            k = longest[4]
            if k == 2:
                stack.append((ax, ay, mxp, myp, cx2, cy2))
                stack.append((mxp, myp, bx, by, cx2, cy2))
            elif k == 0:
                stack.append((ax, ay, bx, by, mxp, myp))
                stack.append((ax, ay, mxp, myp, cx2, cy2))
            else:
                stack.append((ax, ay, bx, by, mxp, myp))
                stack.append((mxp, myp, bx, by, cx2, cy2))
            total += 1
            continue
        gx, gy = (ax + bx + cx2) / 3.0, (ay + by + cy2) / 3.0
        r = min(1.0, math.hypot(gx - cx, gy - cy) / radius)
        t0 = math.cos(r * math.pi / 2.0)
        idx = step_index(1.0 - t0 if inv else t0)
        pts = groups.setdefault(idx, [])
        for px, py in ((ax, ay), (bx, by), (cx2, cy2)):
            pts.extend(back(px, py))
    return groups


def pattern_segments(rings, fams, scale, rot, origin, unit=1.0, max_runs=MAX_RUNS, max_lines=MAX_LINES_PER_FAMILY):
    if not rings or scale <= 0:
        return np.zeros((0, 4)), False
    ex0, ey0, ex1, ey1 = [], [], [], []
    for ring in rings:
        arr = np.asarray(ring, dtype=float)
        nxt = np.roll(arr, -1, axis=0)
        ex0.append(arr[:, 0])
        ey0.append(arr[:, 1])
        ex1.append(nxt[:, 0])
        ey1.append(nxt[:, 1])
    X0, Y0, X1, Y1 = (np.concatenate(v) for v in (ex0, ey0, ex1, ey1))
    pieces = []
    runs = 0
    dense = False
    steps_left = MAX_DASH_STEPS
    cr, sr = math.cos(rot), math.sin(rot)
    k = scale * unit
    for f in fams[:MAX_FAMILIES]:
        phi = math.radians(f["angle"]) + rot
        ux, uy = math.cos(phi), math.sin(phi)
        nx, ny = -uy, ux
        fox, foy = f["origin"][0] * k, f["origin"][1] * k
        ox = origin[0] + fox * cr - foy * sr
        oy = origin[1] + fox * sr + foy * cr
        dxs, dys = f["offset"][0] * k, f["offset"][1] * k
        sn = abs(dys)
        if sn < 1e-12:
            continue
        sgn = 1.0 if dys > 0 else -1.0
        sj = sgn * dxs
        a0 = (X0 - ox) * ux + (Y0 - oy) * uy
        b0 = (X0 - ox) * nx + (Y0 - oy) * ny
        a1 = (X1 - ox) * ux + (Y1 - oy) * uy
        b1 = (X1 - ox) * nx + (Y1 - oy) * ny
        lo = np.minimum(b0, b1)
        hi = np.maximum(b0, b1)
        first = np.ceil(lo / sn)
        last = np.ceil(hi / sn)
        counts = np.maximum(last - first, 0).astype(np.int64)
        counts[b0 == b1] = 0
        total = int(counts.sum())
        if total == 0:
            continue
        nlines = int(np.ceil(hi.max() / sn) - np.ceil(lo.min() / sn))
        if nlines > max_lines:
            dense = True
            break
        eidx = np.repeat(np.arange(len(counts)), counts)
        offs = np.concatenate(([0], np.cumsum(counts)[:-1]))
        j = first[eidx] + (np.arange(total) - offs[eidx])
        bb0, bb1 = b0[eidx], b1[eidx]
        t = (j * sn - bb0) / (bb1 - bb0)
        ac = a0[eidx] + t * (a1[eidx] - a0[eidx])
        order = np.lexsort((ac, j))
        j = j[order]
        ac = ac[order]
        if len(j) % 2:
            j = j[:-1]
            ac = ac[:-1]
        sa_ = ac[0::2]
        sb_ = ac[1::2]
        sjj = j[0::2]
        shift = sjj * sj
        dashes = f.get("dashes") or []
        if not dashes or sum(abs(d) for d in dashes) * k < 1e-12:
            seg_j, seg_a, seg_b = sjj, sa_, sb_
        else:
            ds = [d * k for d in dashes]
            period = sum(abs(d) for d in ds)
            p0 = sa_ - shift
            p1 = sb_ - shift
            c0 = np.floor(p0 / period)
            c1 = np.floor(p1 / period)
            ncell = (c1 - c0 + 1).astype(np.int64)
            cells = int(ncell.sum())
            steps_left -= cells * len(ds)
            if steps_left < 0 or cells > max_runs * 4:
                dense = True
                break
            sidx = np.repeat(np.arange(len(ncell)), ncell)
            cstart = np.concatenate(([0], np.cumsum(ncell)[:-1]))
            cell = c0[sidx] + (np.arange(cells) - cstart[sidx])
            pp0, pp1 = p0[sidx], p1[sidx]
            pos = 0.0
            outj, outa, outb = [], [], []
            dot = DOT_FRACTION * min(sn, period)
            for d in ds:
                ln = abs(d)
                if d >= 0:
                    st = cell * period + pos
                    en = st + (ln if d > 0 else dot)
                    if d == 0:
                        st = st - dot / 2.0
                        en = st + dot
                    a = np.maximum(st, pp0)
                    b = np.minimum(en, pp1)
                    keep = b > a
                    if keep.any():
                        outj.append(sjj[sidx][keep])
                        outa.append(a[keep] + shift[sidx][keep])
                        outb.append(b[keep] + shift[sidx][keep])
                pos += ln
            if not outj:
                continue
            seg_j = np.concatenate(outj)
            seg_a = np.concatenate(outa)
            seg_b = np.concatenate(outb)
        runs += len(seg_j)
        if runs > max_runs:
            dense = True
            break
        bn = seg_j * sn
        pieces.append(np.stack((ox + seg_a * ux + bn * nx, oy + seg_a * uy + bn * ny, ox + seg_b * ux + bn * nx, oy + seg_b * uy + bn * ny), axis=1))
    if dense:
        return np.zeros((0, 4)), True
    if not pieces:
        return np.zeros((0, 4)), False
    return np.concatenate(pieces, axis=0), False
