import copy
import fnmatch
import math

from app.doc import layerops as LO
from app.doc import rename as R
from app.doc.entities import entity_from_dict
from app.doc.model import layout_space

MAX_TILES = 16
MIN_TILE = 0.08
LIMIT = 1e12
PAN_STEP = 0.2
ORIENTS = ("Horizontal", "Vertical", "Above", "Below", "Left", "Right")
TOO_LARGE = "The view is too large to show. Nothing was changed."


class ViewError(Exception):
    pass


def view_session(doc) -> dict:
    s = getattr(doc, "view_session", None)
    if s is None:
        s = {"snapshot": True, "tile": 0}
        doc.view_session = s
    return s


def fit_height(doc, width: float, height: float) -> float:
    return max(height, width / max(getattr(doc, "aspect", 1.6), 1e-6))


def check_size(center, height) -> None:
    if not all(math.isfinite(v) for v in (center[0], center[1], height)) or abs(center[0]) > LIMIT or abs(center[1]) > LIMIT or height > LIMIT or height <= 0:
        raise ViewError(TOO_LARGE)


def current_layout(doc) -> str:
    sp = doc.current_space
    return sp.split(":", 1)[1] if sp.startswith("layout:") else ""


def valid_view_name(name) -> bool:
    return R.valid_name(name) and not str(name).startswith("*")


def view_space_label(rec) -> str:
    return rec.get("layout") or "Model"


def list_views(d) -> list:
    out = []
    for rec in d.tables["views"].values():
        out.append({"name": rec["name"], "layout": rec.get("layout", ""), "space": view_space_label(rec), "center": list(rec["center"]), "width": rec["width"], "height": rec["height"], "twist": rec.get("twist", 0.0), "layerState": rec.get("layer_state", "")})
    return sorted(out, key=lambda r: LO.natural_key(r["name"]))


def save_view(doc, name: str, window=None, snapshot=None) -> tuple:
    d = doc.drawing
    name = str(name or "").strip()
    if not valid_view_name(name):
        raise ViewError('"%s" is not a valid view name.' % name)
    if window is not None:
        a, b = window
        w, h = abs(b[0] - a[0]), abs(b[1] - a[1])
        center = [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0]
    else:
        h = float(doc.view["height"])
        w = h * getattr(doc, "aspect", 1.6)
        center = [doc.view["center"][0], doc.view["center"][1]]
    if not (w > 0 and h > 0) or not all(math.isfinite(v) for v in (w, h, center[0], center[1])):
        raise ViewError("The view has no area.")
    snap = view_session(doc)["snapshot"] if snapshot is None else bool(snapshot)
    old = d.tables["views"].get(name)
    rec = {"name": old["name"] if old else name, "layout": current_layout(doc), "center": center, "width": w, "height": h, "twist": 0.0, "layer_state": ""}
    internal = "*V:" + rec["name"]
    if snap:
        LO.save_state(d, internal, internal=True, overwrite=True)
        rec["layer_state"] = internal
    elif d.tables["layerstates"].get(internal) is not None:
        d.table_remove("layerstates", internal)
    d.table_set("views", rec)
    return rec, old is not None


def restore_view(doc, name: str) -> dict:
    d = doc.drawing
    rec = d.tables["views"].get(str(name).strip())
    if rec is None:
        raise ViewError('Cannot find view "%s".' % str(name).strip())
    if not (rec["width"] > 0 and rec["height"] > 0):
        raise ViewError("The view has no area.")
    layout = rec.get("layout", "")
    lrec = None
    if layout:
        lrec = d.tables["layouts"].get(layout)
        if lrec is None:
            raise ViewError('The layout "%s" of this view no longer exists.' % layout)
    space = layout_space(lrec["name"]) if lrec else "model"
    center = list(rec["center"])
    height = fit_height(doc, rec["width"], rec["height"])
    check_size(center, height)
    notes = []
    snap = rec.get("layer_state", "")
    if snap:
        if d.tables["layerstates"].get(snap) is None:
            notes.append('Its layer snapshot "%s" is missing.' % snap)
        else:
            LO.restore_state(d, snap, create_missing=False, restore_current=True)
    if doc.current_space != space:
        doc.current_space = space
    doc.set_view(center, height)
    doc.request_view("restore", center=center, height=height, space=space, name=rec["name"])
    return {"name": rec["name"], "space": space, "center": center, "height": height, "notes": notes}


def delete_views(d, spec) -> list:
    pats = [s.strip() for s in (spec if isinstance(spec, (list, tuple)) else str(spec).split(",")) if str(s).strip()]
    gone = []
    for rec in list(d.tables["views"].values()):
        if any(fnmatch.fnmatchcase(rec["name"].casefold(), p.casefold()) for p in pats):
            gone.append(rec["name"])
    for n in gone:
        d.table_remove("views", n)
        if d.tables["layerstates"].get("*V:" + n) is not None:
            d.table_remove("layerstates", "*V:" + n)
    return gone


def pan_by(doc, dx: float, dy: float) -> dict:
    c = doc.view["center"]
    h = doc.view["height"]
    center = [c[0] - dx, c[1] - dy]
    check_size(center, h)
    doc.set_view(center, h)
    return doc.request_view("pan", center=center, height=h)


def pan_step(doc, direction: str) -> dict:
    h = float(doc.view["height"])
    w = h * getattr(doc, "aspect", 1.6)
    dx, dy = {"left": (w * PAN_STEP, 0.0), "right": (-w * PAN_STEP, 0.0), "up": (0.0, -h * PAN_STEP), "down": (0.0, h * PAN_STEP)}[direction.lower()]
    return pan_by(doc, dx, dy)


def regen(doc, everywhere: bool) -> int:
    from app.doc import tableops as O

    d = doc.drawing
    space = doc.current_space
    n = 0
    for h in [h for h, e in d.ents.items() if e.kind == "table" and (everywhere or e.owner == space)]:
        before = d.ents[h].to_dict()
        probe = entity_from_dict(copy.deepcopy(before))
        try:
            O.recalc(d, probe)
        except Exception:
            continue
        if probe.to_dict() != before:
            O.recalc(d, d.modify(h))
            n += 1
    try:
        from app.display import state as dstate

        dstate._states.pop(doc, None)
    except Exception:
        pass
    doc.bump("regen")
    return n


def active_rec(d) -> dict:
    rec = d.tables["vports"].get("*Active")
    if rec is None or not rec.get("tiles"):
        raise ViewError("There is no active viewport configuration.")
    return rec


def current_index(doc) -> int:
    n = len(active_rec(doc.drawing)["tiles"])
    s = view_session(doc)
    s["tile"] = max(0, min(int(s.get("tile", 0)), n - 1))
    return s["tile"]


def sync(doc) -> None:
    rec = active_rec(doc.drawing)
    t = rec["tiles"][current_index(doc)]
    t["center"] = [doc.view["center"][0], doc.view["center"][1]]
    t["height"] = float(doc.view["height"])


def describe_tiles(doc) -> dict:
    d = doc.drawing
    sync(doc)
    rec = active_rec(d)
    cur = current_index(doc)
    tiles = []
    for i, t in enumerate(rec["tiles"]):
        tiles.append({"index": i + 1, "lowerLeft": list(t["lower_left"]), "upperRight": list(t["upper_right"]), "center": list(t["center"]), "height": t["height"], "aspect": t.get("aspect", 1.0), "current": i == cur})
    configs = [r["name"] for r in d.tables["vports"].values() if r["name"] != "*Active"]
    return {"tiles": tiles, "current": cur + 1, "configs": sorted(configs, key=LO.natural_key)}


def rects_for(rect, count: int, orient: str) -> list:
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    o = orient.lower()

    def rows(n, top=y1, hh=None, left=x0, ww=None):
        ww = w if ww is None else ww
        hh = h if hh is None else hh
        step = hh / n
        return [(left, top - (i + 1) * step, left + ww, top - i * step) for i in range(n)]

    def cols(n, bottom=y0, hh=None, left=x0, ww=None):
        ww = w if ww is None else ww
        hh = h if hh is None else hh
        step = ww / n
        return [(left + i * step, bottom, left + (i + 1) * step, bottom + hh) for i in range(n)]

    if count == 2:
        return cols(2) if o == "vertical" else rows(2)
    if o == "horizontal":
        return rows(count)
    if o == "vertical":
        return cols(count)
    small = count - 1
    big = 0.5 if count == 3 else 2.0 / 3.0
    if o == "above":
        return [(x0, y1 - h * big, x1, y1)] + cols(small, y0, h * (1 - big))
    if o == "below":
        return [(x0, y0, x1, y0 + h * big)] + cols(small, y0 + h * big, h * (1 - big))
    if o == "left":
        return [(x0, y0, x0 + w * big, y1)] + rows(small, y1, h, x0 + w * big, w * (1 - big))
    if o == "right":
        return rows(small, y1, h, x0, w * (1 - big)) + [(x0 + w * (1 - big), y0, x1, y1)]
    raise ViewError("Choose Horizontal, Vertical, Above, Below, Left or Right.")


def arrange(doc, count: int, orient: str = "") -> dict:
    d = doc.drawing
    if count not in (2, 3, 4):
        raise ViewError("Choose 2, 3 or 4 viewports.")
    orient = (orient or ("Vertical" if count == 2 else "Right")).strip()
    if orient.lower() not in [o.lower() for o in ORIENTS] or (count == 2 and orient.lower() not in ("horizontal", "vertical")):
        raise ViewError("Choose Horizontal or Vertical." if count == 2 else "Choose Horizontal, Vertical, Above, Below, Left or Right.")
    sync(doc)
    rec = copy.deepcopy(active_rec(d))
    cur = current_index(doc)
    t = rec["tiles"][cur]
    rect = (t["lower_left"][0], t["lower_left"][1], t["upper_right"][0], t["upper_right"][1])
    parts = rects_for(rect, count, orient)
    if any((p[2] - p[0]) < MIN_TILE or (p[3] - p[1]) < MIN_TILE for p in parts):
        raise ViewError("The current viewport is too small to divide.")
    if len(rec["tiles"]) - 1 + count > MAX_TILES:
        raise ViewError("There are too many viewports.")
    fresh = []
    for p in parts:
        fresh.append({"lower_left": [p[0], p[1]], "upper_right": [p[2], p[3]], "center": list(t["center"]), "height": t["height"], "aspect": (p[2] - p[0]) / max(p[3] - p[1], 1e-9)})
    rec["tiles"] = rec["tiles"][:cur] + fresh + rec["tiles"][cur + 1:]
    d.table_set("vports", rec)
    view_session(doc)["tile"] = cur
    return describe_tiles(doc)


def _area(t) -> float:
    return (t["upper_right"][0] - t["lower_left"][0]) * (t["upper_right"][1] - t["lower_left"][1])


def join(doc, dominant: int, other: int) -> dict:
    d = doc.drawing
    sync(doc)
    rec = copy.deepcopy(active_rec(d))
    n = len(rec["tiles"])
    if not (1 <= dominant <= n and 1 <= other <= n):
        raise ViewError("There is no such viewport.")
    if dominant == other:
        raise ViewError("Choose two different viewports.")
    a, b = rec["tiles"][dominant - 1], rec["tiles"][other - 1]
    x0 = min(a["lower_left"][0], b["lower_left"][0])
    y0 = min(a["lower_left"][1], b["lower_left"][1])
    x1 = max(a["upper_right"][0], b["upper_right"][0])
    y1 = max(a["upper_right"][1], b["upper_right"][1])
    if abs((x1 - x0) * (y1 - y0) - _area(a) - _area(b)) > 1e-9:
        raise ViewError("The selected viewports do not form a rectangle.")
    cur = current_index(doc)
    a["lower_left"], a["upper_right"] = [x0, y0], [x1, y1]
    a["aspect"] = (x1 - x0) / max(y1 - y0, 1e-9)
    del rec["tiles"][other - 1]
    d.table_set("vports", rec)
    di = dominant - 1 - (1 if other < dominant else 0)
    s = view_session(doc)
    if cur == other - 1 or cur == dominant - 1:
        s["tile"] = di
    else:
        s["tile"] = cur - (1 if other - 1 < cur else 0)
    return describe_tiles(doc)


def single(doc) -> dict:
    d = doc.drawing
    sync(doc)
    rec = copy.deepcopy(active_rec(d))
    t = rec["tiles"][current_index(doc)]
    t["lower_left"], t["upper_right"], t["aspect"] = [0.0, 0.0], [1.0, 1.0], 1.0
    rec["tiles"] = [t]
    d.table_set("vports", rec)
    view_session(doc)["tile"] = 0
    return describe_tiles(doc)


def set_current_tile(doc, number: int) -> dict:
    rec = active_rec(doc.drawing)
    if not 1 <= number <= len(rec["tiles"]):
        raise ViewError("There is no such viewport.")
    sync(doc)
    view_session(doc)["tile"] = number - 1
    t = rec["tiles"][number - 1]
    doc.view = {"center": [t["center"][0], t["center"][1]], "height": float(t["height"])}
    doc.request_view("tile", center=list(t["center"]), height=float(t["height"]), tile=number)
    return describe_tiles(doc)


def save_config(doc, name: str) -> tuple:
    d = doc.drawing
    name = str(name or "").strip()
    if not valid_view_name(name):
        raise ViewError('"%s" is not a valid viewport configuration name.' % name)
    sync(doc)
    old = d.tables["vports"].get(name)
    rec = {"name": old["name"] if old else name, "tiles": copy.deepcopy(active_rec(d)["tiles"]), "current": current_index(doc)}
    d.table_set("vports", rec)
    return rec, old is not None


def restore_config(doc, name: str) -> dict:
    d = doc.drawing
    src = d.tables["vports"].get(str(name).strip())
    if src is None or src["name"] == "*Active":
        raise ViewError('Could not find viewport configuration "%s".' % str(name).strip())
    rec = copy.deepcopy(active_rec(d))
    rec["tiles"] = copy.deepcopy(src["tiles"])
    d.table_set("vports", rec)
    cur = max(0, min(int(src.get("current", 0)), len(rec["tiles"]) - 1))
    s = view_session(doc)
    s["tile"] = cur
    t = rec["tiles"][cur]
    doc.view = {"center": [t["center"][0], t["center"][1]], "height": float(t["height"])}
    doc.request_view("tile", center=list(t["center"]), height=float(t["height"]), tile=cur + 1)
    return describe_tiles(doc)


def delete_configs(d, spec) -> list:
    pats = [s.strip() for s in (spec if isinstance(spec, (list, tuple)) else str(spec).split(",")) if str(s).strip()]
    gone = []
    for rec in list(d.tables["vports"].values()):
        if rec["name"] == "*Active":
            continue
        if any(fnmatch.fnmatchcase(rec["name"].casefold(), p.casefold()) for p in pats):
            gone.append(rec["name"])
    for n in gone:
        d.table_remove("vports", n)
    return gone
