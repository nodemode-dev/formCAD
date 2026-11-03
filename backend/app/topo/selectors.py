import numpy as np

from app.topo.grid import Grid, TopoError

MAX_SAMPLES = 3_000_000


class FaceSet:
    def __init__(self, pos: np.ndarray, idx: np.ndarray, tri_face: np.ndarray):
        self.pos = pos.astype(np.float64)
        self.tri = idx.reshape(-1, 3).astype(np.int64)
        self.face_of = tri_face.astype(np.int64)
        self.ids = np.unique(self.face_of)
        a, b, c = (self.pos[self.tri[:, k]] for k in range(3))
        cr = np.cross(b - a, c - a)
        self.area_vec = 0.5 * cr
        self.area = 0.5 * np.linalg.norm(cr, axis=1)
        self.bbox = {}
        self.centre = {}
        for f in self.ids:
            sel = self.face_of == f
            pts = self.pos[self.tri[sel]].reshape(-1, 3)
            self.bbox[int(f)] = (pts.min(axis=0), pts.max(axis=0))
            w = self.area[sel]
            cen = (self.pos[self.tri[sel]].mean(axis=1) * w[:, None]).sum(axis=0) / max(w.sum(), 1e-300)
            self.centre[int(f)] = cen
        lo = self.pos.min(axis=0)
        hi = self.pos.max(axis=0)
        self.lo, self.hi = lo, hi
        self.diag = float(np.linalg.norm(hi - lo))


def faces_for(sel: dict, fs: FaceSet) -> list:
    tol = float(sel.get("tol", 1e-4 * max(fs.diag, 1.0)))
    if sel.get("all"):
        return [int(f) for f in fs.ids]
    out = set()
    if "faces" in sel:
        known = {int(f) for f in fs.ids}
        for f in sel["faces"]:
            if int(f) not in known:
                raise TopoError("The body has no face %d." % int(f))
            out.add(int(f))
    if "box" in sel:
        lo = np.minimum(sel["box"][0], sel["box"][1]) - tol
        hi = np.maximum(sel["box"][0], sel["box"][1]) + tol
        for f, (a, b) in fs.bbox.items():
            if np.all(a >= lo) and np.all(b <= hi):
                out.add(f)
    if "plane" in sel:
        p = sel["plane"]
        ax = "xyz".index(str(p["axis"]).lower())
        t = float(p.get("tol", tol))
        for f, (a, b) in fs.bbox.items():
            if abs(a[ax] - float(p["value"])) <= t and abs(b[ax] - float(p["value"])) <= t:
                out.add(f)
    if "point" in sel:
        pt = np.array(sel["point"], dtype=float)
        best = min(fs.centre, key=lambda f: float(np.linalg.norm(fs.centre[f] - pt)))
        out.add(best)
    return sorted(out)


def sample_faces(fs: FaceSet, faces: list, step: float):
    keep = np.isin(fs.face_of, np.array(faces, dtype=np.int64))
    tri = fs.pos[fs.tri[keep]]
    ref_area = fs.area[keep]
    nrm = fs.area_vec[keep]
    if not len(tri):
        return np.zeros((0, 3)), np.zeros(0), np.zeros(3)
    total = float(ref_area.sum())
    step = max(step, (total / MAX_SAMPLES) ** 0.5 * 1.5)
    pts, wts = [], []
    cur = tri
    for _ in range(12):
        e = np.max(np.stack([np.linalg.norm(cur[:, 1] - cur[:, 0], axis=1), np.linalg.norm(cur[:, 2] - cur[:, 1], axis=1), np.linalg.norm(cur[:, 0] - cur[:, 2], axis=1)]), axis=0)
        small = e <= step
        if small.any():
            t = cur[small]
            pts.append(t.mean(axis=1))
            wts.append(0.5 * np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1))
        cur = cur[~small]
        if not len(cur):
            break
        a, b, c = cur[:, 0], cur[:, 1], cur[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        cur = np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1), np.stack([ab, bc, ca], 1)], axis=0)
    if len(cur):
        pts.append(cur.mean(axis=1))
        wts.append(0.5 * np.linalg.norm(np.cross(cur[:, 1] - cur[:, 0], cur[:, 2] - cur[:, 0]), axis=1))
    return np.concatenate(pts, axis=0), np.concatenate(wts), nrm.sum(axis=0)


def node_weights(grid: Grid, fs: FaceSet, faces: list, live_nodes: np.ndarray):
    pts, wts, nsum = sample_faces(fs, faces, 0.5 * grid.h)
    w = np.zeros(grid.nn)
    if not len(pts):
        return w, 0.0, nsum
    rel = (pts - grid.origin) / grid.h
    cell = np.floor(rel).astype(np.int64)
    cell[:, 0] = np.clip(cell[:, 0], 0, grid.nx - 1)
    cell[:, 1] = np.clip(cell[:, 1], 0, grid.ny - 1)
    cell[:, 2] = np.clip(cell[:, 2], 0, grid.nz - 1)
    sx, sy = grid.nx + 1, grid.ny + 1
    for c in range(2):
        for b in range(2):
            for a in range(2):
                node = (cell[:, 0] + a) + sx * ((cell[:, 1] + b) + sy * (cell[:, 2] + c))
                xyz = grid.origin + np.stack([cell[:, 0] + a, cell[:, 1] + b, cell[:, 2] + c], axis=1) * grid.h
                near = np.linalg.norm(xyz - pts, axis=1) <= 0.75 * grid.h
                ok = near & live_nodes[node]
                share = np.where(ok, 1.0, 0.0)
                if a == 0 and b == 0 and c == 0:
                    shares = [share]
                    nodes = [node]
                else:
                    shares.append(share)
                    nodes.append(node)
    total = np.sum(shares, axis=0)
    total[total == 0] = np.inf
    for share, node in zip(shares, nodes):
        np.add.at(w, node, wts * share / total)
    return w, float(wts.sum()), nsum
