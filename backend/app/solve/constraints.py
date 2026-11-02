import math

import numpy as np

from .errors import SolverFault

TAU = 2.0 * math.pi

GEOMETRIC = (
    "coincident", "collinear", "concentric", "fix", "parallel", "perpendicular",
    "horizontal", "vertical", "tangent", "smooth", "symmetric", "equal",
)
DIMENSIONAL = ("distance", "hdistance", "vdistance", "angle", "radius", "diameter")
PREFIX = {"distance": "d", "hdistance": "d", "vdistance": "d", "angle": "ang", "radius": "rad", "diameter": "dia"}


def split_ref(sk, ref):
    if isinstance(ref, (tuple, list)):
        eid, part = ref[0], str(ref[1])
    else:
        eid, part = ref, "whole"
    ent = sk.ents.get(eid)
    if ent is None:
        raise SolverFault("unknown entity %s" % (eid,))
    return ent, part


def pointlike(ent, part):
    return ent.kind == "point" or part != "whole"


def point_fn(ent, part):
    o = ent.off
    k = ent.kind
    if k == "point" and part in ("whole", "point"):
        return (lambda x: (x[o], x[o + 1])), [o, o + 1]
    if k == "line":
        if part == "start":
            return (lambda x: (x[o], x[o + 1])), [o, o + 1]
        if part == "end":
            return (lambda x: (x[o + 2], x[o + 3])), [o + 2, o + 3]
        if part == "mid":
            return (lambda x: (0.5 * (x[o] + x[o + 2]), 0.5 * (x[o + 1] + x[o + 3]))), [o, o + 1, o + 2, o + 3]
    if k in ("circle", "arc", "ellipse") and part == "center":
        return (lambda x: (x[o], x[o + 1])), [o, o + 1]
    if k == "arc":
        if part == "start":
            return (lambda x: (x[o] + x[o + 2] * math.cos(x[o + 3]), x[o + 1] + x[o + 2] * math.sin(x[o + 3]))), [o, o + 1, o + 2, o + 3]
        if part == "end":
            return (lambda x: (x[o] + x[o + 2] * math.cos(x[o + 4]), x[o + 1] + x[o + 2] * math.sin(x[o + 4]))), [o, o + 1, o + 2, o + 4]
        if part == "mid":
            def mid(x):
                a = x[o + 3] + 0.5 * ((x[o + 4] - x[o + 3]) % TAU)
                return x[o] + x[o + 2] * math.cos(a), x[o + 1] + x[o + 2] * math.sin(a)
            return mid, [o, o + 1, o + 2, o + 3, o + 4]
    if k == "ellipse":
        if part == "major":
            return (lambda x: (x[o] + x[o + 2], x[o + 1] + x[o + 3])), [o, o + 1, o + 2, o + 3]
        if ent.n == 7 and part in ("start", "end"):
            t = 5 if part == "start" else 6

            def ep(x):
                c = math.cos(x[o + t])
                s = math.sin(x[o + t]) * x[o + 4]
                return x[o] + c * x[o + 2] - s * x[o + 3], x[o + 1] + c * x[o + 3] + s * x[o + 2]
            return ep, [o, o + 1, o + 2, o + 3, o + 4, o + t]
    raise SolverFault("%s has no reference '%s'" % (ent.kind, part))


def line_fn(ent):
    o = ent.off
    return (lambda x: (x[o], x[o + 1], x[o + 2], x[o + 3])), [o, o + 1, o + 2, o + 3]


def _dir(x, o):
    dx = x[o + 2] - x[o]
    dy = x[o + 3] - x[o + 1]
    L = math.hypot(dx, dy)
    if L < 1e-12:
        L = 1e-12
    return dx, dy, L


def signed_line_dist(x, o, px, py):
    dx, dy, L = _dir(x, o)
    return (dx * (py - x[o + 1]) - dy * (px - x[o])) / L


def on_curve(ent):
    o = ent.off
    k = ent.kind
    if k == "line":
        return (lambda x, px, py: signed_line_dist(x, o, px, py)), [o, o + 1, o + 2, o + 3]
    if k in ("circle", "arc"):
        return (lambda x, px, py: math.hypot(px - x[o], py - x[o + 1]) - x[o + 2]), [o, o + 1, o + 2]

    if k == "ellipse":
        def ell(x, px, py):
            a = math.hypot(x[o + 2], x[o + 3])
            a = max(a, 1e-12)
            b = max(a * x[o + 4], 1e-12)
            e1x, e1y = x[o + 2] / a, x[o + 3] / a
            u = (px - x[o]) * e1x + (py - x[o + 1]) * e1y
            v = -(px - x[o]) * e1y + (py - x[o + 1]) * e1x
            return (math.sqrt((u / a) ** 2 + (v / b) ** 2) - 1.0) * a
        return ell, [o, o + 1, o + 2, o + 3, o + 4]
    raise SolverFault("cannot place a point on %s" % k)


def _sign(v):
    return -1.0 if v < 0 else 1.0


def _wrap(a):
    return math.atan2(math.sin(a), math.cos(a))


def _need(refs, n, kind):
    if len(refs) != n:
        raise SolverFault("%s expects %d reference(s)" % (kind, n))


def _kind_of(ent, part):
    return "point" if pointlike(ent, part) else ent.kind


def _expand_line(sk, refs):
    if len(refs) == 1:
        ent, part = split_ref(sk, refs[0])
        if ent.kind == "line" and part == "whole":
            return [(ent.id, "start"), (ent.id, "end")]
    return refs


def build(sk, kind, refs, value, ctx):
    x0 = sk.xarray()
    ents = []
    vars_ = []

    def touch(ent, idx):
        if ent.id not in ents:
            ents.append(ent.id)
        vars_.extend(idx)

    def pt(ref):
        ent, part = split_ref(sk, ref)
        if not pointlike(ent, part):
            raise SolverFault("%s needs a point reference" % kind)
        f, idx = point_fn(ent, part)
        touch(ent, idx)
        return f

    def lin(ref):
        ent, part = split_ref(sk, ref)
        if ent.kind != "line" or part != "whole":
            raise SolverFault("%s needs a line" % kind)
        f, idx = line_fn(ent)
        touch(ent, idx)
        return ent.off

    def crv(ref):
        ent, part = split_ref(sk, ref)
        if ent.kind not in ("circle", "arc", "ellipse") or part != "whole":
            raise SolverFault("%s needs a circle, arc or ellipse" % kind)
        touch(ent, [ent.off, ent.off + 1])
        return ent

    if kind in DIMENSIONAL and value is None:
        raise SolverFault("%s needs a value" % kind)

    if kind == "coincident":
        _need(refs, 2, kind)
        ea, pa = split_ref(sk, refs[0])
        eb, pb = split_ref(sk, refs[1])
        if pointlike(ea, pa) and pointlike(eb, pb):
            fa, fb = pt(refs[0]), pt(refs[1])
            fn = lambda x: np.array([fb(x)[0] - fa(x)[0], fb(x)[1] - fa(x)[1]])
            rows = 2
        elif pointlike(ea, pa) or pointlike(eb, pb):
            pref, cref = (refs[0], refs[1]) if pointlike(ea, pa) else (refs[1], refs[0])
            fp = pt(pref)
            cent, cpart = split_ref(sk, cref)
            if cpart != "whole":
                raise SolverFault("coincident needs a point and a curve")
            fc, idx = on_curve(cent)
            touch(cent, idx)
            fn = lambda x: np.array([fc(x, *fp(x))])
            rows = 1
        else:
            raise SolverFault("coincident needs at least one point")
    elif kind == "collinear":
        _need(refs, 2, kind)
        a, b = lin(refs[0]), lin(refs[1])

        def fn(x):
            d1x, d1y, L1 = _dir(x, a)
            d2x, d2y, L2 = _dir(x, b)
            return np.array([(d1x * d2y - d1y * d2x) / (L1 * L2), signed_line_dist(x, a, x[b], x[b + 1])])
        rows = 2
    elif kind == "concentric":
        _need(refs, 2, kind)
        a, b = crv(refs[0]).off, crv(refs[1]).off
        fn = lambda x: np.array([x[b] - x[a], x[b + 1] - x[a + 1]])
        rows = 2
    elif kind == "fix":
        _need(refs, 1, kind)
        ent, part = split_ref(sk, refs[0])
        if pointlike(ent, part):
            f = pt(refs[0])
            px, py = f(x0)
            fn = lambda x: np.array([f(x)[0] - px, f(x)[1] - py])
            rows = 2
        else:
            idx = list(range(ent.off, ent.off + ent.n))
            touch(ent, idx)
            base = x0[idx].copy()
            fn = lambda x: x[idx] - base
            rows = len(idx)
    elif kind in ("parallel", "perpendicular"):
        _need(refs, 2, kind)
        a, b = lin(refs[0]), lin(refs[1])
        if kind == "parallel":
            def fn(x):
                d1x, d1y, L1 = _dir(x, a)
                d2x, d2y, L2 = _dir(x, b)
                return np.array([(d1x * d2y - d1y * d2x) / (L1 * L2)])
        else:
            def fn(x):
                d1x, d1y, L1 = _dir(x, a)
                d2x, d2y, L2 = _dir(x, b)
                return np.array([(d1x * d2x + d1y * d2y) / (L1 * L2)])
        rows = 1
    elif kind in ("horizontal", "vertical"):
        ax = 1 if kind == "horizontal" else 0
        if len(refs) == 1:
            ent, part = split_ref(sk, refs[0])
            if ent.kind == "line" and part == "whole":
                o = lin(refs[0])
                fn = lambda x: np.array([x[o + 2 + ax] - x[o + ax]])
            elif ent.kind == "ellipse" and part == "whole":
                touch(ent, [ent.off + 2, ent.off + 3])
                o = ent.off
                fn = lambda x: np.array([x[o + 2 + ax]])
            else:
                raise SolverFault("%s needs a line, an ellipse or two points" % kind)
        else:
            _need(refs, 2, kind)
            fa, fb = pt(refs[0]), pt(refs[1])
            fn = lambda x: np.array([fb(x)[ax] - fa(x)[ax]])
        rows = 1
    elif kind in ("tangent", "smooth"):
        _need(refs, 2, kind)
        ea, _ = split_ref(sk, refs[0])
        eb, _ = split_ref(sk, refs[1])
        if eb.kind == "line" and ea.kind != "line":
            ea, eb = eb, ea
        if ea.kind == "line" and eb.kind in ("circle", "arc"):
            lo = lin((ea.id, "whole"))
            ce = crv((eb.id, "whole"))
            c = ce.off
            touch(ce, [c + 2])
            if "s" not in ctx:
                ctx["s"] = _sign(signed_line_dist(x0, lo, x0[c], x0[c + 1]))
            s = ctx["s"]
            fn = lambda x: np.array([signed_line_dist(x, lo, x[c], x[c + 1]) - s * x[c + 2]])
        elif ea.kind == "line" and eb.kind == "ellipse":
            lo = lin((ea.id, "whole"))
            ee = crv((eb.id, "whole"))
            c = ee.off
            touch(ee, [c + 2, c + 3, c + 4])

            def support(x):
                dx, dy, L = _dir(x, lo)
                nx, ny = -dy / L, dx / L
                a = math.hypot(x[c + 2], x[c + 3])
                a = max(a, 1e-12)
                mn = nx * x[c + 2] + ny * x[c + 3]
                mp = (-nx * x[c + 3] + ny * x[c + 2]) / a
                return math.sqrt(mn * mn + (a * x[c + 4] * mp) ** 2)
            if "s" not in ctx:
                ctx["s"] = _sign(signed_line_dist(x0, lo, x0[c], x0[c + 1]))
            s = ctx["s"]
            fn = lambda x: np.array([signed_line_dist(x, lo, x[c], x[c + 1]) - s * support(x)])
        elif ea.kind in ("circle", "arc") and eb.kind in ("circle", "arc"):
            ca, cb = crv((ea.id, "whole")).off, crv((eb.id, "whole")).off
            touch(ea, [ca + 2])
            touch(eb, [cb + 2])
            if "mode" not in ctx:
                d = math.hypot(x0[cb] - x0[ca], x0[cb + 1] - x0[ca + 1])
                r1, r2 = x0[ca + 2], x0[cb + 2]
                if abs(d - (r1 + r2)) <= abs(d - abs(r1 - r2)):
                    ctx["mode"] = 0.0
                else:
                    ctx["mode"] = _sign(r1 - r2)
            mode = ctx["mode"]
            if mode == 0.0:
                fn = lambda x: np.array([math.hypot(x[cb] - x[ca], x[cb + 1] - x[ca + 1]) - (x[ca + 2] + x[cb + 2])])
            else:
                fn = lambda x: np.array([math.hypot(x[cb] - x[ca], x[cb + 1] - x[ca + 1]) - mode * (x[ca + 2] - x[cb + 2])])
        else:
            raise SolverFault("tangent is defined for line with circle, arc or ellipse, and for circle or arc pairs")
        rows = 1
    elif kind == "symmetric":
        _need(refs, 3, kind)
        axis = lin(refs[2])
        ea, pa = split_ref(sk, refs[0])
        eb, pb = split_ref(sk, refs[1])

        def mirror_rows(fa, fb):
            def r(x):
                ax_, ay_ = fa(x)
                bx_, by_ = fb(x)
                dx, dy, L = _dir(x, axis)
                return [((bx_ - ax_) * dx + (by_ - ay_) * dy) / L,
                        signed_line_dist(x, axis, 0.5 * (ax_ + bx_), 0.5 * (ay_ + by_))]
            return r

        if pointlike(ea, pa) and pointlike(eb, pb):
            r0 = mirror_rows(pt(refs[0]), pt(refs[1]))
            fn = lambda x: np.array(r0(x))
            rows = 2
        elif ea.kind in ("circle", "arc") and eb.kind in ("circle", "arc"):
            ca, cb = crv(refs[0]), crv(refs[1])
            touch(ca, [ca.off + 2])
            touch(cb, [cb.off + 2])
            r0 = mirror_rows(lambda x: (x[ca.off], x[ca.off + 1]), lambda x: (x[cb.off], x[cb.off + 1]))
            fn = lambda x: np.array(r0(x) + [x[ca.off + 2] - x[cb.off + 2]])
            rows = 3
        elif ea.kind == "line" and eb.kind == "line":
            la, lb = lin(refs[0]), lin(refs[1])
            if "swap" not in ctx:
                dx, dy, L = _dir(x0, axis)
                sd0 = signed_line_dist(x0, axis, x0[lb], x0[lb + 1])
                mx_ = x0[lb] - 2 * sd0 * (-dy / L)
                my_ = x0[lb + 1] - 2 * sd0 * (dx / L)
                near = math.hypot(mx_ - x0[la], my_ - x0[la + 1])
                far = math.hypot(mx_ - x0[la + 2], my_ - x0[la + 3])
                ctx["swap"] = 1.0 if far < near else 0.0
            sw = ctx["swap"]
            ia, ib = (0, 2) if sw else (0, 0)
            ja, jb = (2, 0) if sw else (2, 2)
            r1 = mirror_rows(lambda x: (x[la + ia], x[la + ia + 1]), lambda x: (x[lb + ib], x[lb + ib + 1]))
            r2 = mirror_rows(lambda x: (x[la + ja], x[la + ja + 1]), lambda x: (x[lb + jb], x[lb + jb + 1]))
            fn = lambda x: np.array(r1(x) + r2(x))
            rows = 4
        else:
            raise SolverFault("symmetric needs two points, two lines or two circles, and an axis line")
    elif kind == "equal":
        _need(refs, 2, kind)
        ea, _ = split_ref(sk, refs[0])
        eb, _ = split_ref(sk, refs[1])
        if ea.kind == "line" and eb.kind == "line":
            a, b = lin(refs[0]), lin(refs[1])
            fn = lambda x: np.array([_dir(x, a)[2] - _dir(x, b)[2]])
        elif ea.kind in ("circle", "arc") and eb.kind in ("circle", "arc"):
            a, b = crv(refs[0]), crv(refs[1])
            touch(a, [a.off + 2])
            touch(b, [b.off + 2])
            oa, ob = a.off, b.off
            fn = lambda x: np.array([x[oa + 2] - x[ob + 2]])
        else:
            raise SolverFault("equal needs two lines or two circles or arcs")
        rows = 1
    elif kind in ("distance", "hdistance", "vdistance"):
        v = float(value)
        if v < 0:
            raise SolverFault("a distance cannot be negative")
        refs = _expand_line(sk, refs)
        _need(refs, 2, kind)
        ea, pa = split_ref(sk, refs[0])
        eb, pb = split_ref(sk, refs[1])
        if kind == "distance" and (ea.kind == "line" and pa == "whole" or eb.kind == "line" and pb == "whole"):
            lref, pref = (refs[0], refs[1]) if ea.kind == "line" and pa == "whole" else (refs[1], refs[0])
            lo = lin(lref)
            fp = pt(pref)
            if "s" not in ctx:
                ctx["s"] = _sign(signed_line_dist(x0, lo, *fp(x0)))
            s = ctx["s"]
            fn = lambda x: np.array([s * signed_line_dist(x, lo, *fp(x)) - v])
        else:
            fa, fb = pt(refs[0]), pt(refs[1])
            if kind == "distance":
                fn = lambda x: np.array([math.hypot(fb(x)[0] - fa(x)[0], fb(x)[1] - fa(x)[1]) - v])
            else:
                ax = 0 if kind == "hdistance" else 1
                if "s" not in ctx:
                    ctx["s"] = _sign(fb(x0)[ax] - fa(x0)[ax])
                s = ctx["s"]
                fn = lambda x: np.array([fb(x)[ax] - fa(x)[ax] - s * v])
        rows = 1
    elif kind == "angle":
        v = math.radians(float(value))
        if len(refs) == 2:
            if abs(float(value)) > 180.0 + 1e-9:
                raise SolverFault("an angle between two lines must be within 180 degrees")
            a, b = lin(refs[0]), lin(refs[1])

            def fn(x):
                d1x, d1y, _ = _dir(x, a)
                d2x, d2y, _ = _dir(x, b)
                return np.array([_wrap(math.atan2(d1x * d2y - d1y * d2x, d1x * d2x + d1y * d2y) - v)])
        else:
            _need(refs, 1, kind)
            ent, part = split_ref(sk, refs[0])
            if ent.kind != "arc" or part != "whole":
                raise SolverFault("angle needs two lines or an arc")
            if not 0.0 < float(value) <= 360.0:
                raise SolverFault("an arc sweep must be within 0 to 360 degrees")
            o = ent.off
            touch(ent, [o + 3, o + 4])
            fn = lambda x: np.array([_wrap(x[o + 4] - x[o + 3] - v)])
        rows = 1
    elif kind in ("radius", "diameter"):
        _need(refs, 1, kind)
        ent = crv(refs[0])
        if ent.kind == "ellipse":
            raise SolverFault("%s needs a circle or arc" % kind)
        if float(value) <= 0:
            raise SolverFault("%s must be positive" % kind)
        o = ent.off
        touch(ent, [o + 2])
        k = 1.0 if kind == "radius" else 2.0
        v = float(value)
        fn = lambda x: np.array([k * x[o + 2] - v])
        rows = 1
    else:
        raise SolverFault("unknown constraint kind '%s'" % kind)

    return fn, sorted(set(vars_)), rows, ents
