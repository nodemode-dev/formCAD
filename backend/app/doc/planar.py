import math

from app.doc import curves2d as C
from app.doc import geom

TAU = geom.TAU
MAX_PRIMS = 60000
MAX_ISLANDS = 4096
RAY_ANGLES = (0.1234567, 1.0471975, 2.3561944, 3.7699111, 5.2359877, 0.7853981, 4.4505896, 5.9)


class TooComplex(Exception):
    pass


class Edge:
    __slots__ = ("n0", "n1", "kind", "p0", "p1", "c", "r", "a0", "sw", "src", "pid", "rev")

    def __init__(self, n0, n1, kind, p0, p1, src, pid):
        self.rev = False
        self.n0 = n0
        self.n1 = n1
        self.kind = kind
        self.p0 = p0
        self.p1 = p1
        self.c = None
        self.r = 0.0
        self.a0 = 0.0
        self.sw = 0.0
        self.src = src
        self.pid = pid


class DirectedEdge:
    __slots__ = ("p", "q", "kind", "c", "r", "theta", "src", "pid")

    def __init__(self, p, q, kind, c, r, theta, src, pid):
        self.p = p
        self.q = q
        self.kind = kind
        self.c = c
        self.r = r
        self.theta = theta
        self.src = src
        self.pid = pid


class NodeIndex:
    def __init__(self, tol):
        self.tol = tol
        self.cell = max(tol * 2.0, 1e-300)
        self.cells = {}
        self.pts = []

    def key(self, x, y):
        return int(math.floor(x / self.cell)), int(math.floor(y / self.cell))

    def add(self, x, y):
        kx, ky = self.key(x, y)
        tol = self.tol
        for i in (kx - 1, kx, kx + 1):
            for j in (ky - 1, ky, ky + 1):
                for nid in self.cells.get((i, j), ()):
                    p = self.pts[nid]
                    if abs(p[0] - x) <= tol and abs(p[1] - y) <= tol:
                        return nid
        nid = len(self.pts)
        self.pts.append((x, y))
        self.cells.setdefault((kx, ky), []).append(nid)
        return nid


def tolerance_for(prims):
    boxes = [p.box for p in prims]
    if not boxes:
        return 1e-9
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    size = max(math.hypot(x1 - x0, y1 - y0), 1e-6)
    return max(size * 1e-9, 1e-12)


def endpoints(p):
    if p.kind == "line":
        return [p.a, p.b]
    return [p.at(0.0), p.at(p.sw)]


class Graph:
    def __init__(self, prims, tol=None, gap=0.0, prune=True, merge=True):
        if len(prims) > MAX_PRIMS:
            raise TooComplex("Too many objects for boundary detection.")
        self.tol = tol if tol is not None else tolerance_for(prims)
        self.prims = prims
        for i, p in enumerate(prims):
            p.pid = i
        self.nodes = NodeIndex(self.tol)
        self.parent = []
        self.edges = []
        self.ties = []
        self.bridges = 0
        self.build(prims)
        self.resolve_ties()
        if merge:
            self.dedupe()
        if gap > 0.0:
            self.bridge(gap)
        if prune:
            self.prune()
        self.index()

    def find(self, i):
        par = self.parent
        while par[i] != i:
            par[i] = par[par[i]]
            i = par[i]
        return i

    def split(self, prims):
        tol = self.tol
        cuts = [[0.0, p.span()] for p in prims]
        n = len(prims)
        if n == 0:
            return cuts
        for ia, ib in self.pairs(prims):
            a = prims[ia]
            b = prims[ib]
            m = tol + a.slack + b.slack
            if b.box[1] > a.box[3] + m or b.box[3] < a.box[1] - m or b.box[0] > a.box[2] + m or b.box[2] < a.box[0] - m:
                continue
            for t, u in C.intersections(a, b, tol + max(a.slack, b.slack)):
                cuts[ia].append(t)
                cuts[ib].append(u)
            for src, dst, idst in ((a, b, ib), (b, a, ia)):
                reach = tol + dst.slack
                bx = dst.box
                for q in endpoints(src):
                    if q[0] < bx[0] - reach or q[0] > bx[2] + reach or q[1] < bx[1] - reach or q[1] > bx[3] + reach:
                        continue
                    t, d = C.closest_param(dst, q[0], q[1])
                    if d <= reach:
                        cuts[idst].append(t)
                        if d > tol:
                            self.ties.append((q, dst.at(t)))
        return cuts

    def pairs(self, prims):
        n = len(prims)
        sizes = sorted(max(p.box[2] - p.box[0], p.box[3] - p.box[1]) for p in prims)
        cell = max(sizes[n // 2] * 1.5, sizes[-1] / 512.0, self.tol * 4.0)
        grid = {}
        big = []
        margin = self.tol + max(p.slack for p in prims)
        for i, p in enumerate(prims):
            x0 = int(math.floor((p.box[0] - margin) / cell))
            x1 = int(math.floor((p.box[2] + margin) / cell))
            y0 = int(math.floor((p.box[1] - margin) / cell))
            y1 = int(math.floor((p.box[3] + margin) / cell))
            if (x1 - x0 + 1) * (y1 - y0 + 1) > 256:
                big.append(i)
                continue
            for gx in range(x0, x1 + 1):
                for gy in range(y0, y1 + 1):
                    grid.setdefault((gx, gy), []).append(i)
        seen = set()
        for lst in grid.values():
            k = len(lst)
            for x in range(k):
                for y in range(x + 1, k):
                    key = (lst[x], lst[y]) if lst[x] < lst[y] else (lst[y], lst[x])
                    if key not in seen:
                        seen.add(key)
                        yield key
        for i in big:
            for j in range(n):
                if j != i:
                    key = (i, j) if i < j else (j, i)
                    if key not in seen:
                        seen.add(key)
                        yield key

    def build(self, prims):
        tol = self.tol
        cuts = self.split(prims)
        nodes = self.nodes
        for i, p in enumerate(prims):
            span = p.span()
            ts = sorted(min(max(t, 0.0), span) for t in cuts[i])
            tt = p.scale_t(tol)
            merged = [ts[0]]
            for t in ts[1:]:
                if t - merged[-1] > tt:
                    merged.append(t)
            if merged[-1] < span - tt:
                merged.append(span)
            else:
                merged[-1] = span
            for k in range(len(merged) - 1):
                t0, t1 = merged[k], merged[k + 1]
                q0, q1 = p.at(t0), p.at(t1)
                n0 = nodes.add(q0[0], q0[1])
                n1 = nodes.add(q1[0], q1[1])
                if p.kind == "line":
                    if n0 == n1:
                        continue
                    e = Edge(n0, n1, "line", q0, q1, p.src, p.pid)
                else:
                    if n0 == n1 and t1 - t0 < 1.0:
                        continue
                    e = Edge(n0, n1, "arc", q0, q1, p.src, p.pid)
                    e.c = p.c
                    e.r = p.r
                    e.a0 = p.a0 + t0
                    e.sw = t1 - t0
                e.rev = p.rev
                self.edges.append(e)
        self.parent = list(range(len(nodes.pts)))

    def resolve_ties(self):
        nodes = self.nodes
        for a, b in self.ties:
            ia = nodes.add(a[0], a[1])
            ib = nodes.add(b[0], b[1])
            if ia >= len(self.parent):
                self.parent.extend(range(len(self.parent), ia + 1))
            if ib >= len(self.parent):
                self.parent.extend(range(len(self.parent), ib + 1))
            ra, rb = self.find(ia), self.find(ib)
            if ra != rb:
                self.parent[rb] = ra
        keep = []
        for e in self.edges:
            e.n0 = self.find(e.n0)
            e.n1 = self.find(e.n1)
            if e.n0 == e.n1 and e.kind == "line":
                continue
            if e.n0 == e.n1 and e.kind == "arc" and e.sw < 1.0:
                continue
            keep.append(e)
        self.edges = keep

    def dedupe(self):
        seen = {}
        out = []
        q = self.tol * 50.0
        for e in self.edges:
            a, b = (e.n0, e.n1) if e.n0 <= e.n1 else (e.n1, e.n0)
            if e.kind == "line":
                key = (a, b, 0)
            else:
                mx = e.c[0] + e.r * math.cos(e.a0 + e.sw / 2.0)
                my = e.c[1] + e.r * math.sin(e.a0 + e.sw / 2.0)
                key = (a, b, 1, round(mx / q), round(my / q))
            prev = seen.get(key)
            if prev is None:
                seen[key] = e
                out.append(e)
        self.edges = out

    def degrees(self):
        deg = {}
        for e in self.edges:
            deg[e.n0] = deg.get(e.n0, 0) + 1
            deg[e.n1] = deg.get(e.n1, 0) + 1
        return deg

    def bridge(self, gap):
        deg = self.degrees()
        ends = [n for n, d in deg.items() if d == 1]
        pts = self.nodes.pts
        pairs = []
        for i in range(len(ends)):
            a = pts[ends[i]]
            for j in range(i + 1, len(ends)):
                b = pts[ends[j]]
                d = math.hypot(a[0] - b[0], a[1] - b[1])
                if d <= gap:
                    pairs.append((d, ends[i], ends[j]))
        pairs.sort()
        used = set()
        for d, a, b in pairs:
            if a in used or b in used:
                continue
            if d <= self.tol:
                continue
            used.add(a)
            used.add(b)
            self.edges.append(Edge(a, b, "line", pts[a], pts[b], None, -1))
            self.bridges += 1

    def prune(self):
        deg = self.degrees()
        alive = [True] * len(self.edges)
        at = {}
        for i, e in enumerate(self.edges):
            at.setdefault(e.n0, []).append(i)
            if e.n1 != e.n0:
                at.setdefault(e.n1, []).append(i)
        stack = [n for n, d in deg.items() if d == 1]
        while stack:
            n = stack.pop()
            if deg.get(n, 0) != 1:
                continue
            for i in at.get(n, ()):
                if not alive[i]:
                    continue
                alive[i] = False
                e = self.edges[i]
                for m in (e.n0, e.n1):
                    deg[m] -= 1
                    if deg[m] == 1:
                        stack.append(m)
                break
        self.edges = [e for i, e in enumerate(self.edges) if alive[i]]

    def hang(self, h):
        e = self.edges[h >> 1]
        if e.kind == "line":
            ang = math.atan2(e.p1[1] - e.p0[1], e.p1[0] - e.p0[0])
            if h & 1:
                ang += math.pi
            curv = 0.0
        elif h & 1:
            ang = e.a0 + e.sw + math.pi / 2.0 + math.pi
            curv = -1.0 / e.r
        else:
            ang = e.a0 + math.pi / 2.0
            curv = 1.0 / e.r
        ang = math.atan2(math.sin(ang), math.cos(ang))
        return round(ang, 9), curv

    def index(self):
        adj = {}
        for i, e in enumerate(self.edges):
            adj.setdefault(e.n0, []).append(2 * i)
            adj.setdefault(e.n1, []).append(2 * i + 1)
        self.adj = adj
        self.pos = {}
        for n, lst in adj.items():
            lst.sort(key=self.hang)
            for k, h in enumerate(lst):
                self.pos[h] = k
        par = {}

        def root(x):
            while par.setdefault(x, x) != x:
                par[x] = par[par[x]]
                x = par[x]
            return x

        for e in self.edges:
            a, b = root(e.n0), root(e.n1)
            if a != b:
                par[b] = a
        self.comp = [root(e.n0) for e in self.edges]

    def head(self, h):
        e = self.edges[h >> 1]
        return e.n0 if h & 1 else e.n1

    def nxt(self, h):
        lst = self.adj[self.head(h)]
        return lst[self.pos[h ^ 1] - 1]

    def trace(self, h):
        seq = []
        cur = h
        limit = 2 * len(self.edges) + 2
        while True:
            seq.append(cur)
            cur = self.nxt(cur)
            if cur == h or len(seq) > limit:
                break
        return seq

    def directed(self, h):
        e = self.edges[h >> 1]
        if h & 1:
            return DirectedEdge(e.p1, e.p0, e.kind, e.c, e.r, -e.sw if e.kind == "arc" else 0.0, e.src, e.pid)
        return DirectedEdge(e.p0, e.p1, e.kind, e.c, e.r, e.sw if e.kind == "arc" else 0.0, e.src, e.pid)

    def area_of(self, seq):
        s = 0.0
        for h in seq:
            d = self.directed(h)
            s += 0.5 * (d.p[0] * d.q[1] - d.q[0] * d.p[1])
            if d.kind == "arc":
                s += 0.5 * d.r * d.r * (d.theta - math.sin(d.theta))
        return s

    def faces(self):
        seen = set()
        out = []
        for h in range(2 * len(self.edges)):
            if h in seen:
                continue
            seq = self.trace(h)
            seen.update(seq)
            out.append((seq, self.area_of(seq)))
        return out

    def ray_hit(self, px, py, ang, skip):
        dx, dy = math.cos(ang), math.sin(ang)
        best = None
        tol = self.tol
        for i, e in enumerate(self.edges):
            if self.comp[i] in skip:
                continue
            if e.kind == "line":
                rx, ry = e.p1[0] - e.p0[0], e.p1[1] - e.p0[1]
                den = dx * ry - dy * rx
                ln = math.hypot(rx, ry)
                if abs(den) <= 1e-12 * ln:
                    continue
                qx, qy = e.p0[0] - px, e.p0[1] - py
                t = (qx * ry - qy * rx) / den
                u = (qx * dy - qy * dx) / den
                if t <= tol:
                    continue
                if u < -1e-9 or u > 1.0 + 1e-9:
                    continue
                near_end = u < 1e-7 or u > 1.0 - 1e-7
                cand = (t, i, near_end, (0.0, 0.0), (rx / ln, ry / ln))
            else:
                fx, fy = px - e.c[0], py - e.c[1]
                bb = fx * dx + fy * dy
                cc = fx * fx + fy * fy - e.r * e.r
                disc = bb * bb - cc
                if disc < 0.0:
                    continue
                sq = math.sqrt(disc)
                tangent = sq < 1e-9 * e.r
                cand = None
                for t in ((-bb,) if tangent else (-bb - sq, -bb + sq)):
                    if t <= tol:
                        continue
                    phi = math.atan2(py + dy * t - e.c[1], px + dx * t - e.c[0])
                    s = geom.ccw_sweep(e.a0, phi)
                    if s > e.sw + 1e-9 and s < TAU - 1e-9:
                        continue
                    odd = tangent or s < 1e-7 or abs(s - e.sw) < 1e-7 or s > TAU - 1e-7
                    c2 = (t, i, odd, (0.0, 0.0), (-math.sin(phi), math.cos(phi)))
                    if cand is None or c2[0] < cand[0]:
                        cand = c2
                if cand is None:
                    continue
            if best is None or cand[0] < best[0]:
                best = cand
        return best

    def face_at(self, px, py, skip=None):
        skip = set(skip or ())
        for _round in range(len(set(self.comp)) + 1):
            hit = None
            for ang in RAY_ANGLES:
                hit = self.ray_hit(px, py, ang, skip)
                if hit is None:
                    break
                if not hit[2]:
                    break
                hit = False
            if hit is None:
                return None
            if hit is False:
                return None
            t, i, _ne, _x, tau = hit
            dx, dy = math.cos(ang), math.sin(ang)
            h = 2 * i if dx * tau[1] - dy * tau[0] > 0 else 2 * i + 1
            seq = self.trace(h)
            area = self.area_of(seq)
            if area > 0 and self.contains(seq, px, py):
                return seq, area
            skip.add(self.comp[i])
        return None

    def sample(self, seq, per_arc=None):
        pts = []
        for h in seq:
            d = self.directed(h)
            pts.append(d.p)
            if d.kind == "arc":
                n = max(2, int(math.ceil(abs(d.theta) / 0.05)))
                a0 = math.atan2(d.p[1] - d.c[1], d.p[0] - d.c[0])
                for k in range(1, n):
                    a = a0 + d.theta * k / n
                    pts.append((d.c[0] + d.r * math.cos(a), d.c[1] + d.r * math.sin(a)))
        return pts

    def contains(self, seq, x, y):
        return point_in_ring(x, y, self.sample(seq))

    def outline(self, comp):
        best = None
        for seq, area in self.faces_of(comp):
            if area < 0 and (best is None or area < best[1]):
                best = (seq, area)
        return best

    def faces_of(self, comp):
        cache = getattr(self, "_faces", None)
        if cache is None:
            cache = {}
            for seq, area in self.faces():
                c = self.comp[seq[0] >> 1]
                cache.setdefault(c, []).append((seq, area))
            self._faces = cache
        return cache.get(comp, [])

    def components(self):
        return sorted(set(self.comp))

    def loop(self, seq):
        items = [self.directed(h) for h in seq]
        return merge_items(items)


def point_in_ring(x, y, ring):
    hit = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            hit = not hit
        j = i
    return hit


def bulge_of(theta):
    return math.tan(theta / 4.0)


def merge_items(items):
    n = len(items)
    if n == 0:
        return [], []
    start = 0
    for i in range(n):
        a, b = items[i - 1], items[i]
        if a.pid != b.pid or a.kind != b.kind or (a.kind == "arc" and (a.theta > 0) != (b.theta > 0)):
            start = i
            break
    seq = items[start:] + items[:start]
    groups = []
    for d in seq:
        g = groups[-1] if groups else None
        if g is not None and g[0].pid == d.pid and g[0].kind == d.kind and (d.kind == "line" or ((g[0].theta > 0) == (d.theta > 0) and abs(sum(x.theta for x in g)) + abs(d.theta) <= 1.5 * math.pi)):
            g.append(d)
        else:
            groups.append([d])
    verts = []
    sources = []
    for g in groups:
        first = g[0]
        if first.kind == "line":
            verts.append({"p": [first.p[0], first.p[1]], "bulge": 0.0})
        else:
            theta = sum(x.theta for x in g)
            verts.append({"p": [first.p[0], first.p[1]], "bulge": bulge_of(theta)})
        for x in g:
            if x.src is not None and x.src not in sources:
                sources.append(x.src)
    if len(groups) == 1 and groups[0][0].kind == "arc":
        d = groups[0][0]
        half = sum(x.theta for x in groups[0]) / 2.0
        a0 = math.atan2(d.p[1] - d.c[1], d.p[0] - d.c[0])
        mid = (d.c[0] + d.r * math.cos(a0 + half), d.c[1] + d.r * math.sin(a0 + half))
        verts = [{"p": [d.p[0], d.p[1]], "bulge": bulge_of(half)}, {"p": [mid[0], mid[1]], "bulge": bulge_of(half)}]
    return verts, sources


def loop_area(verts):
    s = 0.0
    n = len(verts)
    for i in range(n):
        a = verts[i]["p"]
        b = verts[(i + 1) % n]["p"]
        s += 0.5 * (a[0] * b[1] - b[0] * a[1])
        bg = verts[i].get("bulge", 0.0) or 0.0
        if bg:
            theta = 4.0 * math.atan(bg)
            chord = math.hypot(b[0] - a[0], b[1] - a[1])
            r = chord / (2.0 * abs(math.sin(theta / 2.0))) if abs(math.sin(theta / 2.0)) > 1e-300 else 0.0
            s += 0.5 * r * r * (theta - math.sin(theta))
    return s


def loop_perimeter(verts):
    s = 0.0
    n = len(verts)
    for i in range(n):
        a = verts[i]["p"]
        b = verts[(i + 1) % n]["p"]
        chord = math.hypot(b[0] - a[0], b[1] - a[1])
        bg = verts[i].get("bulge", 0.0) or 0.0
        if bg:
            theta = 4.0 * math.atan(bg)
            sn = abs(math.sin(theta / 2.0))
            s += chord / (2.0 * sn) * abs(theta) if sn > 1e-300 else chord
        else:
            s += chord
    return s


def reverse_loop(verts):
    n = len(verts)
    out = []
    for i in range(n):
        j = (n - i) % n
        prev = verts[(j - 1) % n]
        out.append({"p": list(verts[j]["p"]), "bulge": -(prev.get("bulge", 0.0) or 0.0)})
    return out


def flatten_loop(verts, step=0.05):
    pts = []
    n = len(verts)
    for i in range(n):
        a = verts[i]["p"]
        b = verts[(i + 1) % n]["p"]
        bg = verts[i].get("bulge", 0.0) or 0.0
        pts.append((a[0], a[1]))
        if bg:
            arc = geom.bulge_to_arc([a[0], a[1], 0.0], [b[0], b[1], 0.0], bg)
            if arc is None:
                continue
            center, r, a_start, a_end, ccw = arc
            theta = 4.0 * math.atan(bg)
            k = max(2, int(math.ceil(abs(theta) / step)))
            a0 = math.atan2(a[1] - center[1], a[0] - center[0])
            for m in range(1, k):
                ang = a0 + theta * m / k
                pts.append((center[0] + r * math.cos(ang), center[1] + r * math.sin(ang)))
    return pts
