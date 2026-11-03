import math

from app.part.registry import RefLost
from app.solid import ids as solid_ids

ACCEPT = 0.35
MARGIN = 1.5


def base_key(key: str) -> str:
    head, sep, tail = key.rpartition("#")
    return head if sep and tail.isdigit() else key


def creator(key: str) -> str:
    return key.split(":", 1)[0] if ":" in key else ""


def unique(keys, sigs=None):
    seen = {}
    for i, k in enumerate(keys):
        seen.setdefault(k, []).append(i)
    used = set(keys)
    for k, members in seen.items():
        if len(members) < 2:
            continue
        if sigs is not None:
            got = sigs(members)
            members = sorted(members, key=lambda i: (tuple(round(v, 5) for v in (got.get(i) or {}).get("c", (0, 0, 0))), i))
        n = 1
        for i in members[1:]:
            while "%s#%d" % (k, n) in used:
                n += 1
            keys[i] = "%s#%d" % (k, n)
            used.add(keys[i])
    return keys


def inherit(rows, old_keys, out):
    for old in sorted(rows, key=int):
        o = int(old)
        if o >= len(old_keys):
            continue
        for rank, new in enumerate(rows[old].get("to") or []):
            if 0 <= new < len(out) and out[new] is None:
                out[new] = old_keys[o] if rank == 0 else "%s#%d" % (old_keys[o], rank)


def name_result(fid, result, base_wid, base_faces, base_edges, adjacency, sig_fetch=None):
    nf = int(result["summary"]["faces"])
    ne = int(result["summary"]["edges"])
    fk = [None] * nf
    ek = [None] * ne
    for inp in (result.get("history") or {}).get("inputs") or []:
        if base_wid is None or inp.get("id") != base_wid:
            continue
        inherit(inp.get("faces") or {}, base_faces, fk)
        inherit(inp.get("edges") or {}, base_edges, ek)
    created = result.get("created") or {}
    for arr, tag in ((fk, "faces"), (ek, "edges")):
        roles = created.get(tag)
        if isinstance(roles, dict):
            for idx, role in roles.items():
                i = int(idx)
                if 0 <= i < len(arr) and arr[i] is None:
                    arr[i] = "%s:%s" % (fid, role)
    adj = adjacency or []
    neigh = [set() for _ in range(nf)]
    for faces in adj:
        for a in faces:
            for b in faces:
                if a != b and a < nf and b < nf:
                    neigh[a].add(b)
    for _round in range(3):
        todo = [i for i in range(nf) if fk[i] is None]
        if not todo:
            break
        for i in todo:
            ks = sorted({fk[g] for g in neigh[i] if fk[g] is not None})
            if ks:
                fk[i] = "%s:~%s" % (fid, "|".join(ks[:4]))
    for i in range(nf):
        if fk[i] is None:
            fk[i] = "%s:~i%d" % (fid, i)
    fk = unique(fk, (lambda idx: sig_fetch("faces", idx)) if sig_fetch else None)
    for i in range(ne):
        if ek[i] is None:
            faces = adj[i] if i < len(adj) else []
            ks = sorted({fk[g] for g in faces if g < nf})
            ek[i] = "e(%s)" % "|".join(ks[:3]) if ks else "%s:e~%d" % (fid, i)
    ek = unique(ek, (lambda idx: sig_fetch("edges", idx)) if sig_fetch else None)
    return fk, ek


def assign_pids(d, tree, keys, kind_tag):
    names = tree["names"]
    out = []
    lineage = {}
    for k in keys:
        pid = names.get(k)
        if pid is None:
            pid = solid_ids.next_pid(d)
            names[k] = pid
        out.append(pid)
        b = base_key(k)
        if b != k and b in names:
            lineage[str(pid)] = names[b]
    return out, lineage


def distance(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def score(sig, cand, diag):
    if sig.get("k") != cand.get("k"):
        return None
    if sig.get("n") is not None and cand.get("n") is not None:
        dot = sum(x * y for x, y in zip(sig["n"], cand["n"]))
        if dot < 0.999:
            return None
    if sig.get("r") is not None and cand.get("r") is not None and abs(sig["r"] - cand["r"]) > 0.5 * max(abs(sig["r"]), 1e-9):
        return None
    dist = distance(sig.get("c", (0, 0, 0)), cand.get("c", (0, 0, 0))) / max(diag, 1e-9)
    ar = 0.0
    if sig.get("a") is not None and cand.get("a") is not None:
        ar = abs(sig["a"] - cand["a"]) / max(sig["a"], cand["a"], 1e-9)
    elif sig.get("l") is not None and cand.get("l") is not None:
        ar = abs(sig["l"] - cand["l"]) / max(sig["l"], cand["l"], 1e-9)
    return dist + 0.5 * ar


def match_signature(sig, cands, diag, taken=()):
    rows = []
    for idx, cand in cands.items():
        if int(idx) in taken:
            continue
        s = score(sig, cand, diag)
        if s is not None:
            rows.append((s, int(idx)))
    rows.sort()
    if not rows or rows[0][0] > ACCEPT:
        return None
    if len(rows) > 1 and rows[1][0] <= rows[0][0] * MARGIN + 0.02:
        return None
    return rows[0][1]


def lost(slot, ref, what="reference"):
    key = ref.get("key") or ""
    article = "An" if what[:1].lower() in "aeiou" else "A"
    return RefLost("%s %s in %s no longer exists (%s) and no matching shape was found." % (article, what, slot, key or "unnamed"), slot, key)
