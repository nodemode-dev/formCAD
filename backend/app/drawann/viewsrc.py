import math

PROVIDERS = []


class ViewError(Exception):
    pass


def register(provider) -> None:
    if provider not in PROVIDERS:
        PROVIDERS.append(provider)


def provider_for(e):
    for p in PROVIDERS:
        if e is not None and e.kind in p.kinds:
            return p
    return None


def view_kinds() -> tuple:
    out = []
    for p in PROVIDERS:
        out.extend(p.kinds)
    return tuple(out)


def is_view(e) -> bool:
    return provider_for(e) is not None


def views(d, space=None) -> list:
    kinds = view_kinds()
    out = []
    for e in d.ents.values():
        if e.kind in kinds and (space is None or e.owner == space):
            out.append(e)
    return out


def need(d, handle):
    e = d.ents.get(int(handle)) if handle not in (None, "", 0) else None
    if e is None or provider_for(e) is None:
        raise ViewError("Handle %s is not a drawing view." % handle)
    return e


def edges(d, view) -> list:
    return provider_for(view).edges(d, view)


def edge(d, view, key):
    for ed in edges(d, view):
        if ed["id"] == key:
            return ed
    return None


def edge_point(ed, link):
    t = link.get("t")
    typ = ed["type"]
    if typ == "line":
        p0, p1 = ed["p"][0], ed["p"][1]
        if t == "start":
            return (float(p0[0]), float(p0[1]))
        if t == "end":
            return (float(p1[0]), float(p1[1]))
        if t == "mid":
            return ((p0[0] + p1[0]) / 2.0, (p0[1] + p1[1]) / 2.0)
        return None
    c, r = ed["c"], float(ed["r"])
    if t == "center":
        return (float(c[0]), float(c[1]))
    if typ == "circle":
        if t == "ang":
            a = float(link.get("a", 0.0))
            return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
        return None
    a0, a1 = float(ed["a0"]), float(ed["a1"])
    sweep = (a1 - a0) % (2 * math.pi)
    if t == "start":
        return (c[0] + r * math.cos(a0), c[1] + r * math.sin(a0))
    if t == "end":
        return (c[0] + r * math.cos(a1), c[1] + r * math.sin(a1))
    if t == "mid":
        m = a0 + sweep / 2.0
        return (c[0] + r * math.cos(m), c[1] + r * math.sin(m))
    if t == "ang":
        a = float(link.get("a", 0.0))
        return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
    return None


def edge_features(ed) -> list:
    typ = ed["type"]
    if typ == "line":
        return [{"t": "start"}, {"t": "end"}, {"t": "mid"}]
    if typ == "circle":
        return [{"t": "center"}]
    return [{"t": "start"}, {"t": "end"}, {"t": "mid"}, {"t": "center"}]


def point(d, link):
    view = d.ents.get(link.get("h"))
    if view is None or provider_for(view) is None:
        return None
    ed = edge(d, view, str(link.get("e", "")))
    if ed is None:
        return None
    return edge_point(ed, link)


def nearest_link(d, view, p, tol=1e-3, kinds=("start", "end", "mid", "center")):
    best = None
    for ed in edges(d, view):
        for f in edge_features(ed):
            if f["t"] not in kinds:
                continue
            q = edge_point(ed, f)
            if q is None:
                continue
            dist = math.hypot(q[0] - p[0], q[1] - p[1])
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, dict(f, h=view.handle, e=ed["id"]))
    return best[1] if best else None


def nearest_on_edge(d, view, p, styles=("visible", "silhouette", "sharp")):
    best = None
    for ed in edges(d, view):
        if ed.get("style", "visible") not in styles:
            continue
        q, dist = project_onto(ed, p)
        if best is None or dist < best[0]:
            best = (dist, ed, q)
    return best


def project_onto(ed, p):
    typ = ed["type"]
    if typ == "line":
        a, b = ed["p"][0], ed["p"][1]
        dx, dy = b[0] - a[0], b[1] - a[1]
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 < 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2))
        q = (a[0] + dx * t, a[1] + dy * t)
        return q, math.hypot(q[0] - p[0], q[1] - p[1])
    c, r = ed["c"], float(ed["r"])
    ang = math.atan2(p[1] - c[1], p[0] - c[0])
    if typ == "arc":
        a0, a1 = float(ed["a0"]), float(ed["a1"])
        sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
        rel = (ang - a0) % (2 * math.pi)
        if rel > sweep:
            ends = [a0, a1]
            ang = min(ends, key=lambda a: abs(((a - ang + math.pi) % (2 * math.pi)) - math.pi))
    q = (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
    return q, math.hypot(q[0] - p[0], q[1] - p[1])


def link_for_point(d, view, p, tol):
    near = nearest_link(d, view, p, tol)
    if near:
        return near
    hit = nearest_on_edge(d, view, p)
    if hit and hit[0] <= tol:
        ed = hit[1]
        if ed["type"] in ("circle", "arc"):
            c = ed["c"]
            return {"h": view.handle, "e": ed["id"], "t": "ang", "a": math.atan2(hit[2][1] - c[1], hit[2][0] - c[0])}
    return None
