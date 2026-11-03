import struct
import threading
import zlib
from collections import OrderedDict

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from app.doc.kinds.subdbody import SubdBody
from app.param.units import mm_per_unit
from app.subd import cc, sym as symmetry
from app.subd.cage import Cage
from app.subd.cc import INF, SubdError

BODY_MAGIC = 0x4D424346
BODY_HEADER = 96
MAX_DISPLAY_TRIANGLES = 120000
CACHE_LIMIT = 8
_scene: OrderedDict = OrderedDict()
_lock = threading.RLock()


def load(ent) -> Cage:
    return Cage.from_entity(ent)


def summary_of(cage: Cage) -> dict:
    an = cage.analysis()
    return {
        "vertices": an["vertices"], "faces": an["faces"], "edges": an["edges"], "closed": an["closed"], "manifold": an["manifold"],
        "creases": an["creases"], "extraordinary": an["extraordinary_count"], "boundary_edges": an["boundary_edges"], "euler": an["euler"],
        "bbox": cage.bbox(), "volume_estimate": an["volume_estimate"],
    }


def fill(d, ent, cage: Cage, source=None, sym=None) -> None:
    cage.validate()
    fields = cage.to_fields()
    ent.v, ent.f, ent.crease = fields["v"], fields["f"], fields["crease"]
    if sym is not None:
        ent.sym = symmetry.clean(sym)
    ent.version = int(ent.version) + 1
    ent.summary = summary_of(cage)
    bb = ent.summary["bbox"]
    ent.extent = [bb[0], bb[1], bb[3], bb[4]]
    if source is not None:
        ent.source = source
    with _lock:
        _scene.clear()


def touch() -> None:
    with _lock:
        _scene.clear()


def new_entity(d, cage: Cage, name: str, source: dict, sym=None, display="both", level=3, rgb=None, origin=None) -> SubdBody:
    ent = SubdBody(name=name, display=display, level=int(level), rgb=list(rgb or []), version=0)
    fill(d, ent, cage, source, sym if sym is not None else symmetry.default_sym())
    return ent


def display_level(cage: Cage, wanted: int) -> int:
    corners = sum(len(f) for f in cage.f)
    level = max(1, min(4, int(wanted)))
    while level > 1 and 2 * corners * 4 ** (level - 1) > MAX_DISPLAY_TRIANGLES:
        level -= 1
    return level


def pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


def corner_normals(lv, face_n):
    ea, eb, inv, cnt, nxt, prv = cc.edge_table(lv)
    n = len(lv.fv)
    s = cc.edge_sharpness(lv, ea, eb, cnt)
    order = np.argsort(inv, kind="stable")
    sorted_e = inv[order]
    first = np.searchsorted(sorted_e, np.arange(len(ea)))
    two = np.nonzero((cnt == 2) & (s <= 0))[0]
    c1 = order[first[two]]
    c2 = order[first[two] + 1]
    rows = np.concatenate([c1, nxt[c1]])
    cols = np.concatenate([nxt[c2], c2])
    g = coo_matrix((np.ones(len(rows)), (rows, cols)), shape=(n, n))
    _, comp = connected_components(g, directed=False)
    acc = np.zeros((comp.max() + 1, 3)) if n else np.zeros((0, 3))
    np.add.at(acc, comp, face_n[lv.cf])
    out = acc[comp]
    ln = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(ln, 1e-300)


def smooth_mesh(cage: Cage, level: int):
    chain = cc.refine(cage.v, cage.f, cage.crease, level)
    lv = chain[-1]
    quads = lv.quads()
    p = lv.v
    a, b, c, d = (p[quads[:, i]] for i in range(4))
    fn = np.cross(c - a, d - b)
    cn = corner_normals(lv, fn)
    root = cc.face_root(chain)
    return lv, quads, cn, root


def pack_body(pos, nor, idx, tri_face, faces, edges, epos, snaps, box):
    body = bytearray()
    offsets = {}
    for name, arr in (("pos", pos), ("nor", nor), ("idx", idx), ("tri_face", tri_face), ("faces", faces), ("edges", edges), ("epos", epos), ("snaps", snaps)):
        pad4(body)
        offsets[name] = BODY_HEADER + len(body)
        body.extend(np.ascontiguousarray(arr).tobytes())
    pad4(body)
    nt = len(idx) // 3
    total = BODY_HEADER + len(body)
    crc = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    head = struct.pack("<16I6f", BODY_MAGIC, 1, len(pos), nt, len(faces), len(edges), len(epos), len(snaps), offsets["pos"], offsets["nor"], offsets["idx"], offsets["tri_face"], offsets["faces"], offsets["edges"], offsets["epos"], offsets["snaps"], *[float(x) for x in box])
    head = head[:64] + struct.pack("<2I", total, crc) + head[64:]
    return head + bytes(body)


SNAP = np.dtype([("p", "<f4", 3), ("kind", "<u4"), ("owner", "<u4"), ("n", "<f4", 3)])


def scene_bytes(d, ent) -> bytes:
    key = (ent.handle, ent.version, ent.display, ent.level)
    with _lock:
        got = _scene.get(key)
        if got is not None:
            _scene.move_to_end(key)
            return got
    s = mm_per_unit(d)
    cage = load(ent)
    nf = len(cage.f)
    show_surface = ent.display in ("smooth", "both")
    show_cage = ent.display in ("box", "both")
    pos_l, nor_l, idx_l, tri_l = [], [], [], []
    face_rows = np.zeros((nf, 4), dtype="<u4")
    if show_surface:
        try:
            lv, quads, cn, root = smooth_mesh(cage, display_level(cage, ent.level))
        except SubdError:
            show_surface = False
            show_cage = True
    if show_surface:
        order = np.argsort(root, kind="stable")
        q = quads[order]
        r = root[order]
        cn4 = cn.reshape(-1, 4, 3)[order]
        corner_pos = lv.v[q]
        tri_idx = np.array([0, 1, 2, 0, 2, 3])
        pos = corner_pos[:, tri_idx, :].reshape(-1, 3)
        nor = cn4[:, tri_idx, :].reshape(-1, 3)
        tri_face = np.repeat(r, 2)
        counts = 2 * np.bincount(r, minlength=nf)
    else:
        verts, norms, tf = [], [], []
        counts = np.zeros(nf, dtype=np.int64)
        for fi, face in enumerate(cage.f):
            pts = cage.v[face]
            nrm = np.zeros(3)
            for i in range(len(face)):
                nrm += np.cross(pts[i], pts[(i + 1) % len(face)])
            ln = np.linalg.norm(nrm)
            nrm = nrm / ln if ln > 0 else np.array([0.0, 0.0, 1.0])
            for i in range(1, len(face) - 1):
                verts.extend((pts[0], pts[i], pts[i + 1]))
                norms.extend((nrm, nrm, nrm))
                tf.append(fi)
            counts[fi] = len(face) - 2
        pos = np.array(verts).reshape(-1, 3)
        nor = np.array(norms).reshape(-1, 3)
        tri_face = np.array(tf, dtype=np.int64)
    first = np.concatenate(([0], np.cumsum(counts)[:-1])) if nf else np.zeros(0, dtype=np.int64)
    for fi in range(nf):
        face_rows[fi] = (fi + 1, int(first[fi]), int(counts[fi]), 10)
    pos_mm = (pos * s).astype("<f4")
    idx = np.arange(len(pos_mm), dtype="<u4")
    edges_k = cage.edge_list()
    edge_rows, epos = [], []
    for k, (a, b) in enumerate(edges_k):
        w = cage.crease.get((a, b), 0.0)
        cls = 2 if w >= INF else (1 if w > 0 else 0)
        edge_rows.append((k + 1, len(epos), 2, 20 + cls))
        epos.extend((cage.v[a] * s, cage.v[b] * s))
    owners_count = {}
    for face in cage.f:
        for i in range(len(face)):
            owners_count[(min(face[i], face[(i + 1) % len(face)]), max(face[i], face[(i + 1) % len(face)]))] = owners_count.get((min(face[i], face[(i + 1) % len(face)]), max(face[i], face[(i + 1) % len(face)])), 0) + 1
    for k, e in enumerate(edges_k):
        if owners_count.get(e, 0) == 1:
            edge_rows[k] = (k + 1, edge_rows[k][1], 2, 23)
    if not show_cage:
        keep = [i for i, r in enumerate(edge_rows) if r[3] != 20]
        rows2, epos2 = [], []
        for i in keep:
            r = edge_rows[i]
            rows2.append((r[0], len(epos2), 2, r[3]))
            epos2.extend((epos[r[1]], epos[r[1] + 1]))
        edge_rows, epos = rows2, epos2
    edges_arr = np.array(edge_rows, dtype="<u4").reshape(-1, 4)
    epos_arr = np.array(epos, dtype="<f4").reshape(-1, 3)
    if show_cage and len(cage.v):
        snaps = np.zeros(len(cage.v), dtype=SNAP)
        snaps["p"] = (cage.v * s).astype("<f4")
        snaps["kind"] = 0
        snaps["owner"] = np.arange(1, len(cage.v) + 1, dtype="<u4")
        snaps["n"] = 0.0
    else:
        snaps = np.zeros(0, dtype=SNAP)
    allp = [pos_mm] if len(pos_mm) else []
    if len(epos_arr):
        allp.append(epos_arr)
    if allp:
        stack = np.concatenate(allp)
        box = [*stack.min(axis=0), *stack.max(axis=0)]
    else:
        box = [0.0] * 6
    out = pack_body(pos_mm, nor.astype("<f4"), idx, tri_face.astype("<u4"), face_rows, edges_arr, epos_arr, snaps, box)
    with _lock:
        _scene[key] = out
        while len(_scene) > CACHE_LIMIT:
            _scene.popitem(last=False)
    return out


def limit_mesh(cage: Cage, level: int):
    level = max(1, min(4, int(level)))
    corners = sum(len(f) for f in cage.f)
    if corners * 4 ** (level - 1) > 200000:
        raise SubdError("That level would make more than 200000 faces.")
    chain = cc.refine(cage.v, cage.f, cage.crease, level)
    lv = chain[-1]
    return lv.v, lv.quads(), cc.face_root(chain)
