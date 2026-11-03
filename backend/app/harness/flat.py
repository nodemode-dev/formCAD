import heapq
import math

from app.harness.store import HarnessError

ANGLES = [90, -90, 60, -60, 120, -120, 45, -45, 135, -135, 30, -30, 150, -150, 75, -75, 105, -105, 15, -15, 165, -165, 0, 180]


def seg_dist(p, q, r, s) -> float:
    def pt(a, b, c):
        ab = (b[0] - a[0], b[1] - a[1])
        L = ab[0] ** 2 + ab[1] ** 2
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((c[0] - a[0]) * ab[0] + (c[1] - a[1]) * ab[1]) / L))
        return math.hypot(c[0] - a[0] - t * ab[0], c[1] - a[1] - t * ab[1])

    def cross(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    if cross(p, q, r) * cross(p, q, s) < 0 and cross(r, s, p) * cross(r, s, q) < 0:
        return 0.0
    return min(pt(p, q, r), pt(p, q, s), pt(r, s, p), pt(r, s, q))


def components(nodes_used, edges):
    adj = {n: [] for n in nodes_used}
    for sid, a, b, L in edges:
        adj[a].append(b)
        adj[b].append(a)
    seen, out = set(), []
    for n in nodes_used:
        if n in seen:
            continue
        comp, stack = [], [n]
        seen.add(n)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        out.append(comp)
    return out


def dijkstra(adj, sources):
    dist = {s: 0.0 for s in sources}
    prev = {}
    heap = [(0.0, s) for s in sources]
    heapq.heapify(heap)
    while heap:
        dd, u = heapq.heappop(heap)
        if dd > dist.get(u, math.inf):
            continue
        for v, sid, L in adj[u]:
            nd = dd + L
            if nd < dist.get(v, math.inf) - 1e-12:
                dist[v] = nd
                prev[v] = (u, sid)
                heapq.heappush(heap, (nd, v))
    return dist, prev


def layout(h, report, trunk=None, angle=None, clearance=None) -> dict:
    st = h["settings"]
    angle = float(angle if angle is not None else st["branch_angle"])
    clearance = float(clearance if clearance is not None else st["clearance"])
    length = {s["id"]: s["length"] for s in report["segments"]}
    edges = [(s["id"], s["a"], s["b"], length[s["id"]]) for s in report["segments"]]
    if not edges:
        raise HarnessError("There are no segments to flatten.")
    used = []
    for _sid, a, b, _L in edges:
        for n in (a, b):
            if n not in used:
                used.append(n)
    adj = {n: [] for n in used}
    for sid, a, b, L in edges:
        adj[a].append((b, sid, L))
        adj[b].append((a, sid, L))
    by_id = {sid: (a, b, L) for sid, a, b, L in edges}
    comps = components(used, edges)
    pos, tree_edges, cut, placed, parent = {}, set(), [], [], {}
    trunk_all = []
    y0 = 0.0
    for comp in comps:
        cset = set(comp)
        if trunk and len(comps) == 1:
            order = [str(t) for t in trunk]
            for t in order:
                if t not in by_id:
                    raise HarnessError("There is no segment %s to use as the trunk." % t)
            chain = order
            start = None
            a0, b0, _ = by_id[chain[0]]
            if len(chain) == 1:
                start = a0
            else:
                a1, b1, _ = by_id[chain[1]]
                start = b0 if a0 in (a1, b1) else a0
            nodes_seq, cur = [start], start
            for t in chain:
                a, b, _L = by_id[t]
                if cur not in (a, b):
                    raise HarnessError("The trunk segments are not connected in order at %s." % t)
                cur = b if cur == a else a
                nodes_seq.append(cur)
        else:
            d0, _ = dijkstra(adj, [comp[0]])
            far = max(comp, key=lambda n: (d0[n], n))
            d1, prev = dijkstra(adj, [far])
            end = max(comp, key=lambda n: (d1[n], n))
            nodes_seq, chain, cur = [end], [], end
            while cur != far:
                u, sid = prev[cur]
                chain.append(sid)
                nodes_seq.append(u)
                cur = u
            chain = chain[::-1]
            nodes_seq = nodes_seq[::-1]
            if nodes_seq[0] > nodes_seq[-1]:
                chain = chain[::-1]
                nodes_seq = nodes_seq[::-1]
        trunk_all += chain
        x = 0.0
        segs_drawn = []
        pos[nodes_seq[0]] = [0.0, y0]
        for k, sid in enumerate(chain):
            x += by_id[sid][2]
            pos[nodes_seq[k + 1]] = [x, y0]
            segs_drawn.append((sid, nodes_seq[k], nodes_seq[k + 1]))
            parent[nodes_seq[k + 1]] = nodes_seq[k]
            tree_edges.add(sid)
        dist, prev = dijkstra(adj, nodes_seq)
        kids = {}
        for n, (u, sid) in prev.items():
            kids.setdefault(u, []).append((n, sid))
            tree_edges.add(sid)
        placed_here = list(segs_drawn)
        direction = {}
        for k, sid in enumerate(chain):
            direction[nodes_seq[k + 1]] = (1.0, 0.0)
        direction[nodes_seq[0]] = (1.0, 0.0)
        queue = list(nodes_seq)
        flip = {}
        qi = 0
        while qi < len(queue):
            u = queue[qi]
            qi += 1
            for n, sid in sorted(kids.get(u, []), key=lambda t: t[1]):
                if n in pos:
                    continue
                L = by_id[sid][2]
                base = direction[u]
                side = flip.get(u, 1)
                flip[u] = -side
                cands = [angle * side] + [a for a in ANGLES if a != angle * side]
                best, best_bad = None, None
                for a in cands:
                    th = math.radians(a)
                    dx = base[0] * math.cos(th) - base[1] * math.sin(th)
                    dy = base[0] * math.sin(th) + base[1] * math.cos(th)
                    q = [pos[u][0] + dx * L, pos[u][1] + dy * L]
                    worst = math.inf
                    for s2, a2, b2 in placed + placed_here:
                        if u in (a2, b2):
                            continue
                        worst = min(worst, seg_dist(pos[u], q, pos[a2], pos[b2]))
                    if worst >= clearance:
                        best, best_bad = (dx, dy, q), None
                        break
                    if best_bad is None or worst > best_bad[0]:
                        best_bad = (worst, (dx, dy, q))
                if best is None:
                    best = best_bad[1]
                dx, dy, q = best
                pos[n] = q
                parent[n] = u
                direction[n] = (dx, dy)
                placed_here.append((sid, u, n))
                queue.append(n)
        placed += placed_here
        miny = min(pos[n][1] for n in comp)
        maxy = max(pos[n][1] for n in comp)
        shift = (y0 - miny) if miny < y0 else 0.0
        if shift:
            for n in comp:
                pos[n][1] += shift
        y0 = (maxy + shift) + 120.0
    for sid, a, b, L in edges:
        if sid not in tree_edges:
            cut.append(sid)
    overlaps = []
    drawn = [(sid, a, b) for sid, a, b, _L in edges if sid in tree_edges]
    for i in range(len(drawn)):
        for j in range(i + 1, len(drawn)):
            s1, a1, b1 = drawn[i]
            s2, a2, b2 = drawn[j]
            if {a1, b1} & {a2, b2}:
                continue
            if seg_dist(pos[a1], pos[b1], pos[a2], pos[b2]) < clearance * 0.5:
                overlaps.append([s1, s2])
    return {"nodes": {n: [round(p[0], 4), round(p[1], 4)] for n, p in pos.items()}, "parent": parent, "trunk": trunk_all, "cut": cut, "overlaps": overlaps, "angle": angle, "clearance": clearance, "scale": 1.0}


def rotate_branch(flat, node, to):
    parent = flat.get("parent", {})
    up = parent.get(node)
    if up is None:
        raise HarnessError("Node %s has no parent on the formboard; only branch nodes can be turned." % node)
    pos = flat["nodes"]
    a0 = math.atan2(pos[node][1] - pos[up][1], pos[node][0] - pos[up][0])
    a1 = math.atan2(float(to[1]) - pos[up][1], float(to[0]) - pos[up][0])
    da = a1 - a0
    members, stack = {node}, [node]
    while stack:
        u = stack.pop()
        for n, p in parent.items():
            if p == u and n not in members:
                members.add(n)
                stack.append(n)
    c, s = math.cos(da), math.sin(da)
    for n in members:
        x, y = pos[n][0] - pos[up][0], pos[n][1] - pos[up][1]
        pos[n] = [round(pos[up][0] + x * c - y * s, 4), round(pos[up][1] + x * s + y * c, 4)]
    return sorted(members)
