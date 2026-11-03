import re
import struct

import numpy as np

from app.meshes.core import Mesh, MeshError, compact

MAX_FILE = 512 * 1024 * 1024
MAX_VERTICES = 20_000_000
MAX_FACES = 20_000_000
MAX_HEADER = 64 * 1024
SCALARS = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1", "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4", "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}
PLY_UNITS = re.compile(r"units?\s*[:=]\s*([A-Za-z]+)", re.IGNORECASE)


def parse_header(data: bytes):
    end = data.find(b"end_header", 0, MAX_HEADER)
    if not data.startswith(b"ply") or end < 0:
        raise MeshError("The file is not a PLY file: it has no ply header.")
    nl = data.find(b"\n", end)
    if nl < 0:
        raise MeshError("The PLY header is cut off.")
    lines = data[:nl].decode("ascii", errors="replace").replace("\r", "").split("\n")
    fmt = None
    elements = []
    comments = []
    for line in lines[1:]:
        parts = line.split()
        if not parts:
            continue
        key = parts[0]
        if key == "format":
            fmt = parts[1] if len(parts) > 1 else None
        elif key == "comment":
            comments.append(" ".join(parts[1:]))
        elif key == "element":
            if len(parts) != 3:
                raise MeshError("A PLY element line is malformed.")
            elements.append({"name": parts[1], "count": int(parts[2]), "props": []})
        elif key == "property":
            if not elements:
                raise MeshError("A PLY property comes before any element.")
            if parts[1] == "list":
                if len(parts) != 5 or parts[2] not in SCALARS or parts[3] not in SCALARS:
                    raise MeshError("A PLY list property is malformed.")
                elements[-1]["props"].append({"name": parts[4], "list": True, "count_type": SCALARS[parts[2]], "type": SCALARS[parts[3]]})
            else:
                if len(parts) != 3 or parts[1] not in SCALARS:
                    raise MeshError("A PLY property uses a type this reader does not know.")
                elements[-1]["props"].append({"name": parts[2], "list": False, "type": SCALARS[parts[1]]})
        elif key == "end_header":
            break
    if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise MeshError("The PLY format line is missing or unknown.")
    return fmt, elements, comments, nl + 1


def file_unit(comments):
    for c in comments:
        m = PLY_UNITS.search(c)
        if m:
            return m.group(1).lower()
    return ""


def read_ply(data: bytes) -> tuple:
    if len(data) > MAX_FILE:
        raise MeshError("The file is larger than the 512 MB limit.")
    fmt, elements, comments, start = parse_header(data)
    names = {e["name"]: e for e in elements}
    vert = names.get("vertex")
    if vert is None or vert["count"] <= 0:
        raise MeshError("The PLY file holds no vertices.")
    if vert["count"] > MAX_VERTICES:
        raise MeshError("The PLY file holds more than %d vertices." % MAX_VERTICES)
    face = names.get("face")
    if face is not None and face["count"] > MAX_FACES:
        raise MeshError("The PLY file holds more than %d faces." % MAX_FACES)
    pnames = [p["name"] for p in vert["props"]]
    if not all(k in pnames for k in ("x", "y", "z")):
        raise MeshError("The PLY vertices lack x, y and z.")
    if any(p["list"] for p in vert["props"]):
        raise MeshError("A PLY vertex with a list property is not supported.")
    colour_names = None
    for trio in (("red", "green", "blue"), ("r", "g", "b")):
        if all(k in pnames for k in trio):
            colour_names = trio
            break
    if fmt == "ascii":
        verts, tris, colours = read_ascii(data[start:], elements, pnames, colour_names)
    else:
        verts, tris, colours = read_binary(data[start:], elements, "<" if fmt == "binary_little_endian" else ">", pnames, colour_names)
    if not len(tris):
        raise MeshError("The PLY file holds no faces; point clouds are not read here.")
    m = Mesh(verts, tris)
    uniq = None
    rgb = None
    if colours is not None and len(colours):
        used = np.unique(m.t)
        c = colours[used]
        uniq = np.unique(c, axis=0)
        rgb = [round(float(x) / 255.0, 4) for x in (uniq[0] if len(uniq) == 1 else c.mean(axis=0))]
    notes = []
    if rgb is not None and uniq is not None and len(uniq) > 1:
        notes.append("The vertex colours differ; the mean colour is used for the whole body.")
    return compact(m), {"form": fmt, "unit": file_unit(comments), "rgb": rgb, "notes": notes, "triangles": int(len(tris)), "comments": comments}


def triangulate(counts, flat):
    tris = []
    pos = 0
    for n in counts:
        n = int(n)
        if n >= 3:
            base = flat[pos]
            for k in range(1, n - 1):
                tris.append((base, flat[pos + k], flat[pos + k + 1]))
        pos += n
    return np.array(tris, dtype=np.int64).reshape(-1, 3)


def vertex_arrays(table, pnames, colour_names):
    verts = np.stack([table[k].astype(np.float64) for k in ("x", "y", "z")], axis=1)
    colours = None
    if colour_names:
        cols = [table[k].astype(np.float64) for k in colour_names]
        scale = 255.0 if table[colour_names[0]].dtype.kind == "f" and max(c.max() for c in cols) <= 1.0 else 1.0
        colours = np.clip(np.stack(cols, axis=1) * scale, 0, 255)
    return verts, colours


def read_ascii(body: bytes, elements, pnames, colour_names):
    lines = body.decode("ascii", errors="replace").splitlines()
    row = 0
    verts = tris = colours = None
    for el in elements:
        chunk = lines[row:row + el["count"]]
        if len(chunk) < el["count"]:
            raise MeshError("The PLY file ends before its %s data does." % el["name"])
        row += el["count"]
        if el["name"] == "vertex":
            cols = len(el["props"])
            try:
                arr = np.array([r.split()[:cols] for r in chunk], dtype=np.float64).reshape(-1, cols)
            except ValueError:
                raise MeshError("A PLY vertex holds a value that is not a number.")
            table = {p["name"]: arr[:, i] for i, p in enumerate(el["props"])}
            verts, colours = vertex_arrays(table, pnames, colour_names)
        elif el["name"] == "face":
            index_prop = next((i for i, p in enumerate(el["props"]) if p["list"] and p["name"] in ("vertex_indices", "vertex_index")), None)
            if index_prop is None:
                raise MeshError("The PLY faces have no vertex_indices list.")
            counts, flat = [], []
            for r in chunk:
                tok = r.split()
                at = 0
                for i, p in enumerate(el["props"]):
                    if p["list"]:
                        n = int(float(tok[at]))
                        if i == index_prop:
                            counts.append(n)
                            flat.extend(int(float(x)) for x in tok[at + 1:at + 1 + n])
                        at += 1 + n
                    else:
                        at += 1
            tris = triangulate(counts, flat)
    if verts is None:
        raise MeshError("The PLY file holds no vertices.")
    if tris is None:
        tris = np.zeros((0, 3), dtype=np.int64)
    return verts, tris, colours


def read_binary(body: bytes, elements, endian, pnames, colour_names):
    pos = 0
    verts = tris = colours = None
    for el in elements:
        n = el["count"]
        if not any(p["list"] for p in el["props"]):
            dt = np.dtype([(p["name"], endian + p["type"]) for p in el["props"]])
            need = dt.itemsize * n
            if pos + need > len(body):
                raise MeshError("The PLY file ends before its %s data does." % el["name"])
            table = np.frombuffer(body, dtype=dt, count=n, offset=pos)
            pos += need
            if el["name"] == "vertex":
                verts, colours = vertex_arrays(table, pnames, colour_names)
            continue
        simple = [p for p in el["props"] if not p["list"]]
        lists = [p for p in el["props"] if p["list"]]
        if el["name"] == "face" and len(el["props"]) == 1 and len(lists) == 1:
            p = lists[0]
            ct, vt = np.dtype(endian + p["count_type"]), np.dtype(endian + p["type"])
            first = np.frombuffer(body, dtype=ct, count=1, offset=pos) if n and pos + ct.itemsize <= len(body) else None
            if first is not None:
                k = int(first[0])
                stride = ct.itemsize + k * vt.itemsize
                end = pos + stride * n
                if end <= len(body):
                    rec = np.dtype([("n", ct), ("v", vt, (k,))]) if k else None
                    if rec is not None:
                        arr = np.frombuffer(body, dtype=rec, count=n, offset=pos)
                        if (arr["n"] == k).all():
                            pos = end
                            if el["name"] == "face":
                                counts = np.full(n, k)
                                tris = triangulate(counts, arr["v"].reshape(-1).astype(np.int64)) if k != 3 else arr["v"].reshape(-1, 3).astype(np.int64)
                            continue
        counts_out, flat_out = [], []
        for _i in range(n):
            for p in el["props"]:
                if p["list"]:
                    ct, vt = np.dtype(endian + p["count_type"]), np.dtype(endian + p["type"])
                    if pos + ct.itemsize > len(body):
                        raise MeshError("The PLY file ends before its %s data does." % el["name"])
                    k = int(np.frombuffer(body, dtype=ct, count=1, offset=pos)[0])
                    pos += ct.itemsize
                    if k < 0 or pos + k * vt.itemsize > len(body):
                        raise MeshError("A PLY list is cut off.")
                    items = np.frombuffer(body, dtype=vt, count=k, offset=pos)
                    pos += k * vt.itemsize
                    if el["name"] == "face" and p["name"] in ("vertex_indices", "vertex_index"):
                        counts_out.append(k)
                        flat_out.extend(int(x) for x in items)
                else:
                    pos += np.dtype(p["type"]).itemsize
        if el["name"] == "face":
            tris = triangulate(counts_out, flat_out)
    if verts is None:
        raise MeshError("The PLY file holds no vertices.")
    if tris is None:
        tris = np.zeros((0, 3), dtype=np.int64)
    return verts, tris, colours


def write_ply(meshes: list, binary: bool = True, unit: str = "mm") -> bytes:
    vs, ts, cs, base = [], [], [], 0
    any_colour = any(rgb for _m, rgb in meshes)
    for m, rgb in meshes:
        vs.append(m.v)
        ts.append(m.t.astype(np.int64) + base)
        base += len(m.v)
        if any_colour:
            c = np.tile(np.array([round(float(x) * 255.0) for x in rgb] if rgb else [200, 200, 200], dtype=np.uint8), (len(m.v), 1))
            cs.append(c)
    v = np.vstack(vs)
    t = np.vstack(ts)
    if not len(t):
        raise MeshError("The mesh has no triangles to write.")
    head = ["ply", "format %s 1.0" % ("binary_little_endian" if binary else "ascii"), "comment FormCAD", "comment units: %s" % unit, "element vertex %d" % len(v), "property float x", "property float y", "property float z"]
    if any_colour:
        head += ["property uchar red", "property uchar green", "property uchar blue"]
    head += ["element face %d" % len(t), "property list uchar int vertex_indices", "end_header"]
    header = ("\n".join(head) + "\n").encode("ascii")
    if binary:
        vdt = np.dtype([("p", "<f4", 3)] + ([("c", "u1", 3)] if any_colour else []))
        vr = np.zeros(len(v), dtype=vdt)
        vr["p"] = v.astype(np.float32)
        if any_colour:
            vr["c"] = np.vstack(cs)
        fr = np.zeros(len(t), dtype=np.dtype([("n", "u1"), ("v", "<i4", 3)]))
        fr["n"] = 3
        fr["v"] = t.astype(np.int32)
        return header + vr.tobytes() + fr.tobytes()
    rows = []
    cc = np.vstack(cs) if any_colour else None
    for i, q in enumerate(v):
        rows.append("%.9g %.9g %.9g" % tuple(q) + (" %d %d %d" % tuple(cc[i]) if any_colour else ""))
    for a, b, c in t:
        rows.append("3 %d %d %d" % (a, b, c))
    return header + ("\n".join(rows) + "\n").encode("ascii")
