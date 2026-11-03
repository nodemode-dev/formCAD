import math

from app.bodies import multibody
from app.core import guard
from app.mold import settings
from app.mold.settings import MoldError
from app.solid import work
from app.solid.work import SolidError

LAYER = "Mold"
ROLES = ("core", "cavity", "block", "parting_surface", "shut_offs", "part_shrunk")
NAMES = {"core": "Mold core", "cavity": "Mold cavity", "block": "Mold block", "parting_surface": "Parting surface", "shut_offs": "Shut-off surfaces", "part_shrunk": "Part with shrinkage"}
AGENT_GRID = 5


def cfg_of(d, args: dict) -> dict:
    base = settings.current(d)
    base.pop("defined", None)
    given = {k: v for k, v in (args or {}).items() if k in base and v is not None}
    return settings.merge(base, given) if given else base


def is_product(e) -> bool:
    return e.kind == "solidbody" and (e.source or {}).get("op") == "mold"


def products(d) -> list:
    return [e for e in d.ents.values() if is_product(e)]


def source_body(doc, handle):
    d = doc.drawing
    if handle:
        e = multibody.solid(d, handle)
        if is_product(e):
            raise MoldError("Body %s is a mold product; pick the part." % handle)
        return e
    from app.part import rebuild, store

    if store.has_part(d):
        try:
            rebuild.ensure_built(doc)
        except Exception:
            pass
        h = int(store.tree(d).get("body") or 0)
        if h and h in d.ents and d.ents[h].kind == "solidbody":
            return d.ents[h]
    found = [e for e in d.ents.values() if e.kind == "solidbody" and not is_product(e)]
    if len(found) == 1:
        return found[0]
    if not found:
        raise MoldError("The document has no solid body to build a mold for.")
    raise MoldError("The document has %d solid bodies; set the part body in the mold settings (body handle)." % len(found))


def call(method, params, timeout=work.LONG):
    try:
        return work.kcall(method, params, timeout)
    except SolidError as err:
        raise MoldError(str(err))


def free(wids) -> None:
    ids = [w for w in wids if w]
    if ids:
        try:
            work.kcall("shape_free", {"ids": ids}, 10.0)
        except SolidError:
            pass


def centre_mm(d, body) -> list:
    bb = (body.summary or {}).get("bbox")
    if not bb:
        return [0.0, 0.0, 0.0]
    s = work.mm(d)
    off = [float(c) * s for c in body.offset]
    return [(bb[0] + bb[3]) / 2.0 + off[0], (bb[1] + bb[4]) / 2.0 + off[1], (bb[2] + bb[5]) / 2.0 + off[2]]


def prepared(d, body, cfg):
    wid = work.worker_id(d, body)
    f = settings.factors(cfg["shrink"])
    info = {"factors": f, "convention": cfg["shrink"]["convention"], "percent": cfg["shrink"]["percent"], "scaled": any(abs(x - 1.0) > 1e-12 for x in f)}
    if not info["scaled"]:
        return wid, None, info
    s = work.mm(d)
    origin = cfg["shrink"]["origin"]
    o = centre_mm(d, body) if origin is None else [float(c) * s for c in origin]
    res = call("md_shrink", {"id": wid, "factors": f, "origin": o})
    info["origin"] = [c / s for c in o]
    info["volume_before"] = res["volume_before"] / s ** 3
    info["volume_after"] = res["volume"] / s ** 3
    return res["id"], res["id"], info


def grid_of(cfg) -> int:
    g = int(cfg["grid"])
    return min(g, AGENT_GRID) if guard.CALLER.get() else g


def pts_units(rows, s):
    return [[[c / s for c in q] for q in poly] for poly in rows]


def analyze(doc, args) -> dict:
    d = doc.drawing
    cfg = cfg_of(d, args)
    body = source_body(doc, cfg["body"])
    s = work.mm(d)
    wid, temp, info = prepared(d, body, cfg)
    try:
        res = call("md_analyze", {"id": wid, "pull": cfg["pull"], "min_draft": cfg["min_draft"], "grid": grid_of(cfg), "undercut": True})
    finally:
        free([temp])
    ids = list(body.face_ids)
    faces = []
    for r in res["faces"]:
        r = dict(r)
        r["pid"] = ids[r["face"]] if r["face"] < len(ids) else None
        r["area"] = r["area"] / s ** 2
        faces.append(r)
    total = res["area"] / s ** 2
    by = {k: v / s ** 2 for k, v in res["area_by_class"].items()}
    out = {
        "body": body.handle,
        "pull": res["pull"],
        "min_draft": res["min_draft"],
        "grid": res["grid"],
        "shrink": info,
        "legend": {"ok": "draft at or above the minimum, blue", "steep": "draft below the minimum, yellow", "undercut": "blocked along the pull, red"},
        "faces": faces,
        "area": total,
        "area_by_class": by,
        "percent_by_class": {k: (100.0 * v / total if total else 0.0) for k, v in by.items()},
        "faces_by_class": res["faces_by_class"],
        "undercut_faces": res["undercut_faces"],
        "steep_faces": res["steep_faces"],
        "straddle_faces": res["straddle_faces"],
        "ok": not res["undercut_faces"],
        "ms": res["ms"],
    }
    return out


def parting(doc, args, prep=None) -> dict:
    d = doc.drawing
    cfg = cfg_of(d, args)
    body = source_body(doc, cfg["body"])
    s = work.mm(d)
    wid, temp, info = prep or prepared(d, body, cfg)
    try:
        params = {"id": wid, "pull": cfg["pull"], "min_draft": cfg["min_draft"], "grid": grid_of(cfg)}
        if cfg["height"] is not None:
            params["height"] = cfg["height"] * s
        res = call("md_parting", params)
    finally:
        if prep is None:
            free([temp])
    out = {
        "body": body.handle,
        "pull": res["pull"],
        "height": res["height"] / s,
        "height_source": res["height_source"],
        "planar": res["planar"],
        "spread": res["spread"] / s,
        "range": [c / s for c in res["range"]],
        "shrink": info,
        "edges": res["edges"],
        "wires": [{"edges": w["edges"], "closed": w["closed"], "length": w["length"] / s, "polylines": pts_units(w["polylines"], s)} for w in res["wires"]],
        "outline": [{"area": l["area"] / s ** 2, "length": l["length"] / s, "centre": [c / s for c in l["centre"]]} for l in res["section_outer"]],
        "through_holes": [{"area": l["area"] / s ** 2, "length": l["length"] / s, "diameter": l["equivalent_diameter"] / s, "centre": [c / s for c in l["centre"]]} for l in res["through_holes"]],
        "wrong_side": res["wrong_side"],
        "notes": res["notes"],
        "ok": res["planar"] and not res["wrong_side"],
        "ms": res["ms"],
    }
    return out


def default_margins(d, body, cfg) -> dict:
    s = work.mm(d)
    bb = (body.summary or {}).get("bbox")
    diag = math.sqrt(sum((bb[i + 3] - bb[i]) ** 2 for i in range(3))) if bb else 50.0
    base = max(5.0, 0.2 * diag) / s
    cap = max(50.0, 5.0 * diag) / s
    for key in ("margin", "cavity_margin", "core_margin"):
        if cfg[key] is not None and cfg[key] > cap:
            raise settings.MoldError("The %s is larger than 5 times the part diagonal (%g); use a smaller value." % (key.replace("_", " "), cap))
    return {"margin": base if cfg["margin"] is None else cfg["margin"], "cavity_margin": base if cfg["cavity_margin"] is None else cfg["cavity_margin"], "core_margin": base if cfg["core_margin"] is None else cfg["core_margin"]}


def clear(d) -> list:
    gone = []
    for e in products(d):
        d.erase_entity(e.handle)
        gone.append(e.handle)
    return gone


def make_body(d, piece, role, source_name):
    if piece is None:
        return None
    body = work.new_body(d, piece["id"], piece["summary"], NAMES[role], {"op": "mold", "role": role, "from": source_name})
    body.layer = LAYER
    d.add_entity(body, "model")
    return body.handle


def block(doc, args) -> dict:
    d = doc.drawing
    cfg = cfg_of(d, args)
    body = source_body(doc, cfg["body"])
    s = work.mm(d)
    wid, temp, info = prepared(d, body, cfg)
    try:
        m = default_margins(d, body, cfg)
        res = call("md_block", {"id": wid, "pull": cfg["pull"], "margin": m["margin"] * s, "cavity_margin": m["cavity_margin"] * s, "core_margin": m["core_margin"] * s})
    finally:
        free([temp])
    for e in [e for e in products(d) if (e.source or {}).get("role") == "block"]:
        d.erase_entity(e.handle)
    handle = make_body(d, res, "block", body.name or "Body")
    return {"block": handle, "size": [c / s for c in res["size"]], "volume": res["volume"] / s ** 3, "part_volume": res["part_volume"] / s ** 3, "margins": m, "shrink": info}


def check_units(c, s) -> dict:
    out = {k: (c[k] / s ** 3 if k in ("block", "part", "core", "cavity", "sum", "residual", "overlap") else c[k]) for k in c}
    out["unit_cubed"] = True
    return out


def split(doc, args) -> dict:
    d = doc.drawing
    cfg = cfg_of(d, args)
    keep_block = bool((args or {}).get("keep_block", False))
    body = source_body(doc, cfg["body"])
    s = work.mm(d)
    prep = prepared(d, body, cfg)
    wid, temp, info = prep
    temps = [temp]
    try:
        pt = parting(doc, args, prep)
        height = pt["height"] if cfg["height"] is None else cfg["height"]
        m = default_margins(d, body, cfg)
        res = call("md_split", {"id": wid, "pull": cfg["pull"], "height": height * s, "margin": m["margin"] * s, "cavity_margin": m["cavity_margin"] * s, "core_margin": m["core_margin"] * s})
        temps += [res[k]["id"] for k in ("block", "core", "cavity", "parting_surface", "shut_offs") if res.get(k)]
    except Exception:
        free(temps)
        raise
    chk = check_units(res["check"], s)
    name = body.name or "Body"
    gone = clear(d)
    made = {}
    keep = {"core": res["core"], "cavity": res["cavity"], "parting_surface": res.get("parting_surface"), "shut_offs": res.get("shut_offs")}
    if keep_block:
        keep["block"] = res["block"]
    used = set()
    for role, piece in keep.items():
        h = make_body(d, piece, role, name)
        if h:
            made[role] = h
            used.add(piece["id"])
    if info["scaled"] and bool((args or {}).get("keep_part", True)):
        made["part_shrunk"] = make_body(d, {"id": prep[0], "summary": call("shape_summary", {"id": prep[0]})["summary"]}, "part_shrunk", name)
        used.add(prep[0])
    free([t for t in temps if t not in used])
    pieces = {}
    for k in ("core", "cavity", "block"):
        pieces[k] = {"solids": res[k]["summary"]["solids"], "valid": res[k]["summary"]["valid"], "faces": res[k]["summary"]["faces"], "volume": res[k]["volume"] / s ** 3}
    out = {
        "body": body.handle,
        "height": height,
        "parting": {"planar": pt["planar"], "wires": len(pt["wires"]), "through_holes": len(pt["through_holes"]), "wrong_side": len(pt["wrong_side"]), "notes": pt["notes"]},
        "shrink": info,
        "bodies": made,
        "replaced": gone,
        "pieces": pieces,
        "check": chk,
        "shut_offs": [{"area": r["area"] / s ** 2, "diameter": r["equivalent_diameter"] / s, "centre": [c / s for c in r["centre"]]} for r in res["shut_off_faces"]],
        "block_size": [c / s for c in res["block_size"]],
        "margins": m,
        "ok": bool(chk["ok"]) and all(pieces[k]["solids"] == 1 and pieces[k]["valid"] for k in ("core", "cavity")),
        "ms": res["ms"],
    }
    settings.store_result(d, {"split": {"height": height, "bodies": made, "check": chk, "shut_offs": out["shut_offs"], "shrink": {"percent": info["percent"], "convention": info["convention"], "factors": info["factors"]}, "ok": out["ok"]}})
    return out


def report(doc) -> dict:
    d = doc.drawing
    last = settings.last_result(d)
    live = {}
    for e in products(d):
        live[(e.source or {}).get("role")] = e.handle
    return {"settings": settings.current(d), "result": last, "products": live}
