LAYOUT = {
    "linear": ("d0", "d13", "d14"),
    "aligned": ("d0", "d13", "d14"),
    "radius": ("d0", "d15"),
    "jogged": ("d0", "d15", "jc", "jp"),
    "diameter": ("d0", "d15"),
    "angular": ("d0", "d13", "d14", "d15", "d16"),
    "angular3": ("d0", "d13", "d14", "d15"),
    "arc": ("d0", "d13", "d14", "d15"),
    "ordinate": ("d13", "d14"),
    "center": ("d15",),
}
FIELD = {"d0": "def_point", "d13": "p13", "d14": "p14", "d15": "p15", "d16": "p16"}
MARK_FIELD = {"jc": "jog_center", "jp": "jog_point"}
MARK_POINTS = ("jog_center", "jog_point", "jog", "sector_pt")
MARK_ANGLES = ("text_angle", "oblique")


def _p(v):
    return [float(v[0]), float(v[1])]


def points(e):
    out = []
    for gid in LAYOUT.get(e.dim_type, ("d0", "d13", "d14")):
        if gid in FIELD:
            v = getattr(e, FIELD[gid])
        else:
            v = e.marks.get(MARK_FIELD[gid])
        if v:
            out.append((gid, "defpoint", _p(v)))
    if e.text_point:
        out.append(("text", "text", _p(e.text_point)))
    return out


def stretch(e, gid, t):
    if gid == "text":
        e.text_point = [t[0], t[1], 0.0]
        e.text_moved = True
        return True
    if gid in FIELD:
        setattr(e, FIELD[gid], [t[0], t[1], 0.0])
        return True
    if gid in MARK_FIELD:
        m = dict(e.marks)
        m[MARK_FIELD[gid]] = [t[0], t[1]]
        e.marks = m
        return True
    return False


def transform(e, xf, P):
    for name in e.POINTS:
        v = getattr(e, name)
        if v:
            setattr(e, name, P(v))
    marks = dict(e.marks)
    for key in MARK_POINTS:
        v = marks.get(key)
        if v:
            q = P([v[0], v[1], 0.0])
            marks[key] = [q[0], q[1]]
    for item in marks.get("breaks", []) or []:
        q = P([item["p"][0], item["p"][1], 0.0])
        item["p"] = [q[0], q[1]]
        item["size"] = float(item.get("size", 0.0)) * xf.k
    for key in MARK_ANGLES:
        if marks.get(key) is not None:
            marks[key] = xf.ang(float(marks[key]))
    if marks.get("radius") is not None:
        marks["radius"] = float(marks["radius"]) * xf.k
    if marks.get("ccw") is not None and xf.flip:
        marks["ccw"] = not marks["ccw"]
    e.marks = marks
    if e.dim_type == "linear":
        e.rotation = xf.ang(float(e.rotation))
    e.measurement *= xf.k
