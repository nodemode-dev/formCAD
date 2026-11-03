import math

from app.doc import layouts, tables as T

CLASSES = ("sharp_v", "sharp_h", "smooth_v", "smooth_h", "sewn_v", "sewn_h", "outline_v", "outline_h")
VTYPES = ("base", "projected", "auxiliary", "section", "detail", "broken", "crop")
MODES = ("exact", "draft", "auto")
DRAFT_CUTOVER_FACES = 600

LAYER_VISIBLE = "VIEW_VISIBLE"
LAYER_HIDDEN = "VIEW_HIDDEN"
LAYER_TANGENT = "VIEW_TANGENT"
LAYER_SECTION = "VIEW_SECTION"
LAYER_BREAK = "VIEW_BREAK"
LAYER_LABEL = "VIEW_LABEL"
LAYER_VIEWS = "VIEWS"

CLASS_LAYER = {
    "sharp_v": LAYER_VISIBLE, "outline_v": LAYER_VISIBLE, "sewn_v": LAYER_TANGENT, "smooth_v": LAYER_TANGENT,
    "sharp_h": LAYER_HIDDEN, "outline_h": LAYER_HIDDEN, "smooth_h": LAYER_HIDDEN, "sewn_h": LAYER_HIDDEN,
}
LAYER_DEFS = {
    LAYER_VISIBLE: {"color": 7, "linetype": "Continuous", "lineweight": 50},
    LAYER_HIDDEN: {"color": 8, "linetype": "HIDDEN", "lineweight": 25},
    LAYER_TANGENT: {"color": 7, "linetype": "Continuous", "lineweight": 18},
    LAYER_SECTION: {"color": 7, "linetype": "Continuous", "lineweight": 13},
    LAYER_BREAK: {"color": 7, "linetype": "Continuous", "lineweight": 25},
    LAYER_LABEL: {"color": 7, "linetype": "Continuous", "lineweight": 25},
    LAYER_VIEWS: {"color": 7, "linetype": "Continuous", "lineweight": 25},
}

DEFAULT_SHOW = {"hidden": True, "tangent": False, "silhouette": True, "seam": False, "hatch": True, "label": True}
STANDARD = {
    "front": ([0, -1, 0], [0, 0, 1]), "back": ([0, 1, 0], [0, 0, 1]), "left": ([-1, 0, 0], [0, 0, 1]), "right": ([1, 0, 0], [0, 0, 1]),
    "top": ([0, 0, 1], [0, 1, 0]), "bottom": ([0, 0, -1], [0, -1, 0]), "iso": ([1, -1, 1], [0, 0, 1]),
}
REL = ("top", "bottom", "left", "right")


class ViewError(ValueError):
    pass


def unit(v):
    n = math.sqrt(sum(float(c) * float(c) for c in v))
    if n < 1e-12:
        raise ViewError("A view direction has zero length.")
    return [float(c) / n for c in v]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def dot(a, b):
    return sum(float(x) * float(y) for x, y in zip(a, b))


def neg(a):
    return [-float(c) for c in a]


def frame(normal, up):
    n = unit(normal)
    x = cross(up, n)
    if dot(x, x) < 1e-12:
        pick = [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [0.0, 1.0, 0.0]
        x = cross(pick, n)
    x = unit(x)
    y = unit(cross(n, x))
    return x, y, n


def view_frame(view):
    return frame(view.vnormal, view.vup)


def standard_direction(name):
    key = str(name or "").strip().lower()
    if key not in STANDARD:
        raise ViewError("Unknown standard view %s; use front, back, left, right, top, bottom or iso." % name)
    n, u = STANDARD[key]
    return unit(n), unit(u)


def derived_direction(parent, rel):
    x, y, n = view_frame(parent)
    if rel == "right":
        return list(x), list(y)
    if rel == "left":
        return neg(x), list(y)
    if rel == "top":
        return list(y), neg(n)
    if rel == "bottom":
        return neg(y), list(n)
    raise ViewError("Unknown projected view %s; use top, bottom, left or right." % rel)


def projection_of(d, layout: str) -> str:
    rec = layouts.find(d, layout)
    val = str((rec or {}).get("projection", "third")).lower()
    return "first" if val == "first" else "third"


def set_projection(d, layout: str, system: str) -> str:
    system = str(system or "").strip().lower()
    if system not in ("first", "third"):
        raise ViewError("The projection angle must be first or third.")
    rec = layouts.find(d, layout)
    if rec is None:
        raise ViewError('Layout "%s" not found.' % layout)
    rec = d.modify_record("layouts", rec["name"])
    rec["projection"] = system
    return system


def placement(angle, rel, base_pos, base_half, new_half, gap):
    if rel not in REL:
        raise ViewError("A projected view is top, bottom, left or right.")
    sign = {"top": (0, 1), "bottom": (0, -1), "left": (-1, 0), "right": (1, 0)}[rel]
    if angle == "first":
        sign = (-sign[0], -sign[1])
    x = base_pos[0] + sign[0] * (base_half[0] + gap + new_half[0])
    y = base_pos[1] + sign[1] * (base_half[1] + gap + new_half[1])
    return [x, y]


def side_of(angle, rel):
    sign = {"top": "up", "bottom": "down", "left": "left", "right": "right"}[rel]
    if angle == "first":
        return {"up": "down", "down": "up", "left": "right", "right": "left"}[sign]
    return sign


def to_paper(view, unit_mm, local):
    k = float(view.scale) / unit_mm
    return [view.position[0] + local[0] * k, view.position[1] + local[1] * k]


def to_local(view, unit_mm, paper):
    k = float(view.scale) / unit_mm
    return [(paper[0] - view.position[0]) / k, (paper[1] - view.position[1]) / k]


def project(view, point):
    x, y, _n = view_frame(view)
    o = view.origin
    d = [float(point[i]) - float(o[i]) for i in range(3)]
    return [dot(d, x), dot(d, y)]


def lift(view, local, depth=0.0):
    x, y, n = view_frame(view)
    o = view.origin
    return [o[i] + x[i] * local[0] + y[i] * local[1] + n[i] * depth for i in range(3)]


def ensure_layers(d) -> None:
    for name, spec in LAYER_DEFS.items():
        if not d.tables["layers"].has(name):
            lt = spec["linetype"]
            if not d.tables["linetypes"].has(lt):
                lt = "Continuous"
            d.table_set("layers", T.new_layer(name, color=spec["color"], linetype=lt, lineweight=spec["lineweight"]))


def class_enabled(show: dict, cls: str) -> bool:
    s = {**DEFAULT_SHOW, **(show or {})}
    hidden = cls.endswith("_h")
    if hidden and not s["hidden"]:
        return False
    if cls.startswith("smooth") and not s["tangent"]:
        return False
    if cls.startswith("sewn") and not s["seam"]:
        return False
    if cls.startswith("outline") and not s["silhouette"]:
        return False
    return True
