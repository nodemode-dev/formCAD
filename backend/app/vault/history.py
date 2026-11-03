from app.vault import entities
from app.vault.base import MAX_LOG, VaultError, unhex


def doc_row(c, doc: str):
    row = c.execute("SELECT * FROM doc WHERE id=?", (doc,)).fetchone()
    if row is None:
        raise VaultError("There is no document %s in this vault." % doc, 404)
    return row


def version_row(c, text, doc: str = ""):
    s = str(text or "").strip().lower()
    if not s:
        raise VaultError("Give a version.")
    if len(s) == 64:
        row = c.execute("SELECT * FROM version WHERE hash=?", (unhex(s, "version"),)).fetchone()
    elif 6 <= len(s) < 64 and all(ch in "0123456789abcdef" for ch in s):
        rows = c.execute("SELECT * FROM version WHERE hex(hash) LIKE ? LIMIT 3", (s.upper() + "%",)).fetchall()
        if len(rows) > 1:
            raise VaultError("The version prefix %s is ambiguous." % s)
        row = rows[0] if rows else None
    else:
        row = None
    if row is None:
        raise VaultError("There is no version %s." % s[:12], 404)
    if doc and row["doc"] != doc:
        raise VaultError("Version %s belongs to another document." % s[:12], 404)
    return row


def head_of(c, doc: str, branch: str):
    row = c.execute("SELECT version FROM ref WHERE doc=? AND name=?", (doc, "heads/" + branch)).fetchone()
    return bytes(row[0]) if row else None


def resolve_ref(c, doc: str, text: str) -> bytes:
    s = str(text or "").strip()
    if not s:
        raise VaultError("Give a branch, tag or version.")
    for prefix in ("heads/", "tags/", "rev/", ""):
        row = c.execute("SELECT version FROM ref WHERE doc=? AND name=?", (doc, prefix + s)).fetchone()
        if row:
            return bytes(row[0])
    return bytes(version_row(c, s, doc)["hash"])


def state_of(c, h: bytes) -> tuple:
    row = c.execute("SELECT state, revision FROM lifecycle WHERE version=?", (h,)).fetchone()
    return (row["state"], row["revision"]) if row else ("wip", "")


def ref_map(c, doc: str) -> dict:
    out: dict = {}
    for r in c.execute("SELECT name, version FROM ref WHERE doc=?", (doc,)).fetchall():
        out.setdefault(bytes(r["version"]), []).append(r["name"])
    return out


def vrec(c, row, refs: dict | None = None) -> dict:
    h = bytes(row["hash"])
    state, rev = state_of(c, h)
    names = (refs if refs is not None else ref_map(c, row["doc"])).get(h, [])
    parents = [bytes(p[0]).hex() for p in c.execute("SELECT parent FROM parent WHERE version=? ORDER BY ord", (h,)).fetchall()]
    return {
        "id": h.hex(), "short": h.hex()[:12], "doc": row["doc"], "parents": parents, "author": row["author"], "ts": row["ts"], "message": row["message"],
        "size": row["size"], "members": row["members"], "identical": row["raw"] is None, "container": bytes(row["container"]).hex(), "sha256": row["sha256"],
        "state": state, "revision": rev, "branches": sorted(n[6:] for n in names if n.startswith("heads/")), "tags": sorted(n.split("/", 1)[1] for n in names if n.startswith(("tags/", "rev/"))),
    }


def ancestors(c, h: bytes) -> set:
    rows = c.execute("WITH RECURSIVE anc(v) AS (SELECT ? UNION SELECT parent.parent FROM parent JOIN anc ON parent.version=anc.v) SELECT v FROM anc", (h,)).fetchall()
    return {bytes(r[0]) for r in rows}


def is_ancestor(c, maybe: bytes, of: bytes) -> bool:
    return maybe in ancestors(c, of)


def lca(c, a: bytes, b: bytes) -> tuple:
    common = ancestors(c, a) & ancestors(c, b)
    if not common:
        return None, False
    inner = set()
    for v in common:
        for p in c.execute("SELECT parent FROM parent WHERE version=?", (v,)).fetchall():
            if bytes(p[0]) in common:
                inner.add(bytes(p[0]))
    best = common - inner
    if len(best) == 1:
        return next(iter(best)), False
    ranked = sorted(best, key=lambda x: c.execute("SELECT ts, rowid FROM version WHERE hash=?", (x,)).fetchone()[:2], reverse=True)
    return ranked[0], True


def log(c, doc: str, start: bytes | None, limit: int) -> list:
    limit = max(1, min(int(limit or 200), MAX_LOG))
    refs = ref_map(c, doc)
    if start is None:
        rows = c.execute("SELECT * FROM version WHERE doc=? ORDER BY ts DESC, rowid DESC LIMIT ?", (doc, limit)).fetchall()
    else:
        rows = c.execute("WITH RECURSIVE anc(v) AS (SELECT ? UNION SELECT parent.parent FROM parent JOIN anc ON parent.version=anc.v) SELECT version.* FROM version JOIN anc ON version.hash=anc.v ORDER BY version.ts DESC, version.rowid DESC LIMIT ?", (start, limit)).fetchall()
    return [vrec(c, r, refs) for r in rows]


def graph(c, doc: str, limit: int) -> dict:
    limit = max(1, min(int(limit or 300), MAX_LOG))
    refs = ref_map(c, doc)
    total = c.execute("SELECT COUNT(*) FROM version WHERE doc=?", (doc,)).fetchone()[0]
    rows = c.execute("SELECT * FROM version WHERE doc=? ORDER BY ts DESC, rowid DESC LIMIT ?", (doc, limit)).fetchall()
    nodes = [vrec(c, r, refs) for r in rows]
    present = {n["id"] for n in nodes}
    order = {n["id"]: i for i, n in enumerate(nodes)}
    by_id = {n["id"]: n for n in nodes}
    children: dict = {}
    for n in nodes:
        for p in n["parents"]:
            children.setdefault(p, []).append(n["id"])
    indeg = {n["id"]: len([k for k in children.get(n["id"], []) if k in present]) for n in nodes}
    ready = sorted([i for i, d in indeg.items() if d == 0], key=lambda i: order[i])
    topo = []
    while ready:
        i = ready.pop(0)
        topo.append(by_id[i])
        for p in by_id[i]["parents"]:
            if p in indeg:
                indeg[p] -= 1
                if indeg[p] == 0:
                    ready.append(p)
        ready.sort(key=lambda x: order[x])
    lanes: list = []
    for n in topo:
        if n["id"] in lanes:
            lane = lanes.index(n["id"])
        elif None in lanes:
            lane = lanes.index(None)
            lanes[lane] = n["id"]
        else:
            lanes.append(n["id"])
            lane = len(lanes) - 1
        n["lane"] = lane
        ps = [p for p in n["parents"] if p in present]
        lanes[lane] = None
        for k, p in enumerate(ps):
            if p in lanes:
                continue
            if k == 0:
                lanes[lane] = p
            elif None in lanes:
                lanes[lanes.index(None)] = p
            else:
                lanes.append(p)
    heads = [{"name": r["name"][6:], "version": bytes(r["version"]).hex()} for r in c.execute("SELECT name, version FROM ref WHERE doc=? AND name LIKE 'heads/%' ORDER BY name", (doc,)).fetchall()]
    return {"nodes": topo, "heads": heads, "truncated": total > limit, "total": total, "lanes": max([n["lane"] for n in topo] + [0]) + 1}


def doc_json(vault, c, root: bytes) -> bytes:
    for name, mode, child in vault.tree(c, root):
        if name == "document.json":
            return vault.get_member(c, mode, child)
    raise VaultError("The version has no document.json.", 500)


def emap(vault, c, h: bytes) -> entities.EMap:
    row = c.execute("SELECT root FROM version WHERE hash=?", (h,)).fetchone()
    if row is None:
        raise VaultError("There is no such version.", 404)
    root = bytes(row[0])
    ent = next((child for name, _m, child in vault.tree(c, root) if name == "document.json"), None)
    if ent is None:
        raise VaultError("The version has no document.json.", 500)
    return entities.cached(ent, lambda: doc_json(vault, c, root))


def tree_dict(vault, c, root: bytes) -> dict:
    return {name: (mode, child) for name, mode, child in vault.tree(c, root)}
