import csv
import io
import math

import numpy as np

from app.core import outputs
from app.pipe import fittings, geometry, limits, store
from app.pipe.limits import PipeError

DEG = 180.0 / math.pi


def resolve_points(d, run: dict) -> list:
    out = []
    for p in run["points"]:
        if isinstance(p, dict):
            from app.assembly import store as astore
            from app.assembly import xform

            rec = astore.get(d, p["component"]) or astore.find_component(d, p["component"])
            if rec is None:
                raise PipeError("The component %s is not in this assembly." % p["component"])
            m = xform.as_matrix(rec["transform"])
            out.append([float(c) for c in xform.apply_points(m, [p["local"]])[0]])
        else:
            out.append([float(c) for c in p])
    return out


def spec_of(d, run: dict) -> dict:
    sid = run.get("spec")
    if not sid:
        raise PipeError("Choose a tube spec for this run.")
    return store.need(d, sid, "spec")


def solve(d, run: dict) -> dict:
    spec = spec_of(d, run)
    pts = resolve_points(d, run)
    ends = {"a": run["ends"]["a"], "b": run["ends"]["b"], "a_len": run["ends"]["a_thickness"] if run["ends"]["a"] == "flange" else 0.0, "b_len": run["ends"]["b_thickness"] if run["ends"]["b"] == "flange" else 0.0}
    if run["style"] == "tube":
        default_r = run.get("clr") or float(spec["od"]) * float(spec.get("elbow_clr_factor", 1.5))
        res = geometry.solve_tube(pts, run.get("radii"), default_r, spec, ends)
    else:
        res = geometry.solve_pipe(pts, spec, ends, run.get("taps"), run.get("reducers"), run.get("clr"))
    res["run"] = run["id"]
    res["spec"] = spec["id"]
    res["od"] = float(spec["od"])
    res["wall"] = float(spec["wall"])
    res["errors"] = [v for v in res["violations"] if v["severity"] == "error"]
    return res


def listify(v):
    if isinstance(v, np.ndarray):
        return [round(float(x), 6) for x in v]
    if isinstance(v, dict):
        return {k: listify(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [listify(x) for x in v]
    if isinstance(v, float):
        return round(v, 6)
    return v


def segments(res: dict, scale: float) -> list:
    def pt(p):
        return [round(float(c) * scale, 6) for c in p]

    out = []
    if res["style"] == "tube":
        items = []
        arcs = {a["vertex"]: a for a in res["arcs"]}
        verts = sorted(arcs)
        for k, s in enumerate(res["straights"]):
            items.append({"k": "line", "a": pt(s["start"]), "b": pt(s["end"])})
            nxt = verts[k] if k < len(verts) else None
            if nxt is not None:
                a = arcs[nxt]
                items.append({"k": "arc", "a": pt(a["start"]), "b": pt(a["end"]), "c": pt(a["centre"]), "r": round(a["radius"] * scale, 6), "angle": a["angle"]})
        length = res["total"] * scale
        minr = min([a["radius"] for a in res["arcs"]], default=0.0) * scale
        out.append({"id": "%s.S1" % res["run"], "kind": "pipe", "nodes": [], "points": [pt(p) for p in res["points"]], "radius": minr, "min_radius": 0.0, "diameter": res["od"] * scale, "path": {"mode": "fillet", "pieces": items, "length": length, "tightest": minr or None, "violations": [v for v in res["violations"] if v["code"] == "bend_radius"], "ok": not res["violations"]}, "length": length, "ok": not res["errors"]})
        return out
    for p in res["pieces"]:
        out.append({"id": "%s.P%d" % (res["run"], p["n"]), "kind": "pipe", "nodes": [], "points": [pt(p["from"]), pt(p["to"])], "radius": 0.0, "min_radius": 0.0, "diameter": p["od"] * scale, "path": {"mode": "fillet", "pieces": [{"k": "line", "a": pt(p["from"]), "b": pt(p["to"])}], "length": p["length"] * scale, "tightest": None, "violations": [], "ok": True}, "length": p["length"] * scale, "ok": True})
    return out


def view(res: dict, scale: float = 1.0) -> dict:
    keep = ("run", "spec", "style", "od", "wall", "points", "straights", "arcs", "bender", "tail", "lead", "total", "pieces", "fittings", "violations", "errors", "notes")
    out = {k: listify(res[k]) for k in keep}
    out["arcs"] = [{**a, "angle_deg": round(a["angle"] * DEG, 6)} for a in out["arcs"]]
    out["segments"] = segments(res, scale)
    out["unit_mm"] = scale
    return out


def bender_table(d, run: dict) -> dict:
    if run["style"] != "tube":
        raise PipeError("A bender table is for bent tube runs; this run is a fitted pipe run.")
    res = solve(d, run)
    if res["errors"]:
        raise PipeError(res["errors"][0]["message"])
    rows = [listify(r) for r in res["bender"]]
    return {"run": run["id"], "columns": ["bend", "length", "rotation", "angle", "machine_angle", "radius", "setback", "mark"], "rows": rows, "tail": round(res["tail"], 6), "total": round(res["total"], 6), "bends": len(rows), "convention": "Length is the straight before the bend measured from the previous bend end (from the tube end for the first). Rotation is the signed turn of the bend plane about the tube axis from the previous bend plane, counter-clockwise seen from the tube end, 0 to 360, the first bend 0. Angle is the geometric bend angle; machine angle adds the spec springback."}


def cutlist(d, rid=None) -> list:
    out = []
    runs = [store.need(d, rid, "run")] if rid else store.rows(d, "run")
    for run in runs:
        try:
            res = solve(d, run)
        except PipeError as err:
            out.append({"run": run["id"], "label": run.get("label", ""), "part": run.get("part") or "", "spool": run.get("spool") or "", "error": str(err)})
            continue
        spec = store.get(d, run["spec"], "spec")
        for p in res["pieces"]:
            row = {"run": run["id"], "label": run.get("label", ""), "part": run.get("part") or "", "spool": run.get("spool") or "", "piece": p["n"], "kind": p["kind"], "spec": spec["id"], "material": spec.get("material", ""), "od": p["od"], "wall": p["wall"], "length": round(p["length"], 4), "bends": p["bends"], "end_a": run["ends"]["a"] if p["n"] == 1 else "plain", "end_b": run["ends"]["b"] if p["n"] == len(res["pieces"]) else "plain"}
            if run["style"] == "tube":
                row["bender"] = [[round(r["length"], 3), round(r["rotation"], 3), round(r["angle"], 3)] for r in res["bender"]]
            out.append(row)
    limits.need(len(out), "rows", "Cut list rows")
    return out


def fitting_bom(d) -> list:
    counts = {}
    for run in store.rows(d, "run"):
        try:
            res = solve(d, run)
        except PipeError:
            continue
        for f in res["fittings"]:
            if f["kind"] == "elbow":
                key = ("elbow", "%.4g x %.4g, %.1f deg" % (f["od"], f["wall"], f["angle"]))
            elif f["kind"] == "tee":
                key = ("tee", "%.4g x %.4g" % (f["od"], f["wall"]))
            elif f["kind"] == "reducer":
                key = ("reducer", "%.4g to %.4g" % (f["od"], f["od_to"]))
            else:
                key = ("flange", "%.4g x %.4g, %.4g thick" % (f["od"], f["wall"], f["thickness"]))
            counts[key] = counts.get(key, 0) + 1
    return [{"fitting": k[0], "size": k[1], "count": v} for k, v in sorted(counts.items())]


def write_csv(path: str, header: list, rows_: list) -> dict:
    full = outputs.checked(path, (".csv",), ".csv")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows_:
        w.writerow(r)
    with open(full, "w", encoding="utf-8", newline="") as fh:
        fh.write(buf.getvalue())
    return {"path": full, "rows": len(rows_)}


def export(d, path: str, kind: str, rid=None) -> dict:
    if kind == "cutlist":
        rows_ = [r for r in cutlist(d, rid) if "error" not in r]
        head = ["run", "label", "part", "spool", "piece", "kind", "spec", "material", "od", "wall", "length", "bends", "end_a", "end_b"]
        return write_csv(path, head, [[r.get(k, "") for k in head] for r in rows_])
    if kind == "bender":
        if not rid:
            raise PipeError("A bender table export names one run.")
        t = bender_table(d, store.need(d, rid, "run"))
        head = ["bend", "length", "rotation", "angle", "machine_angle", "radius", "setback", "mark"]
        return write_csv(path, head, [[r[k] for k in head] for r in t["rows"]])
    raise PipeError("Export kind is cutlist or bender.")


def place_of(res: dict, fit: dict) -> dict:
    return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in fit.items() if k in ("point", "axis", "u_in", "u_out", "branch")}


def generate_bodies(d, run: dict) -> dict:
    res = solve(d, run)
    if res["errors"]:
        raise PipeError(res["errors"][0]["message"])
    made = []
    limits.need(len(res["pieces"]) + len(res["fittings"]) + len(res["arcs"]), "bodies", "Bodies")
    if run["style"] == "pipe":
        for p in res["pieces"]:
            h, _s = fittings.straight_body(d, p["from"], p["to"], p["od"], p["wall"], "%s pipe %d" % (run["id"], p["n"]))
            made.append(h)
        for k, f in enumerate(res["fittings"]):
            raw = {"od": f["od"], "wall": f["wall"]}
            if f["kind"] == "elbow":
                raw.update({"clr": f["radius"]})
            elif f["kind"] == "tee":
                raw.update({"c": f["c"], "branch_c": f["c"]})
            elif f["kind"] == "reducer":
                raw.update({"od_to": f["od_to"], "wall_to": f["wall_to"], "length": f["length"]})
            else:
                raw.update({"thickness": f["thickness"], "flange_od": f["od"] * 2.2, "bolt_circle": f["od"] * 1.6})
            if f["kind"] == "flange" and f["thickness"] <= 0:
                continue
            h, _p, _s = fittings.make(d, f["kind"], raw, "%s %s %d" % (run["id"], f["kind"], k + 1), place_of(res, f))
            made.append(h)
    else:
        for s in res["straights"]:
            if s["length"] > 1e-6:
                h, _s = fittings.straight_body(d, s["start"], s["end"], res["od"], res["wall"], "%s straight %d" % (run["id"], s["seg"] + 1))
                made.append(h)
        for a in res["arcs"]:
            tin = a["start"]
            tout = a["end"]
            vtx = res["points"][a["vertex"]]
            uin = geometry.unit(vtx - tin)
            uout = geometry.unit(tout - vtx)
            raw = {"od": res["od"], "wall": res["wall"], "clr": a["radius"]}
            h, _p, _s = fittings.make(d, "elbow", raw, "%s bend %d" % (run["id"], a["vertex"] + 1), {"point": vtx.tolist(), "u_in": uin.tolist(), "u_out": uout.tolist()})
            made.append(h)
    return {"run": run["id"], "bodies": made}
