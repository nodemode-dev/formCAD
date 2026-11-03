import math

import numpy as np

from app.subd.cc import INF, SubdError

MAX_FACES = 20000
MAX_VERTICES = 60000
MAX_FACES_AGENT = 5000
MAX_VERTICES_AGENT = 15000
MAX_FACE_SIZE = 64


def check_caps(nv: int, nf: int, agent: bool = False) -> None:
    fmax = MAX_FACES_AGENT if agent else MAX_FACES
    vmax = MAX_VERTICES_AGENT if agent else MAX_VERTICES
    if nf > fmax:
        raise SubdError("The cage would have %d faces; the limit is %d%s." % (nf, fmax, " for macros and agents" if agent else ""))
    if nv > vmax:
        raise SubdError("The cage would have %d vertices; the limit is %d%s." % (nv, vmax, " for macros and agents" if agent else ""))


class Cage:
    def __init__(self, v, f, crease=None):
        self.v = np.asarray(v, dtype=np.float64).reshape(-1, 3).copy()
        self.f = [list(map(int, face)) for face in f]
        self.crease = {}
        for k, w in (crease or {}).items():
            a, b = int(k[0]), int(k[1])
            if a != b and w > 0:
                self.crease[(min(a, b), max(a, b))] = min(float(w), INF)

    @classmethod
    def from_entity(cls, ent):
        c = cls(ent.v, ent.f)
        for a, b, w in ent.crease:
            a, b = int(a), int(b)
            if w > 0:
                c.crease[(min(a, b), max(a, b))] = min(float(w), INF)
        return c

    def to_fields(self) -> dict:
        return {
            "v": [[float(x) for x in p] for p in self.v.tolist()],
            "f": [list(map(int, face)) for face in self.f],
            "crease": [[a, b, round(w, 9)] for (a, b), w in sorted(self.crease.items())],
        }

    def copy(self):
        return Cage(self.v, self.f, self.crease)

    def validate(self, agent: bool = False) -> None:
        check_caps(len(self.v), len(self.f), agent)
        if not np.all(np.isfinite(self.v)):
            raise SubdError("A vertex position is not a finite number.")
        nv = len(self.v)
        for face in self.f:
            if len(face) < 3 or len(face) > MAX_FACE_SIZE:
                raise SubdError("A face has %d vertices; it needs 3 to %d." % (len(face), MAX_FACE_SIZE))
            if len(set(face)) != len(face):
                raise SubdError("A face repeats a vertex.")
            if min(face) < 0 or max(face) >= nv:
                raise SubdError("A face uses a vertex that does not exist.")

    def edge_list(self):
        seen = set()
        for face in self.f:
            n = len(face)
            for i in range(n):
                a, b = face[i], face[(i + 1) % n]
                seen.add((min(a, b), max(a, b)))
        return sorted(seen)

    def edge_faces(self):
        edges = self.edge_list()
        index = {e: i for i, e in enumerate(edges)}
        owners = [[] for _ in edges]
        for fi, face in enumerate(self.f):
            n = len(face)
            for i in range(n):
                a, b = face[i], face[(i + 1) % n]
                owners[index[(min(a, b), max(a, b))]].append(fi)
        return edges, owners

    def directed(self):
        d = {}
        for fi, face in enumerate(self.f):
            n = len(face)
            for i in range(n):
                d.setdefault((face[i], face[(i + 1) % n]), []).append(fi)
        return d

    def valence(self):
        val = np.zeros(len(self.v), dtype=np.int64)
        for a, b in self.edge_list():
            val[a] += 1
            val[b] += 1
        return val

    def analysis(self) -> dict:
        edges, owners = self.edge_faces()
        d = self.directed()
        nonman = sum(1 for o in owners if len(o) > 2)
        boundary = sum(1 for o in owners if len(o) == 1)
        inconsistent = sum(1 for k, fs in d.items() if len(fs) > 1)
        manifold = nonman == 0 and inconsistent == 0
        closed = manifold and boundary == 0 and len(self.f) > 0
        used = set(i for face in self.f for i in face)
        isolated = len(self.v) - len(used)
        val = self.valence()
        used_list = sorted(used)
        ex = {}
        for v in used_list:
            if val[v] != 4:
                ex[int(val[v])] = ex.get(int(val[v]), 0) + 1
        lens = [float(np.linalg.norm(self.v[a] - self.v[b])) for a, b in edges] or [0.0]
        euler = len(used) - len(edges) + len(self.f)
        vol = None
        if closed:
            vol = self.signed_volume()
        return {
            "vertices": len(self.v), "faces": len(self.f), "edges": len(edges), "closed": bool(closed), "manifold": bool(manifold),
            "nonmanifold_edges": nonman, "boundary_edges": boundary, "inconsistent_edges": inconsistent, "isolated_vertices": isolated,
            "euler": euler, "genus": (2 - euler) // 2 if closed else None, "extraordinary": {str(k): c for k, c in sorted(ex.items())},
            "extraordinary_count": sum(ex.values()), "creases": len(self.crease), "min_edge": min(lens), "max_edge": max(lens),
            "volume_estimate": vol,
            "triangles": sum(1 for face in self.f if len(face) == 3), "quads": sum(1 for face in self.f if len(face) == 4), "ngons": sum(1 for face in self.f if len(face) > 4),
        }

    def signed_volume(self) -> float:
        total = 0.0
        for face in self.f:
            p0 = self.v[face[0]]
            for i in range(1, len(face) - 1):
                total += float(np.dot(p0, np.cross(self.v[face[i]], self.v[face[i + 1]]))) / 6.0
        return total

    def bbox(self):
        if not len(self.v):
            return [0.0] * 6
        return [float(x) for x in (*self.v.min(axis=0), *self.v.max(axis=0))]

    def compact(self):
        used = sorted(set(i for face in self.f for i in face))
        remap = {old: new for new, old in enumerate(used)}
        self.v = self.v[used] if used else np.zeros((0, 3))
        self.f = [[remap[i] for i in face] for face in self.f]
        self.crease = {(min(remap[a], remap[b]), max(remap[a], remap[b])): w for (a, b), w in self.crease.items() if a in remap and b in remap}
        return remap

    def drop_orphan_creases(self):
        edges = set(self.edge_list())
        self.crease = {k: w for k, w in self.crease.items() if k in edges}


def edge_key(a, b):
    return (min(int(a), int(b)), max(int(a), int(b)))


def rotate(v, axis, angle, pivot):
    axis = np.asarray(axis, dtype=np.float64)
    n = np.linalg.norm(axis)
    if n < 1e-12:
        raise SubdError("The rotation axis has zero length.")
    k = axis / n
    c, s = math.cos(angle), math.sin(angle)
    p = np.asarray(v, dtype=np.float64) - pivot
    return pivot + p * c + np.cross(k, p) * s + np.outer(p @ k, k) * (1.0 - c)
