import copy

import numpy as np

from app.additive.jobs import AdditiveError
from app.solid import scene as solid_scene
from app.solid import work
from app.solid.work import SolidError

KINDS = ("solidbody", "meshbody", "subdbody")


class Body:
    __slots__ = ("handle", "name", "version", "v", "t")

    def __init__(self, handle, name, version, v, t):
        self.handle, self.name, self.version, self.v, self.t = handle, name, version, v, t


def listing(doc) -> list:
    d = doc.drawing
    rows = []
    for e in d.ordered_entities():
        if e.kind in KINDS and d.visible(e):
            rows.append({"handle": e.handle, "name": e.name, "kind": e.kind, "version": int(e.version), "offset": list(e.offset or [0, 0, 0])})
    return rows


def triangle_count(doc, handles) -> int:
    d = doc.drawing
    total = 0
    for h in handles:
        e = d.get(int(h))
        if e is not None and e.kind in KINDS:
            total += int(e.summary.get("triangles", 0) or 0)
    return total


def fetch(doc, handles, limit_triangles: int) -> list:
    with doc.lock:
        d = doc.drawing
        ents = []
        for h in handles:
            e = d.get(int(h))
            if e is None or e.kind not in KINDS:
                raise AdditiveError("There is no solid or mesh body with the handle %s." % h)
            ents.append(copy.copy(e))
        scale = work.mm(d)
    out = []
    total = 0
    for e in ents:
        try:
            if e.kind == "meshbody":
                from app.meshes import store as mesh_store

                if e.points_only:
                    raise AdditiveError("%s is a point cloud; it has no surface to print." % (e.name or "A mesh"))
                m = mesh_store.load(d, e)
                v, t = np.array(m.v, dtype=np.float64), np.array(m.t, dtype=np.int64)
            else:
                raw = work.mesh_for(d, e, 1.0) if e.kind == "solidbody" else _subd_raw(d, e)
                parsed = solid_scene.parse(raw)
                v = np.array(parsed["pos"], dtype=np.float64)
                t = np.array(parsed["idx"], dtype=np.int64).reshape(-1, 3)
        except SolidError as err:
            raise AdditiveError(str(err))
        total += len(t)
        if total > limit_triangles:
            raise AdditiveError("The bodies hold %d triangles; the limit here is %d. Reduce the mesh first." % (total, limit_triangles))
        off = np.asarray(e.offset if e.offset else [0.0, 0.0, 0.0], dtype=np.float64) * scale
        out.append(Body(e.handle, e.name or "Body", int(e.version), v + off, t))
    return out


def _subd_raw(d, e):
    from app.subd import store as subd_store

    return subd_store.scene_bytes(d, e)
