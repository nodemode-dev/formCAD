import hashlib
import json

import numpy as np

from app.additive import gcode, motion, pack, placement, slicing
from app.additive import settings as cfg
from app.additive.jobs import AdditiveError, cap
from app.additive.toolpath import FEATURE_NAMES, Builder
from app.additive.settings import SettingError

VERSION = "0.12.0"


class Result:
    def __init__(self):
        self.summary = {}
        self.warnings = []
        self.lines = []
        self.pack = b""
        self.hash = ""


def merge(parts: list, items: list):
    vs, ts, off = [], [], 0
    vol = 0.0
    for body, item in zip(parts, items):
        v, _m = placement.transform(body.v, item)
        nv, nt = slicing.weld(v, body.t)
        if not len(nt):
            continue
        vol += slicing.signed_volume(nv, nt)
        vs.append(nv)
        ts.append(nt + off)
        off += len(nv)
    if not vs:
        raise AdditiveError("There is nothing to slice: the plate holds no triangles.")
    return np.vstack(vs), np.vstack(ts), vol


def hash_of(settings: dict, items: list, parts: list) -> str:
    h = hashlib.sha1()
    h.update(json.dumps(settings, sort_keys=True).encode())
    h.update(json.dumps(items, sort_keys=True).encode())
    for p in parts:
        h.update(("%s:%s:%d:%d" % (p.handle, p.version, len(p.v), len(p.t))).encode())
    return h.hexdigest()[:16]


def slice_job(parts: list, items: list, settings: dict, activity, plate_id: str, profile_id: str, runner=None, fingerprint: str = "") -> Result:
    s = cfg.clean(settings)
    activity.step("prepare", 0.01)
    v, t, vol = merge(parts, items)
    if len(t) > cap("triangles", runner):
        raise AdditiveError("The plate holds %d triangles; the limit here is %d." % (len(t), cap("triangles", runner)))
    zmax = float(v[:, 2].max())
    zmin = float(v[:, 2].min())
    if zmax - zmin > s["max_height"] + 1e-6:
        raise AdditiveError("The plate is %.1f mm tall; the printer profile allows %.1f mm." % (zmax - zmin, s["max_height"]))
    v = v.copy()
    v[:, 2] -= zmin
    stack = slicing.layer_stack(zmax - zmin, s["first_layer_height"], s["layer_height"])
    if len(stack) > cap("layers", runner):
        raise AdditiveError("The plate needs %d layers; the limit here is %d. Use thicker layers." % (len(stack), cap("layers", runner)))
    planes = np.array([z - h / 2.0 + slicing.PLANE_EPS for z, h in stack])
    stats = {}
    pair_cap = slicing.AGENT_PAIRS if cap("triangles", runner) < 1_000_000 else slicing.MAX_PAIRS
    loops = slicing.slice_planes(v, t, planes, activity, pair_cap, stats)
    activity.step("regions", 0.22)
    regions = slicing.to_regions(loops)
    builder = Builder(s, stack, regions, activity)
    try:
        plan = builder.build()
    except SettingError as err:
        raise AdditiveError(str(err))
    plan.model_volume = vol
    motion.finish(plan.layers, s)
    activity.step("output", 0.94)
    res = Result()
    res.warnings = list(plan.warnings)
    if stats.get("open"):
        res.warnings.append({"kind": "open_contours", "severity": "warning", "message": "%d open contours were skipped (layers %s); the mesh may have holes. Repair it first." % (stats["open"], ", ".join(str(x) for x in sorted(set(stats["open_layers"]))[:8])), "where": {}})
    if stats.get("closed_gap"):
        res.warnings.append({"kind": "gaps_closed", "severity": "info", "message": "%d contours with a gap under 0.5 mm were closed." % stats["closed_gap"], "where": {}})
    afil = builder.afil
    fil = sum(L.fil_mm for L in plan.layers)
    per = {}
    for L in plan.layers:
        for op in L.ops:
            if op[0] == "E":
                per[FEATURE_NAMES[op[1]]] = per.get(FEATURE_NAMES[op[1]], 0.0) + motion.path_length(op[2])
    time_s = sum(L.time_s for L in plan.layers)
    bb = [float(x) for x in (*v.min(axis=0), *v.max(axis=0))]
    summary = {"layers": len(plan.layers), "filament_mm": round(fil, 2), "filament_g": None, "time_s": round(time_s, 1), "print_time": clock(time_s), "support_volume_mm3": round(plan.support_volume, 2), "model_volume_mm3": round(vol, 2), "extruded_volume_mm3": round(fil * afil, 2), "lines": int(sum(len(L.ops) for L in plan.layers)), "bbox": [round(x, 3) for x in bb], "per_feature_mm": {k: round(x, 1) for k, x in per.items()}, "bridge_layers": plan.bridge_layers, "support_layers": plan.support_layers}
    key = fingerprint or hash_of(s, items, parts)
    header = {"layers": summary["layers"], "filament_length_mm": summary["filament_mm"], "estimated_print_time": "%s (%d s), heating not included" % (summary["print_time"], int(round(time_s))), "support_volume_mm3": summary["support_volume_mm3"], "model_volume_mm3": summary["model_volume_mm3"], "layer_height": s["layer_height"], "nozzle": s["nozzle"], "infill": "%s %g%%" % (s["infill_pattern"], s["infill_density"]), "plate": plate_id, "version": VERSION}
    lines, layer_lines = gcode.write_gcode(plan.layers, s, header)
    extra = {"totals": {"time_s": summary["time_s"], "filament_mm": summary["filament_mm"], "layers": summary["layers"], "support_volume_mm3": summary["support_volume_mm3"]}, "profile": profile_id, "plate": plate_id, "hash": key, "source": "slice", "gcode_layer_lines": layer_lines}
    res.pack = pack.from_layers(plan.layers, extra)
    res.lines = lines
    res.summary = summary
    res.hash = key
    return res


def clock(seconds: float) -> str:
    s = int(round(seconds))
    return "%dh %02dm %02ds" % (s // 3600, (s % 3600) // 60, s % 60)
