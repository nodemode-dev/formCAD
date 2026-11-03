import math
import os
import re

from app.core import guard
from app.interchange import fileunits
from app.interchange.errors import InterchangeError, Report
from app.param.units import LENGTH_MM, mm_per_unit
from app.pmi import geo, store as pmi_store
from app.solid import work

STEP_EXT = (".step", ".stp")
IGES_EXT = (".iges", ".igs")
SCHEMAS = ("ap203", "ap214", "ap242")
KERNEL_UNIT = {"mm": "mm", "cm": "cm", "m": "m", "in": "inch", "ft": "foot", "um": "micron"}
INSUNITS = {"in": 1, "ft": 2, "mm": 4, "cm": 5, "m": 6, "km": 7, "mil": 9}
MAX_BODIES = 5000
MACRO_BODIES = 200
SCHEMA_NAME = {"ap203": "AP203 (CONFIG_CONTROL_DESIGN)", "ap214": "AP214 (automotive design, IS)", "ap242": "AP242 (DIS schema, OCCT 8.0.1, not edition 3)"}
LAYER_BAD = re.compile(r'[<>/\\":;?*|=`,]')


def body_cap() -> int:
    return MACRO_BODIES if guard.CALLER.get() else MAX_BODIES


def clean_layer(name: str) -> str:
    return LAYER_BAD.sub("_", str(name or "0")).strip()[:80] or "0"


def read_into(path: str, kind: str, report: Report, target=None, options=None):
    from app.doc.model import Drawing

    options = options or {}
    info = fileunits.inspect_file(path, target)
    file_key = info["unit"] or "mm"
    d = Drawing(True if target is None else target.metric)
    if target is not None:
        d.header["INSUNITS"] = target.header.get("INSUNITS", 4)
        doc_key, doc_mm = fileunits.document_unit(d)
    else:
        doc_key = file_key if file_key in INSUNITS else "mm"
        d.header["INSUNITS"] = INSUNITS[doc_key]
        d.metric = doc_key not in ("in", "ft")
        doc_mm = LENGTH_MM[doc_key]
    choice = str(options.get("unit_choice") or "convert").lower()
    if choice not in ("convert", "keep"):
        raise InterchangeError("The unit choice is convert or keep.", "badoption")
    mismatch = abs(LENGTH_MM[file_key] - doc_mm) > 1e-9 * max(doc_mm, 1.0)
    keep = mismatch and choice == "keep"
    want_pmi = bool(options.get("pmi", True)) and kind in STEP_EXT
    kunit = file_key if keep else "mm"
    if kunit not in KERNEL_UNIT:
        kunit = "mm"
    try:
        res = work.kcall("xde_read", {"path": path, "unit": KERNEL_UNIT[kunit], "pmi": want_pmi}, work.LONG)
    except work.SolidError as err:
        raise InterchangeError(str(err), "kernel")
    cap = body_cap()
    if len(res["bodies"]) > cap:
        raise InterchangeError("The file holds %d bodies; this caller may import at most %d." % (len(res["bodies"]), cap), "toomany")
    sizes = []
    for b in res["bodies"]:
        box = (b.get("summary") or {}).get("bbox")
        ext = max((abs(box[i + 3] - box[i]) for i in range(3)), default=0.0) * LENGTH_MM[kunit] if box and all(isinstance(x, (int, float)) and math.isfinite(x) for x in box) else None
        if ext is None or ext > 1e8:
            try:
                work.kcall("shape_free", {"ids": [x["id"] for x in res["bodies"]]}, 10.0)
            except work.SolidError:
                pass
            raise InterchangeError("A body in the file has no usable size (its unit factor is zero, negative or absurd). The file is refused; check the length unit in the STEP header.", "badunit")
        sizes.append((b.get("name") or "A body", ext))
    for name, ext in sizes:
        if ext < 1e-3 or ext > 1e6:
            report.warn('"%s" measures %.4g mm across; check the length unit of the file.' % (name, ext))
    stem = os.path.splitext(os.path.basename(path))[0]
    handles = []
    layers_seen = set()
    paths_seen = set()
    colour_n = 0
    for i, b in enumerate(res["bodies"]):
        wid = b["id"]
        if keep and doc_mm != 1.0:
            try:
                moved = work.kcall("transform", {"id": wid, "scale": doc_mm}, work.LONG)
            except work.SolidError as err:
                raise InterchangeError(str(err), "kernel")
            wid, summary = moved["id"], moved["summary"]
        else:
            summary = b["summary"]
        name = b.get("name") or "%s %d" % (stem, i + 1)
        source = {"op": "import", "file": stem, "format": kind[1:], "path": list(b.get("path") or []), "def": b.get("def") or ""}
        body = work.new_body(d, wid, summary, name, source, b.get("rgb"))
        layers = [clean_layer(x) for x in (b.get("layers") or [])]
        body.layer = layers[0] if layers else "0"
        if len(layers) > 1:
            source["layers"] = layers
            report.warn('"%s" is on %d layers (%s); only the first is kept as its layer.' % (name, len(layers), ", ".join(layers)))
        if layers:
            layers_seen.add(body.layer)
        if b.get("path"):
            paths_seen.add(tuple(b["path"]))
        if b.get("rgb"):
            colour_n += 1
        d.add_entity(body, "model")
        handles.append(body)
    scale_pmi = 1.0 if keep else 1.0 / doc_mm
    pmi = read_pmi(d, res, handles, scale_pmi, report) if want_pmi else {"read": 0, "kept": 0, "not_recovered": [], "detail": []}
    report.note("%d 3D bod%s read; units: file %s, document %s." % (len(handles), "y" if len(handles) == 1 else "ies", file_key, doc_key))
    if info.get("schema"):
        report.note("File schema: %s." % info["schema"].strip())
    if layers_seen:
        report.note("%d layer%s read: %s." % (len(layers_seen), "" if len(layers_seen) == 1 else "s", ", ".join(sorted(layers_seen)[:8])))
    if paths_seen:
        report.note("Assembly structure read: %d assembl%s; each body keeps its path." % (len(paths_seen), "y" if len(paths_seen) == 1 else "ies"))
    report.note("%d bod%s %s a colour." % (colour_n, "y" if colour_n == 1 else "ies", "carries" if colour_n == 1 else "carry"))
    if res.get("colours_in_file", 0) > colour_n:
        report.warn("The file holds %d colours; body colours are kept, face and edge colours are not." % res["colours_in_file"])
    for w in info["warnings"]:
        if "choose to convert" not in w:
            report.warn(w)
    if mismatch:
        report.warn("The file is in %s and the document in %s; the numbers were %s%s." % (file_key, doc_key, "kept as they are" if keep else "converted", "" if keep else " (scale %g)" % (LENGTH_MM[file_key] / doc_mm)))
    report.extra["interchange"] = {"kind": kind[1:], "schema": res.get("schema", ""), "unit": file_key, "document_unit": doc_key, "mismatch": mismatch, "choice": choice if mismatch else "", "bodies": len(handles), "layers": sorted(layers_seen), "assemblies": len(paths_seen)}
    report.extra["pmi"] = pmi
    report.count("bodies", len(handles))
    return d


def read_pmi(d, res, bodies, scale, report) -> dict:
    items = res.get("pmi") or []
    lost = list(res.get("pmi_lost") or [])
    kept = 0
    detail = []
    for it in items:
        b = bodies[it["body"]]
        refs = []
        ok = True
        for key in ("refs", "refs2"):
            out = []
            for r in it.get(key) or []:
                ids = b.face_ids if r["kind"] == "face" else b.edge_ids
                if 0 <= r["index"] < len(ids):
                    out.append({"kind": r["kind"], "pid": ids[r["index"]]})
                else:
                    ok = False
            refs.append(out)
        if not ok:
            lost.append({"what": it["type"], "reason": "a feature index is outside the body"})
            continue
        data = {"type": it["type"], "body": b.handle, "refs": refs[0], "refs2": refs[1]}
        if it["type"] == "dimension":
            k = 1.0 if it["dtype"] == "angle" else scale
            data.update(dtype=it["dtype"], value=it["value"] * k if it["value"] else None, plus=it["plus"] * k, minus=it["minus"] * k)
        elif it["type"] == "tolerance":
            data.update(char=it["char"], tol=it["tol"] * scale, zone=it["zone"], modifier=it["modifier"], datums=it["datums"])
        else:
            data.update(letter=it["letter"])
        try:
            rec = pmi_store.add(d, data)
        except pmi_store.PmiError as err:
            lost.append({"what": it["type"], "reason": str(err)})
            continue
        kept += 1
        detail.append({"id": rec["id"], "type": it["type"], "source": it.get("step_type", "")})
    if kept:
        report.note("%d PMI item%s read from the file (dimensions, tolerances and datums)." % (kept, "" if kept == 1 else "s"))
    if lost:
        report.warn("%d PMI item%s in the file could not be recovered (see the PMI report)." % (len(lost), "" if len(lost) == 1 else "s"))
    return {"read": len(items), "kept": kept, "not_recovered": lost, "detail": detail}


def collect_flat(d, handles):
    bodies = {}
    nodes = []
    groups = {}
    skipped = []
    chosen = None if not handles else {int(h) for h in handles}
    for e in d.entities("model"):
        if e.kind != "solidbody":
            if e.kind == "meshbody":
                skipped.append(e.name or "mesh")
            continue
        if chosen is not None and e.handle not in chosen:
            continue
        key = "b%d" % e.handle
        layer = e.layer if e.layer and e.layer != "0" else ""
        bodies[key] = {"handle": e.handle, "entity": e, "name": e.name or "Body %d" % e.handle, "rgb": list(e.rgb) if len(e.rgb or []) == 3 else None, "layers": [layer] if layer else []}
        parent = -1
        trail = []
        for part in (e.source or {}).get("path") or []:
            trail.append(str(part))
            tkey = tuple(trail)
            if tkey not in groups:
                nodes.append({"name": str(part), "parent": parent})
                groups[tkey] = len(nodes) - 1
            parent = groups[tkey]
        nodes.append({"name": bodies[key]["name"], "parent": parent, "body": key, "matrix": None})
    return bodies, nodes, skipped


def collect_assembly(doc, report):
    from app.assembly import parts as aparts
    from app.assembly import walk

    d = doc.drawing
    s = mm_per_unit(d)
    bodies, nodes, index = {}, [], {}
    for inst in walk.instances(doc):
        lp = inst.part
        if lp is None or inst.suppressed or not inst.visible:
            if lp is None and not inst.suppressed:
                report.warn("Component %s has no loadable part and is not written." % inst.key)
            continue
        parent = index.get(inst.key.rsplit("/", 1)[0], -1) if "/" in inst.key else -1
        label = inst.record.get("label") or inst.key
        world = inst.world
        mat = [float(world[0][0]), float(world[0][1]), float(world[0][2]), float(world[0][3]) * s, float(world[1][0]), float(world[1][1]), float(world[1][2]), float(world[1][3]) * s, float(world[2][0]), float(world[2][1]), float(world[2][2]), float(world[2][3]) * s]
        pbs = list(getattr(lp, "bodies", []) or [])
        if not pbs:
            nodes.append({"name": label, "parent": parent})
            index[inst.key] = len(nodes) - 1
            continue
        if len(pbs) > 1:
            nodes.append({"name": label, "parent": parent})
            holder = len(nodes) - 1
            index[inst.key] = holder
        else:
            holder = parent
        for pb in pbs:
            ident = "%s:%s" % (getattr(lp, "path", "") or inst.cid, pb.handle)
            if ident not in bodies:
                bodies[ident] = {"handle": pb.handle, "lp": lp, "pb": pb, "name": pb.name, "rgb": pb.rgb if len(pb.rgb) == 3 else None, "layers": []}
            nodes.append({"name": label if len(pbs) == 1 else pb.name, "parent": holder, "body": ident, "matrix": mat})
            if len(pbs) == 1:
                index[inst.key] = len(nodes) - 1
    return bodies, nodes, aparts


def pmi_for(d, bodies, schema, options, report):
    if not bool(options.get("pmi", True)):
        return [], {"requested": 0, "written": [], "dropped": [], "skipped": "PMI export was switched off."}
    mm = mm_per_unit(d)
    out = []
    skipped = []
    by_handle = {b["handle"]: k for k, b in bodies.items() if "entity" in b}
    for rec in pmi_store.items(d):
        key = by_handle.get(rec.get("body"))
        if key is None:
            continue
        if pmi_store.state_of(d, rec) != "ok":
            skipped.append({"id": rec["id"], "reason": "a feature of the item no longer exists on the body"})
            continue
        body = bodies[key]["entity"]
        item = {"id": rec["id"], "type": rec["type"], "body": key}
        item["refs"] = geo.indices(body, rec["refs"])
        item["refs2"] = geo.indices(body, rec.get("refs2") or [])
        if rec["type"] == "dimension":
            value = rec["value"]
            if value is None:
                value = geo.kernel_measure(d, body, rec["dtype"], rec["refs"], rec["refs2"])["value"]
            k = 1.0 if rec["dtype"] == "angle" else mm
            item.update(dtype=rec["dtype"], value=value * k, plus=rec["plus"] * k, minus=rec["minus"] * k)
        elif rec["type"] == "tolerance":
            item.update(char=rec["char"], tol=rec["tol"] * mm, zone=rec["zone"], modifier=rec["modifier"], datums=list(rec.get("datums") or []))
        else:
            item.update(letter=rec["letter"])
        out.append(item)
    return out, {"requested": len(out) + len(skipped), "written": [], "dropped": skipped}


def write_file(doc_or_d, path: str, report: Report, options=None, doc=None):
    options = options or {}
    d = doc.drawing if doc is not None else doc_or_d
    ext = os.path.splitext(path)[1].lower()
    iges = ext in IGES_EXT
    schema = str(options.get("schema") or "ap214").lower()
    if schema not in SCHEMAS:
        raise InterchangeError("The schema is ap203, ap214 or ap242.", "badoption")
    unit = fileunits.unit_key(options.get("unit") or "mm")
    if unit not in KERNEL_UNIT:
        raise InterchangeError("STEP and IGES take mm, cm, m, in, ft or um.", "badunit")
    from app.assembly import store as astore

    if doc is not None and astore.is_assembly(d):
        bodies, nodes, aparts = collect_assembly(doc, report)
        skipped = []
        assembly_mode = True
    else:
        bodies, nodes, skipped = collect_flat(d, options.get("bodies"))
        assembly_mode = False
    if not bodies:
        raise InterchangeError("There are no solid bodies to write.", "empty")
    if len(bodies) > body_cap():
        raise InterchangeError("There are %d bodies; this caller may write at most %d." % (len(bodies), body_cap()), "toomany")
    if skipped:
        report.warn("%d mesh bod%s cannot be written to %s and %s left out." % (len(skipped), "y" if len(skipped) == 1 else "ies", "IGES" if iges else "STEP", "was" if len(skipped) == 1 else "were"))
    pmi_items, pmi_report = [], {"requested": 0, "written": [], "dropped": []}
    if iges:
        have = pmi_store.items(d)
        pmi_report = {"requested": len(have), "written": [], "dropped": [{"id": r["id"], "reason": "IGES carries no semantic PMI"} for r in have]}
        if have:
            report.warn("IGES carries no semantic PMI; %d item%s left out." % (len(have), "" if len(have) == 1 else "s"))
    elif not assembly_mode:
        pmi_items, pmi_report = pmi_for(d, bodies, schema, options, report)
    if assembly_mode:
        report.note("PMI of the component parts is not written from an assembly document.")
    if pmi_items and schema != "ap242":
        if options.get("schema"):
            pmi_report["dropped"] = list(pmi_report.get("dropped", [])) + [{"id": it["id"], "reason": "%s carries no semantic PMI" % SCHEMA_NAME[schema].split(" (")[0]} for it in pmi_items]
            report.warn("%s carries no semantic PMI; %d item%s left out. Choose AP242 to keep them." % (SCHEMA_NAME[schema].split(" (")[0], len(pmi_items), "" if len(pmi_items) == 1 else "s"))
            pmi_items = []
        else:
            schema = "ap242"
            report.note("The document carries PMI, so the AP242 schema was used.")
    kernel_bodies = {}
    try:
        for key, b in bodies.items():
            if assembly_mode:
                wid = aparts.shapes(b["lp"], b["pb"])
            else:
                wid = work.worker_id(d, b["entity"])
            kernel_bodies[key] = {"id": wid, "name": b["name"], "rgb": b["rgb"], "layers": b["layers"]}
        res = work.kcall("xde_write", {"path": path, "schema": schema, "unit": KERNEL_UNIT[unit], "nodes": nodes, "bodies": kernel_bodies, "pmi": pmi_items}, work.LONG)
    except work.SolidError as err:
        raise InterchangeError(str(err), "kernel")
    kp = res.get("pmi") or {}
    pmi_report["written"] = kp.get("written", [])
    pmi_report["dropped"] = list(pmi_report.get("dropped", [])) + list(kp.get("dropped", []))
    pmi_report["notes"] = kp.get("notes", [])
    pmi_report["entities"] = res.get("entities", {})
    if pmi_items and options.get("verify", True):
        pmi_report["read_back"] = verify(path, pmi_items)
    report.note("%s written: %d bod%s, %d node%s, unit %s." % ("IGES" if iges else "STEP " + SCHEMA_NAME[schema], len(bodies), "y" if len(bodies) == 1 else "ies", len(nodes), "" if len(nodes) == 1 else "s", unit))
    if res.get("validation"):
        report.note("Volume, area and centroid validation properties were written for %d part%s." % (res["validation"], "" if res["validation"] == 1 else "s"))
    if pmi_report["written"]:
        report.note("%d of %d PMI item%s written." % (len(pmi_report["written"]), pmi_report["requested"], "" if pmi_report["requested"] == 1 else "s"))
    if pmi_report["dropped"]:
        report.warn("%d PMI item%s could not be written (see the PMI report)." % (len(pmi_report["dropped"]), "" if len(pmi_report["dropped"]) == 1 else "s"))
    rb = pmi_report.get("read_back")
    if rb and rb["not_recovered"]:
        report.warn("%d PMI item%s written to the file did not come back when it was read again." % (len(rb["not_recovered"]), "" if len(rb["not_recovered"]) == 1 else "s"))
    report.extra["interchange"] = {"kind": "iges" if iges else "step", "schema": res.get("schema", ""), "schema_requested": res.get("schema_requested", ""), "unit": unit, "bodies": len(bodies), "nodes": len(nodes), "bytes": res.get("bytes", 0), "validation": res.get("validation", 0), "entities": res.get("entities", {})}
    report.extra["pmi"] = pmi_report
    report.count("bodies", len(bodies))
    return res


def verify(path: str, sent: list) -> dict:
    try:
        res = work.kcall("xde_read", {"path": path, "unit": "mm", "pmi": True}, work.LONG)
    except work.SolidError as err:
        return {"error": str(err), "recovered": 0, "not_recovered": [{"what": "all", "reason": str(err)}]}
    try:
        work.kcall("shape_free", {"ids": [b["id"] for b in res["bodies"]]}, 30.0)
    except work.SolidError:
        pass
    got = {"dimension": 0, "tolerance": 0, "datum": 0}
    for it in res.get("pmi") or []:
        got[it["type"]] = got.get(it["type"], 0) + 1
    want = {"dimension": 0, "tolerance": 0, "datum": 0}
    for it in sent:
        want[it["type"]] += 1
    missing = []
    for t in want:
        if got.get(t, 0) < want[t]:
            missing.append({"what": t, "reason": "%d written, %d read back" % (want[t], got.get(t, 0))})
    missing.extend(res.get("pmi_lost") or [])
    return {"written": want, "recovered": got, "not_recovered": missing}
