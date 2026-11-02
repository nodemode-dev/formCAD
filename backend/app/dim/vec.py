import math

EPS = 1e-9


def xy(p):
    return (float(p[0]), float(p[1]))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def mul(a, k):
    return (a[0] * k, a[1] * k)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def length(a):
    return math.hypot(a[0], a[1])


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit(a, fallback=(1.0, 0.0)):
    n = math.hypot(a[0], a[1])
    if n < EPS:
        return fallback
    return (a[0] / n, a[1] / n)


def perp(a):
    return (-a[1], a[0])


def polar(c, r, ang):
    return (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))


def ang_of(a):
    return math.atan2(a[1], a[0])


def norm_pos(a):
    t = math.fmod(a, 2 * math.pi)
    return t + 2 * math.pi if t < 0 else t


def ccw(a0, a1):
    return norm_pos(a1 - a0)


def readable(a):
    t = math.fmod(a, 2 * math.pi)
    if t > math.pi:
        t -= 2 * math.pi
    elif t <= -math.pi:
        t += 2 * math.pi
    if t > math.pi / 2 + 1e-9:
        t -= math.pi
    elif t <= -math.pi / 2 + 1e-9:
        t += math.pi
    return t


def line_hit(p, d, q, e):
    den = cross(d, e)
    if abs(den) < 1e-12:
        return None
    t = cross(sub(q, p), e) / den
    return (p[0] + d[0] * t, p[1] + d[1] * t)
