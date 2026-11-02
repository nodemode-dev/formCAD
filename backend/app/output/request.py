import math

from app.doc import layouts as L
from app.doc import papers
from app.output import devices, plotstyle

LIMIT = 1e12
AREAS = ("extents", "display", "limits", "window", "layout")
TEXT_MODES = ("text", "geometry")
MAX_SHEETS = 256
MAX_LINKS = 2000
MIN_WIDTH_DEFAULT = 0.05


class PlotError(Exception):
    pass


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
    raise PlotError("%s must be yes or no." % what)


def _pair(v, what, bound):
    try:
        a = [float(x) for x in v]
    except (TypeError, ValueError):
        raise PlotError("%s must be two numbers." % what)
    if len(a) != 2 or not all(math.isfinite(x) and abs(x) <= bound for x in a):
        raise PlotError("%s must be two finite numbers." % what)
    return a


def check_window(w):
    try:
        a = [float(x) for x in w]
    except (TypeError, ValueError):
        raise PlotError("A window is four numbers.")
    if len(a) != 4 or not all(math.isfinite(x) and abs(x) <= LIMIT for x in a):
        raise PlotError("A window is four finite numbers within 1e12.")
    x0, x1 = sorted((a[0], a[2]))
    y0, y1 = sorted((a[1], a[3]))
    big = max(abs(x0), abs(x1), abs(y0), abs(y1), 1.0)
    floor = max(1e-9 * big, 1e-9)
    if x1 - x0 < floor or y1 - y0 < floor:
        raise PlotError("The window has no size.")
    return [x0, y0, x1, y1]


def clean(raw):
    if not isinstance(raw, dict):
        raise PlotError("A plot request must be an object.")
    out = {}
    layouts = raw.get("layouts")
    if layouts is None:
        layouts = [raw.get("layout", "Model")]
    if isinstance(layouts, str):
        layouts = [layouts]
    if not isinstance(layouts, list) or not layouts:
        raise PlotError("Name at least one layout.")
    if len(layouts) > MAX_SHEETS:
        raise PlotError("A file holds at most 256 sheets.")
    out["layouts"] = [str(x) for x in layouts]
    for key, label in (("landscape", "Landscape"), ("fit", "Fit"), ("center", "Center"), ("lineweights", "Lineweights"), ("transparency", "Transparency"), ("compress", "Compress"), ("layers", "Layers"), ("include_off", "Include off layers"), ("hyperlinks", "Hyperlinks"), ("display_styles", "Display styles")):
        if raw.get(key) is not None:
            out[key] = _bool(raw[key], label)
    if raw.get("scale") is not None:
        try:
            out["scale"] = L.parse_plot_scale(raw["scale"])
        except L.LayoutError as err:
            raise PlotError(str(err))
    if raw.get("offset") is not None:
        out["offset"] = _pair(raw["offset"], "The offset", 100000.0)
    if raw.get("margins") is not None:
        try:
            m = [float(v) for v in raw["margins"]]
        except (TypeError, ValueError):
            raise PlotError("Margins are four numbers.")
        if len(m) != 4 or not all(math.isfinite(v) and 0.0 <= v <= 1000.0 for v in m):
            raise PlotError("Margins are four numbers between 0 and 1000 millimetres.")
        out["margins"] = m
    if raw.get("window") is not None:
        out["window"] = check_window(raw["window"])
    if raw.get("area") is not None:
        a = str(raw["area"]).strip().casefold()
        if a not in AREAS:
            raise PlotError("The plot area is extents, display, limits, window or layout.")
        out["area"] = a
    if out.get("area") == "window" and "window" not in out:
        raise PlotError("A window plot needs its two corners.")
    paper = raw.get("paper")
    if raw.get("width") is not None or raw.get("height") is not None:
        try:
            w, h = float(raw["width"]), float(raw["height"])
        except (KeyError, TypeError, ValueError):
            raise PlotError("A custom paper needs a width and a height in millimetres.")
        if not papers.sane(w, h):
            raise PlotError("The paper sides are between 0 and 5080 millimetres.")
        out["custom_paper"] = (w, h)
    elif paper:
        rec = papers.lookup(paper)
        if rec is None:
            raise PlotError('Paper "%s" is not known.' % paper)
        out["paper"] = rec
    for key in ("device", "style_table", "title", "path", "text_mode", "output"):
        if raw.get(key) is not None:
            out[key] = str(raw[key])
    if "text_mode" in out and out["text_mode"] not in TEXT_MODES:
        raise PlotError("The text mode is text or geometry.")
    if "output" in out and out["output"] not in devices.OUTPUTS:
        raise PlotError("The output is pdf, png or svg.")
    if raw.get("dpi") is not None:
        try:
            dpi = float(raw["dpi"])
        except (TypeError, ValueError):
            raise PlotError("The resolution is a number from 50 to 2400.")
        if not 50 <= dpi <= 2400:
            raise PlotError("The resolution is a number from 50 to 2400.")
        out["dpi"] = dpi
    if raw.get("min_width") is not None:
        try:
            mw = float(raw["min_width"])
        except (TypeError, ValueError):
            raise PlotError("The minimum line width is a number of millimetres.")
        if not 0.001 <= mw <= 2.0:
            raise PlotError("The minimum line width is between 0.001 and 2 millimetres.")
        out["min_width"] = mw
    if raw.get("view") is not None:
        v = raw["view"]
        try:
            c = [float(x) for x in v["center"]]
            ht = float(v["height"])
            wd = float(v.get("width", 0.0) or 0.0)
        except (KeyError, TypeError, ValueError):
            raise PlotError("A view is a centre and a height.")
        if len(c) != 2 or not all(math.isfinite(x) for x in c) or not math.isfinite(ht) or ht <= 0:
            raise PlotError("A view is a centre and a positive height.")
        out["view"] = {"center": c, "height": ht, "width": wd if math.isfinite(wd) and wd > 0 else 0.0}
    links = raw.get("links")
    if links is not None:
        if not isinstance(links, list):
            raise PlotError("Links are a list of handle and URL pairs.")
        out["links"] = []
        for it in links[:MAX_LINKS]:
            try:
                out["links"].append((int(it["handle"]), str(it["url"])))
            except (KeyError, TypeError, ValueError):
                raise PlotError("A link needs a handle and a URL.")
    return out


def device_for(req, output_hint=None):
    name = req.get("device")
    dev = devices.find(name) if name else None
    if name and dev is None and str(name).strip().casefold() not in ("", "none"):
        dev = None
    if dev is None:
        out = req.get("output") or output_hint or "pdf"
        dev = devices.default_for(out)
    return dev


def layout_exists(d, name):
    return str(name).strip().casefold() == "model" or L.find(d, name) is not None


def resolve_sheet(d, req, name, dev):
    is_model = str(name).strip().casefold() == "model"
    if not is_model and L.find(d, name) is None:
        raise PlotError('Layout "%s" not found.' % name)
    spec = {"name": "Model" if is_model else L.find(d, name)["name"], "model": is_model}
    ps = None if is_model else L.page_setup(d, name)
    spec["ps"] = ps
    if "custom_paper" in req:
        lo, hi = sorted(req["custom_paper"])
        pw, ph, paper_name = lo, hi, papers.custom_name(lo, hi)
        margins = None
    elif "paper" in req:
        r = req["paper"]
        pw, ph, paper_name = min(r["width"], r["height"]), max(r["width"], r["height"]), r["name"]
        margins = None
        dp = devices.paper_of(dev, paper_name)
        if dp is not None:
            margins = dp["margins"]
    elif ps is not None:
        pw, ph = sorted((ps["width"], ps["height"]))
        paper_name = ps["paper"]
        margins = ps["margins"]
    else:
        dp = devices.paper_of(dev, dev["paper"]) or dev["papers"][0]
        if d.metric:
            dp = devices.paper_of(dev, "ISO A4 (210.00 x 297.00 MM)") or dp
        else:
            dp = devices.paper_of(dev, "ANSI A (8.50 x 11.00 Inches)") or dp
        pw, ph, paper_name = dp["width"], dp["height"], dp["name"]
        margins = dp["margins"]
    if "margins" in req:
        margins = req["margins"]
    if margins is None:
        margins = [0.0, 0.0, 0.0, 0.0]
    if "landscape" in req:
        landscape = req["landscape"]
    elif ps is not None:
        landscape = bool(ps["landscape"])
    else:
        landscape = dev["orientation"] == "landscape"
    w, h = (ph, pw) if landscape else (pw, ph)
    if margins[0] + margins[2] >= w or margins[1] + margins[3] >= h:
        raise PlotError("The margins leave no printable area.")
    spec.update({"width": w, "height": h, "paper": paper_name, "landscape": landscape, "margins": list(margins)})
    spec["printable"] = [margins[0], margins[1], w - margins[2], h - margins[3]]
    if is_model:
        spec["unit"] = 1.0 if d.metric else 25.4
    else:
        spec["unit"] = L.unit_mm(d, ps)
    if "area" in req:
        spec["area"] = req["area"] if not is_model or req["area"] != "layout" else "extents"
    else:
        spec["area"] = "extents" if is_model else "layout"
    if is_model and spec["area"] == "layout":
        spec["area"] = "extents"
    spec["window"] = req.get("window") or (ps["window"] if ps and ps["window"] and ps["window"][2] != ps["window"][0] else None)
    if spec["area"] == "window" and spec["window"] is None:
        raise PlotError("A window plot needs its two corners.")
    fit_default = True if is_model else False
    spec["fit"] = req.get("fit", fit_default)
    spec["scale"] = req.get("scale") if "scale" in req else (ps["scale"] if ps else 1.0)
    if "scale" in req:
        spec["fit"] = req.get("fit", False)
    spec["explicit_scale"] = "scale" in req
    spec["center"] = req.get("center", True if is_model else False)
    spec["offset"] = req.get("offset", [0.0, 0.0])
    spec["lineweights"] = req.get("lineweights", ps["plot_lineweights"] if ps else True)
    spec["transparency"] = req.get("transparency", ps["transparency"] if ps else False)
    spec["display_styles"] = req.get("display_styles", ps["display_styles"] if ps else True)
    style_name = req["style_table"] if "style_table" in req else (ps["style_table"] if ps else "")
    spec["style_table"] = style_name
    return spec


def placement(spec, area):
    x0, y0, x1, y1 = area
    w, h = x1 - x0, y1 - y0
    px0, py0, px1, py1 = spec["printable"]
    pw, ph = px1 - px0, py1 - py0
    if w <= 0 and h <= 0:
        raise PlotError("The plot area is empty.")
    w, h = max(w, h * 1e-9), max(h, w * 1e-9)
    if spec["fit"]:
        s = min(pw / w, ph / h)
    elif spec["area"] == "layout" and not spec["explicit_scale"]:
        s = spec["unit"]
    else:
        s = float(spec["scale"]) * spec["unit"]
    if not math.isfinite(s) or s <= 0:
        s = min(pw / w, ph / h)
    if spec["model"] or spec["area"] != "layout" or spec["fit"] or spec["explicit_scale"]:
        if spec["center"]:
            tx = px0 + (pw - w * s) / 2.0 - x0 * s
            ty = py0 + (ph - h * s) / 2.0 - y0 * s
        else:
            ox, oy = spec["offset"]
            tx = px0 + ox - x0 * s
            ty = py0 + oy - y0 * s
    else:
        tx, ty = spec["offset"][0], spec["offset"][1]
        tx -= x0 * s
        ty -= y0 * s
    return s, tx, ty


def style_table(d, spec):
    name = spec.get("style_table")
    if str(name or "").strip().casefold() in plotstyle.NONE_NAMES:
        return None
    return plotstyle.find(d, name)
