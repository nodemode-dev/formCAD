import base64
import os
import time

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

EXPORT_KINDS = {".pdf": "pdf", ".png": "png", ".svg": "svg"}
FILE_KINDS = (".fcad", ".dxf", ".dwg", ".dwt")
MAX_PAGE = 5000
DEFAULT_PAGE = 500
SCRIPT_WAIT = 120.0


class OpError(Exception):
    pass


def document(doc_id: str = ""):
    try:
        if doc_id:
            return service.get(doc_id)
        doc = service.active() or (next(iter(service.docs.values()), None))
        if doc is None:
            raise OpError("No drawing is open. Open or create one first.")
        return doc
    except DocumentFault as err:
        raise OpError(err.message)


def guarded(fn):
    try:
        return fn()
    except DocumentFault as err:
        raise OpError(err.message)
    except CommandFailed as err:
        raise OpError(str(err))


def shape(state: dict) -> dict:
    out = {
        "ok": not state.get("error"),
        "error": state.get("error", ""),
        "prompt": state.get("prompt", ""),
        "active": bool(state.get("active")),
        "command": state.get("command", ""),
        "options": [o["key"] for o in state.get("options", [])],
        "output": state.get("output", []),
        "selection": state.get("selection", []),
        "rev": state.get("rev", 0),
    }
    if state.get("result") is not None:
        out["result"] = state["result"]
    if state.get("script") is not None:
        out["script"] = state["script"]
    return out


def execute(doc, name: str, args: dict | None = None) -> dict:
    return shape(doc.get_runner().run_command(str(name), dict(args or {})))


def type_line(doc, text: str) -> dict:
    return shape(doc.get_runner().submit(str(text)))


def send_point(doc, point) -> dict:
    return shape(doc.get_runner().submit_point([float(point[0]), float(point[1])], None))


def press(doc, key: str) -> dict:
    runner = doc.get_runner()
    if key.lower() in ("escape", "esc", "cancel"):
        return shape(runner.cancel())
    return shape(runner.submit(""))


def command_state(doc) -> dict:
    with doc.lock:
        runner = doc.get_runner()
        runner.begin_call()
        return shape(runner.state())


def run_script_text(doc, text: str, wait: float = SCRIPT_WAIT) -> dict:
    runner = doc.get_runner()
    state = runner.run_command("script", {"data": str(text)})
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        sc = state.get("script")
        if sc is None or sc.get("state") != "running":
            break
        time.sleep(0.02)
        with doc.lock:
            state = runner.state()
    out = shape(state)
    sc = state.get("script")
    if sc is not None and sc.get("state") == "paused":
        out["ok"] = False
        out["error"] = out["error"] or "The script stopped at line %d: %s" % (sc.get("line", 0), sc.get("note", ""))
    return out


def catalogue(filter_text: str = "") -> list:
    from app.cmd import registry

    registry.load_modules()
    needle = filter_text.strip().lower()
    items = []
    for spec in sorted(registry.COMMANDS.values(), key=lambda s: s.name):
        text = " ".join([spec.name, spec.label, " ".join(spec.aliases)]).lower()
        if needle and needle not in text:
            continue
        item = spec.entry()
        item["programmatic"] = spec.execute is not None
        item["id"] = spec.name
        items.append(item)
    return items


def _bounds(ent):
    try:
        b = ent.bounds()
    except Exception:
        return None
    if not b:
        return None
    return [float(b[0]), float(b[1]), float(b[2]), float(b[3])]


def _inside(box, win, crossing: bool) -> bool:
    if box is None:
        return False
    if crossing:
        return not (box[2] < win[0] or box[0] > win[2] or box[3] < win[1] or box[1] > win[3])
    return box[0] >= win[0] and box[2] <= win[2] and box[1] >= win[1] and box[3] <= win[3]


def query_entities(doc, kind: str = "", layer: str = "", selected: bool = False, window=None, crossing: bool = True, offset: int = 0, limit: int = DEFAULT_PAGE, handle: int | None = None, geometry: bool = True) -> dict:
    limit = max(1, min(int(limit), MAX_PAGE))
    offset = max(0, int(offset))
    win = None
    if window:
        v = [float(x) for x in window]
        if len(v) != 4:
            raise OpError("A window is four numbers: x1, y1, x2, y2.")
        win = [min(v[0], v[2]), min(v[1], v[3]), max(v[0], v[2]), max(v[1], v[3])]
    kinds = {k.strip().lower() for k in kind.split(",") if k.strip()} if kind else set()
    with doc.lock:
        d = doc.drawing
        chosen = set(doc.selection) if selected else None
        found = []
        if handle is not None:
            e = d.get(int(handle))
            found = [e] if e is not None else []
        else:
            for e in d.entities(doc.current_space):
                if chosen is not None and e.handle not in chosen:
                    continue
                if kinds and e.kind not in kinds:
                    continue
                if layer and e.layer.lower() != layer.lower():
                    continue
                if win is not None and not _inside(_bounds(e), win, crossing):
                    continue
                found.append(e)
        total = len(found)
        page = found[offset : offset + limit]
        rows = []
        for e in page:
            row = e.to_dict() if geometry else {"handle": e.handle, "kind": e.kind, "layer": e.layer}
            box = _bounds(e)
            if box is not None:
                row["bounds"] = box
            rows.append(row)
    return {"total": total, "returned": len(rows), "offset": offset, "entities": rows}


def find_text(doc, contains: str = "", layer: str = "", limit: int = 200) -> dict:
    needle = contains.lower()
    rows = []
    with doc.lock:
        for e in doc.drawing.entities(doc.current_space):
            if e.kind == "text":
                body = e.text
            elif e.kind == "mtext":
                body = e.contents
            else:
                continue
            if needle and needle not in body.lower():
                continue
            if layer and e.layer.lower() != layer.lower():
                continue
            rows.append({"handle": e.handle, "kind": e.kind, "text": body, "position": list(e.position), "height": e.height, "rotation": e.rotation, "style": e.style, "layer": e.layer})
    return {"total": len(rows), "texts": rows[: max(1, min(int(limit), MAX_PAGE))]}


def summary(doc) -> dict:
    with doc.lock:
        d = doc.drawing
        kinds: dict = {}
        for e in d.entities(doc.current_space):
            kinds[e.kind] = kinds.get(e.kind, 0) + 1
        box = d.extents(doc.current_space)
        info = doc.summary()
        info.update(
            {
                "kinds": kinds,
                "objects": sum(kinds.values()),
                "layers": [r["name"] for r in d.tables["layers"].to_list()],
                "blocks": [r["name"] for r in d.tables["blocks"].to_list() if not r.get("anonymous")],
                "layouts": [r["name"] for r in d.tables["layouts"].to_list()],
                "extents": [float(v) for v in box] if box else None,
                "selection": list(doc.selection),
                "currentLayer": d.current_layer(),
            }
        )
        return info


def selection(doc) -> list:
    return doc.get_runner().current_selection()


def select(doc, handles, mode: str = "set") -> list:
    if mode not in ("set", "add", "remove"):
        raise OpError("The selection mode is set, add or remove.")
    return doc.get_runner().set_selection([int(h) for h in handles], mode)


def variable(doc, name: str):
    from app.sysvars import registry as sv

    try:
        return sv.get_var(doc, name.upper())
    except Exception as err:
        raise OpError("Unknown system variable %s." % name.upper() if not str(err) else str(err))


def set_variable(doc, name: str, value):
    from app.sysvars import registry as sv

    try:
        return sv.set_var(doc, name.upper(), value)
    except Exception as err:
        raise OpError(str(err) or "The value was refused.")


def display_list(doc, space: str = "model") -> str:
    from app import display

    with doc.lock:
        try:
            return display.build(doc, None, space)
        except display.NoSuchSpace:
            raise OpError("No such space.")


def checked_output(path: str, allowed: tuple) -> str:
    full = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not path or os.path.isdir(full):
        raise OpError("An output file name is required.")
    ext = os.path.splitext(full)[1].lower()
    if ext not in allowed:
        raise OpError("That file type is not written here. Use one of: %s." % ", ".join(allowed))
    folder = os.path.dirname(full)
    if not os.path.isdir(folder):
        raise OpError("The folder %s does not exist." % folder)
    return full


def export(doc, path: str, version: str = "", window=None, view: str = "", layout: str = "Model", dpi: float | None = None, paper: str = "") -> dict:
    from app.interchange import files
    from app.interchange.errors import InterchangeError
    from app.output import plot
    from app.output import request as R

    full = checked_output(path, tuple(EXPORT_KINDS) + (".dxf", ".dwg"))
    granted(full)
    ext = os.path.splitext(full)[1].lower()
    if ext in (".dxf", ".dwg"):
        try:
            report = files.write_any(doc.drawing, full, version or "", False)
        except InterchangeError as err:
            raise OpError(str(err))
        return {"path": full, "format": ext[1:], "notes": report.to_dict()}
    raw = plot_request(layout, window, view, dpi, paper)
    raw["path"] = full
    try:
        res = plot.export_svg(doc, raw) if ext == ".svg" else plot.run(doc, raw, EXPORT_KINDS[ext])
    except R.PlotError as err:
        raise OpError(str(err))
    return {"path": res.get("path", full), "format": ext[1:], "size": res["size"], "pages": res["pages"]}


def plot_request(layout: str = "Model", window=None, view: str = "", dpi=None, paper: str = "") -> dict:
    raw: dict = {"layout": layout or "Model"}
    if window:
        raw["area"] = "window"
        raw["window"] = [float(v) for v in window]
    elif view == "extents" or not view:
        if str(layout or "Model").lower() == "model":
            raw["area"] = "extents"
    if dpi:
        raw["dpi"] = float(dpi)
    if paper:
        raw["paper"] = paper
    return raw


def render_png(doc, window=None, size: int = 1600) -> bytes:
    from app.output import plot
    from app.output import request as R

    size = max(200, min(int(size), 4000))
    box = [float(v) for v in window] if window else None
    if box is None:
        ext = doc.drawing.extents(doc.current_space)
        if not ext:
            raise OpError("The drawing is empty; there is nothing to render.")
        box = [float(v) for v in ext]
    w, h = max(box[2] - box[0], 1e-9), max(box[3] - box[1], 1e-9)
    long_mm = 200.0
    pw, ph = (long_mm, max(long_mm * h / w, 10.0)) if w >= h else (max(long_mm * w / h, 10.0), long_mm)
    raw = {"layout": "Model", "area": "window", "window": box, "width": pw, "height": ph, "landscape": w >= h, "margins": [0, 0, 0, 0], "fit": True, "dpi": max(50.0, min(2400.0, size / (long_mm / 25.4)))}
    try:
        return plot.run(doc, raw, "png")["data"]
    except R.PlotError as err:
        raise OpError(str(err))


def render_b64(doc, window=None, size: int = 1600) -> dict:
    data = render_png(doc, window, size)
    return {"mime": "image/png", "bytes": len(data), "data": base64.b64encode(data).decode("ascii")}


def granted(path: str) -> None:
    from app.cmd import barred

    why = barred.path_refusal(path)
    if why:
        raise OpError(why)


def open_path(path: str) -> dict:
    full = os.path.abspath(os.path.expanduser(str(path or "")))
    granted(full)
    if not os.path.isfile(full):
        raise OpError('Cannot find the file "%s".' % path)
    if os.path.splitext(full)[1].lower() not in FILE_KINDS + (".svg", ".svgz"):
        raise OpError("Open reads .fcad, .dxf, .dwg, .dwt and .svg files.")
    return guarded(lambda: service.open(full).summary())


def new_doc(name: str = "", template: str = "") -> dict:
    return guarded(lambda: service.new(name or "", template or "").summary())


def save_doc(doc, path: str = "") -> dict:
    if path:
        granted(checked_output(path, FILE_KINDS))
    return guarded(lambda: service.save(doc, path or "").summary())


def close_doc(doc, force: bool = False) -> dict:
    closed = service.close(doc, bool(force))
    return {"closed": closed, "dirty": doc.dirty and not closed}
