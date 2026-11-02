from app.dim import features, regen

LINKABLE = {
    "linear": ("p13", "p14"),
    "aligned": ("p13", "p14"),
    "angular": ("p13", "p14", "p15", "p16"),
    "angular3": ("p13", "p14", "p15"),
    "arc": ("p13", "p14", "p15"),
    "radius": ("def_point", "p15"),
    "jogged": ("def_point", "p15"),
    "diameter": ("def_point", "p15"),
    "ordinate": ("p13",),
    "center": ("p15",),
}
FOLLOWERS = {
    "radius": ("def_point", "p15", "text_point"),
    "diameter": ("def_point", "p15", "text_point"),
    "jogged": ("def_point", "p15", "text_point"),
    "ordinate": ("p14", "text_point"),
    "center": ("def_point", "p15", "text_point"),
}
DEFAULT_FOLLOWERS = ("def_point", "text_point")
MARK_POINTS = ("jog_center", "jog_point", "jog", "sector_pt")


def linkable(dim):
    return LINKABLE.get(dim.dim_type, ())


def _pt(dim, name):
    v = getattr(dim, name)
    return (float(v[0]), float(v[1])) if v else None


def attach(d, dim, space=None, hints=None):
    links = dict(hints or {})
    tol = d.tolerances["absolute"] * 10.0
    for name in linkable(dim):
        if name in links:
            continue
        p = _pt(dim, name)
        if p is None:
            continue
        link = features.find_link(d, p, space or dim.owner, tol)
        if link:
            links[name] = link
    dim.associativity = links
    return len(links)


def detach(dim):
    n = len(dim.associativity or {})
    dim.associativity = {}
    return n


def reassociate(d, dim):
    n = attach(d, dim)
    return n, len(linkable(dim))


def _same(p, q, tol):
    return abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol


def _shift_point(ent, name, dx, dy):
    cur = getattr(ent, name)
    if cur:
        setattr(ent, name, [cur[0] + dx, cur[1] + dy, cur[2] if len(cur) > 2 else 0.0])


def follow(doc, changed):
    d = doc.drawing
    tol = d.tolerances["absolute"] * 10.0
    ctx = None
    count = 0
    for dim in list(d.ents.values()):
        if dim.kind != "dimension":
            continue
        dim_changed = dim.handle in changed
        links = dim.associativity or {}
        linked = any(l.get("h") in changed for l in links.values())
        if not dim_changed and not linked:
            continue
        if d.layer_locked(dim.layer):
            continue
        keep = {}
        moves = {}
        dropped = False
        for name, link in links.items():
            obj = d.ents.get(link.get("h"))
            fp = features.feature_point(obj, link) if obj is not None else None
            cur = _pt(dim, name)
            if fp is None or cur is None:
                dropped = True
                continue
            if _same(cur, fp, tol):
                keep[name] = link
                continue
            if dim_changed and link.get("h") not in changed:
                dropped = True
                continue
            keep[name] = link
            moves[name] = (fp[0] - cur[0], fp[1] - cur[1])
        ent = d.modify(dim.handle)
        if dropped:
            ent.associativity = keep
        if moves:
            vecs = list(moves.values())
            vx, vy = vecs[0]
            rigid = len(moves) == len(keep) and all(abs(v[0] - vx) <= tol and abs(v[1] - vy) <= tol for v in vecs)
            if rigid and not dim_changed:
                for name in FOLLOWERS.get(ent.dim_type, DEFAULT_FOLLOWERS):
                    if name not in keep:
                        _shift_point(ent, name, vx, vy)
                marks = dict(ent.marks)
                for key in MARK_POINTS:
                    v = marks.get(key)
                    if v:
                        marks[key] = [v[0] + vx, v[1] + vy]
                ent.marks = marks
            for name, (dx, dy) in moves.items():
                _shift_point(ent, name, dx, dy)
        if ctx is None:
            ctx = regen.make_context(doc)
        regen.refresh(doc, ent, ctx, keep_block=False)
        count += 1
    return count
