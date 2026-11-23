import re
import struct
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


class Mesh:
    def __init__(self, vertices, triangles, unit=None):
        self.vertices = [tuple(float(c) for c in v) for v in vertices]
        self.triangles = [tuple(int(i) for i in t) for t in triangles]
        self.unit = unit

    def welded(self, digits=6):
        index, verts, remap = {}, [], []
        for v in self.vertices:
            key = tuple(round(c, digits) + 0.0 for c in v)
            if key not in index:
                index[key] = len(verts)
                verts.append(v)
            remap.append(index[key])
        tris = [tuple(remap[i] for i in t) for t in self.triangles]
        return Mesh(verts, [t for t in tris if len(set(t)) == 3], self.unit)

    def closed(self):
        directed = Counter()
        for a, b, c in self.triangles:
            for e in ((a, b), (b, c), (c, a)):
                directed[e] += 1
        if any(n != 1 for n in directed.values()):
            return False
        return all((b, a) in directed for a, b in directed)

    def signed_volume(self):
        total = 0.0
        v = self.vertices
        for i, j, k in self.triangles:
            a, b, c = v[i], v[j], v[k]
            total += a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])
        return total / 6.0

    def bbox(self):
        xs, ys, zs = zip(*self.vertices)
        return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


def read_stl(path):
    data = Path(path).read_bytes()
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]
        if 84 + 50 * count == len(data):
            verts, tris = [], []
            for i in range(count):
                vals = struct.unpack_from("<12f", data, 84 + 50 * i)
                base = len(verts)
                verts += [vals[3:6], vals[6:9], vals[9:12]]
                tris.append((base, base + 1, base + 2))
            return Mesh(verts, tris), "binary"
    text = data.decode("ascii")
    assert text.lstrip().startswith("solid"), "an ASCII STL starts with solid"
    nums = re.findall(r"^\s*vertex\s+(\S+)\s+(\S+)\s+(\S+)", text, re.M)
    verts = [tuple(float(c) for c in n) for n in nums]
    assert len(verts) % 3 == 0 and text.count("endfacet") == len(verts) // 3
    return Mesh(verts, [(i, i + 1, i + 2) for i in range(0, len(verts), 3)]), "ascii"


def read_obj(path):
    verts, tris = [], []
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "v":
            verts.append(tuple(float(c) for c in parts[1:4]))
        elif parts[0] == "f":
            idx = []
            for p in parts[1:]:
                i = int(p.split("/")[0])
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                tris.append((idx[0], idx[k], idx[k + 1]))
    return Mesh(verts, tris)


PLY_TYPES = {"char": "b", "int8": "b", "uchar": "B", "uint8": "B", "short": "h", "int16": "h", "ushort": "H", "uint16": "H", "int": "i", "int32": "i", "uint": "I", "uint32": "I", "float": "f", "float32": "f", "double": "d", "float64": "d"}


def read_ply(path):
    data = Path(path).read_bytes()
    end = data.index(b"end_header") + len(b"end_header")
    end = data.index(b"\n", end) + 1
    header = data[:end].decode("ascii").splitlines()
    assert header[0].strip() == "ply"
    fmt = None
    unit = None
    elements = []
    for line in header[1:]:
        p = line.split()
        if not p:
            continue
        if p[0] == "format":
            fmt = p[1]
        elif p[0] == "comment" and len(p) >= 3 and p[1].lower() in ("unit", "units"):
            unit = p[2]
        elif p[0] == "element":
            elements.append([p[1], int(p[2]), []])
        elif p[0] == "property":
            elements[-1][2].append(p[1:])
    verts, tris = [], []
    body = data[end:]
    if fmt == "ascii":
        tokens = body.decode("ascii").split()
        pos = 0
        for name, count, props in elements:
            for _ in range(count):
                row = []
                for prop in props:
                    if prop[0] == "list":
                        n = int(tokens[pos])
                        pos += 1
                        row.append([float(t) for t in tokens[pos:pos + n]])
                        pos += n
                    else:
                        row.append(float(tokens[pos]))
                        pos += 1
                _keep(name, props, row, verts, tris)
    else:
        order = "<" if fmt == "binary_little_endian" else ">"
        pos = 0
        for name, count, props in elements:
            for _ in range(count):
                row = []
                for prop in props:
                    if prop[0] == "list":
                        ct, it = PLY_TYPES[prop[1]], PLY_TYPES[prop[2]]
                        n = struct.unpack_from(order + ct, body, pos)[0]
                        pos += struct.calcsize(ct)
                        row.append(list(struct.unpack_from(order + it * n, body, pos)))
                        pos += struct.calcsize(it) * n
                    else:
                        t = PLY_TYPES[prop[0]]
                        row.append(struct.unpack_from(order + t, body, pos)[0])
                        pos += struct.calcsize(t)
                _keep(name, props, row, verts, tris)
    return Mesh(verts, tris, unit), fmt


def _keep(name, props, row, verts, tris):
    names = [p[-1] for p in props]
    if name == "vertex":
        verts.append((row[names.index("x")], row[names.index("y")], row[names.index("z")]))
    elif name == "face":
        idx = [int(i) for i in row[0]]
        for k in range(1, len(idx) - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))


CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"


def read_3mf(path):
    with zipfile.ZipFile(path) as z:
        types = z.read("[Content_Types].xml")
        assert b"application/vnd.ms-package.3dmanufacturing-3dmodel+xml" in types
        rels = ET.fromstring(z.read("_rels/.rels"))
        target = [r.get("Target") for r in rels if r.get("Type", "").endswith("/3dmodel")][0].lstrip("/")
        root = ET.fromstring(z.read(target))
    unit = root.get("unit", "millimeter")
    objects = []
    for obj in root.iter(CORE + "object"):
        mesh = obj.find(CORE + "mesh")
        if mesh is None:
            continue
        verts = [(float(v.get("x")), float(v.get("y")), float(v.get("z"))) for v in mesh.find(CORE + "vertices")]
        tris = [(int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))) for t in mesh.find(CORE + "triangles")]
        objects.append((obj.get("name") or "", Mesh(verts, tris, unit)))
    return objects, unit


def read_any(path):
    ext = Path(path).suffix.lower()
    if ext == ".stl":
        return read_stl(path)[0]
    if ext == ".obj":
        return read_obj(path)
    if ext == ".ply":
        return read_ply(path)[0]
    if ext == ".3mf":
        objects, unit = read_3mf(path)
        verts, tris = [], []
        for _name, m in objects:
            base = len(verts)
            verts += m.vertices
            tris += [(a + base, b + base, c + base) for a, b, c in m.triangles]
        return Mesh(verts, tris, unit)
    raise ValueError(ext)
