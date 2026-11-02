import math

from app.dim import sectors
from app.dim import vec as V


def value_of(dim) -> float:
    t = dim.dim_type
    if t == "linear":
        u = (math.cos(dim.rotation), math.sin(dim.rotation))
        return abs(V.dot(V.sub(V.xy(dim.p14), V.xy(dim.p13)), u))
    if t == "aligned":
        return V.dist(V.xy(dim.p13), V.xy(dim.p14))
    if t == "radius" or t == "jogged":
        return V.dist(V.xy(dim.def_point), V.xy(dim.p15))
    if t == "diameter":
        return V.dist(V.xy(dim.def_point), V.xy(dim.p15))
    if t == "angular":
        s = sectors.two_lines(dim)
        return s["sweep"] if s else 0.0
    if t == "angular3":
        return sectors.three_points(dim)["sweep"]
    if t == "arc":
        s = sectors.arc_points(dim)
        return s["r"] * s["sweep"]
    if t == "ordinate":
        f, o = V.xy(dim.p13), V.xy(dim.def_point)
        return f[0] - o[0] if dim.marks.get("ordinate", "x") == "x" else f[1] - o[1]
    return 0.0
