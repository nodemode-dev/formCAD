from tests.support import geometry


def tag(handle: int) -> str:
    return "#%x" % handle


def newest(doc) -> int:
    return max(doc.handles())


def ent(doc, handle: int) -> dict:
    found = [e for e in doc.entities() if e["handle"] == handle]
    assert found, "no entity with handle %d" % handle
    return found[0]


def line(doc, a: str, b: str) -> int:
    doc.type("LINE", a, b, "")
    return newest(doc)


def circle(doc, center: str, radius: float) -> int:
    doc.type("CIRCLE", center, str(radius))
    return newest(doc)


def pline(doc, *points: str, closed: bool = True) -> int:
    doc.type("PLINE", *points, "C" if closed else "")
    return newest(doc)


def pick(doc, handle: int, x: float, y: float) -> dict:
    return doc.pick(point=[x, y], handle=handle)


def corners(e: dict) -> list:
    return [tuple(v["p"]) for v in e["vertices"]]


def ends(e: dict) -> tuple:
    return tuple(e["start"][:2]), tuple(e["end"][:2])


def same_segment(e: dict, a, b, tol: float = 1e-6) -> bool:
    s, t = ends(e)
    return (geometry.same_point(s, a, tol) and geometry.same_point(t, b, tol)) or (geometry.same_point(s, b, tol) and geometry.same_point(t, a, tol))


def lines_matching(doc, segments, tol: float = 1e-6) -> bool:
    found = doc.entities("line")
    if len(found) != len(segments):
        return False
    left = list(found)
    for a, b in segments:
        hit = next((e for e in left if same_segment(e, a, b, tol)), None)
        if hit is None:
            return False
        left.remove(hit)
    return True


def geometry_rows(doc) -> list:
    keep = ("kind", "handle", "layer", "start", "end", "center", "radius", "start_angle", "end_angle", "vertices", "closed", "const_width", "loops")
    return sorted(({k: v for k, v in e.items() if k in keep} for e in doc.entities()), key=lambda r: r["handle"])


def close_rows(a: list, b: list, tol: float = 1e-9) -> bool:
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
        if x.keys() != y.keys():
            return False
        for k in x:
            if not _close(x[k], y[k], tol):
                return False
    return True


def _close(u, v, tol) -> bool:
    if isinstance(u, (int, float)) and isinstance(v, (int, float)) and not isinstance(u, bool):
        return abs(u - v) <= tol * max(1.0, abs(u), abs(v))
    if isinstance(u, (list, tuple)) and isinstance(v, (list, tuple)):
        return len(u) == len(v) and all(_close(p, q, tol) for p, q in zip(u, v))
    if isinstance(u, dict) and isinstance(v, dict):
        return u.keys() == v.keys() and all(_close(u[k], v[k], tol) for k in u)
    return u == v
