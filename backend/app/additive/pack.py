import json
import math
import re

import numpy as np

from app.additive.toolpath import FEATURE_CODES

MAGIC = b"FCL1"
MEDIA_TYPE = "application/vnd.formcad.layers"
WIDTH_UNIT = 0.01


class PackError(ValueError):
    pass


def assemble(layer_rows: list, header_extra: dict, pos_list, idx_list, feat_list, width_list) -> bytes:
    pos = np.asarray(pos_list, dtype="<f4").reshape(-1, 3)
    idx = np.asarray(idx_list, dtype="<u4").reshape(-1, 2)
    feat = np.asarray(feat_list, dtype="u1")
    wid = np.asarray(width_list, dtype="u1")
    blob = bytearray()
    arrays = {}

    def put(name, arr, kind, stride=None, **extra):
        while len(blob) % 4:
            blob.append(0)
        raw = arr.tobytes()
        info = {"offset": len(blob), "count": int(arr.shape[0]), "type": kind}
        if stride:
            info["stride"] = stride
        info.update(extra)
        arrays[name] = info
        blob.extend(raw)

    put("positions", pos, "f32", 3)
    put("indices", idx, "u32", 2)
    put("features", feat, "u8")
    put("widths", wid, "u8", unit_mm=WIDTH_UNIT)
    bbox = [0.0] * 6
    if len(pos):
        lo, hi = pos.min(axis=0), pos.max(axis=0)
        bbox = [float(x) for x in (*lo, *hi)]
    head = {"version": 1, "units": "mm", "layer_count": len(layer_rows), "layers": layer_rows, "feature_codes": FEATURE_CODES, "arrays": arrays, "bbox": bbox}
    head.update(header_extra)
    text = json.dumps(head, separators=(",", ":")).encode("utf-8")
    text += b" " * ((-len(text)) % 4)
    return MAGIC + len(text).to_bytes(4, "little") + text + bytes(blob)


def header_of(data: bytes) -> dict:
    if data[:4] != MAGIC:
        raise PackError("That is not a layer pack.")
    n = int.from_bytes(data[4:8], "little")
    return json.loads(data[8:8 + n].decode("utf-8"))


def from_layers(layers: list, extra: dict) -> bytes:
    pos, idx, feat, wid = [], [], [], []
    rows = []
    for L in layers:
        v0, s0 = len(pos), len(idx)
        cur = None
        z = L.z
        for op in L.ops:
            if op[0] == "T":
                pos.append((op[1], op[2], z))
                vid = len(pos) - 1
                if cur is not None:
                    idx.append((cur, vid))
                    feat.append(0)
                    wid.append(0)
                cur = vid
                continue
            pts = op[2]
            w = min(255, int(round(op[3] / WIDTH_UNIT)))
            if cur is None:
                pos.append((float(pts[0][0]), float(pts[0][1]), z))
                cur = len(pos) - 1
            for q in pts[1:]:
                pos.append((float(q[0]), float(q[1]), z))
                vid = len(pos) - 1
                idx.append((cur, vid))
                feat.append(op[1])
                wid.append(w)
                cur = vid
        rows.append({"index": L.index, "z": round(L.z, 4), "height": round(L.h, 4), "first_vertex": v0, "vertex_count": len(pos) - v0, "first_segment": s0, "segment_count": len(idx) - s0, "time_s": round(L.time_s, 3), "filament_mm": round(L.fil_mm, 4)})
    return assemble(rows, extra, pos, idx, feat, wid)


TYPE_MAP = {"WALL-OUTER": 1, "EXTERNAL PERIMETER": 1, "WALL-INNER": 2, "PERIMETER": 2, "FILL": 3, "INTERNAL INFILL": 3, "SOLID-FILL": 4, "SOLID INFILL": 4, "SKIN": 5, "TOP SOLID INFILL": 5, "BRIDGE": 6, "BRIDGE INFILL": 6, "SUPPORT": 7, "SUPPORT MATERIAL": 7, "SUPPORT-INTERFACE": 8, "SUPPORT MATERIAL INTERFACE": 8, "SKIRT": 9, "SKIRT/BRIM": 9, "GAP-FILL": 10, "GAP FILL": 10}
WORD = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")
MAX_LINES = 6_000_000


def parse_gcode(text: str, limit_lines: int = MAX_LINES) -> bytes:
    lines = text.splitlines()
    if len(lines) > limit_lines:
        raise PackError("The G-code has %d lines; the limit is %d." % (len(lines), limit_lines))
    x = y = z = 0.0
    e_abs = 0.0
    rel = False
    abs_xyz = True
    f = 1500.0
    feature = 3
    width = 45
    layers = []
    cur_layer = None
    pos, idx, feat, wid = [], [], [], []
    cur_vid = None
    z_seen = None
    layer_h = 0.2
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        comment = ""
        if ";" in line:
            line, comment = line.split(";", 1)
            line = line.strip()
            c = comment.strip()
            if c.upper().startswith("TYPE:"):
                feature = TYPE_MAP.get(c[5:].strip().upper(), 3)
            elif c.upper().startswith("WIDTH:"):
                try:
                    width = min(255, int(round(float(c[6:]) / WIDTH_UNIT)))
                except ValueError:
                    pass
            elif c.upper().startswith("HEIGHT:"):
                try:
                    layer_h = float(c[7:])
                except ValueError:
                    pass
        if not line:
            continue
        words = WORD.findall(line)
        if not words:
            continue
        cmd = (words[0][0].upper() + str(int(float(words[0][1])))) if words[0][0].upper() in "GM" else ""
        vals = {k.upper(): float(v) for k, v in words[1:]}
        if cmd == "M83":
            rel = True
        elif cmd == "M82":
            rel = False
        elif cmd == "G90":
            abs_xyz = True
        elif cmd == "G91":
            abs_xyz = False
        elif cmd == "G92":
            if "E" in vals:
                e_abs = vals["E"]
        elif cmd in ("G0", "G1"):
            nx = x + vals["X"] if (not abs_xyz and "X" in vals) else vals.get("X", x)
            ny = y + vals["Y"] if (not abs_xyz and "Y" in vals) else vals.get("Y", y)
            nz = z + vals["Z"] if (not abs_xyz and "Z" in vals) else vals.get("Z", z)
            if "F" in vals:
                f = vals["F"]
            de = 0.0
            if "E" in vals:
                de = vals["E"] if rel else vals["E"] - e_abs
                if not rel:
                    e_abs = vals["E"]
            moved = (nx != x) or (ny != y)
            if nz != z and not moved and de <= 0:
                z = nz
                continue
            if moved:
                if de > 1e-9 and (z_seen is None or abs(z - z_seen) > 1e-6):
                    if len(layers) >= 100000:
                        raise PackError("The G-code has more than 100000 layers.")
                    layers.append({"index": len(layers), "z": round(z, 4), "height": round(layer_h if z_seen is None else z - z_seen, 4), "first_vertex": len(pos), "first_segment": len(idx), "time_s": 0.0, "filament_mm": 0.0})
                    z_seen = z
                    cur_vid = None
                if not layers:
                    x, y, z = nx, ny, nz
                    continue
                lay = layers[-1]
                if cur_vid is None:
                    pos.append((x, y, lay["z"]))
                    cur_vid = len(pos) - 1
                pos.append((nx, ny, lay["z"]))
                vid = len(pos) - 1
                idx.append((cur_vid, vid))
                dist = math.hypot(nx - x, ny - y)
                if de > 1e-9:
                    feat.append(feature)
                    wid.append(width)
                    lay["filament_mm"] += de
                else:
                    feat.append(0)
                    wid.append(0)
                lay["time_s"] += dist / max(f / 60.0, 1.0)
                cur_vid = vid
            x, y, z = nx, ny, nz
    if not idx:
        raise PackError("The G-code holds no moves.")
    for i, lay in enumerate(layers):
        nxt = layers[i + 1] if i + 1 < len(layers) else None
        lay["vertex_count"] = (nxt["first_vertex"] if nxt else len(pos)) - lay["first_vertex"]
        lay["segment_count"] = (nxt["first_segment"] if nxt else len(idx)) - lay["first_segment"]
        lay["time_s"] = round(lay["time_s"], 3)
        lay["filament_mm"] = round(lay["filament_mm"], 4)
    totals = {"time_s": round(sum(a["time_s"] for a in layers), 3), "filament_mm": round(sum(a["filament_mm"] for a in layers), 4), "layers": len(layers), "support_volume_mm3": None}
    return assemble(layers, {"totals": totals, "source": "gcode", "profile": None, "plate": None, "hash": ""}, pos, idx, feat, wid)
