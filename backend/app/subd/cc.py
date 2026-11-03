import numpy as np

INF = 10.0
MAX_LEVEL = 6


class SubdError(Exception):
    pass


class Level:
    __slots__ = ("v", "fv", "fn", "cf", "sharp_a", "sharp_b", "sharp_s", "parent")

    def __init__(self, v, fv, fn, sharp_a, sharp_b, sharp_s, parent):
        self.v = v
        self.fv = fv
        self.fn = fn
        self.cf = np.repeat(np.arange(len(fn)), fn) if len(fn) else np.zeros(0, dtype=np.int64)
        self.sharp_a = sharp_a
        self.sharp_b = sharp_b
        self.sharp_s = sharp_s
        self.parent = parent

    def faces(self):
        out, at = [], 0
        for n in self.fn:
            out.append(self.fv[at:at + n].tolist())
            at += n
        return out

    def quads(self):
        if len(self.fn) and not np.all(self.fn == 4):
            raise SubdError("The mesh has faces that are not quads.")
        return self.fv.reshape(-1, 4)


def from_cage(v, faces, sharp) -> Level:
    v = np.asarray(v, dtype=np.float64).reshape(-1, 3)
    fn = np.array([len(f) for f in faces], dtype=np.int64)
    fv = np.fromiter((i for f in faces for i in f), dtype=np.int64, count=int(fn.sum()))
    if len(fv) and (fv.min() < 0 or fv.max() >= len(v)):
        raise SubdError("A face uses a vertex that does not exist.")
    items = sorted(sharp.items()) if isinstance(sharp, dict) else list(sharp)
    sa = np.array([k[0] for k, _ in items], dtype=np.int64)
    sb = np.array([k[1] for k, _ in items], dtype=np.int64)
    ss = np.array([w for _, w in items], dtype=np.float64)
    return Level(v, fv, fn, sa, sb, ss, np.arange(len(fn)))


def next_corner(lv: Level):
    start = np.concatenate(([0], np.cumsum(lv.fn)[:-1])) if len(lv.fn) else np.zeros(0, dtype=np.int64)
    idx = np.arange(len(lv.fv))
    nxt = idx + 1
    last = start + lv.fn - 1
    nxt[last] = start
    prv = idx - 1
    prv[start] = last
    return start, nxt, prv


def edge_table(lv: Level):
    start, nxt, prv = next_corner(lv)
    a = lv.fv
    b = lv.fv[nxt]
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    key = lo * len(lv.v) + hi
    uniq, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    ea = (uniq // len(lv.v)).astype(np.int64)
    eb = (uniq % len(lv.v)).astype(np.int64)
    return ea, eb, inv, cnt, nxt, prv


def edge_sharpness(lv: Level, ea, eb, cnt):
    s = np.zeros(len(ea))
    if len(lv.sharp_a):
        n = len(lv.v)
        keys = ea * n + eb
        order = np.argsort(keys)
        want = np.minimum(lv.sharp_a, lv.sharp_b) * n + np.maximum(lv.sharp_a, lv.sharp_b)
        pos = np.searchsorted(keys[order], want)
        pos = np.clip(pos, 0, len(keys) - 1)
        ok = keys[order][pos] == want
        s[order[pos[ok]]] = np.maximum(s[order[pos[ok]]], lv.sharp_s[ok])
    s[cnt == 1] = INF
    return np.where(s >= INF, np.inf, s)


def subdivide(lv: Level) -> Level:
    nv, nf = len(lv.v), len(lv.fn)
    ea, eb, inv, cnt, nxt, prv = edge_table(lv)
    ne = len(ea)
    if np.any(cnt > 2):
        raise SubdError("An edge is shared by more than two faces.")
    s = edge_sharpness(lv, ea, eb, cnt)
    fp = np.zeros((nf, 3))
    np.add.at(fp, lv.cf, lv.v[lv.fv])
    fp /= lv.fn[:, None]
    fsum = np.zeros((ne, 3))
    np.add.at(fsum, inv, fp[lv.cf])
    mid = 0.5 * (lv.v[ea] + lv.v[eb])
    smooth = np.where((cnt == 2)[:, None], 0.25 * (lv.v[ea] + lv.v[eb] + fsum), mid)
    sig = np.clip(np.where(np.isinf(s), 1.0, s), 0.0, 1.0)
    ep = (1.0 - sig)[:, None] * smooth + sig[:, None] * mid
    val = np.zeros(nv)
    np.add.at(val, ea, 1)
    np.add.at(val, eb, 1)
    esum = np.zeros((nv, 3))
    np.add.at(esum, ea, lv.v[eb])
    np.add.at(esum, eb, lv.v[ea])
    fcorner = np.zeros((nv, 3))
    np.add.at(fcorner, lv.fv, fp[lv.cf])
    nfc = np.zeros(nv)
    np.add.at(nfc, lv.fv, 1)
    sharp_edge = s > 0
    ns = np.zeros(nv)
    np.add.at(ns, ea[sharp_edge], 1)
    np.add.at(ns, eb[sharp_edge], 1)
    ssum = np.zeros(nv)
    se = np.where(np.isinf(s), INF, s)
    np.add.at(ssum, ea[sharp_edge], se[sharp_edge])
    np.add.at(ssum, eb[sharp_edge], se[sharp_edge])
    csum = np.zeros((nv, 3))
    np.add.at(csum, ea[sharp_edge], lv.v[eb[sharp_edge]])
    np.add.at(csum, eb[sharp_edge], lv.v[ea[sharp_edge]])
    n = np.maximum(val, 1.0)
    smooth_v = ((n - 2.0) / n)[:, None] * lv.v + esum / (n * n)[:, None] + fcorner / (n * n)[:, None]
    crease_v = (csum + 6.0 * lv.v) / 8.0
    sigv = np.clip(np.where(ns > 0, ssum / np.maximum(ns, 1.0), 0.0), 0.0, 1.0)
    vp = smooth_v.copy()
    two = ns == 2
    vp[two] = (1.0 - sigv[two])[:, None] * smooth_v[two] + sigv[two][:, None] * crease_v[two]
    many = ns >= 3
    vp[many] = (1.0 - sigv[many])[:, None] * smooth_v[many] + sigv[many][:, None] * lv.v[many]
    alone = val == 0
    vp[alone] = lv.v[alone]
    out_v = np.concatenate([vp, ep, fp])
    e_base = nv
    f_base = nv + ne
    nfn = np.repeat(np.int64(4), len(lv.fv))
    c_vert = lv.fv
    e_next = e_base + inv
    e_prev = e_base + inv[prv]
    f_id = f_base + lv.cf
    quads = np.stack([c_vert, e_next, f_id, e_prev], axis=1)
    child = np.where(np.isinf(s), np.inf, np.maximum(s - 1.0, 0.0))
    keep = child > 0
    ka = ea[keep]
    kb = eb[keep]
    ks = child[keep]
    mids = e_base + np.nonzero(keep)[0]
    na = np.concatenate([ka, kb])
    nb = np.concatenate([mids, mids])
    nsv = np.concatenate([ks, ks])
    lo = np.minimum(na, nb)
    hi = np.maximum(na, nb)
    ns_vals = np.where(np.isinf(nsv), INF, nsv)
    return Level(out_v, quads.reshape(-1), nfn, lo, hi, ns_vals, lv.cf.copy())


def refine(v, faces, sharp, levels: int):
    levels = int(levels)
    if levels < 0 or levels > MAX_LEVEL:
        raise SubdError("The subdivision level must be 0 to %d." % MAX_LEVEL)
    chain = [from_cage(v, faces, sharp)]
    for _ in range(levels):
        chain.append(subdivide(chain[-1]))
    root = np.arange(len(chain[0].fn))
    for lv in chain[1:]:
        root = root[lv.parent]
        lv.parent = root
    return chain


def face_root(chain):
    return chain[-1].parent if len(chain) > 1 else np.arange(len(chain[0].fn))
