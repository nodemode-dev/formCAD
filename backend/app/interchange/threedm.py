import os
import tempfile

from app.display import palette
from app.doc import tables as T
from app.doc.entities import Line, Point, Polyline3d
from app.doc.kinds.nurbscurve import NurbsCurve
from app.interchange.errors import InterchangeError, Report
from app.meshes import store as mesh_store
from app.meshes.core import MeshError
from app.param.units import INSUNITS_MM, mm_per_unit
from app.solid import surfwork, work
from app.solid.work import SolidError

MAX_REPORT_ROWS = 400
INSUNITS_OF = {"Inches": 1, "Feet": 2, "Miles": 3, "Millimeters": 4, "Centimeters": 5, "Meters": 6, "Kilometers": 7, "Mils": 9, "Yards": 10, "Decimeters": 14}
WRITE_UNIT_OF = {1: "in", 2: "ft", 3: "mi", 4: "mm", 5: "cm", 6: "m", 7: "km", 9: "mil", 10: "yd"}
IMPERIAL = (1, 2, 3, 10)
CURVE_KINDS = ("line", "circle", "arc", "ellipse", "lwpolyline", "polyline3d", "spline")


def call(method: str, params: dict, timeout: float = work.LONG):
    try:
        return work.kcall(method, params, timeout)
    except SolidError as err:
        raise InterchangeError(str(err), "kernel")


def hex_of(c) -> str:
    return "#%02X%02X%02X" % (int(c[0]), int(c[1]), int(c[2]))


def layer_colour(c):
    if tuple(c) in ((0, 0, 0), (255, 255, 255)):
        return 7
    return hex_of(c)


def info(path: str) -> dict:
    return call("threedm_info", {"path": path}, work.SHORT)


def insunits_for(unit: dict) -> int:
    return INSUNITS_OF.get(unit.get("name"), 4)


def layer_name(row: dict) -> str:
    name = str(row.get("path") or row.get("name") or "0").replace("::", "$")
    return name.strip() or "0"


def read_drawing(path: str, report: Report, target=None):
    from app.doc.model import Drawing

    with tempfile.TemporaryDirectory(prefix="fc3dm_") as tmp:
        res = call("threedm_read", {"path": path, "work_dir": tmp}, work.LONG * 2)
        if target is not None:
            code = int(target.header.get("INSUNITS", 0) or 0)
            code = code if code in INSUNITS_MM else (4 if target.metric else 1)
        else:
            code = insunits_for(res["unit"])
        d = Drawing(code not in IMPERIAL)
        d.header["INSUNITS"] = code
        s = INSUNITS_MM[code]
        d.tolerances["absolute"] = max(res["abs_tol"] / s, 1e-9)
        d.tolerances["angular"] = max(float(res["angle_tol"]), 1e-7)
        names = {}
        for row in res["layers"]:
            nm = layer_name(row)
            names[row["index"]] = nm
            d.table_set("layers", T.new_layer(nm, color=layer_colour(row["color"]), on=bool(row["visible"]), locked=bool(row["locked"])))
        stem = os.path.splitext(os.path.basename(path))[0]
        counts = {}
        for item in res["items"]:
            place(d, item, names, s, stem, counts, report)
        for key, n in counts.items():
            report.count(key, n)
        rows = res["report"][:MAX_REPORT_ROWS]
        report.extra["threedm"] = {
            "archive_version": res["archive_version"], "unit": res["unit"]["name"], "tolerance_mm": res["abs_tol"], "angle_tolerance": res["angle_tol"],
            "counts": res["counts"], "objects": [r for r in rows if r["status"] != "converted" or r.get("detail")], "failed_faces": res["failed_faces"][:MAX_REPORT_ROWS], "sewing_tolerance_mm": res["sewing_tolerance"],
        }
    report.note("3DM archive version %d, units %s, model tolerance %g mm." % (res["archive_version"], res["unit"]["name"], res["abs_tol"]))
    for n in res["notes"]:
        report.note(n)
    c = res["counts"]
    report.note("%d object%s read, %d partly, %d skipped, %d failed." % (c.get("converted", 0), "" if c.get("converted", 0) == 1 else "s", c.get("partial", 0), c.get("skipped", 0), c.get("failed", 0)))
    for r in res["report"]:
        if r["status"] == "skipped":
            report.drop("3DM " + r["type"] + " (" + r.get("detail", "not read") + ")")
        elif r["status"] == "failed":
            report.drop("3DM " + r["type"] + " (" + r.get("detail", "failed") + ")")
    for ff in res["failed_faces"][:50]:
        report.warn("Object %d, face %d could not be rebuilt: %s" % (ff["object"], ff["face"], ff["message"]))
    if len(res["failed_faces"]) > 50:
        report.warn("%d more faces could not be rebuilt." % (len(res["failed_faces"]) - 50))
    return d


def place(d, item: dict, names: dict, s: float, stem: str, counts: dict, report: Report) -> None:
    kind = item["kind"]
    layer = names.get(item.get("layer"), "0")
    label = item.get("name") or ""
    ent = None
    if kind == "curve":
        ent = NurbsCurve(name=label)
        rec = item["curve"]
        rec = {**rec, "poles": [[c / s for c in q] for q in rec["poles"]]}
        ent.set_record(rec)
        ent.source = {"op": "import", "format": "3dm"}
        counts["curves"] = counts.get("curves", 0) + 1
    elif kind == "line":
        ent = Line(start=[c / s for c in item["start"]], end=[c / s for c in item["end"]])
        counts["lines"] = counts.get("lines", 0) + 1
    elif kind == "polyline":
        ent = Polyline3d(points=[[c / s for c in q] for q in item["points"]], closed=False)
        if item.get("closed") and len(ent.points) > 2 and ent.points[0] == ent.points[-1]:
            ent.points = ent.points[:-1]
            ent.closed = True
        counts["polylines"] = counts.get("polylines", 0) + 1
    elif kind == "point":
        ent = Point(position=[c / s for c in item["position"]])
        counts["points"] = counts.get("points", 0) + 1
    elif kind == "solid":
        surface = not item["summary"].get("solids")
        ent = work.new_body(d, item["id"], item["summary"], label or "%s %s %d" % (stem, "surface" if surface else "solid", item["i"] + 1), {"op": "import", "format": "3dm", "surface": surface})
        if item.get("color"):
            ent.rgb = [c / 255.0 for c in item["color"]]
        key = "surfaces" if surface else "solids"
        counts[key] = counts.get(key, 0) + 1
    elif kind in ("mesh", "points"):
        try:
            with open(item["path"], "rb") as fh:
                m, pts_only = mesh_store.unpack(fh.read())
            ent = mesh_store.new_body(d, m, label or "%s %s %d" % (stem, "points" if kind == "points" else "mesh", item["i"] + 1), {"op": "import", "format": "3dm"}, mm_per_unit(d), pts_only)
        except (MeshError, OSError) as err:
            report.warn("A %s could not be stored: %s" % (kind, err))
            return
        if item.get("color"):
            ent.rgb = [c / 255.0 for c in item["color"]]
        counts["meshes" if kind == "mesh" else "point clouds"] = counts.get("meshes" if kind == "mesh" else "point clouds", 0) + 1
    if ent is None:
        return
    ent.layer = layer if d.tables["layers"].has(layer) else "0"
    if item.get("color") and kind not in ("solid", "mesh", "points"):
        ent.color = hex_of(item["color"])
    if not item.get("visible", True):
        ent.visible = False
    d.add_entity(ent, "model")


def unit_key(d, override: str = "") -> str:
    if override:
        return override.lower()
    code = int(d.header.get("INSUNITS", 0) or 0)
    return WRITE_UNIT_OF.get(code, "mm" if d.metric else "in")


def entity_colour(d, e):
    c = e.color
    if isinstance(c, bool) or c in (256, 0, None):
        return None
    rgb = palette.true_rgb(c)
    if rgb is None and isinstance(c, (int, float)) and 1 <= int(c) <= 255:
        rgb = palette.index_rgb(int(c))
    return list(rgb) if rgb else None


def layer_rows(d, used: set) -> list:
    rows = []
    for name in sorted(used):
        rec = d.layer(name)
        if rec is None:
            continue
        rgb, _adaptive = palette.resolve(rec.get("color", 7), 7, None)
        rows.append({"name": rec["name"], "color": list(rgb), "visible": bool(rec.get("on", True)) and not rec.get("frozen", False), "locked": bool(rec.get("locked", False))})
    return rows


def write(d, path: str, report: Report, version: int = 0, unit: str = "", entities=None, verify: bool = True) -> dict:
    s = mm_per_unit(d)
    key = unit_key(d, unit)
    tolm = surfwork.model_tolerance(d)
    items, expect, used = [], [], set()
    skipped = {}
    with tempfile.TemporaryDirectory(prefix="fc3dw_") as tmp:
        pool = list(entities) if entities is not None else list(d.entities("model"))
        for n, e in enumerate(pool):
            k = e.kind
            base = {"name": getattr(e, "name", "") or "", "layer": e.layer, "color": entity_colour(d, e), "hidden": not d.visible(e), "key": "e%d" % e.handle}
            used.add(e.layer)
            try:
                if k == "nurbscurve":
                    rec = {**e.record(), "poles": [[c * s for c in q] for q in e.poles]}
                    items.append({**base, "kind": "curve", "curve": rec})
                    expect.append({"key": base["key"], "kind": "curve", "name": base["name"] or "curve", "curve": rec})
                elif k in CURVE_KINDS:
                    items.append({**base, "kind": "spec", "spec": surfwork.curve_spec(d, e)})
                elif k == "point":
                    items.append({**base, "kind": "point", "position": surfwork.p3(e.position, s)})
                elif k == "solidbody":
                    wid = work.worker_id(d, e)
                    items.append({**base, "kind": "shape", "id": wid, "name": e.name or "body %d" % e.handle})
                    expect.append({"key": base["key"], "kind": "shape", "id": wid, "name": e.name, "faces": int(e.summary.get("faces", 1))})
                    if e.rgb and len(e.rgb) == 3:
                        items[-1]["color"] = [int(round(c * 255)) for c in e.rgb]
                elif k == "meshbody":
                    m = mesh_store.load(d, e)
                    off = [float(c) * s for c in e.offset]
                    mm = m.copy()
                    mm.v = mm.v + off
                    fp = os.path.join(tmp, "m%d.fmesh" % n)
                    with open(fp, "wb") as fh:
                        fh.write(mesh_store.pack(mm, e.points_only))
                    items.append({**base, "kind": "points" if e.points_only else "mesh", "path": fp, "name": e.name or "mesh %d" % e.handle})
                    if e.rgb and len(e.rgb) == 3:
                        items[-1]["color"] = [int(round(c * 255)) for c in e.rgb]
                else:
                    skipped[k] = skipped.get(k, 0) + 1
            except (SolidError, MeshError) as err:
                report.warn("%s %d was not written: %s" % (k, e.handle, err))
                skipped[k] = skipped.get(k, 0) + 1
        if not items:
            raise InterchangeError("There is nothing in the drawing that 3DM can hold (curves, points, solids, surfaces or meshes).", "empty")
        params = {"path": path, "version": int(version), "unit": key, "abs_tol": tolm["tol"], "angle_tol": tolm["angtol"], "layers": layer_rows(d, used), "items": items}
        wrote = call("threedm_write", params, work.LONG * 2)
        out = {"path": path, "archive_version": wrote["version_written"], "unit": wrote["unit"], "written": wrote["written"], "tolerance_mm": tolm["tol"], "tolerance_source": tolm["absolute_source"], "lossy": wrote["lossy"], "failed": wrote["failed"], "skipped": dict(skipped)}
        if verify and expect:
            vdir = os.path.join(tmp, "verify")
            os.makedirs(vdir, exist_ok=True)
            ver = call("threedm_verify", {"path": path, "work_dir": vdir, "expect": expect}, work.LONG * 2)
            rows = []
            for r in ver["results"]:
                ok = (not r.get("missing")) and r.get("max", 1e9) <= tolm["tol"] * (1 + 1e-9)
                rows.append({"name": r.get("name", ""), "kind": r["kind"], "max_deviation_mm": r.get("max"), "rms_mm": r.get("rms"), "samples": r.get("samples"), "ok": bool(ok), "missing": bool(r.get("missing"))})
            out["verify"] = rows
            out["verify_ok"] = all(r["ok"] for r in rows)
    for kind, n in skipped.items():
        report.drop(kind, n)
    report.note("Written as 3DM archive version %d in %s; model tolerance %g mm (%s)." % (out["archive_version"], out["unit"], tolm["tol"], tolm["absolute_source"]))
    for item in out["lossy"]:
        report.warn(item["message"])
    for item in out["failed"]:
        report.warn("%s was not written: %s" % (item.get("object") or "An object", item["message"]))
    if out.get("verify"):
        bad = [r for r in out["verify"] if not r["ok"]]
        worst = max((r["max_deviation_mm"] or 0.0) for r in out["verify"])
        report.note("Read back and measured: %d object%s, largest deviation %.3g mm%s." % (len(out["verify"]), "" if len(out["verify"]) == 1 else "s", worst, "" if not bad else "; %d outside the tolerance" % len(bad)))
    report.extra["threedm"] = out
    return out
