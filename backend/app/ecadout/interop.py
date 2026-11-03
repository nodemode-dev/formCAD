import math
import os

from app.core import outputs
from app.ecadout import files, kicad
from app.ecadout import view as V
from app.pcb import store as PS

OFF = "KiCad file interop is off. Turn it on in the electronics settings first."
MAX_IMPORT_TRACKS = 20000
MAX_IMPORT_VIAS = 4000


def enabled(d) -> bool:
    return bool((files.link_header(d).get("kicad") or {}).get("enabled"))


def set_enabled(doc, flag: bool) -> dict:
    d = doc.drawing
    with doc.transaction("ECADKICAD"):
        link = files.link_header(d)
        link["kicad"] = {"enabled": bool(flag)}
        files.save_link(d, link)
    return {"enabled": bool(flag)}


def export_board(doc, out: str) -> dict:
    if not enabled(doc.drawing):
        raise V.OutputError(OFF)
    view = files.board_view(doc)
    try:
        target = outputs.checked(out, (".kicad_pcb",), ".kicad_pcb")
    except outputs.OutputRefused as err:
        raise V.OutputError(str(err))
    text = kicad.write_board(view)
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return {"file": target, "tracks": len(view["tracks"]), "vias": len(view["vias"]), "footprints": len({p.get("ref") for p in view["pads"] if p.get("ref")}), "note": "A subset of the board is written: outline, tracks, vias and footprint pads. Y is flipped to the file format's downward axis."}


def import_board(doc, path: str) -> dict:
    d = doc.drawing
    if not enabled(d):
        raise V.OutputError(OFF)
    raw = os.path.abspath(os.path.expanduser(str(path or "").strip()))
    if not raw.lower().endswith(".kicad_pcb") or not os.path.isfile(raw):
        raise V.OutputError("Choose an existing .kicad_pcb file.")
    if os.path.getsize(raw) > kicad.MAX_BYTES:
        raise V.OutputError("The file is larger than 8 MB.")
    try:
        with open(raw, "r", encoding="utf-8", errors="replace") as fh:
            got = kicad.read_board(fh.read())
    except kicad.KicadError as err:
        raise V.OutputError(str(err))
    loops, circles = kicad.chain(got["edge"]) if got["edge"] else ([], [])
    polys = []
    for run in loops:
        verts = kicad.loops_to_verts(run)
        pts = V.loop_points({"verts": verts}, 0.02)
        polys.append([[round(x, 6), round(y, 6)] for x, y in pts])
    if not polys:
        raise V.OutputError("The file has no closed board edge on Edge.Cuts.")
    polys.sort(key=lambda p: -abs(V.area([tuple(q) for q in p])))
    if len(got["tracks"]) > MAX_IMPORT_TRACKS or len(got["vias"]) > MAX_IMPORT_VIAS:
        raise V.OutputError("The file holds more tracks or vias than this import accepts.")
    skipped = 0
    with doc.transaction("ECADKICAD"):
        PS.set_outline(d, {"outline": polys[0], "cutouts": polys[1:]})
        h = PS.header(d)
        names = PS.copper_layers(h["board"]["layers"])
        for c in circles:
            PS.add_hole(d, {"x": c[1][0], "y": c[1][1], "drill": round(2 * c[2], 6)})
        for t in got["tracks"]:
            if t["layer"] in names and t["a"] != t["b"]:
                PS.add_track(d, t)
            else:
                skipped += 1
        for v in got["vias"]:
            if v["from"] in names and v["to"] in names and v["drill"] < v["dia"]:
                PS.add_via(d, v)
            else:
                skipped += 1
    return {"outline_points": len(polys[0]), "cutouts": len(polys) - 1, "holes": len(circles), "tracks": len(got["tracks"]), "vias": len(got["vias"]), "skipped": skipped, "footprints_in_file": got["footprints"], "note": "Footprints are not imported; place them from the netlist."}
