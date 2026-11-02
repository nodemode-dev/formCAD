import numpy as np

EPS = 1e-12


def signed_area(ring):
    s = 0.0
    n = len(ring)
    for i in range(n):
        x0, y0 = ring[i]
        x1, y1 = ring[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return s / 2.0


def clean_ring(ring):
    out = []
    for p in ring:
        if not out or abs(p[0] - out[-1][0]) > EPS or abs(p[1] - out[-1][1]) > EPS:
            out.append((float(p[0]), float(p[1])))
    while len(out) > 1 and abs(out[0][0] - out[-1][0]) <= EPS and abs(out[0][1] - out[-1][1]) <= EPS:
        out.pop()
    return out


def inside_ring(pt, ring):
    x, y = pt
    hit = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _in_triangle(p, a, b, c):
    d1 = _cross(a, b, p)
    d2 = _cross(b, c, p)
    d3 = _cross(c, a, p)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _bridge(outer, hole):
    mi = max(range(len(hole)), key=lambda i: (hole[i][0], -hole[i][1]))
    m = hole[mi]
    n = len(outer)
    best_x = None
    best_edge = -1
    for i in range(n):
        a = outer[i]
        b = outer[(i + 1) % n]
        if a[1] == b[1]:
            continue
        if (a[1] <= m[1] <= b[1]) or (b[1] <= m[1] <= a[1]):
            t = (m[1] - a[1]) / (b[1] - a[1])
            x = a[0] + t * (b[0] - a[0])
            if x >= m[0] - EPS and (best_x is None or x < best_x):
                best_x = x
                best_edge = i
    if best_edge < 0:
        pi = min(range(n), key=lambda i: (outer[i][0] - m[0]) ** 2 + (outer[i][1] - m[1]) ** 2)
    else:
        a = outer[best_edge]
        b = outer[(best_edge + 1) % n]
        pi = best_edge if a[0] > b[0] else (best_edge + 1) % n
        if abs(best_x - a[0]) <= EPS and abs(m[1] - a[1]) <= EPS:
            pi = best_edge
        elif abs(best_x - b[0]) <= EPS and abs(m[1] - b[1]) <= EPS:
            pi = (best_edge + 1) % n
        else:
            tri_i = (best_x, m[1])
            p = outer[pi]
            best_key = None
            for k in range(n):
                if k == pi:
                    continue
                q = outer[k]
                prev = outer[k - 1]
                nxt = outer[(k + 1) % n]
                if _cross(prev, q, nxt) >= 0:
                    continue
                if q[0] < m[0]:
                    continue
                if _in_triangle(q, m, tri_i, p):
                    dx = q[0] - m[0]
                    ang = abs(q[1] - m[1]) / dx if dx > EPS else 1e18
                    key = (ang, (q[0] - m[0]) ** 2 + (q[1] - m[1]) ** 2)
                    if best_key is None or key < best_key:
                        best_key = key
                        pi = k
    hole_rot = hole[mi:] + hole[:mi] + [hole[mi]]
    return outer[: pi + 1] + hole_rot + [outer[pi]] + outer[pi + 1:]


def ear_clip(poly):
    n = len(poly)
    if n < 3:
        return []
    prv = [(i - 1) % n for i in range(n)]
    nxt = [(i + 1) % n for i in range(n)]
    reflex = set()
    for i in range(n):
        if _cross(poly[prv[i]], poly[i], poly[nxt[i]]) < 0:
            reflex.add(i)
    out = []
    remaining = n
    cur = 0
    while remaining > 3:
        pick = -1
        emit = True
        probe = cur
        for _ in range(remaining):
            a, c = prv[probe], nxt[probe]
            pa, pb, pc = poly[a], poly[probe], poly[c]
            cr = _cross(pa, pb, pc)
            if abs(cr) <= EPS:
                pick, emit = probe, False
                break
            if cr > 0:
                blocked = False
                for k in reflex:
                    if k == a or k == c or k == probe:
                        continue
                    q = poly[k]
                    if q == pa or q == pb or q == pc:
                        continue
                    if _in_triangle(q, pa, pb, pc):
                        blocked = True
                        break
                if not blocked:
                    pick = probe
                    break
            probe = c
        if pick < 0:
            probe = cur
            best = -1.0
            for _ in range(remaining):
                cr = _cross(poly[prv[probe]], poly[probe], poly[nxt[probe]])
                if cr > best:
                    best, pick = cr, probe
                probe = nxt[probe]
            emit = best > 0
        a, c = prv[pick], nxt[pick]
        if emit:
            out.append((poly[a], poly[pick], poly[c]))
        nxt[a] = c
        prv[c] = a
        reflex.discard(pick)
        remaining -= 1
        for v in (a, c):
            if _cross(poly[prv[v]], poly[v], poly[nxt[v]]) < 0:
                reflex.add(v)
            else:
                reflex.discard(v)
        cur = c
    a = cur
    b, c = nxt[a], nxt[nxt[a]]
    if _cross(poly[a], poly[b], poly[c]) > EPS:
        out.append((poly[a], poly[b], poly[c]))
    return out


def triangulate(contours):
    rings = []
    for raw in contours:
        r = clean_ring(raw)
        if len(r) >= 3 and abs(signed_area(r)) > EPS:
            rings.append(r)
    if not rings:
        return np.zeros((0, 2))
    areas = [signed_area(r) for r in rings]
    lead = max(range(len(rings)), key=lambda i: abs(areas[i]))
    sign = 1.0 if areas[lead] > 0 else -1.0
    outers = []
    holes = []
    for r, a in zip(rings, areas):
        (outers if a * sign > 0 else holes).append((r, abs(a)))
    groups = [(o[0] if signed_area(o[0]) > 0 else o[0][::-1], []) for o in outers]
    order = sorted(range(len(outers)), key=lambda i: outers[i][1])
    for h, _a in holes:
        probe = max(h, key=lambda p: (p[0], p[1]))
        owner = None
        for i in order:
            if inside_ring(probe, outers[i][0]):
                owner = i
                break
        ring = h if signed_area(h) < 0 else h[::-1]
        if owner is None:
            groups.append((ring[::-1], []))
        else:
            groups[owner][1].append(ring)
    tris = []
    for outer, hs in groups:
        poly = list(outer)
        for h in sorted(hs, key=lambda r: -max(p[0] for p in r)):
            poly = _bridge(poly, h)
        tris.extend(ear_clip(poly))
    if not tris:
        return np.zeros((0, 2))
    return np.array([p for t in tris for p in t], dtype=float)
