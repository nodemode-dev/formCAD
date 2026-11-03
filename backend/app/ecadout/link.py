import contextlib
import hashlib
import json
import math
import os

from app.doc.entities import LwPolyline
from app.doc.service import DocumentFault, service
from app.ecadout import files
from app.ecadout import view as V
from app.param import sketch as K
from app.param import store as S
from app.param import units as U
from app.part import tree as ptree
from app.pcb import store as PS
from app.solid import work
from app.solid.work import SolidError

MAX_HOLES_FROM_FACE = 64
SKETCH = "BoardOutline"


def part_document(doc_id: str, base=None):
    text = str(doc_id)
    try:
        if text.lower().endswith(".fcad"):
            full = os.path.expanduser(text)
            if not os.path.isabs(full) and base is not None and getattr(base, "path", ""):
                full = os.path.join(os.path.dirname(os.path.abspath(base.path)), full)
            if not os.path.isfile(full):
                raise V.OutputError("The part file %s does not exist." % text)
            got = service.open(full)
        else:
            got = service.get(text)
    except DocumentFault as err:
        raise V.OutputError(err.message)
    if got is base:
        raise V.OutputError("A board cannot link to itself.")
    if got.kind not in ("part", "assembly"):
        raise V.OutputError("The linked document is a %s document; link a part." % got.kind)
    return got


def pick_body(d, handle=None):
    bodies = [e for e in d.ents.values() if getattr(e, "kind", "") == "solidbody"]
    if not bodies:
        raise V.OutputError("The part has no solid body to take an outline from.")
    if handle is not None:
        for b in bodies:
            if b.handle == int(handle):
                return b
        raise V.OutputError("The part has no body with handle %s." % handle)

    def size(b):
        box = (b.summary or {}).get("bbox") or [0, 0, 0, 0, 0, 0]
        return (box[3] - box[0]) * (box[4] - box[1]) * (box[5] - box[2])

    return max(bodies, key=size)


def fingerprint(body) -> str:
    return hashlib.sha256(json.dumps([body.blob, [round(v, 9) for v in body.offset]]).encode()).hexdigest()[:20]


def clean_ref(raw: dict) -> dict:
    raw = dict(raw or {})
    ref = {"doc": str(raw.get("doc") or "").strip(), "body": raw.get("body"), "face": raw.get("face"), "normal": [float(v) for v in (raw.get("normal") or [0.0, 0.0, 1.0])], "which": raw.get("which") or "highest", "offset": [float(v) for v in (raw.get("offset") or [0.0, 0.0])], "hole_max": float(raw.get("hole_max", 6.0)), "tolerance": float(raw.get("tolerance", 0.02)), "origin": raw.get("origin") or "keep"}
    if not ref["doc"]:
        raise V.OutputError("Name the enclosure part document with doc.")
    if ref["face"] is not None:
        ref["face"] = int(ref["face"])
    if len(ref["normal"]) != 3 or not all(math.isfinite(v) for v in ref["normal"]) or math.sqrt(sum(v * v for v in ref["normal"])) < 1e-9:
        raise V.OutputError("normal is three numbers.")
    if len(ref["offset"]) != 2 or not all(math.isfinite(v) for v in ref["offset"]):
        raise V.OutputError("offset is [dx, dy] in millimetres.")
    if not 0.001 <= ref["tolerance"] <= 1.0:
        raise V.OutputError("tolerance is between 0.001 and 1 mm.")
    if ref["origin"] not in ("keep", "bbox_min"):
        raise V.OutputError("origin is keep or bbox_min.")
    if ref["which"] not in ("highest", "lowest"):
        raise V.OutputError("which is highest or lowest.")
    return ref


def read_outline(ref: dict, base=None) -> dict:
    part = part_document(ref["doc"], base)
    with part.lock:
        d = part.drawing
        body = pick_body(d, ref.get("body"))
        wid = work.worker_id(d, body)
        params = {"id": wid, "tolerance": ref["tolerance"]}
        if ref["face"] is not None:
            params["face"] = ref["face"]
        else:
            params["normal"] = ref["normal"]
            params["which"] = ref["which"]
        try:
            res = work.kcall("ecad_face_outline", params, work.LONG)
        except SolidError as err:
            raise V.OutputError(str(err))
        return {"result": res, "fingerprint": fingerprint(body), "body": body.handle}


def shift_loops(loops, dx, dy):
    return [{"outer": lp["outer"], "verts": [[v[0] + dx, v[1] + dy, v[2]] for v in lp["verts"]], "circle": lp.get("circle")} for lp in loops]


def polygon_of(lp, tol):
    pts = V.loop_points({"verts": lp["verts"]}, tol)
    out = [[round(x, 6), round(y, 6)] for x, y in pts]
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def sync_from_part(doc, raw_ref=None, tx=True) -> dict:
    d = doc.drawing
    link = files.link_header(d)
    ref = clean_ref(raw_ref if raw_ref is not None else link.get("outline_ref"))
    got = read_outline(ref, doc)
    res = got["result"]
    loops = res["loops"]
    dx, dy = ref["offset"]
    if ref["origin"] == "bbox_min":
        xs = [x for x, _y in V.loop_points(loops[0])]
        ys = [y for _x, y in V.loop_points(loops[0])]
        dx, dy = dx - min(xs), dy - min(ys)
    loops = shift_loops(loops, dx, dy)
    outer = loops[0]
    cuts, holes = [], []
    for lp in loops[1:]:
        c = lp.get("circle")
        if c and 2.0 * c["r"] <= ref["hole_max"] and len(holes) < MAX_HOLES_FROM_FACE:
            holes.append({"x": round(c["c"][0], 6), "y": round(c["c"][1], 6), "drill": round(2.0 * c["r"], 6)})
        else:
            cuts.append(lp)
    poly = polygon_of(outer, ref["tolerance"])
    cut_polys = [polygon_of(lp, ref["tolerance"]) for lp in cuts]
    approx = bool(res.get("approximated")) or any(abs(v[2]) > 1e-12 for lp in [outer] + cuts for v in lp["verts"])
    with (doc.transaction("ECADLINK") if tx else contextlib.nullcontext()):
        old = PS.header(d)
        for hid in link.get("hole_ids") or []:
            rec = PS.find(old, "holes", hid)
            if rec is not None:
                PS.remove_record(d, "holes", hid)
        PS.set_outline(d, {"outline": poly, "cutouts": cut_polys})
        have = [(r["x"], r["y"], r["drill"]) for r in PS.header(d)["holes"]]
        fresh = [h for h in holes if not any(abs(h["x"] - x) < 0.05 and abs(h["y"] - y) < 0.05 and abs(h["drill"] - k) < 0.05 for x, y, k in have)]
        matched = len(holes) - len(fresh)
        made = [PS.add_hole(d, dict(h, plated=False))["id"] for h in fresh]
        link = files.link_header(d)
        link["outline_ref"] = {k: v for k, v in ref.items()}
        link["hole_ids"] = made
        link["source_loops"] = {"outline": poly, "outer": outer["verts"], "cuts": [lp["verts"] for lp in cuts]}
        link["last"] = {"pulled": {"fingerprint": got["fingerprint"], "body": got["body"], "area": res["area"], "outline_points": len(poly), "cutouts": len(cut_polys), "holes": len(made), "arcs_flattened": approx, "tolerance": ref["tolerance"]}}
        files.save_link(d, link)
    return {"outline_points": len(poly), "cutouts": len(cut_polys), "holes": len(made), "holes_matched": matched, "arcs_flattened": approx, "tolerance": ref["tolerance"], "face_area": res["area"], "fingerprint": got["fingerprint"]}


def status(doc) -> dict:
    d = doc.drawing
    link = files.link_header(d)
    ref = link.get("outline_ref")
    if not ref:
        return {"linked": False, "stale": False}
    out = {"linked": True, "ref": ref, "last": link.get("last", {}), "stale": False}
    try:
        part = part_document(ref["doc"], doc)
    except V.OutputError as err:
        out["problem"] = str(err)
        return out
    with part.lock:
        try:
            body = pick_body(part.drawing, ref.get("body"))
        except V.OutputError as err:
            out["problem"] = str(err)
            return out
        now = fingerprint(body)
    then = ((link.get("last") or {}).get("pulled") or {}).get("fingerprint")
    out["stale"] = now != then
    out["fingerprint"] = now
    return out


def link_set(doc, raw_ref: dict) -> dict:
    ref = clean_ref(raw_ref)
    part = part_document(ref["doc"], doc)
    with part.lock:
        pick_body(part.drawing, ref.get("body"))
    d = doc.drawing
    with doc.transaction("ECADLINK"):
        link = files.link_header(d)
        link["outline_ref"] = ref
        link["last"] = {}
        files.save_link(d, link)
    return {"linked": True, "ref": ref}


def unlink(doc) -> dict:
    d = doc.drawing
    with doc.transaction("ECADLINK"):
        link = files.link_header(d)
        link["outline_ref"] = None
        link["hole_ids"] = []
        link["source_loops"] = None
        link["last"] = {}
        files.save_link(d, link)
    return {"linked": False}


def exact_loops(doc, view):
    link = files.link_header(doc.drawing)
    src = link.get("source_loops")
    if not src:
        return None
    poly = [[round(v[0], 6), round(v[1], 6)] for v in view["outline"]["loops"][0]["verts"]]
    if poly != src.get("outline"):
        return None
    return [{"outer": True, "verts": src["outer"]}] + [{"outer": False, "verts": v} for v in src["cuts"]]


def push_to_part(doc, doc_id: str, plane_z: float = 0.0, name: str = SKETCH) -> dict:
    view = files.board_view(doc)
    exact = exact_loops(doc, view)
    loops = exact if exact is not None else view["outline"]["loops"]
    ox, oy = 0.0, 0.0
    part = part_document(doc_id, doc)
    with part.lock:
        if part.get_runner().run is not None:
            raise V.OutputError("A command is running in the part; finish it first.")
        d = part.drawing
        scale = U.mm_per_unit(d)
        with part.transaction("ECADLINKPUSH"):
            space = ptree.sketch_space(name)
            existing = S.get_sketch(d, name)

            def make(lp):
                return LwPolyline(vertices=[{"p": [(v[0] + ox) / scale, (v[1] + oy) / scale], "bulge": float(v[2]) if len(v) > 2 else 0.0, "sw": 0.0, "ew": 0.0} for v in lp["verts"]], closed=True)

            if existing is None:
                handles = [d.add_entity(make(lp)) for lp in loops]
                ptree.create_sketch(part, name, "XY", plane_z / scale, entities=handles)
                action = "created"
            else:
                sp = existing.get("space") or space
                for h in list(d.spaces.get(sp, [])):
                    d.erase_entity(h)
                d.ensure_space(sp)
                handles = [d.add_entity(make(lp), sp) for lp in loops]
                K.add_entities(d, name, handles)
                ptree.after_edit(part)
                action = "updated"
    return {"sketch": name, "action": action, "loops": len(loops), "arcs_kept": exact is not None, "plane_z": plane_z}
