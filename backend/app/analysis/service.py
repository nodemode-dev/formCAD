import json
import os
import struct
import tempfile
import zlib
from collections import OrderedDict

import numpy as np

from app.analysis import fields, ramps, spec as spec_mod
from app.analysis.spec import SpecError
from app.solid import scene as scene_mod
from app.solid import work
from app.solid.work import SolidError

MAGIC = 0x56414346
VERSION = 1
HEADER = 64
RECORD = 32
DATA_MAGIC = 0x54444146
MEDIA_TYPE = "application/vnd.formcad.analysis"
MODE_CODE = {"zebra": 1, "isophote": 2, "curvature": 3, "draft": 4, "deviation": 5}
CACHE_LIMIT = 24
UNDEFINED = "#8a8a8a"
_cache: OrderedDict = OrderedDict()


def solid_rows(doc, targets: list, only_visible: bool = True) -> list:
    d = doc.drawing
    wanted = set(targets or [])
    rows = []
    for e in d.ordered_entities():
        if e.kind != "solidbody":
            continue
        if wanted and e.handle not in wanted:
            continue
        if only_visible and not d.visible(e):
            continue
        rows.append(e)
    if wanted:
        missing = wanted - {e.handle for e in rows}
        if missing:
            raise SpecError("Object %s is not a visible solid or surface." % sorted(missing)[0])
    if not rows:
        raise SpecError("There are no visible solids or surfaces to analyse.")
    return rows


def base_worker_id(d, body) -> str:
    with work._lock:
        work.reset_if_restarted()
        key = (body.blob, (0.0, 0.0, 0.0))
        wid = work._loaded.get(key)
        if wid is None:
            wid = work.load_blob(d, body.blob)
            work.remember(key, wid)
        return wid


def read_data(path: str) -> tuple:
    with open(path, "rb") as fh:
        raw = fh.read()
    magic, nv, cols, _z = struct.unpack_from("<4I", raw, 0)
    if magic != DATA_MAGIC:
        raise SolidError("The analysis data has the wrong header.")
    arr = np.frombuffer(raw, dtype="<f4", offset=16)
    return arr[: nv * 3].reshape(nv, 3), arr[nv * 3 :].reshape(nv, cols)


def shape_data(d, body, detail: float, curvature: bool) -> tuple:
    tag = (body.blob, work.detail_tag(detail))
    got = _cache.get(tag)
    if got is not None and (got[1].shape[1] >= 7 or not curvature):
        _cache.move_to_end(tag)
        return got
    raw = work.mesh_for(d, body, detail)
    mesh = scene_mod.parse(raw)
    wid = base_worker_id(d, body)
    linear, angular = work.detail_params(body.summary, detail)
    with tempfile.TemporaryDirectory(prefix="fcan_") as tmp:
        out = os.path.join(tmp, "d.adat")
        work.kcall("an_shape_data", {"id": wid, "linear": linear, "angular": angular, "curvature": bool(curvature), "path": out}, work.LONG)
        pos, data = read_data(out)
    if len(pos) != mesh["nv"]:
        raise SolidError("The analysis points do not follow the display mesh (%d against %d vertices); lower the detail and try again." % (len(pos), mesh["nv"]))
    if mesh["nv"]:
        span = float(np.ptp(mesh["pos"], axis=0).max()) or 1.0
        if float(np.abs(pos - mesh["pos"]).max()) > 1e-3 * span:
            raise SolidError("The analysis points do not follow the display mesh; lower the detail and try again.")
    value = (mesh["pos"], data.copy())
    _cache[tag] = value
    _cache.move_to_end(tag)
    while len(_cache) > CACHE_LIMIT:
        _cache.popitem(last=False)
    return value


def clear_cache() -> None:
    _cache.clear()


def stripes(spec: dict, normals: np.ndarray) -> np.ndarray:
    if spec["mode"] == "zebra":
        return fields.zebra(normals, spec["view"], spec["axis"], spec["band"])
    return fields.isophote(normals, spec["light"], spec["band"])


def deviation_values(doc, spec: dict, bodies: list, detail: float) -> tuple:
    d = doc.drawing
    s = work.mm(d)
    target = d.get(spec["target"])
    if target is None or target.kind != "solidbody":
        raise SpecError("The target is not a solid or surface.")
    faces = []
    for pid in spec.get("faces") or []:
        if pid not in target.face_ids:
            raise SpecError("The target has no face %s." % pid)
        faces.append(target.face_ids.index(pid))
    twid = work.worker_id(d, target)
    per_body = {}
    for body in bodies:
        if body.handle == target.handle:
            continue
        mesh = scene_mod.parse(work.mesh_for(d, body, detail))
        pos = mesh["pos"].astype(np.float64) + np.asarray(body.offset, dtype=np.float64) * s
        step = max(1, int(np.ceil(len(pos) / spec["max_vertices"])))
        if step > 1:
            raise SolidError("%s has %d vertices; deviation takes up to %d. Lower the detail." % (body.name or "A body", len(pos), spec["max_vertices"]))
        with tempfile.TemporaryDirectory(prefix="fcdev_") as tmp:
            pts = os.path.join(tmp, "p.pts")
            pos.astype("<f4").tofile(pts)
            out = os.path.join(tmp, "o.adat")
            work.kcall("an_deviation", {"points_path": pts, "target": twid, "faces": faces, "signed": spec["signed"], "path": out}, work.LONG)
            with open(out, "rb") as fh:
                raw = fh.read()
        _m, n, cols, _z = struct.unpack_from("<4I", raw, 0)
        arr = np.frombuffer(raw, dtype="<f8", offset=16).reshape(n, cols)
        dist = arr[:, 0] / s
        if spec["signed"]:
            dist = dist * arr[:, 4]
        per_body[body.handle] = dist.astype(np.float32)
    if not per_body:
        raise SpecError("Choose a source surface other than the target.")
    return per_body, "unit"


def compute(doc, spec: dict, detail: float = 1.0) -> bytes:
    return compute_full(doc, spec, detail)[0]


def compute_full(doc, spec: dict, detail: float = 1.0) -> tuple:
    detail = round(max(0.1, min(10.0, float(detail))), 2)
    with doc.lock:
        d = doc.drawing
        spec = spec_mod.normalise(d, spec)
        mode = spec["mode"]
        scale = work.mm(d)
        rev = doc.rev
        if mode == "deviation":
            bodies = solid_rows(doc, spec["source"]) if spec["source"] else [e for e in solid_rows(doc, []) if e.handle != spec["target"]]
        else:
            bodies = solid_rows(doc, spec["targets"])
        measure = spec.get("measure", "")
        ramp_name, ramp = ramps.resolve(d, mode, measure, spec.get("ramp"))
        entries = []
        values = {}
        unit = ""
        if mode == "deviation":
            values, unit = deviation_values(doc, spec, bodies, detail)
            bodies = [b for b in bodies if b.handle in values]
        else:
            for b in bodies:
                pos, data = shape_data(d, b, detail, mode == "curvature")
                normals = data[:, :3]
                if mode in ("zebra", "isophote"):
                    values[b.handle] = stripes(spec, normals)
                    unit = "stripe"
                elif mode == "draft":
                    values[b.handle] = fields.draft(normals, spec["pull"])
                    unit = "deg"
                else:
                    values[b.handle], unit = fields.curvature(data, measure, scale)
        for b in bodies:
            entries.append((b, values[b.handle]))
        merged = np.concatenate([v for _b, v in entries]) if entries else np.zeros(0, dtype=np.float32)
        if mode == "draft":
            ramp = {**ramp}
            if spec.get("limits"):
                ramp["limits"] = spec["limits"]
            ramp["stops"] = fields.zone_stops(ramp)
            ramp["kind"] = "gradient"
        signed = mode in ("curvature", "draft") or (mode == "deviation" and spec["signed"])
        if mode == "deviation" and not spec["signed"] and ramp.get("max") is None:
            hi = float(np.nanmax(merged)) if np.isfinite(merged).any() else 1.0
            ramp = {**ramp, "max": hi if hi > 0 else 1.0}
        lo, hi = fields.value_range(merged, ramp, signed)
        stats = fields.deviation_stats(merged, spec.get("good"), spec.get("bad")) if mode == "deviation" else fields.summary(merged)
        names = {b.handle: b.name for b, _v in entries}
        versions = {b.handle: b.version for b, _v in entries}
    body_bytes = bytearray()
    table = []
    base = HEADER + RECORD * len(entries)
    for b, v in entries:
        while len(body_bytes) % 4:
            body_bytes.append(0)
        at = base + len(body_bytes)
        body_bytes.extend(np.ascontiguousarray(v, dtype="<f4").tobytes())
        table.append(struct.pack("<8I", b.handle, versions[b.handle], len(v), at, 1, 0, 0, 0))
    while len(body_bytes) % 4:
        body_bytes.append(0)
    meta = {
        "mode": mode, "label": spec_mod.LABELS[mode], "unit": unit, "measure": measure, "ramp_name": ramp_name, "ramp": ramp, "range": [lo, hi],
        "undefined": UNDEFINED, "stats": stats, "params": {k: v for k, v in spec.items() if k not in ("targets",)}, "mm_per_unit": scale,
        "detail": detail, "rev": rev, "bodies": [{"handle": h, "name": names[h]} for h in names],
    }
    blob = json.dumps(meta, separators=(",", ":")).encode("utf-8")
    blob += b" " * ((4 - len(blob) % 4) % 4)
    payload = b"".join(table) + bytes(body_bytes) + blob
    total = HEADER + len(payload)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    strings_at = base + len(body_bytes)
    head = struct.pack("<11I2fI2I", MAGIC, VERSION, HEADER, total, rev, len(entries), 0, HEADER, strings_at, len(blob), crc, lo, hi, MODE_CODE[mode], 0, 0)
    return head + payload, meta


def point_deviation(doc, points: list, target: int, faces: list | None = None, signed: bool = False, good: float | None = None, bad: float | None = None) -> dict:
    with doc.lock:
        d = doc.drawing
        s = work.mm(d)
        ent = d.get(int(target))
        if ent is None or ent.kind != "solidbody":
            raise SpecError("The target is not a solid or surface.")
        idx = []
        for pid in faces or []:
            if pid not in ent.face_ids:
                raise SpecError("The target has no face %s." % pid)
            idx.append(ent.face_ids.index(pid))
        arr = np.asarray(points, dtype=np.float64)
        if arr.ndim != 2 or arr.shape[1] not in (2, 3) or not len(arr) or not np.all(np.isfinite(arr)):
            raise SpecError("Give a list of points, each with two or three numbers.")
        if arr.shape[1] == 2:
            arr = np.concatenate([arr, np.zeros((len(arr), 1))], axis=1)
        if len(arr) > 200000:
            raise SpecError("Give at most 200000 points.")
        wid = work.worker_id(d, ent)
        mm = arr * s
    with tempfile.TemporaryDirectory(prefix="fcdev_") as tmp:
        pts = os.path.join(tmp, "p.pts")
        mm.astype("<f4").tofile(pts)
        out = os.path.join(tmp, "o.adat")
        work.kcall("an_deviation", {"points_path": pts, "target": wid, "faces": idx, "signed": bool(signed), "path": out}, work.LONG)
        with open(out, "rb") as fh:
            raw = fh.read()
    _m, n, cols, _z = struct.unpack_from("<4I", raw, 0)
    res = np.frombuffer(raw, dtype="<f8", offset=16).reshape(n, cols)
    dist = res[:, 0] / s
    if signed:
        dist = dist * res[:, 4]
    near = res[:, 1:4] / s
    return {"count": int(n), "distances": [None if not np.isfinite(x) else float(x) for x in dist], "closest": near.tolist(), "stats": fields.deviation_stats(dist.astype(np.float64), good, bad), "mm_per_unit": s}
