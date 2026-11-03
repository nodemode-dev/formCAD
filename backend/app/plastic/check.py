import time

import numpy as np

from app.core import guard
from app.part import rebuild, store
from app.part.registry import PartError
from app.plastic import job, records, rule
from app.solid import work

DEFAULT_SAMPLES = 1000
MAX_SAMPLES = 4000
MAX_SAMPLES_AGENT = 800
MAX_FINDINGS = 80
SPHERE_CAP = 4000


def last_entry(doc):
    d = doc.drawing
    rebuild.ensure_built(doc)
    t = store.tree(d)
    order = list(t["order"])
    if t.get("rollback") in order:
        order = order[: order.index(t["rollback"]) + 1]
    cache = rebuild.cache_of(doc)
    for fid in reversed(order):
        e = cache.entries.get(fid)
        if e is not None and not e.error and e.wid:
            return e
    return None


def limits(samples):
    cap = MAX_SAMPLES_AGENT if guard.CALLER.get() else MAX_SAMPLES
    n = min(DEFAULT_SAMPLES, cap) if samples is None else int(samples)
    if n < 20:
        raise PartError("Take at least 20 wall thickness samples.")
    if n > cap:
        raise PartError("Take at most %d wall thickness samples%s." % (cap, " for a macro or agent" if guard.CALLER.get() else ""))
    return n


def add(findings, sev, kind, fid, message, **extra):
    row = {"id": "%s.%s" % (kind, extra.pop("tag", "")), "severity": sev, "kind": kind, "message": message, "feature": fid, "face": None, "value": None, "limit": None, "at": None}
    row.update(extra)
    findings.append(row)


def feature_of(key) -> str:
    return str(key or "").split(":", 1)[0]


def wall_section(rl, wall, findings, nominal, skip, minor):
    th = np.array([np.nan if x is None else x for x in wall["thickness"]], dtype=np.float64)
    faces = np.asarray(wall["faces"], dtype=np.int64)
    pts = np.asarray(wall["points"], dtype=np.float64).reshape(-1, 3)
    good = np.isfinite(th) & ~skip
    out = {"method": wall["method"], "samples": int(len(th)), "used": int(np.count_nonzero(good)), "skipped": int(np.count_nonzero(skip)), "misses": int(np.count_nonzero(~np.isfinite(th))), "nominal": nominal, "min": None, "max": None, "median": None, "below_min_area_pct": None, "above_max_area_pct": None, "variation_pct": None}
    if not good.any():
        return out, {}
    v = th[good]
    out["min"], out["max"], out["median"] = float(v.min()), float(v.max()), float(np.median(v))
    wmin, wmax = rl["wall_min"], rl["wall_max"]
    if wmin is not None:
        out["below_min_area_pct"] = 100.0 * float(np.count_nonzero(v < wmin - 1e-9)) / len(v)
    if wmax is not None:
        out["above_max_area_pct"] = 100.0 * float(np.count_nonzero(v > wmax + 1e-9)) / len(v)
    if nominal:
        main = th[good & ~minor]
        if len(main):
            out["main_min"], out["main_max"] = float(main.min()), float(main.max())
            out["variation_pct"] = 100.0 * (out["main_max"] - out["main_min"]) / nominal
    per_face = {}
    for fi in sorted(set(faces[good].tolist())):
        m = good & (faces == fi)
        per_face[fi] = (float(th[m].min()), float(th[m].max()), float(np.median(th[m])), pts[m][int(np.argmin(th[m]))].tolist())
    thin = sorted(((lo, fi, at) for fi, (lo, hi, md, at) in per_face.items() if wmin is not None and lo < wmin - 1e-9))
    for lo, fi, at in thin[:20]:
        add(findings, "error", "wall", None, "Wall %.3g mm at face %d is thinner than the smallest wall %.3g mm." % (lo, fi, wmin), tag="thin", face=fi, value=lo, limit=wmin, at=at)
    thick = sorted(((-hi, fi, at) for fi, (lo, hi, md, at) in per_face.items() if wmax is not None and hi > wmax + 1e-9))
    for nhi, fi, at in thick[:20]:
        add(findings, "warning", "wall", None, "Wall %.3g mm at face %d is thicker than the largest wall %.3g mm; expect sink marks and long cooling." % (-nhi, fi, wmax), tag="thick", face=fi, value=-nhi, limit=wmax, at=per_face[fi][3])
    if nominal and out["variation_pct"] is not None and out["variation_pct"] > rl["wall_variation_pct"] + 1e-9:
        add(findings, "warning", "wall", None, "Wall thickness varies by %.1f percent of the nominal wall; the rule allows %.1f percent." % (out["variation_pct"], rl["wall_variation_pct"]), tag="variation", value=out["variation_pct"], limit=rl["wall_variation_pct"])
    return out, per_face


def adjacent(rl, per_face, adjacency, findings):
    if rl["adjacent_ratio_min"] is None:
        return
    seen = set()
    for fl in adjacency:
        if len(fl) != 2:
            continue
        a, b = fl
        if (a, b) in seen or a not in per_face or b not in per_face:
            continue
        seen.add((a, b))
        ma, mb = per_face[a][2], per_face[b][2]
        ratio = min(ma, mb) / max(ma, mb) if max(ma, mb) > 0 else 1.0
        if ratio < rl["adjacent_ratio_min"] - 1e-9 and len(findings) < MAX_FINDINGS:
            add(findings, "info", "wall", None, "Faces %d and %d meet with walls of %.3g and %.3g mm, a ratio of %.2f; the rule asks for at least %.2f. Blend the change gradually." % (a, b, ma, mb, ratio, rl["adjacent_ratio_min"]), tag="adjacent", face=a, value=ratio, limit=rl["adjacent_ratio_min"])


def draft_section(rl, ins, findings, pull, keys, hooks):
    need = rl["min_draft"] + (rl["texture_depth"] or 0.0) * rl["texture_draft_per_mm"]
    flagged = 0
    for fid in sorted(hooks):
        add(findings, "info", "draft", fid, "Snap hook %s has no draft on its sides; mould it with a slide or a side core." % fid, tag="hook")
    for row in ins["faces"]:
        if not row.get("samples"):
            continue
        if row["face"] < len(keys) and feature_of(keys[row["face"]]) in hooks:
            continue
        lo = row.get("draft_abs_min")
        hi = max(abs(row.get("draft_min", 0.0)), abs(row.get("draft_max", 0.0)))
        if lo is None or hi > 89.0:
            continue
        if lo < need - 1e-6:
            flagged += 1
            if flagged <= 40:
                add(findings, "warning", "draft", None, "Face %d has %.2f degrees of draft about the pull direction; the rule needs at least %.2f." % (row["face"], lo, need), tag="low", face=row["face"], value=lo, limit=need, at=row.get("centre"))
    return {"required": need, "pull": pull, "faces_below": flagged}


def corners_section(rl, ins, findings):
    wall = rl["nominal_wall"] or 0.0
    need = max(rl["corner_radius_min"] or 0.0, (rl["corner_radius_ratio_min"] or 0.0) * wall)
    sharp = ins.get("sharp_edges") or []
    for e in sharp[:30]:
        add(findings, "warning", "corner", None, "Sharp inside corner along edge %d (%.3g mm long, no radius); the rule asks for a radius of at least %.3g mm." % (e["edge"], e["length"], need), tag="sharp", face=e["faces"][0], value=0.0, limit=need, at=e["mid"])
    small = 0
    for row in ins["faces"]:
        if row.get("kind") == "cylinder" and row.get("concave") and row.get("span_deg", 360.0) < 179.0 and row["radius"] < need - 1e-9:
            small += 1
            if small <= 30:
                add(findings, "warning", "corner", None, "Inside fillet on face %d has radius %.3g mm; the rule asks for at least %.3g mm." % (row["face"], row["radius"], need), tag="small", face=row["face"], value=row["radius"], limit=need, at=row.get("centre"))
    return {"required_radius": need, "sharp_edges": len(sharp), "small_fillets": small}


def feature_section(rl, rows, findings):
    wall = rl["nominal_wall"]
    for r in rows:
        fid, kind, v = r["id"], r["kind"], r["values"]
        if kind == "rib":
            t, h = v["thickness"], v["height"]
            if wall:
                ratio = t / wall
                if ratio > rl["rib_ratio_max"] + 1e-9:
                    add(findings, "warning", "rib", fid, "Rib %s is %.0f percent of the wall; above %.0f percent it will sink the opposite face." % (fid, 100 * ratio, 100 * rl["rib_ratio_max"]), tag="thick", value=ratio, limit=rl["rib_ratio_max"])
                elif ratio > rl["rib_ratio_min"] + 1e-9:
                    add(findings, "info", "rib", fid, "Rib %s is %.0f percent of the wall: within the slight sink limit (%.0f percent) but above the minimal sink ratio (%.0f percent)." % (fid, 100 * ratio, 100 * rl["rib_ratio_max"], 100 * rl["rib_ratio_min"]), tag="slight_sink", value=ratio, limit=rl["rib_ratio_min"])
            if h / t > rl["rib_height_max_ratio"] + 1e-9:
                add(findings, "warning", "rib", fid, "Rib %s is %.1f times as tall as it is thick; the rule allows %.1f times." % (fid, h / t, rl["rib_height_max_ratio"]), tag="tall", value=h / t, limit=rl["rib_height_max_ratio"])
            if v["draft"] < rl["min_draft"] - 1e-9:
                add(findings, "warning", "rib", fid, "Rib %s has %.2f degrees of draft per side; the rule needs %.2f." % (fid, v["draft"], rl["min_draft"]), tag="draft", value=v["draft"], limit=rl["min_draft"])
        elif kind == "boss":
            od, hole, h = v["outer_diameter"], v["hole_diameter"], v["height"]
            screw = v.get("screw_diameter") or hole
            lo, hi = (2.0, 3.0)
            if screw and not lo - 1e-9 <= od / screw <= hi + 1e-9:
                add(findings, "warning", "boss", fid, "Boss %s outside diameter is %.2f times the screw diameter; guides give %.1f to %.1f times." % (fid, od / screw, lo, hi), tag="ratio", value=od / screw, limit=lo)
            if h / od > rl["boss_height_max_ratio"] + 1e-9:
                add(findings, "warning", "boss", fid, "Boss %s is %.1f times as tall as its outside diameter; the rule allows %.1f times." % (fid, h / od, rl["boss_height_max_ratio"]), tag="tall", value=h / od, limit=rl["boss_height_max_ratio"])
            if wall:
                bw = (od - hole) / 2.0
                if bw / wall > rl["rib_ratio_max"] + 1e-9:
                    add(findings, "warning", "boss", fid, "Boss %s has a wall of %.3g mm, %.0f percent of the part wall; above %.0f percent it will sink." % (fid, bw, 100 * bw / wall, 100 * rl["rib_ratio_max"]), tag="wall", value=bw / wall, limit=rl["rib_ratio_max"])
        elif kind == "snap_hook":
            eps = v["strain_pct"]
            allow = rl["snap_strain_allowable"]
            if allow is None:
                add(findings, "info", "snap", fid, "Snap hook %s strain is %.2f percent; the rule has no permissible strain for this material, set it in the rule." % (fid, eps), tag="no_limit", value=eps)
            else:
                lim = allow * (rl["snap_repeat_factor"] if rl["snap_repeated"] else 1.0)
                if eps > lim + 1e-9:
                    add(findings, "error", "snap", fid, "Snap hook %s strain is %.2f percent at the root, above the permissible %.2f percent." % (fid, eps, lim), tag="strain", value=eps, limit=lim)
            if v["root_fillet"] < (rl["snap_root_radius_min"] or 0.0) - 1e-9:
                add(findings, "warning", "snap", fid, "Snap hook %s root fillet is %.3g mm; the least is %.3g mm." % (fid, v["root_fillet"], rl["snap_root_radius_min"]), tag="root", value=v["root_fillet"], limit=rl["snap_root_radius_min"])
        elif kind in ("lip", "groove"):
            w = v.get("wall")
            if w is not None and w < rl["lip_min_wall"] - 1e-9:
                add(findings, "warning", "lip", fid, "The wall at %s is %.3g mm; a tongue and groove needs at least %.3g mm." % (fid, w, rl["lip_min_wall"]), tag="wall", value=w, limit=rl["lip_min_wall"])
            if kind == "groove" and v.get("welded") and w is not None and w < rl["welded_min_wall"] - 1e-9:
                add(findings, "warning", "lip", fid, "The welded joint at %s sits on a %.3g mm wall; the smallest for a welded tongue and groove is %.3g mm." % (fid, w, rl["welded_min_wall"]), tag="welded", value=w, limit=rl["welded_min_wall"])


def snap_forces(rl, rows):
    out = []
    for r in rows:
        if r["kind"] != "snap_hook":
            continue
        from app.plastic import snap

        v = r["values"]
        f = snap.forces(v["width"], v["root_thickness"], v["beam_length"], v["strain_pct"], rl["snap_modulus"], rl["snap_friction"], v["lead_angle"])
        out.append({"feature": r["id"], "strain_pct": v["strain_pct"], "allowable_pct": rl["snap_strain_allowable"], "taper_k": v["taper_k"], "deflection_force": f["deflection_force"], "mating_force": f["mating_force"]})
    return out


def run(doc, opts: dict | None = None) -> dict:
    opts = opts or {}
    with doc.lock:
        d = doc.drawing
        rl = rule.current(d)
        entry = last_entry(doc)
        if entry is None:
            raise PartError("The part has no body to check.")
        method = str(opts.get("method") or "sphere")
        if method not in ("ray", "sphere"):
            raise PartError("The wall thickness method is ray or sphere.")
        samples = limits(opts.get("samples"))
        if method == "sphere":
            samples = min(samples, SPHERE_CAP)
        pull = opts.get("pull") or rl["pull"]
        rows = records.features(d)
        wid, keys = entry.wid, list(entry.faces)
        nominal = rl["nominal_wall"]
    margin = 0.5 * nominal if nominal else 0.0
    t0 = time.perf_counter()
    with job.running(doc, "plasticcheck") as act:
        act.step("Inspecting the faces", 0.05)
        ins = job.interruptible(act, work.kcall, "pl_inspect", {"id": wid, "pull": pull, "grid": 7}, work.LONG)
        t1 = time.perf_counter()
        act.step("Measuring the wall thickness", 0.2)
        wall = job.interruptible(act, work.kcall, "pl_wall", {"id": wid, "method": method, "samples": samples, "margin": margin}, work.LONG)
        t2 = time.perf_counter()
        act.step("Writing the report", 0.95)
    findings: list = []
    areas = {r["face"]: r["area"] for r in ins["faces"]}
    min_area = 0.5 * nominal * nominal if nominal else 0.0
    ring_ids = {r["id"] for r in rows if r["kind"] in ("lip", "groove")}
    hook_ids = {r["id"] for r in rows if r["kind"] == "snap_hook"}
    skip_ids = ring_ids | hook_ids
    skip = np.array([areas.get(f, 0.0) < min_area or (f < len(keys) and feature_of(keys[f]) in skip_ids) for f in wall["faces"]], dtype=bool)
    minor_ids = {r["id"] for r in rows if r["kind"] in ("rib", "boss")}
    minor = np.array([f < len(keys) and feature_of(keys[f]) in minor_ids for f in wall["faces"]], dtype=bool)
    wsec, per_face = wall_section(rl, wall, findings, nominal, skip, minor)
    low = sorted((v[0], fi) for fi, v in per_face.items())[:5]
    wsec["lowest"] = [{"face": fi, "face_key": keys[fi] if fi < len(keys) else None, "min": lo} for lo, fi in low]
    adjacent(rl, per_face, ins.get("adjacency") or [], findings)
    dsec = draft_section(rl, ins, findings, list(pull), keys, hook_ids)
    csec = corners_section(rl, ins, findings)
    feature_section(rl, rows, findings)
    for f in findings:
        if isinstance(f.get("face"), int) and 0 <= f["face"] < len(keys):
            f["face_key"] = keys[f["face"]]
        if f.get("at"):
            s = work.mm(doc.drawing)
            f["at_units"] = [c / s for c in f["at"]]
    counts = {"errors": 0, "warnings": 0, "info": 0}
    for f in findings:
        counts[{"error": "errors", "warning": "warnings", "info": "info"}[f["severity"]]] += 1
    return {
        "ok": counts["errors"] == 0,
        "rule": {k: v for k, v in rl.items()},
        "summary": counts,
        "wall": wsec,
        "draft": dsec,
        "corners": csec,
        "snap": snap_forces(rl, rows),
        "findings": findings,
        "body": {"volume": ins["volume"], "area": ins["area"], "faces": len(ins["faces"])},
        "mm_per_unit": work.mm(doc.drawing),
        "ms": {"inspect": round((t1 - t0) * 1000.0, 1), "wall": round((t2 - t1) * 1000.0, 1)},
    }

