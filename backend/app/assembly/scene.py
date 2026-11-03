import json
import struct
import zlib

import numpy as np

from app.assembly import walk
from app.param.units import mm_per_unit
from app.solid import scene as base
from app.solid import work
from app.solid.work import SolidError


def _colour(body, host_d, layer_name="0") -> int:
    rgb = list(body.rgb or [])
    if len(rgb) == 3:
        r, g, b = (max(0, min(255, int(round(float(c) * 255)))) for c in rgb)
        return (r << 16) | (g << 8) | b
    return base.NO_COLOUR


def body_rows(doc, detail: float) -> tuple:
    d = doc.drawing
    scale = mm_per_unit(d)
    rows = []
    issues = []
    for inst in walk.instances(doc):
        if inst.record["type"] == "assembly" or inst.part is None:
            continue
        lp = inst.part
        for b in lp.bodies:
            raw = None
            err = ""
            if inst.visible:
                try:
                    raw = lp.mesh(b, detail)
                except SolidError as e:
                    err = str(e)
                if raw is None and not err:
                    err = "No stored picture of this body is available."
            if err:
                issues.append({"key": inst.key, "body": b.name, "message": err})
            rows.append({"inst": inst, "body": b, "lp": lp, "raw": raw, "visible": inst.visible, "world": inst.world, "mmu": lp.mm_per_unit})
    return rows, issues, scale


def loose_rows(doc, detail: float) -> list:
    d = doc.drawing
    out = []
    for e in d.ordered_entities():
        if e.kind != "solidbody" or e.owner != "model":
            continue
        vis = bool(d.visible(e))
        raw = None
        if vis:
            try:
                raw = work.mesh_for(d, e, detail)
            except SolidError:
                raw = None
        out.append({"ent": e, "raw": raw, "visible": vis, "colour": base.colour_word(d, e)})
    return out


def build(doc, since: int = 0, detail: float = 1.0) -> bytes:
    detail = round(max(0.1, min(10.0, float(detail))), 2)
    with doc.lock:
        rev = doc.rev
        scale = mm_per_unit(doc.drawing)
        rows, issues, _s = body_rows(doc, detail)
        loose = loose_rows(doc, detail)
    return pack(rev, scale, detail, rows, loose, issues)


def pack(rev, scale, detail, rows, loose, issues) -> bytes:
    body = bytearray()
    records = []
    strings = []
    n_rows = len(rows) + len(loose)
    table_bytes = n_rows * base.RECORD
    base_off = base.HEADER + table_bytes
    handle = 0

    def emit(raw, ent_handle, version, flags, colour, local_pos_fn, name, extra, face_ids, edge_ids):
        idx = len(records)
        strings.append({"handle": ent_handle, "name": name, "layer": "0", "source": "assembly", **extra})
        if raw is None:
            records.append(struct.pack("<32I", ent_handle, version, flags, colour, *([0] * 20), idx, *([0] * 7)))
            return
        flags |= base.FLAG_MESHED
        m = base.parse(raw)
        pos, nor, epos, snap_p, snap_n = local_pos_fn(m)
        faces = m["faces"].copy()
        faces[:, 0] = base.pids(face_ids, m["nf"])
        edges = m["edges"].copy()
        edges[:, 0] = base.pids(edge_ids, m["ne"])
        snaps = m["snaps"].copy()
        snaps["p"] = snap_p
        snaps["n"] = snap_n
        if m["ne"]:
            on_edge = snaps["kind"] != 0
            owners = np.clip(snaps["owner"][on_edge], 0, m["ne"] - 1)
            snaps["owner"][on_edge] = base.pids(edge_ids, m["ne"])[owners]
        sections = {}
        for key, arr in (("pos", pos), ("nor", nor), ("idx", m["idx"]), ("tri_face", m["tri_face"]), ("faces", faces), ("edges", edges), ("epos", epos), ("snaps", snaps)):
            base.pad4(body)
            sections[key] = base_off + len(body)
            body.extend(np.ascontiguousarray(arr).tobytes())
        if m["nv"]:
            lo, hi = pos.min(axis=0), pos.max(axis=0)
            box = [float(v) for v in (*lo, *hi)]
        else:
            box = [0.0] * 6
        records.append(
            struct.pack(
                "<18I6f8I", ent_handle, version, flags, colour, m["nv"], m["nt"], m["nf"], m["ne"], m["npts"], m["nsn"],
                sections["pos"], sections["nor"], sections["idx"], sections["tri_face"], sections["faces"], sections["edges"], sections["epos"], sections["snaps"],
                *box, idx, 0, 0, 0, 0, 0, 0, 0,
            )
        )

    for row in rows:
        handle += 1
        inst, b, lp = row["inst"], row["body"], row["lp"]
        R = np.asarray(row["world"][:3, :3], dtype=np.float64)
        t = np.asarray(row["world"][:3, 3], dtype=np.float64)
        off_mm = np.asarray(b.offset, dtype=np.float64) * lp.mm_per_unit
        k = 1.0 / scale

        def tf(m, R=R, t=t, off_mm=off_mm, k=k):
            p = ((m["pos"].astype(np.float64) + off_mm) * k) @ R.T + t
            e = ((m["epos"].astype(np.float64) + off_mm) * k) @ R.T + t
            n = m["nor"].astype(np.float64) @ R.T
            sp = ((m["snaps"]["p"].astype(np.float64) + off_mm) * k) @ R.T + t
            sn = m["snaps"]["n"].astype(np.float64) @ R.T
            return p.astype("<f4"), n.astype("<f4"), e.astype("<f4"), sp.astype("<f4"), sn.astype("<f4")

        version = zlib.crc32(("%s|%s|%s" % (b.blob, inst.key, ",".join("%.9g" % v for v in row["world"].reshape(-1)))).encode()) & 0x7FFFFFFF
        flags = (base.FLAG_VISIBLE if row["visible"] else 0) | (base.FLAG_CLOSED if b.closed else 0)
        extra = {"instance": inst.key, "component": inst.cid, "label": inst.record["label"], "body": b.name, "status": inst.status["status"], "stale": inst.status["stale"], "source_of_mesh": inst.status["source"]}
        emit(row["raw"] if row["visible"] else None, handle, version, flags, _colour(b, None), tf, inst.record["label"] + ("" if len(lp.bodies) == 1 else " / " + b.name), extra, b.face_ids, b.edge_ids)
    for row in loose:
        handle += 1
        e = row["ent"]
        off = np.asarray(e.offset, dtype=np.float64)

        def tfl(m, off=off):
            p = (m["pos"] / np.float32(scale) + off.astype("<f4")).astype("<f4")
            ep = (m["epos"] / np.float32(scale) + off.astype("<f4")).astype("<f4")
            sp = (m["snaps"]["p"] / np.float32(scale) + off.astype("<f4")).astype("<f4")
            return p, m["nor"], ep, sp, m["snaps"]["n"]

        flags = (base.FLAG_VISIBLE if row["visible"] else 0) | (base.FLAG_CLOSED if e.summary.get("closed") else 0)
        emit(row["raw"] if row["visible"] else None, handle, e.version, flags, row["colour"], tfl, e.name or "Body", {"instance": "", "component": "", "label": e.name, "body": e.name, "status": "loaded", "stale": False, "source_of_mesh": "file"}, e.face_ids, e.edge_ids)
    base.pad4(body)
    meta = json.dumps({"bodies": strings, "mm_per_unit": scale, "detail": detail, "rev": rev, "assembly": True, "issues": issues[:100]}, separators=(",", ":")).encode("utf-8")
    meta += b" " * ((4 - len(meta) % 4) % 4)
    table = b"".join(records)
    strings_at = base_off + len(body)
    payload = table + bytes(body) + meta
    total = base.HEADER + len(payload)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    head = struct.pack("<13IfII", base.MAGIC, base.VERSION, base.HEADER, total, rev, len(records), 0, 0, base.HEADER, base.HEADER + table_bytes, strings_at, len(meta), crc, scale, 0, 0)
    return head + payload
