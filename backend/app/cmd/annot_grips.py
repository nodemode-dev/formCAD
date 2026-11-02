from app.doc import geom


def move_landing(e, dx: float, dy: float) -> None:
    old = [e.landing[0], e.landing[1]]
    e.landing = [old[0] + dx, old[1] + dy, 0.0]
    e.content_pos = [e.content_pos[0] + dx, e.content_pos[1] + dy, 0.0]
    for ld in e.leaders:
        last = ld["pts"][-1]
        if geom.dist(last, old) < 1e-9:
            ld["pts"][-1] = [last[0] + dx, last[1] + dy]


def points_of(e) -> list:
    if e.kind == "mleader":
        out = [("a%d" % i, ld["pts"][0], "end") for i, ld in enumerate(e.leaders)]
        if e.leaders:
            out.append(("land", e.landing, "node"))
        out.append(("text", e.content_pos, "insert"))
        return out
    if e.kind == "leader":
        return [("v%d" % i, p, "vertex") for i, p in enumerate(e.points)]
    parts = e.parts()
    px, py = e.position[0], e.position[1]
    return [("p%d" % k, [px + part["dx"], py + part["dy"]], "insert") for k, part in enumerate(parts)]


def stretch(e, gid: str, t) -> bool:
    if e.kind == "mleader":
        if gid.startswith("a"):
            e.leaders[int(gid[1:])]["pts"][0] = [t[0], t[1]]
        else:
            src = e.landing if gid == "land" else e.content_pos
            move_landing(e, t[0] - src[0], t[1] - src[1])
        return True
    if e.kind == "leader":
        e.points[int(gid[1:])] = [t[0], t[1], 0.0]
        return True
    k = int(gid[1:])
    parts = e.parts()
    cur = [e.position[0] + parts[k]["dx"], e.position[1] + parts[k]["dy"]]
    dx, dy = t[0] - cur[0], t[1] - cur[1]
    if k == 0:
        e.position = [e.position[0] + dx, e.position[1] + dy, 0.0]
        return True
    b = dict(e.breaks or {})
    offs = [list(o) for o in (b.get("offsets") or [])]
    while len(offs) <= k:
        offs.append([0.0, 0.0])
    offs[k] = [offs[k][0] + dx, offs[k][1] + dy]
    b["offsets"] = offs
    e.breaks = b
    return True
