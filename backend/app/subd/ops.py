import numpy as np

from app.subd.cage import Cage, check_caps, edge_key
from app.subd.cc import INF, SubdError


def face_edges(face):
    n = len(face)
    return [(face[i], face[(i + 1) % n]) for i in range(n)]


def rotate_to(face, vertex):
    c = face.index(vertex)
    return face[c:] + face[:c]


def check_edge_exists(cage, edges):
    have = set(cage.edge_list())
    out = []
    for e in edges:
        k = edge_key(e[0], e[1])
        if k not in have:
            raise SubdError("Edge %d,%d does not exist." % k)
        out.append(k)
    return out


def edges_of_faces(cage, faces):
    inside = set(int(f) for f in faces)
    for f in inside:
        if not 0 <= f < len(cage.f):
            raise SubdError("Face %d does not exist." % f)
    count = {}
    for fi, face in enumerate(cage.f):
        for a, b in face_edges(face):
            count.setdefault(edge_key(a, b), []).append(fi)
    border = []
    for k, owners in count.items():
        ins = [o for o in owners if o in inside]
        if ins and (len(ins) < len(owners) or len(owners) == 1):
            border.append(k)
    return sorted(border)


def ring_of_edge(cage, owners, edge):
    ring = {edge}
    for start in owners.get(edge, []):
        f = start
        while True:
            face = cage.f[f]
            if len(face) != 4:
                break
            n = 4
            opp = None
            for i in range(n):
                if edge_key(face[i], face[(i + 1) % n]) in ring:
                    opp = edge_key(face[(i + 2) % n], face[(i + 3) % n])
                    break
            if opp is None or opp in ring:
                break
            ring.add(opp)
            nxt = [g for g in owners.get(opp, []) if g != f]
            if not nxt:
                break
            f = nxt[0]
    return ring


def insert_edge(cage: Cage, edges, cuts=1, position=0.5, agent=False):
    cuts = int(cuts)
    if cuts < 1 or cuts > 16:
        raise SubdError("Cuts must be 1 to 16.")
    position = float(position)
    if not 0.0 < position < 1.0:
        raise SubdError("The position must be between 0 and 1.")
    seeds = check_edge_exists(cage, edges)
    if not seeds:
        raise SubdError("Select at least one edge.")
    ek, owners_l = cage.edge_faces()
    owners = {k: owners_l[i] for i, k in enumerate(ek)}
    target = set()
    for s in seeds:
        target |= ring_of_edge(cage, owners, s)
    new_vert = {}
    verts = [p.copy() for p in cage.v]
    fracs = [position] if cuts == 1 else [(i + 1) / (cuts + 1) for i in range(cuts)]
    for (a, b) in sorted(target):
        ids = []
        for t in fracs:
            verts.append(cage.v[a] * (1 - t) + cage.v[b] * t)
            ids.append(len(verts) - 1)
        new_vert[(a, b)] = ids

    def chain(a, b):
        ids = new_vert[edge_key(a, b)]
        return ids if a < b else list(reversed(ids))

    faces = []
    for face in cage.f:
        n = len(face)
        marked = [edge_key(face[i], face[(i + 1) % n]) in target for i in range(n)]
        if n == 4 and marked[0] and marked[2] and not marked[1] and not marked[3]:
            faces.extend(split_strip(face, chain))
        elif n == 4 and marked[1] and marked[3] and not marked[0] and not marked[2]:
            faces.extend(split_strip(face[1:] + face[:1], chain))
        elif n == 4 and all(marked):
            faces.extend(split_grid(face, chain, verts, cuts))
        elif any(marked):
            poly = []
            for i in range(n):
                poly.append(face[i])
                if marked[i]:
                    poly.extend(chain(face[i], face[(i + 1) % n]))
            faces.append(poly)
        else:
            faces.append(list(face))
    crease = {}
    for (a, b), w in cage.crease.items():
        if (a, b) in new_vert:
            ids = [a] + new_vert[(a, b)] + [b]
            for i in range(len(ids) - 1):
                crease[edge_key(ids[i], ids[i + 1])] = w
        else:
            crease[(a, b)] = w
    check_caps(len(verts), len(faces), agent)
    return Cage(verts, faces, crease), {"new_vertices": len(verts) - len(cage.v), "ring_edges": len(target)}


def split_strip(face, chain):
    a, b, c, d = face
    rowa = [a] + chain(a, b) + [b]
    rowb = [d] + chain(d, c) + [c]
    return [[rowa[i], rowa[i + 1], rowb[i + 1], rowb[i]] for i in range(len(rowa) - 1)]


def split_grid(face, chain, verts, cuts):
    a, b, c, d = face
    bottom = [a] + chain(a, b) + [b]
    top = [d] + chain(d, c) + [c]
    left = [a] + chain(a, d) + [d]
    right = [b] + chain(b, c) + [c]
    m = cuts + 2
    grid = [[None] * m for _ in range(m)]
    for i in range(m):
        grid[i][0] = bottom[i]
        grid[i][m - 1] = top[i]
        grid[0][i] = left[i]
        grid[m - 1][i] = right[i]
    pa, pb, pc, pd = (np.asarray(verts[x]) for x in (a, b, c, d))
    for i in range(1, m - 1):
        for j in range(1, m - 1):
            u, v = i / (m - 1), j / (m - 1)
            verts.append((1 - u) * (1 - v) * pa + u * (1 - v) * pb + u * v * pc + (1 - u) * v * pd)
            grid[i][j] = len(verts) - 1
    return [[grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]] for i in range(m - 1) for j in range(m - 1)]


def subdivide_faces(cage: Cage, faces, agent=False):
    todo = sorted(set(int(f) for f in faces))
    if not todo:
        raise SubdError("Select at least one face.")
    for f in todo:
        if not 0 <= f < len(cage.f):
            raise SubdError("Face %d does not exist." % f)
    verts = [p.copy() for p in cage.v]
    mid = {}

    def midpoint(a, b):
        k = edge_key(a, b)
        if k not in mid:
            verts.append((cage.v[a] + cage.v[b]) * 0.5)
            mid[k] = len(verts) - 1
        return mid[k]

    selected = set(todo)
    for f in todo:
        for a, b in face_edges(cage.f[f]):
            midpoint(a, b)
    out = []
    for fi, face in enumerate(cage.f):
        n = len(face)
        if fi in selected:
            verts.append(cage.v[face].mean(axis=0))
            c = len(verts) - 1
            for i in range(n):
                out.append([face[i], midpoint(face[i], face[(i + 1) % n]), c, midpoint(face[i - 1], face[i])])
        else:
            poly = []
            for a, b in face_edges(face):
                poly.append(a)
                k = edge_key(a, b)
                if k in mid:
                    poly.append(mid[k])
            out.append(poly)
    crease = {}
    for (a, b), w in cage.crease.items():
        if (a, b) in mid:
            crease[edge_key(a, mid[(a, b)])] = w
            crease[edge_key(mid[(a, b)], b)] = w
        else:
            crease[(a, b)] = w
    check_caps(len(verts), len(out), agent)
    return Cage(verts, out, crease), {"faces_split": len(todo)}


def delete(cage: Cage, vertices=None, edges=None, faces=None, compact=True):
    kill = set()
    for f in faces or []:
        f = int(f)
        if not 0 <= f < len(cage.f):
            raise SubdError("Face %d does not exist." % f)
        kill.add(f)
    vs = set(int(v) for v in (vertices or []))
    for v in vs:
        if not 0 <= v < len(cage.v):
            raise SubdError("Vertex %d does not exist." % v)
    for fi, face in enumerate(cage.f):
        if vs & set(face):
            kill.add(fi)
    work = [list(f) for f in cage.f]
    alive = [True] * len(work)
    merged = 0
    for e in check_edge_exists(cage, edges or []):
        owners = [i for i, f in enumerate(work) if alive[i] and any(edge_key(a, b) == e for a, b in face_edges(f))]
        if len(owners) == 1:
            kill.add(owners[0])
        elif len(owners) == 2:
            f1, f2 = work[owners[0]], work[owners[1]]
            d1 = [(x, y) for x, y in face_edges(f1) if edge_key(x, y) == e][0]
            d2 = [(x, y) for x, y in face_edges(f2) if edge_key(x, y) == e][0]
            if d1[0] != d2[1]:
                raise SubdError("The faces beside edge %d,%d face opposite ways." % e)
            work[owners[0]] = rotate_to(f1, d1[1]) + rotate_to(f2, d1[0])[1:-1]
            alive[owners[1]] = False
            merged += 1
    keep = [f for i, f in enumerate(work) if alive[i] and i not in kill]
    out = Cage(cage.v, keep, cage.crease)
    if compact:
        out.compact()
    out.drop_orphan_creases()
    return out, {"faces_removed": len(cage.f) - len(keep), "faces_merged": merged}


def crease_targets(cage: Cage, vertices=None, edges=None, faces=None):
    out = set()
    if edges:
        out |= set(check_edge_exists(cage, edges))
    if faces:
        out |= set(edges_of_faces(cage, faces))
    if vertices:
        vs = set(int(v) for v in vertices)
        for v in vs:
            if not 0 <= v < len(cage.v):
                raise SubdError("Vertex %d does not exist." % v)
        for a, b in cage.edge_list():
            if (a in vs and b in vs) or (len(vs) == 1 and (a in vs or b in vs)):
                out.add((a, b))
    if not out:
        raise SubdError("Select edges, faces or vertices.")
    return sorted(out)


def set_crease(cage: Cage, targets, weight):
    w = float(weight)
    if not 0.0 < w <= INF:
        raise SubdError("The crease weight must be above 0 and at most 10.")
    out = cage.copy()
    for k in targets:
        out.crease[k] = w
    return out, {"edges": len(targets)}


def remove_crease(cage: Cage, targets=None, amount=None):
    out = cage.copy()
    keys = list(out.crease) if targets is None else [k for k in targets if k in out.crease]
    for k in keys:
        if amount is None or out.crease[k] - float(amount) <= 1e-12:
            out.crease.pop(k, None)
        else:
            out.crease[k] = out.crease[k] - float(amount)
    return out, {"edges": len(keys)}


def boundary_loops(cage: Cage):
    owners = {}
    for fi, face in enumerate(cage.f):
        for a, b in face_edges(face):
            owners.setdefault(edge_key(a, b), []).append((a, b))
    nxt = {}
    for o in owners.values():
        if len(o) == 1:
            a, b = o[0]
            if a in nxt:
                raise SubdError("A boundary vertex is shared by two open loops.")
            nxt[a] = b
    loops, seen = [], set()
    for start in sorted(nxt):
        if start in seen:
            continue
        loop, cur = [], start
        while cur is not None and cur not in seen:
            seen.add(cur)
            loop.append(cur)
            cur = nxt.get(cur)
        if cur != start:
            raise SubdError("An open boundary is not a closed loop.")
        loops.append(loop)
    return loops


def loop_containing(loops, edge):
    a, b = edge
    for lp in loops:
        n = len(lp)
        for i in range(n):
            if {lp[i], lp[(i + 1) % n]} == {a, b}:
                return lp
    raise SubdError("Edge %d,%d is not on an open boundary." % (a, b))


def bridge(cage: Cage, edges_a=None, edges_b=None, faces_a=None, faces_b=None, twist=None, spans=1, agent=False):
    spans = int(spans)
    if spans < 1 or spans > 16:
        raise SubdError("Spans must be 1 to 16.")
    work = cage
    if faces_a or faces_b:
        if not faces_a or not faces_b:
            raise SubdError("Give two groups of faces to bridge.")
        ga = set(int(f) for f in faces_a)
        gb = set(int(f) for f in faces_b)
        if ga & gb:
            raise SubdError("The two groups share faces.")
        for f in ga | gb:
            if not 0 <= f < len(cage.f):
                raise SubdError("Face %d does not exist." % f)
        va = set(v for f in ga for v in cage.f[f])
        vb = set(v for f in gb for v in cage.f[f])
        work, _ = delete(cage, faces=sorted(ga | gb), compact=False)
        la = lb = None
        for lp in boundary_loops(work):
            s = set(lp)
            if s <= va and la is None:
                la = lp
            elif s <= vb and lb is None:
                lb = lp
        if la is None or lb is None:
            raise SubdError("The two face groups do not leave two separate open loops.")
    else:
        if not edges_a or not edges_b:
            raise SubdError("Give two sets of edges on open boundaries.")
        loops = boundary_loops(cage)
        la = loop_containing(loops, tuple(edges_a[0]))
        lb = loop_containing(loops, tuple(edges_b[0]))
        if la is lb:
            raise SubdError("Both edge sets are on the same open loop.")
    if len(la) != len(lb):
        raise SubdError("The two loops have %d and %d edges; a bridge needs equal counts." % (len(la), len(lb)))
    n = len(la)
    P = work.v
    if twist is None:
        costs = [sum(float(np.linalg.norm(P[la[i]] - P[lb[(t - i + 1) % n]])) for i in range(n)) for t in range(n)]
        twist = int(np.argmin(costs))
    t = int(twist) % n
    verts = [p.copy() for p in P]
    rows = [list(la)]
    for s in range(1, spans):
        row = []
        for i in range(n):
            f = s / spans
            verts.append(P[la[i]] * (1 - f) + P[lb[(t - i + 1) % n]] * f)
            row.append(len(verts) - 1)
        rows.append(row)
    rows.append([lb[(t - i + 1) % n] for i in range(n)])
    faces = [list(f) for f in work.f]
    for s in range(spans):
        top, bot = rows[s], rows[s + 1]
        for i in range(n):
            j = (i + 1) % n
            faces.append([top[j], top[i], bot[i], bot[j]])
    check_caps(len(verts), len(faces), agent)
    out = Cage(verts, faces, work.crease)
    out.compact()
    out.drop_orphan_creases()
    return out, {"faces_added": spans * n, "twist": t, "loop_edges": n}


def fill_hole(cage: Cage, edge=None, style="quads", agent=False):
    if style not in ("ngon", "quads", "star"):
        raise SubdError("The fill style must be ngon, quads or star.")
    loops = boundary_loops(cage)
    if not loops:
        raise SubdError("The cage has no open boundary to fill.")
    chosen = [loop_containing(loops, tuple(edge))] if edge is not None else loops
    verts = [p.copy() for p in cage.v]
    faces = [list(f) for f in cage.f]
    added = 0
    for lp in chosen:
        r = list(reversed(lp))
        n = len(r)
        if n < 3:
            raise SubdError("An open loop has only %d vertices." % n)
        if style == "ngon":
            faces.append(r)
            added += 1
            continue
        verts.append(np.mean([verts[v] for v in lp], axis=0))
        c = len(verts) - 1
        if style == "star":
            for i in range(n):
                faces.append([r[i], r[(i + 1) % n], c])
                added += 1
            continue
        pairs = (n - 3) // 2 if n % 2 else n // 2
        for i in range(pairs):
            faces.append([r[2 * i], r[2 * i + 1], r[(2 * i + 2) % n], c])
            added += 1
        if n % 2:
            faces.append([r[n - 3], r[n - 2], r[n - 1], c])
            faces.append([r[n - 1], r[0], c])
            added += 2
    check_caps(len(verts), len(faces), agent)
    return Cage(verts, faces, cage.crease), {"holes_filled": len(chosen), "faces_added": added}
