import copy
import os
import re
import tempfile
import zipfile

from app.core import guard, outputs
from app.ecadout import excellon, fromboard, gerber, idf
from app.ecadout import view as V
from app.pcb import store as PS
from app.services import kernel
from app.solid import work
from app.solid.work import SolidError

LINK = "ECAD_LINK"
DEFAULTS = {"mask_margin": 0.05, "paste_margin": 0.0, "tent_vias": True}


def restricted() -> bool:
    return bool(guard.CALLER.get())


def link_header(d) -> dict:
    raw = d.header.get(LINK)
    out = {"schema": 1, "export": dict(DEFAULTS), "outline_ref": None, "kicad": {"enabled": False}, "last": {}}
    if isinstance(raw, dict):
        for k, v in copy.deepcopy(raw).items():
            out[k] = v
        out["export"] = {**DEFAULTS, **(out.get("export") or {})}
    return out


def save_link(d, link: dict) -> None:
    d.set_header(LINK, copy.deepcopy(link))


def board_view(doc, options=None) -> dict:
    d = doc.drawing
    if not isinstance(d.header.get(PS.HEADER), dict):
        raise V.OutputError("This document has no board; open an electronics design with a board.")
    h = PS.header(d)
    from app.pcb import zones as Z

    raw = fromboard.view_of(h, Z.fill_all(h))
    raw["name"] = (d.header.get("ECAD") or {}).get("name") or getattr(doc, "name", "") or "board"
    opts = {**link_header(d)["export"], **{k: v for k, v in (options or {}).items() if v is not None}}
    for key, label in (("mask_margin", "mask"), ("paste_margin", "paste")):
        val = opts[key]
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not -1.0 <= val <= 1.0:
            raise V.OutputError("The %s margin is a number between -1 and 1 mm." % label)
    raw["mask_margin"] = opts["mask_margin"]
    raw["paste_margin"] = opts["paste_margin"]
    raw["tent_vias"] = bool(opts["tent_vias"])
    return V.clean(raw, restricted())


def prefix_of(out: str, view: dict) -> str:
    raw = os.path.expanduser(str(out or "").strip())
    if not raw or "\x00" in raw:
        raise V.OutputError("An output name is required.")
    full = os.path.abspath(raw)
    if os.path.isdir(full):
        return os.path.join(full, gerber.file_stem(view["name"]))
    root, ext = os.path.splitext(full)
    return root if ext else full


def path_for(prefix: str, label: str, ext: str, allowed: tuple) -> str:
    try:
        return outputs.checked(prefix + "-" + re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_") + ext, allowed)
    except outputs.OutputRefused as err:
        raise V.OutputError(str(err))


def write_text(path: str, text: str) -> None:
    with open(path, "w", encoding="ascii", errors="replace", newline="\n") as fh:
        fh.write(text)


def layer_report(name, lay) -> dict:
    return {"layer": name, "function": lay.function, "apertures": len(lay.aps), "flashes": lay.flashes, "draws": lay.draws, "regions": lay.regions}


def export_gerber(doc, out: str, as_zip: bool = False, options=None) -> dict:
    view = board_view(doc, options)
    layers = gerber.build(view)
    drills = excellon.build(view)
    report = {"layers": [layer_report(n, lay) for n, _e, lay in layers], "drills": [{"function": f["function"], "tools": f["tools"], "hits": f["hits"], "slots": f["slots"]} for f in drills], "files": []}
    if as_zip:
        try:
            target = outputs.checked(out, (".zip",), ".zip")
        except outputs.OutputRefused as err:
            raise V.OutputError(str(err))
        stem = gerber.file_stem(view["name"])
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            for n, ext, lay in layers:
                z.writestr("%s-%s%s" % (stem, re.sub(r"[^A-Za-z0-9_]+", "_", n).strip("_"), ext), lay.text())
            for f in drills:
                z.writestr("%s-%s.drl" % (stem, f["suffix"]), f["text"])
        report["files"] = [target]
        return report
    prefix = prefix_of(out, view)
    plan = [(path_for(prefix, n, ext, gerber.EXTENSIONS), lay.text()) for n, ext, lay in layers]
    plan += [(path_for(prefix, f["suffix"], ".drl", excellon.EXTENSIONS), f["text"]) for f in drills]
    for path, text in plan:
        write_text(path, text)
        report["files"].append(path)
    return report


def export_drill(doc, out: str, options=None) -> dict:
    view = board_view(doc, options)
    drills = excellon.build(view)
    prefix = prefix_of(out, view)
    plan = [(path_for(prefix, f["suffix"], ".drl", excellon.EXTENSIONS), f) for f in drills]
    for path, f in plan:
        write_text(path, f["text"])
    return {"drills": [{"function": f["function"], "tools": f["tools"], "hits": f["hits"], "slots": f["slots"], "file": p} for p, f in plan]}


def export_idf(doc, out: str, options=None) -> dict:
    view = board_view(doc, options)
    raw = os.path.expanduser(str(out or "").strip())
    if not raw:
        raise V.OutputError("An output name is required.")
    full = os.path.abspath(raw)
    base = os.path.join(full, gerber.file_stem(view["name"])) if os.path.isdir(full) else os.path.splitext(full)[0]
    try:
        emn = outputs.checked(base + ".emn", idf.EXTENSIONS)
        emp = outputs.checked(base + ".emp", idf.EXTENSIONS)
    except outputs.OutputRefused as err:
        raise V.OutputError(str(err))
    write_text(emn, idf.board(view))
    write_text(emp, idf.library(view))
    return {"board": emn, "library": emp, "components": len(view["components"]), "packages": len({(idf.package_name(c), idf.part_number(c)) for c in view["components"]})}


def body_params(view: dict) -> dict:
    loops = []
    for lp in view["outline"]["loops"]:
        loops.append({"outer": lp["outer"], "vertices": [list(v) for v in lp["verts"]]})
    holes = []
    for r in excellon.hits(view):
        if r["span"] == (1, len(view["layers"])):
            holes.append({"x": r["x"], "y": r["y"], "d": r["d"], "slot": r["slot"], "rot": r["rot"]})
    comps = [{"w": c["w"], "d": c["d"], "h": c["h"], "wx": c["wx"], "wy": c["wy"], "rot": c["rot"], "side": c["side"], "z0": c["z0"], "shape": c["shape"]} for c in view["components"]]
    return {"loops": loops, "thickness": view["thickness"], "holes": holes, "components": comps}


def build_body(view: dict) -> dict:
    try:
        return work.kcall("ecad_board_body", body_params(view), work.LONG)
    except SolidError as err:
        raise V.OutputError(str(err))


def free_shapes(*ids) -> None:
    got = [i for i in ids if i]
    if got:
        try:
            kernel.call("shape_free", {"ids": got}, 10.0)
        except Exception:
            pass


def board_summary(doc, options=None) -> dict:
    view = board_view(doc, options)
    res = build_body(view)
    free_shapes(res.get("board"), res.get("components"))
    s = res["board_summary"]
    return {"thickness": view["thickness"], "bbox": s["bbox"], "faces": s["faces"], "valid": s["valid"], "closed": s["closed"], "board_volume": res["board_volume"], "component_volume": res["component_volume"], "components": res["component_count"], "holes": len(body_params(view)["holes"])}


def board_mesh(doc, which: str = "board", detail: float = 1.0, options=None) -> tuple:
    view = board_view(doc, options)
    res = build_body(view)
    try:
        wid = res.get("components") if which == "components" else res.get("board")
        if not wid:
            raise V.OutputError("The board has no component bodies.")
        box = (res["board_summary"] or {}).get("bbox") or [0, 0, 0, 1, 1, 1]
        linear, angular = work.detail_params({"bbox": box}, detail)
        with tempfile.TemporaryDirectory(prefix="fcboard_") as tmp:
            path = os.path.join(tmp, "board.mesh")
            work.kcall("tessellate", {"id": wid, "linear": linear, "angular": angular, "path": path}, work.LONG)
            with open(path, "rb") as fh:
                return fh.read(), {"thickness": view["thickness"], "components": res["component_count"]}
    finally:
        free_shapes(res.get("board"), res.get("components"))


def export_step(doc, out: str, options=None) -> dict:
    view = board_view(doc, options)
    try:
        target = outputs.checked(out, (".step", ".stp"), ".step")
    except outputs.OutputRefused as err:
        raise V.OutputError(str(err))
    res = build_body(view)
    try:
        items = [{"id": res["board"], "name": "Board", "rgb": [0.1, 0.45, 0.2]}]
        if res.get("components"):
            items.append({"id": res["components"], "name": "Components", "rgb": [0.15, 0.15, 0.15]})
        work.kcall("save_step", {"path": target, "bodies": items, "schema": "ap214"}, work.LONG)
    finally:
        free_shapes(res.get("board"), res.get("components"))
    return {"file": target, "bodies": len(items), "components": res["component_count"]}
