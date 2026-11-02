import fnmatch
import math
import re

from app.doc import curves2d, geom
from app.doc.kinds.viewport import Viewport
from app.doc.model import layout_space

MAX_CLIP_VERTICES = 4096
MIN_SCALE = 1e-9
MAX_SCALE = 1e9
OVERRIDE_KEYS = ("color", "linetype", "lineweight", "transparency", "plot_style")


class ViewportError(Exception):
    pass


def of_space(d, space: str) -> list:
    return [e for e in d.entities(space) if e.kind == "viewport"]


def of_layout(d, layout: str) -> list:
    return of_space(d, layout_space(layout))


def next_id(d, space: str) -> int:
    top = 1
    for e in of_space(d, space):
        top = max(top, int(e.vp_id or 0))
    return top + 1


def number_ids(d, space: str) -> None:
    seen = set()
    for e in of_space(d, space):
        if e.vp_id and e.vp_id >= 2 and e.vp_id not in seen:
            seen.add(e.vp_id)
            continue
        ent = d.modify(e.handle)
        top = max(list(seen) + [1])
        ent.vp_id = top + 1
        seen.add(ent.vp_id)


def default_frozen(d) -> list:
    return [r["name"] for r in d.tables["layers"].values() if r.get("new_vp_freeze")]


def by_id(d, space: str, vp_id: int):
    for e in of_space(d, space):
        if e.vp_id == vp_id:
            return e
    return None


def model_view_for(doc, width: float, height: float):
    d = doc.drawing
    box = d.extents("model")
    if not box:
        lim = d.header.get("LIMMAX")
        mn = d.header.get("LIMMIN") or [0.0, 0.0]
        if lim and lim[0] > mn[0] and lim[1] > mn[1]:
            return [(lim[0] + mn[0]) / 2.0, (lim[1] + mn[1]) / 2.0, 0.0], max((lim[0] - mn[0]) / width, (lim[1] - mn[1]) / height)
        return [0.0, 0.0, 0.0], 1.0
    w = max(box[2] - box[0], 1e-9)
    h = max(box[3] - box[1], 1e-9)
    return [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0, 0.0], clamp_scale(max(w / width, h / height))


def clamp_scale(s: float) -> float:
    return min(MAX_SCALE, max(MIN_SCALE, float(s)))


def make(doc, space: str, x0: float, y0: float, x1: float, y1: float, clip=None, fit: bool = True) -> Viewport:
    d = doc.drawing
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < geom.EPS or y1 - y0 < geom.EPS:
        raise ViewportError("The viewport has no size.")
    vp = Viewport()
    vp.center = [(x0 + x1) / 2.0, (y0 + y1) / 2.0, 0.0]
    vp.width = x1 - x0
    vp.height = y1 - y0
    vp.vp_id = next_id(d, space)
    vp.frozen = default_frozen(d)
    vp.anno_scale = str(d.header.get("CANNOSCALE", "1:1"))
    if clip:
        vp.clip = [{"p": [float(v["p"][0]), float(v["p"][1])], "bulge": float(v.get("bulge", 0.0) or 0.0)} for v in clip]
    if fit:
        vp.view_center, vp.scale = model_view_for(doc, vp.width, vp.height)
    return vp


def ratio_scale(d, text: str):
    t = str(text).strip()
    if not t:
        return None
    rec = d.tables["scales"].get(t)
    if rec is not None:
        return d.scale_value(rec["name"])
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*[:=]\s*([0-9]*\.?[0-9]+)\s*$", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return b / a if a > 0 and b > 0 else None
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*/\s*([0-9]*\.?[0-9]+)\s*$", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return b / a if a > 0 and b > 0 else None
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*xp\s*$", t, re.I)
    if m:
        n = float(m.group(1))
        return 1.0 / n if n > 0 else None
    m = re.match(r"^\s*([0-9]*\.?[0-9]+)\s*$", t)
    if m:
        n = float(m.group(1))
        return 1.0 / n if n > 0 else None
    return None


def parse_scale(d, value) -> float:
    if isinstance(value, bool):
        raise ViewportError("Enter a scale such as 1:50.")
    if isinstance(value, (int, float)):
        if not math.isfinite(value) or value <= 0:
            raise ViewportError("The scale must be above zero.")
        return clamp_scale(1.0 / float(value))
    s = ratio_scale(d, str(value))
    if s is None or not math.isfinite(s) or s <= 0:
        raise ViewportError("Enter a scale such as 1:50, 1/50 or 0.02.")
    return clamp_scale(s)


def scale_name(d, model_per_paper: float) -> str:
    for rec in d.tables["scales"].values():
        if rec["paper"] > 0 and abs(d.scale_value(rec["name"]) - model_per_paper) <= 1e-9 * max(1.0, model_per_paper):
            return rec["name"]
    return ratio_text(model_per_paper)


def ratio_text(s: float) -> str:
    if s >= 1.0 - 1e-12:
        return "1:%s" % _g(s)
    return "%s:1" % _g(1.0 / s)


def _g(v: float) -> str:
    return ("%.6f" % v).rstrip("0").rstrip(".")


def set_scale(vp, model_per_paper: float, d=None) -> None:
    if vp.locked:
        raise ViewportError("The viewport is locked.")
    vp.scale = clamp_scale(model_per_paper)
    if d is not None:
        rec = None
        for r in d.tables["scales"].values():
            if r["paper"] > 0 and abs(d.scale_value(r["name"]) - vp.scale) <= 1e-9 * max(1.0, vp.scale):
                rec = r
                break
        if rec is not None:
            vp.anno_scale = rec["name"]


def zoom_extents(doc, vp) -> None:
    if vp.locked:
        raise ViewportError("The viewport is locked.")
    vp.view_center, vp.scale = model_view_for(doc, vp.width, vp.height)


def set_view(vp, center, height: float) -> None:
    if height <= 0 or not math.isfinite(height):
        raise ViewportError("The view height must be above zero.")
    if vp.locked:
        raise ViewportError("The viewport is locked.")
    vp.view_center = [float(center[0]), float(center[1]), 0.0]
    vp.scale = clamp_scale(height / vp.height)


def pan_view(vp, center) -> None:
    vp.view_center = [float(center[0]), float(center[1]), 0.0]


def arrangement(kind: int, how: str, x0: float, y0: float, x1: float, y1: float) -> list:
    w, h = x1 - x0, y1 - y0
    how = (how or "").lower()
    out = []

    def col(i, n, xa, xb):
        return [xa + (xb - xa) * i / n, xa + (xb - xa) * (i + 1) / n]

    if kind == 1:
        return [(x0, y0, x1, y1)]
    if kind == 2:
        if how.startswith("h"):
            return [(x0, y0 + h / 2.0, x1, y1), (x0, y0, x1, y0 + h / 2.0)]
        return [(x0, y0, x0 + w / 2.0, y1), (x0 + w / 2.0, y0, x1, y1)]
    if how.startswith("h"):
        return [(x0, y0 + h * (kind - 1 - i) / kind, x1, y0 + h * (kind - i) / kind) for i in range(kind)]
    if how.startswith("v"):
        return [(col(i, kind, x0, x1)[0], y0, col(i, kind, x0, x1)[1], y1) for i in range(kind)]
    if kind == 4 and how.startswith("e"):
        return [(x0, y0 + h / 2.0, x0 + w / 2.0, y1), (x0 + w / 2.0, y0 + h / 2.0, x1, y1), (x0, y0, x0 + w / 2.0, y0 + h / 2.0), (x0 + w / 2.0, y0, x1, y0 + h / 2.0)]
    small = kind - 1
    half_x, half_y = x0 + w / 2.0, y0 + h / 2.0
    if how.startswith("l"):
        out.append((x0, y0, half_x, y1))
        out.extend((half_x, y0 + h * (small - 1 - i) / small, x1, y0 + h * (small - i) / small) for i in range(small))
    elif how.startswith("a"):
        out.append((x0, half_y, x1, y1))
        out.extend((col(i, small, x0, x1)[0], y0, col(i, small, x0, x1)[1], half_y) for i in range(small))
    elif how.startswith("b"):
        out.append((x0, y0, x1, half_y))
        out.extend((col(i, small, x0, x1)[0], half_y, col(i, small, x0, x1)[1], y1) for i in range(small))
    else:
        out.extend((x0, y0 + h * (small - 1 - i) / small, half_x, y0 + h * (small - i) / small) for i in range(small))
        out.append((half_x, y0, x1, y1))
    return out


def clip_from_entity(e):
    if e.kind == "lwpolyline":
        if not e.closed:
            raise ViewportError("Select a closed polyline, circle, ellipse or spline.")
        verts = [{"p": [float(v["p"][0]), float(v["p"][1])], "bulge": float(v.get("bulge", 0.0) or 0.0)} for v in e.vertices]
    elif e.kind == "circle":
        c, r = e.center, float(e.radius)
        verts = [{"p": [c[0] + r, c[1]], "bulge": 1.0}, {"p": [c[0] - r, c[1]], "bulge": 1.0}]
    elif e.kind == "ellipse":
        pts, full, _slack = curves2d.ellipse_points(e)
        if not full:
            raise ViewportError("Select a closed polyline, circle, ellipse or spline.")
        verts = [{"p": [p[0], p[1]], "bulge": 0.0} for p in pts[:-1]]
    elif e.kind == "spline":
        res = curves2d.spline_points(e)
        if res is None or not res[1]:
            raise ViewportError("Select a closed polyline, circle, ellipse or spline.")
        verts = [{"p": [p[0], p[1]], "bulge": 0.0} for p in res[0][:-1]]
    else:
        raise ViewportError("Select a closed polyline, circle, ellipse or spline.")
    if len(verts) < 2 or len(verts) > MAX_CLIP_VERTICES:
        raise ViewportError("The outline has too many or too few vertices.")
    return verts


def apply_clip(vp, verts) -> None:
    vp.clip = [dict(p=list(v["p"]), bulge=float(v.get("bulge", 0.0) or 0.0)) for v in verts]
    area = 0.0
    pts = vp.outline_points()
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        area += a[0] * b[1] - b[0] * a[1]
    if abs(area) < geom.EPS:
        vp.clip = None
        raise ViewportError("The outline encloses no area.")
    vp.clip_source = 0
    vp.fit_to_outline()


def clear_clip(vp) -> bool:
    if not vp.clip:
        return False
    box = vp.outline_box()
    vp.clip = None
    vp.clip_source = 0
    vp.recentre([(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0, 0.0])
    vp.width = box[2] - box[0]
    vp.height = box[3] - box[1]
    return True


def match_layers(d, spec: str) -> tuple:
    found, missing = [], []
    table = d.tables["layers"]
    for raw in str(spec).split(","):
        nm = raw.strip()
        if not nm:
            continue
        if any(c in nm for c in "*?"):
            hits = [r["name"] for r in table.values() if fnmatch.fnmatchcase(r["name"].casefold(), nm.casefold())]
            if not hits:
                missing.append(nm)
            found.extend(h for h in hits if h not in found)
        else:
            rec = table.get(nm)
            if rec is None:
                missing.append(nm)
            elif rec["name"] not in found:
                found.append(rec["name"])
    return found, missing


def is_frozen(vp, layer: str) -> bool:
    key = str(layer).casefold()
    return any(str(n).casefold() == key for n in vp.frozen)


def freeze(vp, layer: str) -> bool:
    if is_frozen(vp, layer):
        return False
    vp.frozen = list(vp.frozen) + [layer]
    return True


def thaw(vp, layer: str) -> bool:
    key = str(layer).casefold()
    keep = [n for n in vp.frozen if str(n).casefold() != key]
    if len(keep) == len(vp.frozen):
        return False
    vp.frozen = keep
    return True


def override_of(vp, layer: str) -> dict:
    return vp.overrides.get(str(layer).casefold(), {})


def set_override(vp, layer: str, key: str, value) -> None:
    if key not in OVERRIDE_KEYS:
        raise ViewportError("Unknown override %s." % key)
    cur = dict(vp.overrides)
    rec = dict(cur.get(layer.casefold(), {"name": layer}))
    if value is None:
        rec.pop(key, None)
    else:
        rec[key] = value
    if len([k for k in rec if k != "name"]) == 0:
        cur.pop(layer.casefold(), None)
    else:
        cur[layer.casefold()] = rec
    vp.overrides = cur


def clear_overrides(vp, layer: str) -> bool:
    if layer.casefold() in vp.overrides:
        cur = dict(vp.overrides)
        cur.pop(layer.casefold())
        vp.overrides = cur
        return True
    return False


def active(doc):
    h = int(getattr(doc, "active_vp", 0) or 0)
    if not h:
        return None
    e = doc.drawing.get(h)
    return e if e is not None and e.kind == "viewport" and e.owner == doc.tab else None


def input_point(doc, pt):
    vp = active(doc)
    if vp is None or not vp.contains(pt):
        return pt
    return vp.to_model(pt)


def info(d, vp) -> dict:
    return {"h": vp.handle, "id": vp.vp_id, "layer": vp.layer, "center": [vp.center[0], vp.center[1]], "size": [vp.width, vp.height], "viewCenter": [vp.view_center[0], vp.view_center[1]], "viewHeight": vp.view_height, "scale": vp.scale, "scaleText": scale_name(d, vp.scale), "on": bool(vp.on), "locked": bool(vp.locked), "clipped": bool(vp.clip), "frozen": list(vp.frozen), "overrides": {k: dict(v) for k, v in vp.overrides.items()}, "annoScale": vp.anno_scale}
