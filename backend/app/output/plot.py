import math
import os

from app.doc import layouts as L
from app.output import build, devices, pdfwrite, pngwrite, raster, request as R, svgwrite
from app.output.sheet import Sheet

MIMES = {"pdf": "application/pdf", "png": "image/png", "svg": "image/svg+xml"}


def _target(path, ext: str) -> str:
    from app.core import outputs

    try:
        return outputs.checked(str(path), (ext,), ext)
    except outputs.OutputRefused as err:
        raise R.PlotError(str(err))


def requests_of(raw):
    if not isinstance(raw, dict):
        raise R.PlotError("A plot request must be an object.")
    base = {k: v for k, v in raw.items() if k not in ("sheets",)}
    items = raw.get("sheets")
    if items is None:
        return [R.clean(base)]
    if not isinstance(items, list) or not items:
        raise R.PlotError("Sheets are a list of page options.")
    if len(items) > R.MAX_SHEETS:
        raise R.PlotError("A file holds at most 256 sheets.")
    out = []
    for it in items:
        if isinstance(it, str):
            it = {"layout": it}
        if not isinstance(it, dict):
            raise R.PlotError("A sheet is a layout name or an object.")
        merged = {**base, **it}
        merged.pop("layouts", None)
        if "layout" not in merged:
            raise R.PlotError("Every sheet names a layout.")
        source = merged.pop("file", None) if isinstance(it, dict) and "file" in it else None
        req = R.clean(merged)
        if source:
            req["file"] = str(source)
        out.append(req)
    return out


def source_doc(doc, path):
    from app.doc.document import Document
    from app.doc.service import service

    full = os.path.realpath(os.path.expanduser(str(path)))
    for d in list(service.docs.values()):
        if d.path and os.path.realpath(d.path) == full:
            return d
    if not os.path.isfile(full):
        raise R.PlotError('The drawing "%s" was not found.' % path)
    try:
        if os.path.splitext(full)[1].lower() == ".fcad":
            from app.doc import container

            drawing, _ = container.load(full)
        else:
            from app.interchange import files

            drawing, _, _ = files.read_any(full)
    except Exception as err:
        raise R.PlotError('The drawing "%s" could not be read: %s' % (os.path.basename(full), err))
    return Document(drawing, os.path.splitext(os.path.basename(full))[0], full, "drawing", drawing.metric)


def by_source(doc, reqs):
    groups = []
    for r in reqs:
        src = source_doc(doc, r["file"]) if r.get("file") else doc
        if groups and groups[-1][0] is src:
            groups[-1][1].append(r)
        else:
            groups.append((src, [r]))
    return groups


def output_of(reqs, raw):
    first = reqs[0]
    if first.get("output"):
        return first["output"]
    dev = devices.find(first.get("device")) if first.get("device") else None
    if dev is not None:
        return dev["output"]
    path = str(first.get("path", ""))
    ext = os.path.splitext(path)[1].lower().lstrip(".")
    return ext if ext in devices.OUTPUTS else "pdf"


def make_sheets(doc, reqs, output):
    d = doc.drawing
    names = []
    for r in reqs:
        for n in r["layouts"]:
            names.append((r, n))
    if not names:
        raise R.PlotError("Name at least one layout.")
    if len(names) > R.MAX_SHEETS:
        raise R.PlotError("A file holds at most 256 sheets.")
    want_text = output == "pdf" and all(r.get("text_mode", "text") == "text" for r in reqs)
    cache = build.Cache(doc, any(r.get("include_off") for r in reqs), want_text)
    sheets = []
    dev = None
    for r, name in names:
        dev = R.device_for(r, output)
        spec = R.resolve_sheet(d, r, name, dev)
        table = R.style_table(d, spec)
        spec["transparency"] = override_transparency(doc, spec["transparency"])
        sheets.append(build.SheetBuilder(doc, r, spec, table, cache, output).build())
    return sheets, dev


def override_transparency(doc, current):
    try:
        from app.sysvars import registry as sv

        mode = int(sv.get_var(doc, "PLOTTRANSPARENCYOVERRIDE"))
    except Exception:
        return current
    return {0: False, 2: True}.get(mode, current)


def info_of(sheets):
    return [{"name": s.name, "width": s.width, "height": s.height, "empty": s.empty, "ops": len(s.ops), "layers": len(s.layers), "links": len(s.links)} for s in sheets]


def render_bytes(sheets, output, reqs, dev):
    r = reqs[0]
    mw = r.get("min_width", R.MIN_WIDTH_DEFAULT)
    if output == "pdf":
        title = r.get("title") or "FormCAD plot"
        return pdfwrite.render(sheets, title=title, compress=r.get("compress", True), layers=r.get("layers", True), min_width=mw, links=r.get("hyperlinks", True))
    if len(sheets) != 1:
        raise R.PlotError("A %s file holds one sheet; use PDF for several." % output.upper())
    if output == "svg":
        return svgwrite.render(sheets[0], min_width=mw)
    dpi = r.get("dpi") or (dev["resolution"] if dev else 300)
    arr, used = raster.render(sheets[0], dpi)
    return pngwrite.encode(arr, used)


def run(doc, raw, output=None):
    reqs = requests_of(raw)
    out = output or output_of(reqs, raw)
    sheets, dev = [], None
    for src, group in by_source(doc, reqs):
        with src.lock:
            part, dev = make_sheets(src, group, out)
        sheets.extend(part)
    if len(sheets) > R.MAX_SHEETS:
        raise R.PlotError("A file holds at most 256 sheets.")
    data = render_bytes(sheets, out, reqs, dev)
    result = {"output": out, "mime": MIMES[out], "pages": info_of(sheets), "size": len(data), "device": dev["name"] if dev else "", "data": data}
    path = reqs[0].get("path")
    if path:
        full = _target(path, "." + out)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        result["path"] = full
    return result


def preview(doc, raw, long_side=1600):
    reqs = requests_of(raw)
    reqs = [reqs[0]]
    with doc.lock:
        sheets, dev = make_sheets(doc, reqs, "png")
    sh = sheets[0]
    inch = max(sh.width, sh.height) / 25.4
    dpi = max(50.0, min(300.0, long_side / inch))
    arr, used = raster.render(sh, dpi)
    data = pngwrite.encode(arr, used)
    return {"data": data, "mime": "image/png", "width": int(arr.shape[1]), "height": int(arr.shape[0]), "dpi": used, "paper": reqs[0].get("paper", {}).get("name") if isinstance(reqs[0].get("paper"), dict) else "", "sheet": {"name": sh.name, "width": sh.width, "height": sh.height, "printable": sh.printable}}


def export_svg(doc, raw):
    r = R.clean(raw)
    name = r["layouts"][0]
    d = doc.drawing
    out = "svg"
    with doc.lock:
        cache = build.Cache(doc, r.get("include_off", False), False)
        is_model = str(name).strip().casefold() == "model"
        ps = None if is_model else L.page_setup(d, name)
        if not is_model and L.find(d, name) is None:
            raise R.PlotError('Layout "%s" not found.' % name)
        unit = 1.0 if (d.metric or is_model and d.metric) else 25.4
        if not is_model:
            unit = L.unit_mm(d, ps)
        spec = {"name": "Model" if is_model else L.find(d, name)["name"], "model": is_model, "ps": ps, "width": 1.0, "height": 1.0, "paper": "", "landscape": True, "margins": [0.0] * 4, "printable": [0.0, 0.0, 1.0, 1.0], "unit": unit, "area": r.get("area", "extents" if is_model else "layout"), "window": r.get("window"), "fit": False, "scale": 1.0, "explicit_scale": True, "center": False, "offset": [0.0, 0.0], "lineweights": r.get("lineweights", True), "transparency": r.get("transparency", True), "display_styles": True, "style_table": ""}
        if not is_model and r.get("style_table") is None and ps and ps.get("display_styles"):
            spec["style_table"] = ps.get("style_table", "")
        if r.get("style_table") is not None:
            spec["style_table"] = r["style_table"]
        table = R.style_table(d, spec)
        sb = build.SheetBuilder(doc, r, spec, table, cache, out)
        key = "model" if is_model else "layout:" + spec["name"]
        src = cache.get(key)
        if is_model or spec["area"] != "layout":
            area = sb.area_model(src) if is_model else sb.area_from(src, spec)
            if spec["area"] != "window":
                pad = 0.02 * max(area[2] - area[0], area[3] - area[1], 1e-9)
                if area[2] - area[0] < 1e-12 and area[3] - area[1] < 1e-12:
                    area = [area[0] - 0.5, area[1] - 0.5, area[2] + 0.5, area[3] + 0.5]
                    pad = 0.0
                area = [area[0] - pad, area[1] - pad, area[2] + pad, area[3] + pad]
        else:
            wl, hl = L.sheet_units(d, ps)
            area = [0.0, 0.0, wl, hl]
        w, h = (area[2] - area[0]) * unit, (area[3] - area[1]) * unit
        if w > 100000.0 or h > 100000.0 or not (math.isfinite(w) and math.isfinite(h)):
            raise R.PlotError("The export area is too large.")
        spec["width"], spec["height"], spec["printable"] = w, h, [0.0, 0.0, w, h]
        sb.sheet = Sheet(spec["name"], w, h, spec["printable"])
        M = (unit, -area[0] * unit, -area[1] * unit)
        sb.draw_items(key, M)
        if sb.sheet.empty and is_model:
            raise R.PlotError("The plot area is empty.")
        data = svgwrite.render(sb.sheet, min_width=r.get("min_width", 0.0 if False else max(max(w, h) / 1500.0 if not r.get("lineweights", True) else R.MIN_WIDTH_DEFAULT, 0.001)))
    result = {"output": out, "mime": MIMES[out], "size": len(data), "data": data, "pages": info_of([sb.sheet])}
    path = r.get("path")
    if path:
        full = _target(path, ".svg")
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(data)
        result["path"] = full
    return result
