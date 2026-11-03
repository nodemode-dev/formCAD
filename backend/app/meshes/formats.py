import re

import numpy as np

from app.meshes.core import Mesh, MeshError, compact

MAX_FILE = 512 * 1024 * 1024
MAX_TRIANGLES = 20_000_000
MAX_FACE_VERTS = 1000
HEADER_TEXT = b"FormCAD binary STL"
BINARY = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
VERTEX = re.compile(rb"vertex\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)", re.IGNORECASE)


def indexed(points) -> Mesh:
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    if not len(pts):
        raise MeshError("The file holds no triangles.")
    uniq, inverse = np.unique(pts, axis=0, return_inverse=True)
    return Mesh(uniq, inverse.reshape(-1, 3))


def read_stl(data: bytes) -> tuple:
    if len(data) > MAX_FILE:
        raise MeshError("The file is larger than the 512 MB limit.")
    note = []
    if len(data) >= 84:
        count = int.from_bytes(data[80:84], "little")
        if len(data) == 84 + 50 * count:
            if count > MAX_TRIANGLES:
                raise MeshError("The file holds more than %d triangles." % MAX_TRIANGLES)
            if count == 0:
                raise MeshError("The file holds no triangles.")
            rec = np.frombuffer(data, dtype=BINARY, count=count, offset=84)
            pts = rec["v"].astype(np.float64).reshape(-1, 3)
            if not np.isfinite(pts).all():
                raise MeshError("The file holds coordinates that are not finite.")
            return indexed(pts), {"form": "binary", "solids": 1, "triangles": int(count)}
    head = data[:5].lstrip().lower()
    if not data.lstrip()[:5].lower() == b"solid":
        raise MeshError("The file is not a readable STL: it is neither a binary file of the stated size nor text starting with solid.")
    found = VERTEX.findall(data)
    if not found or len(found) % 3:
        raise MeshError("The text STL holds no complete triangles.")
    try:
        pts = np.array([[float(x) for x in row] for row in found], dtype=np.float64)
    except ValueError:
        raise MeshError("The text STL holds a number that cannot be read.")
    if not np.isfinite(pts).all():
        raise MeshError("The file holds coordinates that are not finite.")
    solids = len(re.findall(rb"^\s*solid\b", data, re.IGNORECASE | re.MULTILINE))
    if solids > 1:
        note.append("The file holds %d solids; they are read as one mesh." % solids)
    return indexed(pts), {"form": "ascii", "solids": max(solids, 1), "triangles": len(found) // 3, "notes": note}


def facet_normals(m: Mesh):
    p = m.v[m.t]
    n = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    ln = np.linalg.norm(n, axis=1)
    ln[ln == 0] = 1.0
    return n / ln[:, None]


def write_stl(m: Mesh, binary: bool = True, name: str = "FormCAD") -> bytes:
    if not len(m.t):
        raise MeshError("The mesh has no triangles to write.")
    if len(m.t) > MAX_TRIANGLES:
        raise MeshError("The mesh has more than %d triangles." % MAX_TRIANGLES)
    nrm = facet_normals(m)
    if binary:
        rec = np.zeros(len(m.t), dtype=BINARY)
        rec["n"] = nrm
        rec["v"] = m.v[m.t]
        head = HEADER_TEXT.ljust(80, b" ")
        return head + len(m.t).to_bytes(4, "little") + rec.tobytes()
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name) or "FormCAD"
    lines = ["solid %s" % safe]
    p = m.v[m.t]
    for n, tri in zip(nrm, p):
        lines.append("facet normal %.9e %.9e %.9e" % tuple(n))
        lines.append("  outer loop")
        for q in tri:
            lines.append("    vertex %.9e %.9e %.9e" % tuple(q))
        lines.append("  endloop")
        lines.append("endfacet")
    lines.append("endsolid %s" % safe)
    return ("\n".join(lines) + "\n").encode("ascii")


def obj_index(token: str, count: int) -> int:
    first = token.split("/")[0]
    k = int(first)
    if k < 0:
        k = count + k
    else:
        k -= 1
    if not 0 <= k < count:
        raise MeshError("A face refers to a vertex that does not exist.")
    return k


def read_obj(data: bytes) -> tuple:
    if len(data) > MAX_FILE:
        raise MeshError("The file is larger than the 512 MB limit.")
    verts, tris = [], []
    skipped = 0
    objects = 0
    for raw in data.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line[0] == "#":
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            if len(parts) < 4:
                raise MeshError("A vertex line has fewer than three numbers.")
            v3 = (float(parts[1]), float(parts[2]), float(parts[3]))
            if not np.isfinite(v3).all():
                raise MeshError("A vertex holds a number that is not finite.")
            verts.append(v3)
        elif tag == "f":
            if len(parts) < 4:
                skipped += 1
                continue
            if len(parts) > MAX_FACE_VERTS + 1:
                raise MeshError("A face line holds more than %d vertices." % MAX_FACE_VERTS)
            idx = [obj_index(t, len(verts)) for t in parts[1:]]
            for k in range(1, len(idx) - 1):
                tris.append((idx[0], idx[k], idx[k + 1]))
        elif tag in ("o", "g"):
            objects += 1
        if len(tris) > MAX_TRIANGLES:
            raise MeshError("The file holds more than %d triangles." % MAX_TRIANGLES)
    if not verts or not tris:
        raise MeshError("The file holds no triangles.")
    m = compact(Mesh(np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int32)))
    notes = []
    if skipped:
        notes.append("%d face lines with fewer than three vertices were skipped." % skipped)
    return m, {"form": "obj", "objects": objects, "triangles": len(m.t), "notes": notes}


def write_obj(meshes: list) -> bytes:
    out = ["# FormCAD OBJ"]
    base = 0
    for name, m in meshes:
        safe = re.sub(r"\s+", "_", name or "mesh")
        out.append("o %s" % safe)
        for q in m.v:
            out.append("v %.10g %.10g %.10g" % tuple(q))
        for a, b, c in m.t + 1 + base:
            out.append("f %d %d %d" % (a, b, c))
        base += len(m.v)
    return ("\n".join(out) + "\n").encode("utf-8")


def merged(meshes: list) -> Mesh:
    vs, ts, base = [], [], 0
    for m in meshes:
        vs.append(m.v)
        ts.append(m.t + base)
        base += len(m.v)
    return Mesh(np.vstack(vs), np.vstack(ts))
