import datetime
import os

from app.cam import export as cam_export
from app.cam import limits as cam_limits
from app.cam import post
from app.cam import toolpath as T
from app.cmd import barred
from app.core import guard, outputs
from app.cutting import layout, nest as N, records, shapes as S, sources
from app.cutting import plan as P
from app.cutting import process as PR
from app.cutting.shapes import CutError


def round_part(p):
    out = dict(p)
    out["loops"] = [{"pts": [[round(x, 4), round(y, 4)] for x, y in l["pts"]], "circle": ({"c": [round(l["circle"]["c"][0], 4), round(l["circle"]["c"][1], 4)], "r": round(l["circle"]["r"], 4)} if l.get("circle") else None), "outer": l["outer"]} for l in p["loops"]]
    return out


def build_parts(d, body: dict) -> list:
    specs = []
    for p in body.get("parts") or []:
        specs.append(p)
    ff = body.get("from_flat")
    if ff is not None:
        specs.extend(sources.from_flat(d, (ff or {}).get("handle"), int((ff or {}).get("qty", 1))))
    fo = body.get("from_outlines")
    if fo is not None:
        specs.extend(sources.from_entities(d, (fo or {}).get("layer"), int((fo or {}).get("qty", 1)), (fo or {}).get("qty_by_handle")))
    who = guard.CALLER.get()
    for x in body.get("dxf") or []:
        if who and not barred._inside(x.get("path"), barred._granted(None, who)):
            raise CutError("The DXF file is outside the folders granted to this %s." % ("macro" if who == "macro" else "agent"))
        specs.extend(sources.from_dxf(x["path"], int(x.get("qty", 1))))
    if not specs:
        raise CutError("Give parts, from_flat, from_outlines or dxf files.")
    if len(specs) > 400:
        raise CutError("At most 400 part definitions.")
    return [S.normalize_part(s, i) for i, s in enumerate(specs)]


def sources_view(d) -> dict:
    out = {"flat": None, "outlines": None}
    try:
        parts = sources.from_flat(d)
        out["flat"] = [{"name": p["name"], "loops": len(p["loops"])} for p in parts]
    except CutError as err:
        out["flat_note"] = str(err)
    try:
        parts = sources.from_entities(d)
        out["outlines"] = [{"name": p["name"], "handle": p["handle"], "loops": len(p["loops"])} for p in parts]
    except CutError as err:
        out["outlines_note"] = str(err)
    return out


def run_nest(parts, body: dict, agent: bool, progress=None, cancelled=None) -> dict:
    return N.nest(parts, body.get("sheets") or [], clearance=float(body.get("clearance", 0.0)), kerf=float(body.get("kerf", 0.0)), margin=float(body.get("margin", 5.0)), seconds=float(body.get("seconds", 20.0)), restarts=int(body.get("restarts", 8)), seed=int(body.get("seed", 1)), rotations=body.get("rotations"), defects=body.get("defects"), agent=agent, progress=progress, cancelled=cancelled)


def nest_record(parts, body, result) -> dict:
    req = {k: v for k, v in body.items() if k not in ("parts", "from_flat", "from_outlines", "dxf", "wait", "id")}
    return {"parts": [round_part(p) for p in parts], "request": req, "result": result}


def summary(rec) -> dict:
    r = rec["result"]
    return {"id": rec["id"], "sheet_count": r["sheet_count"], "utilization": r["utilization"], "cut_length": r["cut_length"], "placed": r["placed"], "unplaced": r["unplaced"], "verify": r["verify"], "passes": r["passes"], "seconds": r["seconds"], "timed_out": bool(r.get("timed_out")), "stamp": rec["stamp"], "sheets": [{"index": s["index"], "width": s["width"], "height": s["height"], "parts": len(s["placements"]), "utilization": s["utilization"], "cut_length": s["cut_length"], "extent": s["extent"]} for s in r["sheets"]]}


def process_for(d, ref) -> dict:
    if isinstance(ref, dict):
        return PR.clean(ref)
    return records.process_view(records.get_process(d, str(ref)))


def plan(d, nid, process_ref, sheet=None, order="part", home=(0.0, 0.0)) -> list:
    rec = records.get_nest(d, nid)
    proc = process_for(d, process_ref)
    out = []
    for sh in rec["result"]["sheets"]:
        if sheet is not None and sh["index"] != int(sheet) - 1:
            continue
        wp = layout.world_parts(rec["parts"], sh)
        res = P.plan_sheet(wp, proc, order, (0.0, 0.0, sh["width"], sh["height"]), home)
        res["sheet"] = sh["index"] + 1
        res["parts"] = len(wp)
        out.append(res)
    if not out:
        raise CutError("The nest has no such sheet.")
    return out


def estimate(res, proc) -> dict:
    ct = T.cycle_time(res["moves"], {"rapid": proc["rapid"]})
    return {"simple_s": round(ct["simple_s"], 2), "trapezoid_s": round(ct["trapezoid_s"], 2)}


def export(d, program, nid, process_ref, post_id, path, sheet=None, order="part", home=(0.0, 0.0), options=None) -> dict:
    proc = process_for(d, process_ref)
    plans = plan(d, nid, proc, sheet, order, home)
    spec = post.load(post_id)
    base = outputs.checked(path, cam_export.ALLOWED, spec["extension"])
    root, ext = os.path.splitext(base)
    files = []
    total = {"cut_length": 0.0, "lead_length": 0.0, "pierces": 0, "time_s": 0.0, "dwell_s": 0.0}
    opt = dict(options or {})
    opt.setdefault("program", program)
    opt["date"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if opt.get("date") is True else ""
    for res in plans:
        setup = {"id": "S%d" % res["sheet"], "label": "Sheet %d of nest %s" % (res["sheet"], nid), "wcs": {"slot": 1}, "machine": "laser"}
        op = {"id": "%s-S%d" % (nid, res["sheet"]), "label": "Cut sheet %d" % res["sheet"]}
        moves = [["comment", "%s cutting, kerf %g mm, %d pierces" % (proc["kind"], proc["kerf"], res["stats"]["pierces"])]] + res["moves"]
        out = post.generate([{"setup": setup, "op": op, "toolpath": T.Toolpath(moves, {}), "tool": {}}], post_id, opt)
        target = base if len(plans) == 1 else "%s-%d%s" % (root, res["sheet"], ext)
        target = outputs.checked(target, cam_export.ALLOWED, spec["extension"])
        with open(target, "w", encoding="ascii", errors="replace", newline="\n") as fh:
            fh.write(out["text"])
        est = estimate(res, proc)
        files.append({"path": target, "sheet": res["sheet"], "lines": out["lines"], "warnings": out["warnings"] + res["warnings"], "stats": res["stats"], "time_s": est["trapezoid_s"]})
        total["cut_length"] += res["stats"]["cut_length"]
        total["lead_length"] += res["stats"]["lead_length"]
        total["pierces"] += res["stats"]["pierces"]
        total["time_s"] += est["trapezoid_s"]
        total["dwell_s"] += res["stats"]["dwell_s"]
    return {"files": files, "total": {k: round(v, 3) for k, v in total.items()}, "post": post_id}


def limits_agent() -> bool:
    return cam_limits.limited()
