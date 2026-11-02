import math

from app.doc import geom, nurbs

MAX_DEGREE = 25
TOL = 1e-9


def _h(curve):
    out = []
    for i, p in enumerate(curve.ctrl):
        w = curve.weights[i] if curve.weights else 1.0
        z = p[2] if len(p) > 2 else 0.0
        out.append([p[0] * w, p[1] * w, z * w, w])
    return out


def _from_h(h, degree, knots, rational, closed=False):
    ctrl = []
    weights = []
    for q in h:
        w = q[3] if q[3] != 0 else 1.0
        ctrl.append([q[0] / w, q[1] / w, q[2] / w])
        weights.append(q[3])
    uniform = all(abs(w - 1.0) < 1e-12 for w in weights)
    return nurbs.Curve(degree, list(knots), ctrl, [] if (uniform and not rational) else weights, closed)


def multiplicity(knots, u, tol=TOL):
    return sum(1 for k in knots if abs(k - u) <= tol)


def insert_knot(curve, u, times=1):
    p = curve.degree
    U = list(curve.knots)
    P = _h(curve)
    for _ in range(times):
        n = len(P)
        k = nurbs.find_span(n, p, u, U)
        Q = []
        for i in range(n + 1):
            if i <= k - p:
                Q.append(list(P[i]))
            elif i > k:
                Q.append(list(P[i - 1]))
            else:
                den = U[i + p] - U[i]
                a = (u - U[i]) / den if den != 0 else 0.0
                Q.append([a * P[i][j] + (1.0 - a) * P[i - 1][j] for j in range(4)])
        U = U[: k + 1] + [u] + U[k + 1 :]
        P = Q
    return _from_h(P, p, U, bool(curve.weights), curve.closed)


def split_at(curve, u):
    p = curve.degree
    lo, hi = curve.domain()
    if u <= lo + TOL or u >= hi - TOL:
        raise ValueError("The split parameter is at an end of the curve.")
    need = p - multiplicity(curve.knots, u)
    c = insert_knot(curve, u, need) if need > 0 else curve
    U = c.knots
    k = max(i for i, v in enumerate(U) if abs(v - u) <= TOL)
    H = _h(c)
    rational = bool(c.weights)
    left = _from_h(H[: k - p + 1], p, list(U[: k + 1]) + [u], rational)
    right = _from_h(H[k - p :], p, [u] + list(U[k - p + 1 :]), rational)
    return left, right


def sub_curve(curve, u0, u1):
    lo, hi = curve.domain()
    c = curve
    if u1 < hi - TOL:
        c = split_at(c, u1)[0]
    if u0 > lo + TOL:
        c = split_at(c, u0)[1]
    return c


def reverse_curve(curve):
    ks = curve.knots
    top = ks[0] + ks[-1]
    knots = [top - k for k in reversed(ks)]
    return nurbs.Curve(curve.degree, knots, [list(p) for p in reversed(curve.ctrl)], list(reversed(curve.weights)) if curve.weights else [], curve.closed)


def bezier_pieces(curve):
    p = curve.degree
    lo, hi = curve.domain()
    c = curve
    inner = sorted({k for k in curve.knots if lo + TOL < k < hi - TOL})
    for u in inner:
        need = p - multiplicity(c.knots, u)
        if need > 0:
            c = insert_knot(c, u, need)
    H = _h(c)
    pieces = []
    for i in range(0, len(H) - p, p):
        pieces.append(H[i : i + p + 1])
    breaks = [lo] + inner + [hi]
    return pieces, breaks


def _elevate_bezier(pts, t):
    q = len(pts) - 1
    out = [list(pts[0])]
    for i in range(1, q + 1):
        a = i / (q + 1.0)
        out.append([a * pts[i - 1][j] + (1.0 - a) * pts[i][j] for j in range(4)])
    out.append(list(pts[-1]))
    return out


def elevate(curve, times=1):
    if times <= 0:
        return curve
    if curve.degree + times > MAX_DEGREE:
        raise ValueError("Requires an order between %d and %d." % (curve.degree + 2, MAX_DEGREE + 1))
    pieces, breaks = bezier_pieces(curve)
    q = curve.degree + times
    done = []
    for pc in pieces:
        for _ in range(times):
            pc = _elevate_bezier(pc, q)
        done.append(pc)
    ctrl = list(done[0])
    for pc in done[1:]:
        ctrl.extend(pc[1:])
    knots = [breaks[0]] * (q + 1)
    for b in breaks[1:-1]:
        knots.extend([b] * q)
    knots.extend([breaks[-1]] * (q + 1))
    return _from_h(ctrl, q, knots, bool(curve.weights))


def remove_knot_once(curve, u, tol=1e-7):
    p = curve.degree
    U = list(curve.knots)
    r = max(i for i, v in enumerate(U) if abs(v - u) <= TOL)
    s = multiplicity(U, u)
    P = _h(curve)
    first, last = r - p, r - s
    if first < 1 or last + 1 >= len(P):
        return None
    temp = [None] * (last - first + 3)
    temp[0] = list(P[first - 1])
    temp[last - first + 2] = list(P[last + 1])
    i, j = first, last
    ii, jj = 1, last - first + 1
    while j - i > 0:
        ai = (u - U[i]) / (U[i + p + 1] - U[i])
        aj = (u - U[j]) / (U[j + p + 1] - U[j])
        temp[ii] = [(P[i][c] - (1.0 - ai) * temp[ii - 1][c]) / ai for c in range(4)]
        temp[jj] = [(P[j][c] - aj * temp[jj + 1][c]) / (1.0 - aj) for c in range(4)]
        i += 1
        ii += 1
        j -= 1
        jj -= 1
    if j - i < 0:
        gap = math.dist(temp[ii - 1][:3], temp[jj + 1][:3])
    else:
        ai = (u - U[i]) / (U[i + p + 1] - U[i])
        mix = [ai * temp[ii + 1][c] + (1.0 - ai) * temp[ii - 1][c] for c in range(4)]
        gap = math.dist(P[i][:3], mix[:3])
    if gap > tol:
        return None
    i, j = first, last
    ii, jj = 1, last - first + 1
    while j - i > 0:
        P[i] = temp[ii]
        P[j] = temp[jj]
        i += 1
        ii += 1
        j -= 1
        jj -= 1
    P.pop((2 * r - s - p) // 2)
    U.pop(r)
    return _from_h(P, p, U, bool(curve.weights))


def tidy(curve, tol=1e-7):
    out = curve
    lo, hi = curve.domain()
    changed = True
    while changed:
        changed = False
        for u in sorted({k for k in out.knots if lo + TOL < k < hi - TOL}):
            if multiplicity(out.knots, u) >= out.degree:
                continue
            try:
                nxt = remove_knot_once(out, u, tol)
            except (IndexError, ZeroDivisionError):
                nxt = None
            if nxt is not None and nxt.valid():
                out = nxt
                changed = True
                break
    return out


def line_curve(a, b):
    return nurbs.Curve(1, [0.0, 0.0, 1.0, 1.0], [[a[0], a[1], 0.0], [b[0], b[1], 0.0]], [], False)


def arc_curve(center, r, a0, sweep):
    n = max(1, int(math.ceil(abs(sweep) / (math.pi / 2.0) - 1e-9)))
    dt = sweep / n
    w1 = math.cos(dt / 2.0)
    ctrl = []
    weights = []
    for k in range(n):
        t0 = a0 + dt * k
        t1 = t0 + dt
        tm = (t0 + t1) / 2.0
        if k == 0:
            ctrl.append([center[0] + r * math.cos(t0), center[1] + r * math.sin(t0), 0.0])
            weights.append(1.0)
        rm = r / w1
        ctrl.append([center[0] + rm * math.cos(tm), center[1] + rm * math.sin(tm), 0.0])
        weights.append(w1)
        ctrl.append([center[0] + r * math.cos(t1), center[1] + r * math.sin(t1), 0.0])
        weights.append(1.0)
    knots = [0.0] * 3
    for k in range(1, n):
        knots.extend([float(k)] * 2)
    knots.extend([float(n)] * 3)
    return nurbs.Curve(2, knots, ctrl, weights, False)


def polyline_curve(verts, closed=False):
    segs = []
    n = len(verts)
    count = n if closed else n - 1
    for i in range(count):
        a, b = verts[i], verts[(i + 1) % n]
        arc = geom.bulge_to_arc(a["p"], b["p"], a.get("bulge", 0.0) or 0.0)
        if arc is None:
            segs.append(line_curve(a["p"], b["p"]))
        else:
            theta = 4.0 * math.atan(a["bulge"])
            segs.append(arc_curve(arc[0], arc[1], geom.angle_of(arc[0], a["p"]), theta))
    return chain(segs)


def chain(curves):
    deg = max(c.degree for c in curves)
    cs = [elevate(c, deg - c.degree) if c.degree < deg else c for c in curves]
    out = cs[0]
    for c in cs[1:]:
        out = join_curves(out, c)
    return out


def join_curves(a, b):
    p = a.degree
    if b.degree != p:
        raise ValueError("Degrees differ.")
    wa = a.weights[-1] if a.weights else 1.0
    wb = b.weights[0] if b.weights else 1.0
    rational = bool(a.weights or b.weights)
    shift = a.knots[-1] - b.knots[0]
    knots = list(a.knots[:-1]) + [k + shift for k in b.knots[p + 1 :]]
    mid = [(a.ctrl[-1][i] + b.ctrl[0][i]) / 2.0 for i in range(3)]
    ctrl = [list(q) for q in a.ctrl[:-1]] + [mid] + [list(q) for q in b.ctrl[1:]]
    weights = []
    if rational:
        wa_list = list(a.weights) if a.weights else [1.0] * len(a.ctrl)
        wb_list = list(b.weights) if b.weights else [1.0] * len(b.ctrl)
        scale = wa / wb if wb else 1.0
        weights = wa_list[:-1] + [wa] + [w * scale for w in wb_list[1:]]
    return nurbs.Curve(p, knots, ctrl, weights, False)


def ends(curve):
    lo, hi = curve.domain()
    return nurbs.point_at(curve, lo), nurbs.point_at(curve, hi)


def insert_control(curve, u):
    lo, hi = curve.domain()
    if u <= lo + TOL or u >= hi - TOL:
        raise ValueError("The location is at an end of the spline.")
    return insert_knot(curve, u, 1)


def delete_control(curve, index):
    p = curve.degree
    n = len(curve.ctrl)
    if n - 1 < p + 1:
        raise ValueError("The spline needs at least %d control vertices." % (p + 1))
    if index < 0 or index >= n:
        raise ValueError("Invalid vertex.")
    if curve.closed:
        uniq = n - p
        ctrl = [list(q) for i, q in enumerate(curve.ctrl[:uniq]) if i != index]
        weights = [w for i, w in enumerate(curve.weights[:uniq]) if i != index] if curve.weights else None
        if len(ctrl) < 3:
            raise ValueError("The spline needs at least 3 control vertices.")
        return nurbs.from_control_points(ctrl, p, True, weights)
    ctrl = [list(q) for i, q in enumerate(curve.ctrl) if i != index]
    weights = [w for i, w in enumerate(curve.weights) if i != index] if curve.weights else []
    return nurbs.Curve(p, nurbs.clamped_uniform(len(ctrl), p), ctrl, weights, False)


def curvature(curve, u):
    lo, hi = curve.domain()
    h = (hi - lo) * 1e-4
    mid = min(max(u, lo + h), hi - h)
    a, b, c = nurbs.point_at(curve, mid - h), nurbs.point_at(curve, mid), nurbs.point_at(curve, mid + h)
    d1 = [(c[0] - a[0]) / (2.0 * h), (c[1] - a[1]) / (2.0 * h)]
    d2 = [(c[0] - 2 * b[0] + a[0]) / (h * h), (c[1] - 2 * b[1] + a[1]) / (h * h)]
    den = (d1[0] ** 2 + d1[1] ** 2) ** 1.5
    return (d1[0] * d2[1] - d1[1] * d2[0]) / den if den > 1e-18 else 0.0
