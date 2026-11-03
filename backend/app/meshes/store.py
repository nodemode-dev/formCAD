import struct
import threading
import zlib
from collections import OrderedDict

import numpy as np

from app.meshes import core
from app.meshes.core import Mesh, MeshError
from app.solid import blobs, ids

FCM_MAGIC = b"FCM1"
BODY_MAGIC = 0x4D424346
BODY_HEADER = 96
FLAT_LIMIT = 200_000
CACHE_LIMIT = 8
_cache: OrderedDict = OrderedDict()
_scene: OrderedDict = OrderedDict()
_lock = threading.RLock()


def pack(m: Mesh, points_only: bool = False) -> bytes:
    return FCM_MAGIC + struct.pack("<III", len(m.v), len(m.t), 1 if points_only else 0) + m.v.astype("<f8").tobytes() + m.t.astype("<i4").tobytes()


def unpack(data: bytes):
    if len(data) < 16 or data[:4] != FCM_MAGIC:
        raise MeshError("A stored mesh has the wrong header.")
    nv, nt, flags = struct.unpack("<III", data[4:16])
    if len(data) != 16 + nv * 24 + nt * 12:
        raise MeshError("A stored mesh is truncated.")
    v = np.frombuffer(data, dtype="<f8", count=nv * 3, offset=16).reshape(nv, 3)
    t = np.frombuffer(data, dtype="<i4", count=nt * 3, offset=16 + nv * 24).reshape(nt, 3)
    return Mesh(v, t), bool(flags & 1)


def mesh_path(blob: str) -> str:
    return "%s%s.fmesh" % (blobs.MESH_DIR, blob)


def put(d, data: bytes) -> str:
    if len(data) > blobs.MAX_BLOB:
        raise MeshError("The mesh is larger than the 256 MB limit.")
    blob = blobs.digest(data)
    d.blobs.setdefault(mesh_path(blob), data)
    return blob


def load(d, ent) -> Mesh:
    with _lock:
        got = _cache.get(ent.blob)
        if got is not None:
            _cache.move_to_end(ent.blob)
            return got
    data = d.blobs.get(mesh_path(ent.blob))
    if data is None:
        raise MeshError("The stored mesh %s is missing from the file." % ent.blob)
    m, _points = unpack(data)
    with _lock:
        _cache[ent.blob] = m
        while len(_cache) > CACHE_LIMIT:
            _cache.popitem(last=False)
    return m


def summary_of(m: Mesh, points_only: bool = False) -> dict:
    if points_only:
        return {"vertices": int(len(m.v)), "triangles": 0, "bbox": m.bbox(), "closed": False, "points": True}
    r = core.report(m)
    return r


def extent_units(scale: float, bbox) -> list:
    if not bbox or len(bbox) != 6:
        return []
    return [bbox[0] / scale, bbox[1] / scale, bbox[3] / scale, bbox[4] / scale]


def fill_body(d, body, m: Mesh, source: dict, scale: float, points_only: bool = False) -> None:
    data = pack(m, points_only)
    body.blob = put(d, data)
    body.version = int(body.version) + 1
    body.summary = summary_of(m, points_only)
    body.source = source
    body.extent = extent_units(scale, body.summary.get("bbox"))
    body.points_only = bool(points_only)
    body.offset = [0.0, 0.0, 0.0] if not body.offset else body.offset
    if not body.face_ids:
        body.face_ids = ids.mint(d, 1)
    body.edge_ids = []
    with _lock:
        _cache[body.blob] = m


def new_body(d, m: Mesh, name: str, source: dict, scale: float, points_only: bool = False, rgb=None):
    from app.doc.kinds.meshbody import MeshBody

    body = MeshBody(name=name, source=source, version=0, rgb=list(rgb or []))
    fill_body(d, body, m, source, scale, points_only)
    return body


def naked_polylines(m: Mesh) -> list:
    cls = core.edge_classes(m)
    if not len(cls["naked"]):
        return []
    loops, chains = core.naked_loops(cls["naked"])
    out = []
    for lp in loops:
        out.append(lp + [lp[0]])
    out.extend(chains)
    return out


def pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


def scene_bytes(d, ent) -> bytes:
    key = (ent.blob, bool(ent.points_only))
    with _lock:
        got = _scene.get(key)
        if got is not None:
            _scene.move_to_end(key)
            return got
    m = load(d, ent)
    flat = len(m.t) <= FLAT_LIMIT
    if ent.points_only or not len(m.t):
        pos = np.zeros((0, 3), dtype="<f4")
        nor = np.zeros((0, 3), dtype="<f4")
        idx = np.zeros(0, dtype="<u4")
    elif flat:
        pos = m.v[m.t].reshape(-1, 3).astype("<f4")
        nor = np.repeat(core.triangle_normals(m), 3, axis=0).astype("<f4")
        idx = np.arange(len(m.t) * 3, dtype="<u4")
    else:
        pos = m.v.astype("<f4")
        nor = core.vertex_normals(m).astype("<f4")
        idx = m.t.astype("<u4").ravel()
    nt = len(idx) // 3
    lines = [] if ent.points_only else naked_polylines(m)
    epos, erows = [], []
    for k, ln in enumerate(lines):
        erows.append((0, len(epos), len(ln), 8))
        epos.extend(m.v[ln].tolist())
    epos_arr = np.array(epos, dtype="<f4").reshape(-1, 3)
    faces = np.array([[0, 0, nt, 10]], dtype="<u4")
    edges = np.array(erows, dtype="<u4").reshape(-1, 4)
    tri_face = np.zeros(nt, dtype="<u4")
    snaps = np.zeros(0, dtype=np.dtype([("p", "<f4", 3), ("kind", "<u4"), ("owner", "<u4"), ("n", "<f4", 3)]))
    body = bytearray()
    offsets = {}
    for name, arr in (("pos", pos), ("nor", nor), ("idx", idx), ("tri_face", tri_face), ("faces", faces), ("edges", edges), ("epos", epos_arr), ("snaps", snaps)):
        pad4(body)
        offsets[name] = BODY_HEADER + len(body)
        body.extend(np.ascontiguousarray(arr).tobytes())
    pad4(body)
    box = m.bbox() if len(m.v) else [0.0] * 6
    total = BODY_HEADER + len(body)
    crc = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    head = struct.pack("<16I6f", BODY_MAGIC, 1, len(pos), nt, 1, len(edges), len(epos_arr), 0, offsets["pos"], offsets["nor"], offsets["idx"], offsets["tri_face"], offsets["faces"], offsets["edges"], offsets["epos"], offsets["snaps"], *[float(x) for x in box])
    head = head[:64] + struct.pack("<2I", total, crc) + head[64:]
    out = head + bytes(body)
    with _lock:
        _scene[key] = out
        while len(_scene) > CACHE_LIMIT:
            _scene.popitem(last=False)
    return out
