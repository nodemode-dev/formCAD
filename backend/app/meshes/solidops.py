import numpy as np

from app.meshes import core
from app.meshes.core import Mesh, MeshError
from app.meshes.jobs import QUIET

OPS = ("union", "difference", "intersection")


def to_manifold(m: Mesh, label: str):
    import manifold3d as mf

    if not len(m.t):
        raise MeshError("%s has no triangles." % label)
    solid = mf.Manifold(mf.Mesh64(np.array(m.v, dtype=np.float64), np.array(m.t, dtype=np.uint64)))
    status = solid.status()
    if status != mf.Error.NoError:
        r = core.report(m)
        why = []
        if r["naked_edges"]:
            why.append("%d naked edges" % r["naked_edges"])
        if r["nonmanifold_edges"]:
            why.append("%d non-manifold edges" % r["nonmanifold_edges"])
        if r["inconsistent_edges"]:
            why.append("%d edges with mismatched direction" % r["inconsistent_edges"])
        raise MeshError("%s is not a closed manifold mesh (%s%s). Repair it first." % (label, ", ".join(why) or str(status.name), ""))
    if solid.volume() < 0:
        raise MeshError("%s has its normals pointing inwards; unify its normals first." % label)
    return solid


def from_manifold(solid) -> Mesh:
    raw = solid.to_mesh64()
    verts = np.asarray(raw.vert_properties)[:, :3]
    tris = np.asarray(raw.tri_verts).astype(np.int64)
    return core.compact(Mesh(verts, tris))


def combine(base: Mesh, tools: list, op: str, names=None, act=QUIET) -> tuple:
    import manifold3d as mf

    if op not in OPS:
        raise MeshError("The operation is union, difference or intersection.")
    if not tools:
        raise MeshError("Give at least one tool mesh.")
    names = names or ["the base mesh"] + ["tool %d" % (i + 1) for i in range(len(tools))]
    act.step("Checking the meshes", 0.1)
    solids = [to_manifold(base, names[0])]
    for i, t in enumerate(tools):
        solids.append(to_manifold(t, names[i + 1]))
    act.step("Combining the meshes", 0.4)
    first = solids[0]
    rest = solids[1:]
    if op == "union":
        res = mf.Manifold.batch_boolean(solids, mf.OpType.Add)
    elif op == "intersection":
        res = mf.Manifold.batch_boolean(solids, mf.OpType.Intersect)
    else:
        res = first
        for s in rest:
            res = res - s
    if res.status() != mf.Error.NoError:
        raise MeshError("The boolean failed (%s)." % res.status().name)
    if res.is_empty():
        raise MeshError("The result is empty: the meshes do not overlap in the way this operation needs.")
    act.step("Collecting the result", 0.9)
    out = from_manifold(res)
    info = {"op": op, "triangles": int(len(out.t)), "volume": float(res.volume()), "genus": int(res.genus()), "inputs": [float(s.volume()) for s in solids]}
    return out, info
