import math

SAGITTA = 0.002
MAX_ARC_STEPS = 4096


def arc_steps(r, sweep, min_steps=2):
    r = abs(r)
    if r < 1e-12 or sweep <= 0:
        return min_steps
    step = 2.0 * math.acos(max(-1.0, 1.0 - SAGITTA))
    return max(min_steps, min(MAX_ARC_STEPS, int(math.ceil(sweep / step))))


def arc_pts(cx, cy, r, a0, sweep, n=None):
    n = n or arc_steps(r, abs(sweep))
    return [(cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n)) for i in range(n + 1)]


def ccw(a0, a1):
    s = (a1 - a0) % (2.0 * math.pi)
    return s


def bulge_pts(p0, p1, bulge):
    if abs(bulge) < 1e-12:
        return [(p0[0], p0[1]), (p1[0], p1[1])]
    chord = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if chord < 1e-12:
        return [(p0[0], p0[1])]
    theta = 4.0 * math.atan(bulge)
    r = chord / (2.0 * math.sin(abs(theta) / 2.0))
    mx, my = (p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0
    ux, uy = (p1[0] - p0[0]) / chord, (p1[1] - p0[1]) / chord
    off = r * math.cos(theta / 2.0)
    side = 1.0 if bulge > 0 else -1.0
    cx, cy = mx - uy * off * side, my + ux * off * side
    a0 = math.atan2(p0[1] - cy, p0[0] - cx)
    n = arc_steps(r, abs(theta))
    out = []
    for i in range(n + 1):
        a = a0 + theta * i / n
        out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    out[0] = (p0[0], p0[1])
    out[-1] = (p1[0], p1[1])
    return out


def poly_pts(verts, closed):
    out = []
    n = len(verts)
    count = n if closed else n - 1
    for i in range(max(count, 0)):
        a = verts[i]
        b = verts[(i + 1) % n]
        seg = bulge_pts(a, b, a[2] if len(a) > 2 else 0.0)
        out.extend(seg if not out else seg[1:])
    if not out and verts:
        out.append((verts[0][0], verts[0][1]))
    if closed and len(out) > 1 and abs(out[0][0] - out[-1][0]) < 1e-12 and abs(out[0][1] - out[-1][1]) < 1e-12:
        out.pop()
    return out


def flat_xy(points):
    out = []
    for p in points:
        out.append(p[0])
        out.append(p[1])
    return out


def ellipse_pts(c, major, ratio, a0, a1, n=None):
    sweep = a1 - a0
    if sweep <= 0:
        sweep += 2.0 * math.pi
    ux, uy = major[0], major[1]
    vx, vy = -uy * ratio, ux * ratio
    a = math.hypot(ux, uy)
    n = n or max(8, arc_steps(a, sweep))
    out = []
    for i in range(n + 1):
        t = a0 + sweep * i / n
        out.append((c[0] + ux * math.cos(t) + vx * math.sin(t), c[1] + uy * math.cos(t) + vy * math.sin(t)))
    return out


def point_in_ring(x, y, ring):
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


def hatch_lines(rings, angle, spacing, limit=20000):
    if not rings or spacing <= 1e-12:
        return []
    ca, sa = math.cos(angle), math.sin(angle)
    rot = [[(x * ca + y * sa, -x * sa + y * ca) for x, y in r] for r in rings]
    ys = [p[1] for r in rot for p in r]
    lo, hi = min(ys), max(ys)
    count = int((hi - lo) / spacing) + 1
    if count > limit:
        return []
    out = []
    k0 = math.floor(lo / spacing) + 1
    y = k0 * spacing
    while y < hi:
        xs = []
        for r in rot:
            n = len(r)
            for i in range(n):
                a = r[i]
                b = r[(i + 1) % n]
                if (a[1] <= y < b[1]) or (b[1] <= y < a[1]):
                    xs.append(a[0] + (y - a[1]) / (b[1] - a[1]) * (b[0] - a[0]))
        xs.sort()
        for i in range(0, len(xs) - 1, 2):
            x0, x1 = xs[i], xs[i + 1]
            if x1 - x0 > 1e-12:
                out.append([x0 * ca - y * sa, x0 * sa + y * ca, x1 * ca - y * sa, x1 * sa + y * ca])
        y += spacing
    return out
