import copy
import math
import re

from app.doc import papers
from app.doc import tables as T
from app.doc.model import SPACE_MODEL, layout_space

BAD_CHARS = set('<>/\\":;?*|,=`')
MAX_NAME = 255
PLOT_AREAS = ("layout", "extents", "display", "window", "limits")
MAX_OFFSET = 100000.0
MAX_MARGIN = 1000.0
SETUP_KEYS = ("device", "paper", "width", "height", "landscape", "margins", "plot_area", "window", "fit", "scale", "scale_text", "offset", "center", "style_table", "plot_lineweights", "display_styles", "transparency", "paper_mm")


class LayoutError(Exception):
    pass


def records(d) -> list:
    return sorted(d.tables["layouts"].values(), key=lambda r: (r.get("tab_order", 0), r["name"].casefold()))


def names(d) -> list:
    return [r["name"] for r in records(d)]


def find(d, name):
    return d.tables["layouts"].get(str(name).strip())


def check_name(d, name: str, ignore: str = "") -> str:
    n = str(name)
    if not n.strip():
        return "A layout name cannot be empty."
    if len(n) > MAX_NAME:
        return "A layout name is at most 255 characters."
    if any(c in BAD_CHARS or ord(c) < 32 for c in n):
        return "A layout name cannot contain any of < > / \\ \" : ; ? * | , = `."
    if n.strip().casefold() == "model":
        return 'The name "Model" is reserved.'
    other = find(d, n.strip())
    if other is not None and other["name"].casefold() != str(ignore).casefold():
        return 'A layout named "%s" already exists.' % other["name"]
    return ""


def first_free(d) -> str:
    i = 1
    while find(d, "Layout%d" % i) is not None:
        i += 1
    return "Layout%d" % i


def copy_name(d, src: str) -> str:
    base = re.sub(r"\s*\(\d+\)$", "", src)
    i = 2
    while find(d, "%s (%d)" % (base, i)) is not None:
        i += 1
    return "%s (%d)" % (base, i)


def default_setup(metric: bool) -> dict:
    ps = copy.deepcopy(T.new_layout("x", 1, metric)["page_setup"])
    if metric:
        ps["width"], ps["height"] = 297.0, 210.0
        ps["margins"] = [5.0, 5.0, 5.0, 5.0]
    else:
        ps["width"], ps["height"] = 279.4, 215.9
        ps["margins"] = [6.35, 6.35, 6.35, 6.35]
    ps["paper"] = papers.name_for_size(ps["width"], ps["height"])
    ps["landscape"] = True
    ps["scale_text"] = "1:1"
    ps["offset"] = [0.0, 0.0]
    return ps


def normalize(d, ps: dict) -> dict:
    base = default_setup(d.metric)
    out = {**base, **copy.deepcopy(ps or {})}
    w, h = papers.clamp_record(out["width"], out["height"])
    lo, hi = min(w, h), max(w, h)
    out["width"], out["height"] = (hi, lo) if out["landscape"] else (lo, hi)
    out["margins"] = _margins(out["margins"], out["width"], out["height"], base["margins"])
    if not out.get("paper"):
        out["paper"] = papers.name_for_size(out["width"], out["height"])
    return out


def _margins(raw, w, h, fallback) -> list:
    try:
        m = [float(v) for v in raw]
    except (TypeError, ValueError):
        return list(fallback)
    if len(m) != 4 or not all(math.isfinite(v) and 0.0 <= v <= MAX_MARGIN for v in m):
        return list(fallback)
    if m[0] + m[2] >= w or m[1] + m[3] >= h:
        return list(fallback) if fallback[0] + fallback[2] < w and fallback[1] + fallback[3] < h else [0.0, 0.0, 0.0, 0.0]
    return m


def page_setup(d, name: str) -> dict:
    rec = find(d, name)
    if rec is None:
        raise LayoutError('Layout "%s" not found.' % name)
    return normalize(d, rec.get("page_setup"))


def sheet_size(ps: dict) -> tuple:
    w, h = papers.clamp_record(ps.get("width"), ps.get("height"))
    lo, hi = min(w, h), max(w, h)
    return (hi, lo) if ps.get("landscape", True) else (lo, hi)


def printable(ps: dict) -> list:
    w, h = sheet_size(ps)
    m = ps.get("margins") or [0.0, 0.0, 0.0, 0.0]
    return [m[0], m[1], w - m[2], h - m[3]]


def unit_mm(d, ps: dict) -> float:
    return 1.0 if d.metric or ps.get("paper_mm", True) else 25.4


def sheet_units(d, ps: dict) -> tuple:
    k = unit_mm(d, ps)
    w, h = sheet_size(ps)
    return w / k, h / k


def printable_units(d, ps: dict) -> list:
    k = unit_mm(d, ps)
    return [v / k for v in printable(ps)]


def parse_plot_scale(text) -> float:
    if isinstance(text, bool):
        raise LayoutError("Enter a scale such as 1:50.")
    if isinstance(text, (int, float)):
        v = float(text)
    else:
        t = str(text).strip()
        m = re.match(r"^([0-9]*\.?[0-9]+)\s*[:=]\s*([0-9]*\.?[0-9]+)$", t)
        if m:
            a, b = float(m.group(1)), float(m.group(2))
            if a <= 0 or b <= 0:
                raise LayoutError("The scale must be above zero.")
            v = a / b
        else:
            try:
                v = float(t)
            except ValueError:
                raise LayoutError("Enter a scale such as 1:50 or 0.02.")
    if not math.isfinite(v) or v <= 0:
        raise LayoutError("The scale must be above zero.")
    return v


def scale_text_of(v: float) -> str:
    if v >= 1.0 - 1e-12:
        return "%s:1" % ("%.6f" % v).rstrip("0").rstrip(".")
    return "1:%s" % ("%.6f" % (1.0 / v)).rstrip("0").rstrip(".")


def _bool(v, what):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)) and v in (0, 1):
        return bool(v)
    s = str(v).strip().casefold()
    if s in ("yes", "y", "true", "on", "1"):
        return True
    if s in ("no", "n", "false", "off", "0"):
        return False
    raise LayoutError("%s must be yes or no." % what)


def apply_changes(d, ps: dict, changes: dict) -> dict:
    out = normalize(d, ps)
    ch = dict(changes)
    orient = ch.pop("orientation", None)
    if orient is not None:
        o = str(orient).strip().casefold()
        if o not in ("landscape", "portrait"):
            raise LayoutError("Orientation is landscape or portrait.")
        ch["landscape"] = o == "landscape"
    for key in ch:
        if key not in SETUP_KEYS:
            raise LayoutError("Unknown page setup field %s." % key)
    if "paper" in ch:
        rec = papers.lookup(ch["paper"])
        if rec is None:
            raise LayoutError('Paper "%s" is not known.' % ch["paper"])
        out["paper"] = rec["name"]
        out["width"], out["height"] = rec["width"], rec["height"]
        if "width" in ch or "height" in ch:
            raise LayoutError("Give a paper name or a width and height, not both.")
    if "width" in ch or "height" in ch:
        try:
            w = float(ch.get("width", out["width"] if out["landscape"] else out["height"]))
            h = float(ch.get("height", out["height"] if out["landscape"] else out["width"]))
        except (TypeError, ValueError):
            raise LayoutError("The paper size must be numbers in millimetres.")
        if not papers.sane(w, h):
            raise LayoutError("The paper sides are between 0 and 5080 millimetres.")
        out["width"], out["height"] = w, h
        out["paper"] = papers.name_for_size(w, h)
    if "landscape" in ch:
        out["landscape"] = _bool(ch["landscape"], "Landscape")
    lo, hi = min(out["width"], out["height"]), max(out["width"], out["height"])
    out["width"], out["height"] = (hi, lo) if out["landscape"] else (lo, hi)
    if "margins" in ch:
        try:
            m = [float(v) for v in ch["margins"]]
        except (TypeError, ValueError):
            raise LayoutError("Margins are four numbers: left, bottom, right, top.")
        if len(m) != 4 or not all(math.isfinite(v) and 0.0 <= v <= MAX_MARGIN for v in m):
            raise LayoutError("Margins are four numbers between 0 and 1000 millimetres.")
        out["margins"] = m
    if out["margins"][0] + out["margins"][2] >= out["width"] or out["margins"][1] + out["margins"][3] >= out["height"]:
        raise LayoutError("The margins leave no printable area.")
    if "plot_area" in ch:
        a = str(ch["plot_area"]).strip().casefold()
        if a not in PLOT_AREAS:
            raise LayoutError("The plot area is layout, extents, display, window or limits.")
        out["plot_area"] = a
    if "window" in ch:
        try:
            w4 = [float(v) for v in ch["window"]]
        except (TypeError, ValueError):
            raise LayoutError("A window is four numbers.")
        if len(w4) != 4 or not all(math.isfinite(v) for v in w4):
            raise LayoutError("A window is four numbers.")
        out["window"] = w4
    if "scale" in ch:
        v = parse_plot_scale(ch["scale"])
        out["scale"] = v
        out["scale_text"] = ch["scale"] if isinstance(ch["scale"], str) and ":" in ch["scale"] else scale_text_of(v)
    if "scale_text" in ch and "scale" not in ch:
        out["scale"] = parse_plot_scale(ch["scale_text"])
        out["scale_text"] = str(ch["scale_text"])
    if "offset" in ch:
        try:
            o = [float(v) for v in ch["offset"]]
        except (TypeError, ValueError):
            raise LayoutError("The offset is two numbers in millimetres.")
        if len(o) != 2 or not all(math.isfinite(v) and abs(v) <= MAX_OFFSET for v in o):
            raise LayoutError("The offset is two numbers within 100000 millimetres.")
        out["offset"] = o
    for key, label in (("fit", "Fit"), ("center", "Center"), ("plot_lineweights", "Lineweights"), ("display_styles", "Display styles"), ("transparency", "Transparency"), ("paper_mm", "Paper in millimetres")):
        if key in ch:
            out[key] = _bool(ch[key], label)
    for key in ("device", "style_table"):
        if key in ch:
            out[key] = str(ch[key]).strip()
            if len(out[key]) > 255:
                raise LayoutError("The name is too long.")
    return out


def set_page_setup(d, name: str, changes: dict) -> dict:
    rec = find(d, name)
    if rec is None:
        raise LayoutError('Layout "%s" not found.' % name)
    new = apply_changes(d, rec.get("page_setup"), changes)
    rec = d.modify_record("layouts", rec["name"])
    rec["page_setup"] = new
    return copy.deepcopy(new)


def renumber(d) -> None:
    for i, r in enumerate(records(d), 1):
        if r.get("tab_order") != i:
            d.modify_record("layouts", r["name"])["tab_order"] = i


def create(d, name: str = "", setup: dict | None = None) -> dict:
    n = (name or "").strip() or first_free(d)
    err = check_name(d, n)
    if err:
        raise LayoutError(err)
    rec = T.new_layout(n, len(d.tables["layouts"]) + 1, d.metric)
    rec["page_setup"] = normalize(d, setup) if setup else default_setup(d.metric)
    d.table_set("layouts", rec)
    d.ensure_space(layout_space(n))
    renumber(d)
    return d.tables["layouts"].get(n)


def copy_layout(d, src: str, new: str = "") -> dict:
    rec = find(d, src)
    if rec is None:
        raise LayoutError('Layout "%s" not found.' % src)
    n = (new or "").strip() or copy_name(d, rec["name"])
    err = check_name(d, n)
    if err:
        raise LayoutError(err)
    fresh = copy.deepcopy(rec)
    fresh["name"] = n
    fresh["tab_order"] = len(d.tables["layouts"]) + 1
    d.table_set("layouts", fresh)
    space = layout_space(n)
    d.ensure_space(space)
    ids = {}
    for e in list(d.entities(layout_space(rec["name"]))):
        c = e.copy_as_new()
        if c.kind == "viewport":
            c.clip_source = 0
            ids[c.vp_id] = c
        d.add_entity(c, space)
    renumber(d)
    return d.tables["layouts"].get(n)


def delete(d, name: str) -> str:
    rec = find(d, name)
    if rec is None:
        raise LayoutError('Layout "%s" not found.' % name)
    if len(d.tables["layouts"]) <= 1:
        raise LayoutError("The last layout cannot be deleted.")
    space = layout_space(rec["name"])
    for h in list(d.spaces.get(space, ())):
        d.erase_entity(h)
    d._rec_space(space)
    d.spaces.pop(space, None)
    d.table_remove("layouts", rec["name"])
    renumber(d)
    return rec["name"]


def rename(d, old: str, new: str) -> dict:
    rec = find(d, old)
    if rec is None:
        raise LayoutError('Layout "%s" not found.' % old)
    n = str(new).strip()
    err = check_name(d, n, ignore=rec["name"])
    if err:
        raise LayoutError(err)
    if n == rec["name"]:
        return rec
    o_space, n_space = layout_space(rec["name"]), layout_space(n)
    fresh = copy.deepcopy(rec)
    fresh["name"] = n
    for h in list(d.spaces.get(o_space, ())):
        d.modify(h).owner = n_space
    d._rec_space(o_space)
    d._rec_space(n_space)
    d.spaces[n_space] = d.spaces.pop(o_space, [])
    d.table_remove("layouts", rec["name"])
    d.table_set("layouts", fresh)
    for v in d.tables["views"].values():
        if str(v.get("layout", "")).casefold() == rec["name"].casefold():
            d.modify_record("views", v["name"])["layout"] = n
    return d.tables["layouts"].get(n)


def move(d, name: str, index: int) -> list:
    rec = find(d, name)
    if rec is None:
        raise LayoutError('Layout "%s" not found.' % name)
    order = [r["name"] for r in records(d) if r["name"] != rec["name"]]
    order.insert(max(0, min(int(index), len(order))), rec["name"])
    for i, nm in enumerate(order, 1):
        r = d.tables["layouts"].get(nm)
        if r.get("tab_order") != i:
            d.modify_record("layouts", nm)["tab_order"] = i
    return names(d)


def tab_label(doc) -> str:
    tab = doc.tab
    return "Model" if tab == SPACE_MODEL else tab.split(":", 1)[1]


def heal(doc) -> str:
    d = doc.drawing
    tab = doc.tab
    if tab != SPACE_MODEL and tab not in d.spaces:
        hint = int(getattr(doc, "tab_hint", 0) or 0)
        pick = None
        for r in records(d):
            if r.get("tab_order") == hint:
                pick = r
        doc.tab = layout_space(pick["name"]) if pick else SPACE_MODEL
        doc.active_vp = 0
        doc.vp_max = 0
        _enter_view(doc, doc.tab)
    return doc.tab


def effective_space(doc) -> str:
    tab = heal(doc)
    if doc.active_vp:
        vp = doc.drawing.ents.get(doc.active_vp)
        if vp is None or vp.kind != "viewport" or vp.owner != tab:
            doc.active_vp = 0
            doc.vp_max = 0
        else:
            return SPACE_MODEL
    return tab


def _default_layout_view(doc, tab: str) -> dict:
    d = doc.drawing
    rec = d.tables["layouts"].get(tab.split(":", 1)[1])
    ps = normalize(d, rec.get("page_setup") if rec else None)
    w, h = sheet_units(d, ps)
    return {"center": [w / 2.0, h / 2.0], "height": h * 1.08}


def _enter_view(doc, tab: str) -> None:
    saved = doc.space_views.get(tab)
    if saved is None and tab != SPACE_MODEL:
        rec = doc.drawing.tables["layouts"].get(tab.split(":", 1)[1])
        saved = rec.get("view") if rec else None
    if saved is None:
        saved = _default_layout_view(doc, tab) if tab != SPACE_MODEL else doc.view
    doc.view = {"center": [saved["center"][0], saved["center"][1]], "height": saved["height"]}


def switch(doc, target: str) -> str:
    d = doc.drawing
    t = str(target or "").strip()
    if t.casefold() in ("", "model"):
        tab = SPACE_MODEL
    else:
        rec = find(d, t)
        if rec is None:
            raise LayoutError('Layout "%s" not found.' % t)
        tab = layout_space(rec["name"])
    old = heal(doc)
    if tab == old and not doc.active_vp:
        return tab
    if doc.vp_max:
        from app.doc import vpmax

        vpmax.restore_view(doc)
    saved = {"center": [doc.view["center"][0], doc.view["center"][1]], "height": doc.view["height"]}
    doc.space_views[old] = saved
    if old != SPACE_MODEL:
        rec_old = d.tables["layouts"].get(old.split(":", 1)[1])
        if rec_old is not None:
            rec_old["view"] = dict(saved)
    doc.tab = tab
    doc.active_vp = 0
    doc.vp_max = 0
    if tab != SPACE_MODEL:
        doc.tab_hint = d.tables["layouts"].get(tab.split(":", 1)[1]).get("tab_order", 0)
    _enter_view(doc, tab)
    announce(doc)
    return tab


def announce(doc) -> None:
    doc.request_view("space", center=[doc.view["center"][0], doc.view["center"][1]], height=doc.view["height"], space=doc.tab, viewport=doc.active_vp, maximized=doc.vp_max)


def listing(doc) -> list:
    d = doc.drawing
    out = []
    for r in records(d):
        ps = normalize(d, r.get("page_setup"))
        space = layout_space(r["name"])
        w, h = sheet_size(ps)
        out.append({"name": r["name"], "order": r.get("tab_order", 0), "paper": ps["paper"], "width": w, "height": h, "landscape": ps["landscape"], "viewports": sum(1 for e in d.entities(space) if e.kind == "viewport"), "objects": len(d.spaces.get(space, ())), "current": doc.tab == space})
    return out
