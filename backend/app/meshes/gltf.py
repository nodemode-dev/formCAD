import base64
import json
import math
import os
import struct

import numpy as np

from app.meshes.core import Mesh, MeshError

MAX_JSON = 64 * 1024 * 1024
MAX_BUFFER = 512 * 1024 * 1024
MAX_TRIANGLES = 20_000_000
MAX_NODES = 100000
MAX_DEPTH = 64
COMPONENT = {5120: "i1", 5121: "u1", 5122: "i2", 5123: "u2", 5125: "u4", 5126: "f4"}
WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
METAL_WORDS = ("steel", "iron", "aluminium", "aluminum", "brass", "bronze", "copper", "titanium", "zinc", "nickel", "magnesium", "metal", "alloy")


def srgb_to_linear(c):
    c = max(0.0, min(1.0, float(c)))
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c):
    c = max(0.0, min(1.0, float(c)))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def pbr_for(rgb, material_name):
    name = (material_name or "").lower()
    metal = any(w in name for w in METAL_WORDS)
    base = rgb if rgb else ([0.72, 0.74, 0.77] if metal else [0.78, 0.78, 0.8])
    return {
        "name": material_name or "Default",
        "pbrMetallicRoughness": {"baseColorFactor": [srgb_to_linear(base[0]), srgb_to_linear(base[1]), srgb_to_linear(base[2]), 1.0], "metallicFactor": 1.0 if metal else 0.0, "roughnessFactor": 0.4 if metal else 0.8},
        "doubleSided": False,
    }


def pad(blob: bytes, fill: bytes) -> bytes:
    return blob + fill * ((4 - len(blob) % 4) % 4)


def write_glb(parts: list, title: str = "FormCAD") -> bytes:
    bin_chunks = []
    views, accessors, meshes, nodes, materials = [], [], [], [], []
    offset = 0
    mat_index = {}
    for p in parts:
        m = p["mesh"]
        if not len(m.t):
            continue
        key = (tuple(p.get("rgb") or ()), p.get("material") or "")
        if key not in mat_index:
            mat_index[key] = len(materials)
            materials.append(pbr_for(p.get("rgb"), p.get("material")))
        pos = (m.v * 0.001).astype("<f4")
        idx = m.t.astype("<u4")
        pos_bytes = pad(pos.tobytes(), b"\x00")
        idx_bytes = pad(idx.tobytes(), b"\x00")
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(pos.tobytes()), "target": 34962})
        bin_chunks.append(pos_bytes)
        offset += len(pos_bytes)
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(idx.tobytes()), "target": 34963})
        bin_chunks.append(idx_bytes)
        offset += len(idx_bytes)
        lo, hi = pos.min(axis=0), pos.max(axis=0)
        accessors.append({"bufferView": len(views) - 2, "componentType": 5126, "count": int(len(pos)), "type": "VEC3", "min": [float(x) for x in lo], "max": [float(x) for x in hi]})
        accessors.append({"bufferView": len(views) - 1, "componentType": 5125, "count": int(idx.size), "type": "SCALAR"})
        meshes.append({"name": str(p.get("name") or "Body")[:120], "primitives": [{"attributes": {"POSITION": len(accessors) - 2}, "indices": len(accessors) - 1, "material": mat_index[key], "mode": 4}]})
        nodes.append({"name": str(p.get("name") or "Body")[:120], "mesh": len(meshes) - 1})
    if not meshes:
        raise MeshError("There are no triangles to write.")
    root = {"name": "FormCAD Z-up to Y-up", "rotation": [-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)], "children": list(range(len(nodes)))}
    doc = {
        "asset": {"version": "2.0", "generator": "FormCAD", "extras": {"title": title, "sourceUnit": "mm", "note": "Metres, Y up. The root node turns the FormCAD Z-up model."}},
        "scene": 0,
        "scenes": [{"nodes": [len(nodes)]}],
        "nodes": nodes + [root],
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": offset}],
    }
    js = pad(json.dumps(doc, separators=(",", ":")).encode("utf-8"), b" ")
    bn = b"".join(bin_chunks)
    total = 12 + 8 + len(js) + 8 + len(bn)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bn), 0x004E4942) + bn


def split_glb(data: bytes):
    if len(data) < 20:
        raise MeshError("The GLB file is truncated.")
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2:
        raise MeshError("The file is not a glTF 2.0 binary.")
    if length > len(data):
        raise MeshError("The GLB length field is larger than the file.")
    pos, js, bn = 12, None, None
    while pos + 8 <= length:
        clen, ctype = struct.unpack_from("<II", data, pos)
        pos += 8
        chunk = data[pos:pos + clen]
        if len(chunk) != clen:
            raise MeshError("A GLB chunk is cut off.")
        if ctype == 0x4E4F534A and js is None:
            js = chunk
        elif ctype == 0x004E4942 and bn is None:
            bn = chunk
        pos += clen
    if js is None:
        raise MeshError("The GLB file has no JSON chunk.")
    return json.loads(js.decode("utf-8")), bn


def load_buffers(doc, glb_bin, base_dir):
    out = []
    for b in doc.get("buffers", []):
        uri = b.get("uri")
        if uri is None:
            if glb_bin is None:
                raise MeshError("A buffer has no data.")
            out.append(glb_bin)
        elif uri.startswith("data:"):
            try:
                out.append(base64.b64decode(uri.split(",", 1)[1], validate=False))
            except (ValueError, IndexError):
                raise MeshError("A buffer data URI is malformed.")
        else:
            if base_dir is None or "/" in uri.replace("\\", "/") or uri.startswith(".") or os.path.isabs(uri):
                raise MeshError("A buffer file must sit in the same folder as the glTF file; \"%s\" is refused." % uri)
            full = os.path.join(base_dir, uri)
            if not os.path.isfile(full) or os.path.getsize(full) > MAX_BUFFER:
                raise MeshError("The buffer file \"%s\" is missing or too large." % uri)
            with open(full, "rb") as fh:
                out.append(fh.read())
        if len(out[-1]) > MAX_BUFFER:
            raise MeshError("A buffer is larger than the 512 MB limit.")
    return out


def accessor_array(doc, buffers, index):
    acc = doc["accessors"][index]
    if "sparse" in acc:
        raise MeshError("A sparse accessor is not supported.")
    dt = COMPONENT.get(acc.get("componentType"))
    width = WIDTH.get(acc.get("type"))
    if dt is None or width is None:
        raise MeshError("An accessor has an unknown type.")
    count = int(acc.get("count", 0))
    if "bufferView" not in acc:
        return np.zeros((count, width), dtype=dt)
    view = doc["bufferViews"][acc["bufferView"]]
    buf = buffers[view["buffer"]]
    start = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
    item = np.dtype(dt).itemsize * width
    stride = int(view.get("byteStride", 0)) or item
    need = start + stride * (count - 1) + item if count else start
    if need > len(buf):
        raise MeshError("An accessor reads past the end of its buffer.")
    if stride == item:
        arr = np.frombuffer(buf, dtype="<" + dt, count=count * width, offset=start).reshape(count, width)
    else:
        raw = np.frombuffer(buf, dtype=np.uint8, count=stride * (count - 1) + item, offset=start)
        rows = np.lib.stride_tricks.as_strided(raw, shape=(count, item), strides=(stride, 1))
        arr = np.frombuffer(np.ascontiguousarray(rows).tobytes(), dtype="<" + dt).reshape(count, width)
    return arr


def node_matrix(node):
    if "matrix" in node:
        m = np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
        return m
    t = node.get("translation", [0, 0, 0])
    q = node.get("rotation", [0, 0, 0, 1])
    s = node.get("scale", [1, 1, 1])
    x, y, z, w = [float(c) for c in q]
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    m = np.eye(4)
    m[:3, :3] = r * np.array(s, dtype=np.float64)
    m[:3, 3] = t
    return m


def read_gltf(data: bytes, base_dir=None) -> tuple:
    if len(data) > MAX_BUFFER:
        raise MeshError("The file is larger than the 512 MB limit.")
    binary = data[:4] == b"glTF"
    try:
        if binary:
            doc, glb_bin = split_glb(data)
        else:
            if len(data) > MAX_JSON:
                raise MeshError("The glTF JSON is larger than the 64 MB limit.")
            doc, glb_bin = json.loads(data.decode("utf-8")), None
    except (ValueError, UnicodeDecodeError) as err:
        raise MeshError("The glTF JSON cannot be read (%s)." % err)
    if not isinstance(doc, dict) or str((doc.get("asset") or {}).get("version", "")) != "2.0":
        raise MeshError("The file is not glTF 2.0.")
    if any(e in doc.get("extensionsRequired", []) for e in ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization")):
        raise MeshError("The file needs a compression extension (Draco, meshopt or quantization) that this reader does not implement.")
    buffers = load_buffers(doc, glb_bin, base_dir)
    nodes = doc.get("nodes", [])
    if len(nodes) > MAX_NODES:
        raise MeshError("The glTF file holds more than %d nodes." % MAX_NODES)
    scenes = doc.get("scenes", [])
    roots = scenes[doc.get("scene", 0)].get("nodes", []) if scenes else list(range(len(nodes)))
    mats = doc.get("materials", [])
    notes, warns = [], []
    parts = []
    total = [0]
    yup = np.array([[1.0, 0, 0, 0], [0, 0, -1.0, 0], [0, 1.0, 0, 0], [0, 0, 0, 1.0]])

    def visit(index, parent, depth):
        if depth > MAX_DEPTH:
            raise MeshError("The glTF nodes nest too deeply.")
        node = nodes[index]
        mat = parent @ node_matrix(node)
        if "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            for prim in mesh.get("primitives", []):
                mode = prim.get("mode", 4)
                if mode not in (4, 5, 6):
                    warns.append("A primitive of mode %s (points or lines) is skipped." % mode)
                    continue
                pos = accessor_array(doc, buffers, prim["attributes"]["POSITION"]).astype(np.float64)
                if "indices" in prim:
                    idx = accessor_array(doc, buffers, prim["indices"]).reshape(-1).astype(np.int64)
                else:
                    idx = np.arange(len(pos), dtype=np.int64)
                if mode == 4:
                    idx = idx[: len(idx) // 3 * 3].reshape(-1, 3)
                elif mode == 5:
                    idx = np.array([(idx[i] if i % 2 == 0 else idx[i + 1], idx[i + 1] if i % 2 == 0 else idx[i], idx[i + 2]) for i in range(len(idx) - 2)], dtype=np.int64).reshape(-1, 3)
                else:
                    idx = np.array([(idx[0], idx[i], idx[i + 1]) for i in range(1, len(idx) - 1)], dtype=np.int64).reshape(-1, 3)
                total[0] += len(idx)
                if total[0] > MAX_TRIANGLES:
                    raise MeshError("The glTF file holds more than %d triangles." % MAX_TRIANGLES)
                if len(idx) and (idx.min() < 0 or idx.max() >= len(pos)):
                    raise MeshError("A glTF index refers to a vertex that does not exist.")
                world = (np.c_[pos, np.ones(len(pos))] @ mat.T)[:, :3]
                z_up = (np.c_[world, np.ones(len(world))] @ yup.T)[:, :3] * 1000.0
                rgb = None
                if "material" in prim and prim["material"] < len(mats):
                    f = (mats[prim["material"]].get("pbrMetallicRoughness") or {}).get("baseColorFactor")
                    if f:
                        rgb = [round(linear_to_srgb(c), 4) for c in f[:3]]
                parts.append({"name": node.get("name") or mesh.get("name") or "Body", "mesh": Mesh(z_up, idx), "rgb": rgb})
        for child in node.get("children", []):
            visit(child, mat, depth + 1)

    for r in roots:
        visit(r, np.eye(4), 0)
    if not parts:
        raise MeshError("The glTF file holds no triangle meshes.")
    notes.append("glTF is metres and Y up; the geometry was scaled by 1000 and turned to Z up.")
    return parts, {"unit": "m", "unit_mm": 1000.0, "notes": notes, "warnings": warns, "form": "glb" if binary else "gltf"}
