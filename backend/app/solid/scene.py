import copy
import json
import struct
import zlib

import numpy as np

from app.display import palette
from app.solid import work
from app.solid.work import SolidError

MAGIC = 0x43534346
VERSION = 1
HEADER = 64
RECORD = 128
BODY_MAGIC = 0x4D424346
BODY_HEADER = 96
NO_COLOUR = 0xFFFFFFFF
FLAG_VISIBLE = 1
FLAG_MESHED = 2
FLAG_CLOSED = 4
SNAP = np.dtype([("p", "<f4", 3), ("kind", "<u4"), ("owner", "<u4"), ("n", "<f4", 3)])
MEDIA_TYPE = "application/vnd.formcad.scene"
BODY_KINDS = ("solidbody", "meshbody", "subdbody")


def pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


def colour_word(d, ent) -> int:
    if len(ent.rgb) == 3:
        r, g, b = (max(0, min(255, int(round(float(c) * 255)))) for c in ent.rgb)
        return (r << 16) | (g << 8) | b
    layer = d.layer(ent.layer)
    rgb, adaptive = palette.resolve(ent.color, layer["color"] if layer else 7, None)
    if adaptive:
        return NO_COLOUR
    return (rgb[0] << 16) | (rgb[1] << 8) | rgb[2]


def parse(mesh: bytes) -> dict:
    if len(mesh) < BODY_HEADER:
        raise SolidError("A stored mesh is truncated.")
    h = struct.unpack_from("<18I", mesh, 0)
    if h[0] != BODY_MAGIC or h[1] != 1 or h[16] != len(mesh):
        raise SolidError("A stored mesh has the wrong header.")
    if zlib.crc32(mesh[BODY_HEADER:]) & 0xFFFFFFFF != h[17]:
        raise SolidError("A stored mesh fails its checksum.")
    nv, nt, nf, ne, npts, nsn = h[2:8]
    off = h[8:16]

    def view(dtype, count, at, shape=None):
        arr = np.frombuffer(mesh, dtype=dtype, count=count, offset=at)
        return arr.reshape(shape) if shape else arr

    return {
        "nv": nv, "nt": nt, "nf": nf, "ne": ne, "npts": npts, "nsn": nsn,
        "pos": view("<f4", nv * 3, off[0], (nv, 3)),
        "nor": view("<f4", nv * 3, off[1], (nv, 3)),
        "idx": view("<u4", nt * 3, off[2]),
        "tri_face": view("<u4", nt, off[3]),
        "faces": view("<u4", nf * 4, off[4], (nf, 4)),
        "edges": view("<u4", ne * 4, off[5], (ne, 4)),
        "epos": view("<f4", npts * 3, off[6], (npts, 3)),
        "snaps": np.frombuffer(mesh, dtype=SNAP, count=nsn, offset=off[7]),
    }


def pids(values: list, count: int) -> np.ndarray:
    arr = np.zeros(count, dtype="<u4")
    n = min(count, len(values))
    if n:
        arr[:n] = np.asarray(values[:n], dtype="<u4")
    return arr


def collect(doc, since: int):
    d = doc.drawing
    if since <= 0:
        picked = [e for e in d.ordered_entities() if e.kind in BODY_KINDS]
        removed = []
    else:
        picked = [d.ents[h] for h, r in doc.ent_rev.items() if r > since and h in d.ents and d.ents[h].kind in BODY_KINDS]
        removed = [h for h, r in doc.removed_rev.items() if r > since and h not in d.ents]
    rows = []
    for e in picked:
        rows.append({"ent": copy.copy(e), "visible": bool(d.visible(e)), "colour": colour_word(d, e), "layer": e.layer})
    return rows, removed, doc.rev, work.mm(d)


def build(doc, since: int = 0, detail: float = 1.0) -> bytes:
    detail = round(max(0.1, min(10.0, float(detail))), 2)
    with doc.lock:
        rows, removed, rev, scale = collect(doc, int(since))
        d = doc.drawing
    meshes = {}
    for row in rows:
        if row["visible"]:
            if row["ent"].kind == "meshbody":
                from app.meshes import store as mesh_store

                try:
                    meshes[row["ent"].handle] = mesh_store.scene_bytes(d, row["ent"])
                except Exception as err:
                    raise SolidError(str(err))
            elif row["ent"].kind == "subdbody":
                from app.subd import store as subd_store

                try:
                    meshes[row["ent"].handle] = subd_store.scene_bytes(d, row["ent"])
                except Exception as err:
                    raise SolidError(str(err))
            else:
                meshes[row["ent"].handle] = work.mesh_for(d, row["ent"], detail)
    body = bytearray()
    records = []
    strings = []
    table_bytes = len(rows) * RECORD
    base = HEADER + table_bytes + 4 * len(removed)
    for i, row in enumerate(rows):
        ent = row["ent"]
        raw = meshes.get(ent.handle)
        strings.append({"handle": ent.handle, "name": ent.name, "layer": ent.layer, "source": ent.source.get("op", "")})
        flags = (FLAG_VISIBLE if row["visible"] else 0) | (FLAG_CLOSED if ent.summary.get("closed") else 0)
        if raw is None:
            records.append(struct.pack("<32I", ent.handle, ent.version, flags, row["colour"], *([0] * 20), i, *([0] * 7)))
            continue
        flags |= FLAG_MESHED
        m = parse(raw)
        off = np.asarray(ent.offset, dtype="<f4")
        pos = (m["pos"] / np.float32(scale) + off).astype("<f4")
        epos = (m["epos"] / np.float32(scale) + off).astype("<f4")
        faces = m["faces"].copy()
        edges = m["edges"].copy()
        if ent.kind != "subdbody":
            faces[:, 0] = pids(ent.face_ids, m["nf"])
            edges[:, 0] = pids(ent.edge_ids, m["ne"])
        snaps = m["snaps"].copy()
        snaps["p"] = snaps["p"] / np.float32(scale) + off
        edge_pid = pids(ent.edge_ids, m["ne"])
        on_edge = snaps["kind"] != 0
        if m["ne"]:
            owners = np.clip(snaps["owner"][on_edge], 0, m["ne"] - 1)
            snaps["owner"][on_edge] = edge_pid[owners]
        sections = {}
        for name, arr in (("pos", pos), ("nor", m["nor"]), ("idx", m["idx"]), ("tri_face", m["tri_face"]), ("faces", faces), ("edges", edges), ("epos", epos), ("snaps", snaps)):
            pad4(body)
            sections[name] = base + len(body)
            body.extend(np.ascontiguousarray(arr).tobytes())
        if m["nv"]:
            lo = pos.min(axis=0)
            hi = pos.max(axis=0)
            box = [float(v) for v in (*lo, *hi)]
        else:
            box = [0.0] * 6
        records.append(
            struct.pack(
                "<18I6f8I",
                ent.handle, ent.version, flags, row["colour"], m["nv"], m["nt"], m["nf"], m["ne"], m["npts"], m["nsn"],
                sections["pos"], sections["nor"], sections["idx"], sections["tri_face"], sections["faces"], sections["edges"], sections["epos"], sections["snaps"],
                *box,
                i, 0, 0, 0, 0, 0, 0, 0,
            )
        )
    pad4(body)
    meta = json.dumps({"bodies": strings, "mm_per_unit": scale, "detail": detail, "rev": rev}, separators=(",", ":")).encode("utf-8")
    meta += b" " * ((4 - len(meta) % 4) % 4)
    table = b"".join(records)
    removed_bytes = struct.pack("<%dI" % len(removed), *removed) if removed else b""
    strings_at = base + len(body)
    payload = table + removed_bytes + bytes(body) + meta
    total = HEADER + len(payload)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    head = struct.pack(
        "<13IfII",
        MAGIC, VERSION, HEADER, total, rev, len(rows), 1 if since > 0 else 0, len(removed),
        HEADER, HEADER + table_bytes, strings_at, len(meta), crc, scale, 0, 0,
    )
    return head + payload
