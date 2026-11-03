import json

import numpy as np

MM = 1e-3
MAX_TETS = 400000


class MeshError(ValueError):
    pass


class Model:
    def __init__(self, mesh, nodes_mm, tets, tris, tri_face, groups, meta):
        self.mesh = mesh
        self.nodes_mm = nodes_mm
        self.tets = tets
        self.tris = tris
        self.tri_face = tri_face
        self.groups = groups
        self.meta = meta

    @property
    def curved(self) -> bool:
        return bool(self.meta.get("curved"))


def keys_of(tri: np.ndarray, n: int) -> np.ndarray:
    s = np.sort(tri.astype(np.int64), axis=0)
    return (s[0] * n + s[1]) * n + s[2]


def build(path: str, groups: dict | None = None) -> Model:
    from skfem import MeshTet, MeshTet2

    with np.load(path, allow_pickle=False) as z:
        nodes = z["nodes"]
        tets = z["tets"]
        tris = z["tris"]
        tri_face = z["tri_face"]
        pairs = z["edge_mid_pairs"]
        mids = z["edge_mid_xyz"]
        meta = json.loads(str(z["meta"]))
    if len(tets) > MAX_TETS:
        raise MeshError("The mesh holds %d elements, over the limit of %d." % (len(tets), MAX_TETS))
    n = len(nodes)
    m = MeshTet(np.ascontiguousarray((nodes * MM).T), np.ascontiguousarray(tets.T.astype(np.int64)))
    fkeys = keys_of(m.facets, n)
    order = np.argsort(fkeys)
    sorted_keys = fkeys[order]
    tkeys = keys_of(tris.T, n)
    pos = np.searchsorted(sorted_keys, tkeys)
    pos = np.minimum(pos, len(sorted_keys) - 1)
    hit = sorted_keys[pos] == tkeys
    if not hit.all():
        raise MeshError("A boundary triangle of the mesh does not match a facet of the volume mesh.")
    facet_of_tri = order[pos]
    boundaries = {}
    for name, faces in (groups or meta.get("groups") or {}).items():
        sel = np.isin(tri_face, np.array(faces, dtype=np.int32))
        boundaries[name] = np.unique(facet_of_tri[sel]).astype(np.int64)
    boundaries["_all"] = np.unique(facet_of_tri)
    if len(pairs):
        m = MeshTet2.from_mesh(m)
        ek = (np.minimum(pairs[:, 0], pairs[:, 1]).astype(np.int64) * n + np.maximum(pairs[:, 0], pairs[:, 1]))
        ord2 = np.argsort(ek)
        sk = ek[ord2]
        edges = np.sort(m.edges.astype(np.int64), axis=0)
        mk = edges[0] * n + edges[1]
        p = np.minimum(np.searchsorted(sk, mk), len(sk) - 1)
        if not (sk[p] == mk).all():
            raise MeshError("The curved midside nodes do not match the mesh edges.")
        m.doflocs[:, m.dofs.edge_dofs[0]] = (mids[ord2[p]] * MM).T
    else:
        m = MeshTet2.from_mesh(m)
    m = m.with_boundaries(boundaries)
    return Model(m, nodes, tets, tris, tri_face, {k: v for k, v in boundaries.items() if k != "_all"}, meta)
