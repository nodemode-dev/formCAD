import numpy as np
import scipy.sparse as sp
from scipy.spatial import cKDTree

from app.simnl.elements import EDGES


class ContactError(ValueError):
    pass


def surface_nodes(conn, tri):
    conn = np.asarray(conn)
    tri = np.asarray(tri)
    if conn.shape[1] == 4:
        return tri.copy()
    n = int(conn[:, :4].max()) + 1
    keys = []
    mids = []
    for k, (i, j) in enumerate(EDGES):
        a, b = conn[:, i], conn[:, j]
        keys.append(np.minimum(a, b).astype(np.int64) * n + np.maximum(a, b))
        mids.append(conn[:, 4 + k])
    keys = np.concatenate(keys)
    mids = np.concatenate(mids)
    order = np.argsort(keys)
    keys, mids = keys[order], mids[order]
    out = np.zeros((len(tri), 6), dtype=np.int64)
    out[:, :3] = tri
    for c, (i, j) in enumerate(((0, 1), (1, 2), (2, 0))):
        a, b = tri[:, i], tri[:, j]
        q = np.minimum(a, b).astype(np.int64) * n + np.maximum(a, b)
        pos = np.searchsorted(keys, q)
        if np.any(pos >= len(keys)) or np.any(keys[np.minimum(pos, len(keys) - 1)] != q):
            raise ContactError("A contact face edge does not belong to the mesh.")
        out[:, 3 + c] = mids[pos]
    return out


def tributary(X, tri, nodes_per_face):
    p = X[tri[:, :3]]
    area = 0.5 * np.linalg.norm(np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]), axis=1)
    nn = nodes_per_face.shape[1]
    ids = nodes_per_face.ravel()
    w = np.repeat(area / nn, nn)
    uniq, inv = np.unique(ids, return_inverse=True)
    a = np.bincount(inv, weights=w, minlength=len(uniq))
    return uniq, a


def closest_on_triangles(p, a, b, c):
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = np.einsum("ij,ij->i", ab, ap), np.einsum("ij,ij->i", ac, ap)
    bp = p - b
    d3, d4 = np.einsum("ij,ij->i", ab, bp), np.einsum("ij,ij->i", ac, bp)
    cp = p - c
    d5, d6 = np.einsum("ij,ij->i", ab, cp), np.einsum("ij,ij->i", ac, cp)
    n = len(p)
    u = np.zeros(n)
    v = np.zeros(n)
    w = np.zeros(n)
    done = np.zeros(n, dtype=bool)

    def put(mask, uu, vv, ww):
        m = mask & ~done
        u[m], v[m], w[m] = uu[m] if np.ndim(uu) else uu, vv[m] if np.ndim(vv) else vv, ww[m] if np.ndim(ww) else ww
        done[m] = True

    put((d1 <= 0) & (d2 <= 0), 1.0, 0.0, 0.0)
    put((d3 >= 0) & (d4 <= d3), 0.0, 1.0, 0.0)
    vc = d1 * d4 - d3 * d2
    with np.errstate(divide="ignore", invalid="ignore"):
        t = d1 / (d1 - d3)
        put((vc <= 0) & (d1 >= 0) & (d3 <= 0), 1.0 - t, t, 0.0)
        put((d6 >= 0) & (d5 <= d6), 0.0, 0.0, 1.0)
        vb = d5 * d2 - d1 * d6
        t = d2 / (d2 - d6)
        put((vb <= 0) & (d2 >= 0) & (d6 <= 0), 1.0 - t, 0.0, t)
        va = d3 * d6 - d5 * d4
        t = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        put((va <= 0) & ((d4 - d3) >= 0) & ((d5 - d6) >= 0), 0.0, 1.0 - t, t)
        denom = 1.0 / (va + vb + vc)
        vv, ww = vb * denom, vc * denom
        put(~done, 1.0 - vv - ww, vv, ww)
    return u, v, w


class Contact:
    def __init__(self, nnodes, eps_n, mu=0.0, eps_t=None, method="penalty"):
        if method not in ("penalty", "augmented"):
            raise ContactError("Contact method must be penalty or augmented.")
        if not eps_n > 0.0:
            raise ContactError("The normal contact stiffness must be positive.")
        if mu < 0.0:
            raise ContactError("Friction coefficient must not be negative.")
        self.nn = nnodes
        self.eps_n = float(eps_n)
        self.mu = float(mu)
        self.eps_t = float(eps_t) if eps_t else 0.3 * float(eps_n)
        self.method = method
        self.pairs = []
        self.last = {}

    def add_plane(self, nodes, area, point, normal, mu=None):
        n = np.asarray(normal, dtype=float)
        L = np.linalg.norm(n)
        if L == 0.0:
            raise ContactError("The contact plane normal is zero.")
        mu = self.mu if mu is None else float(mu)
        if mu < 0.0:
            raise ContactError("Friction coefficient must not be negative.")
        self.pairs.append({"kind": "plane", "nodes": np.asarray(nodes), "area": np.asarray(area, dtype=float), "point": np.asarray(point, dtype=float), "n": n / L, "mu": mu})
        self._arm(self.pairs[-1])

    def add_surface(self, slave_nodes, slave_area, master_tri, radius):
        self.pairs.append({"kind": "surface", "nodes": np.asarray(slave_nodes), "area": np.asarray(slave_area, dtype=float), "tri": np.asarray(master_tri)[:, :3], "radius": float(radius), "mu": 0.0})
        self._arm(self.pairs[-1])

    def _arm(self, pair):
        m = len(pair["nodes"])
        pair["lam"] = np.zeros(m)
        pair["anchor"] = np.zeros((m, 3))
        pair["has_anchor"] = np.zeros(m, dtype=bool)
        pair["slip"] = np.zeros((m, 3))

    def snapshot(self):
        return [(p["lam"].copy(), p["anchor"].copy(), p["has_anchor"].copy(), p["slip"].copy()) for p in self.pairs]

    def restore(self, snap):
        for p, (a, b, c, d) in zip(self.pairs, snap):
            p["lam"][:] = a
            p["anchor"][:] = b
            p["has_anchor"][:] = c
            p["slip"][:] = d

    def evaluate(self, x, want_k=True):
        x = np.asarray(x, dtype=float).reshape(-1, 3)
        fc = np.zeros(3 * self.nn)
        rows, cols, vals = [], [], []
        pen = 0.0
        active = 0
        fn_total = 0.0
        records = []
        for pair in self.pairs:
            nodes = pair["nodes"]
            xs = x[nodes]
            if pair["kind"] == "plane":
                n = np.broadcast_to(pair["n"], xs.shape)
                gap = (xs - pair["point"]) @ pair["n"]
                mnodes = None
                w = None
            else:
                n, gap, mnodes, w = self._project(pair, x, xs)
            eps = self.eps_n * pair["area"]
            raw = (pair["lam"] if self.method == "augmented" else 0.0) - eps * gap
            p = np.maximum(raw, 0.0)
            on = raw >= 0.0
            pair["_p"] = p
            pair["_gap"] = gap
            pair["_on"] = on
            pair["_n"] = n
            pair["_xs"] = xs
            if not np.any(on):
                records.append(None)
                continue
            idx = np.nonzero(on)[0]
            pen = max(pen, float(-gap[idx].min())) if np.any(gap[idx] < 0) else pen
            active += len(idx)
            fvec = p[idx, None] * n[idx]
            self._scatter(fc, nodes[idx], fvec, mnodes, w, idx)
            fn_total += float(p[idx].sum())
            tvec = np.zeros((len(idx), 3))
            kfric = None
            if pair["mu"] > 0.0:
                ut = xs[idx] - pair["anchor"][idx]
                fresh = ~pair["has_anchor"][idx]
                nn_ = n[idx]
                if np.any(fresh):
                    pair["anchor"][idx[fresh]] = xs[idx[fresh]]
                    pair["has_anchor"][idx[fresh]] = True
                    ut = xs[idx] - pair["anchor"][idx]
                ut = ut - np.einsum("ij,ij->i", ut, nn_)[:, None] * nn_
                slipv = pair["slip"][idx]
                et = self.eps_t * pair["area"][idx]
                Ttr = et[:, None] * (ut - slipv)
                Tn = np.linalg.norm(Ttr, axis=1)
                cap = pair["mu"] * p[idx]
                sliding = Tn > cap
                th = np.where(sliding, cap / np.maximum(Tn, 1e-300), 1.0)
                T = Ttr * th[:, None]
                tvec = -T
                kfric = (idx, et, sliding, Tn, cap, Ttr)
                self._scatter(fc, nodes[idx], tvec, mnodes, w, idx)
            records.append((pair, idx, kfric, mnodes, w, eps))
            if want_k:
                self._tangent(rows, cols, vals, pair, idx, kfric, mnodes, w, eps)
        K = None
        if want_k:
            if vals:
                K = sp.coo_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(3 * self.nn, 3 * self.nn)).tocsr()
            else:
                K = sp.csr_matrix((3 * self.nn, 3 * self.nn))
        self.last = {"penetration": pen, "active": active, "normal_force": fn_total}
        return fc, K

    def _scatter(self, fc, nodes, fvec, mnodes, w, idx):
        for c in range(3):
            fc[3 * nodes + c] += fvec[:, c]
        if mnodes is not None:
            for k in range(3):
                for c in range(3):
                    np.subtract.at(fc, 3 * mnodes[idx, k] + c, w[idx, k] * fvec[:, c])

    def _tangent(self, rows, cols, vals, pair, idx, kfric, mnodes, w, eps):
        n = pair["_n"][idx]
        nodes = pair["nodes"][idx]
        cnt = len(idx)
        if mnodes is None:
            gn = nodes[:, None]
            coef = np.ones((cnt, 1))
        else:
            gn = np.column_stack([nodes, mnodes[idx]])
            coef = np.column_stack([np.ones(cnt), -w[idx]])
        ke = eps[idx, None, None] * np.einsum("ij,ik->ijk", n, n)
        if kfric is not None:
            _, et, sliding, Tn, cap, Ttr = kfric
            Pt = np.eye(3)[None] - np.einsum("ij,ik->ijk", n, n)
            kt = et[:, None, None] * Pt
            if np.any(sliding):
                s = np.nonzero(sliding)[0]
                that = Ttr[s] / Tn[s, None]
                ks = (cap[s] * et[s] / Tn[s])[:, None, None] * (Pt[s] - np.einsum("ij,ik->ijk", that, that))
                ks = ks - pair["mu"] * eps[idx][s][:, None, None] * np.einsum("ij,ik->ijk", that, n[s])
                kt[s] = ks
            ke = ke + kt
        m = gn.shape[1]
        for a in range(m):
            for b in range(m):
                blk = coef[:, a, None, None] * coef[:, b, None, None] * ke
                for i in range(3):
                    for j in range(3):
                        rows.append(3 * gn[:, a] + i)
                        cols.append(3 * gn[:, b] + j)
                        vals.append(blk[:, i, j])

    def _project(self, pair, x, xs):
        tri = pair["tri"]
        a, b, c = x[tri[:, 0]], x[tri[:, 1]], x[tri[:, 2]]
        cen = (a + b + c) / 3.0
        tree = cKDTree(cen)
        k = min(8, len(tri))
        dist, cand = tree.query(xs, k=k)
        if k == 1:
            cand = cand[:, None]
        m = len(xs)
        best_t = np.zeros(m, dtype=np.int64)
        best_w = np.zeros((m, 3))
        best_cp = np.zeros((m, 3))
        best_d = np.full(m, np.inf)
        for j in range(cand.shape[1]):
            t = cand[:, j]
            u, v, w = closest_on_triangles(xs, a[t], b[t], c[t])
            cp = u[:, None] * a[t] + v[:, None] * b[t] + w[:, None] * c[t]
            d = np.linalg.norm(xs - cp, axis=1)
            better = d < best_d
            best_d = np.where(better, d, best_d)
            best_t = np.where(better, t, best_t)
            best_w = np.where(better[:, None], np.column_stack([u, v, w]), best_w)
            best_cp = np.where(better[:, None], cp, best_cp)
        tn = np.cross(b - a, c - a)
        vn = np.zeros((len(x), 3))
        for k in range(3):
            for c3 in range(3):
                vn[:, c3] += np.bincount(tri[:, k], weights=tn[:, c3], minlength=len(x))
        vn /= np.maximum(np.linalg.norm(vn, axis=1), 1e-300)[:, None]
        sel = tri[best_t]
        nrm = np.einsum("mk,mkc->mc", best_w, vn[sel])
        nrm /= np.maximum(np.linalg.norm(nrm, axis=1), 1e-300)[:, None]
        best_gap = np.einsum("ij,ij->i", xs - best_cp, nrm)
        far = best_d > pair["radius"]
        best_gap[far] = 1.0e30
        return nrm, best_gap, sel, best_w

    def commit(self, x):
        for pair in self.pairs:
            if "_p" not in pair:
                continue
            p, on = pair["_p"], pair["_on"]
            if pair["mu"] > 0.0:
                lost = ~on
                pair["has_anchor"][lost] = False
                pair["slip"][lost] = 0.0
                idx = np.nonzero(on)[0]
                if len(idx):
                    nn_ = pair["_n"][idx]
                    xs = pair["_xs"][idx]
                    ut = xs - pair["anchor"][idx]
                    ut = ut - np.einsum("ij,ij->i", ut, nn_)[:, None] * nn_
                    et = self.eps_t * pair["area"][idx]
                    Ttr = et[:, None] * (ut - pair["slip"][idx])
                    Tn = np.linalg.norm(Ttr, axis=1)
                    cap = pair["mu"] * p[idx]
                    sl = Tn > cap
                    if np.any(sl):
                        s = idx[sl]
                        that = Ttr[sl] / Tn[sl, None]
                        pair["slip"][s] = ut[sl] - (cap[sl] / et[sl])[:, None] * that

    def imbalance(self):
        worst = 0.0
        top = 0.0
        for pair in self.pairs:
            if "_p" not in pair:
                continue
            p = pair["_p"]
            eps = self.eps_n * pair["area"]
            live = p > 0.0
            if np.any(live):
                worst = max(worst, float(np.max(eps[live] * np.abs(pair["_gap"][live]))))
                top = max(top, float(p.max()))
        return worst / max(top, 1.0e-300)

    def advance_multipliers(self):
        if self.method != "augmented":
            return
        for pair in self.pairs:
            if "_p" in pair:
                pair["lam"] = pair["_p"].copy()
