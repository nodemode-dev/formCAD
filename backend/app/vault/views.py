from app.vault import commit, entities, history
from app.vault.base import MAX_DOCS, VaultError
from app.vault.store import Vault


def doc_record(c, r) -> dict:
    doc = r["id"]
    heads, tags = [], []
    for ref in c.execute("SELECT name, version, ts FROM ref WHERE doc=? ORDER BY name", (doc,)).fetchall():
        h = bytes(ref["version"])
        state, rev = history.state_of(c, h)
        rec = {"name": ref["name"].split("/", 1)[1], "head": h.hex(), "state": state, "ts": ref["ts"], "revision": rev}
        (heads if ref["name"].startswith("heads/") else tags).append(rec)
    default = next((b for b in heads if b["name"] == r["default_branch"]), None)
    paths = [x["path"] for x in c.execute("SELECT path FROM binding WHERE doc=? ORDER BY ts DESC", (doc,)).fetchall()]
    count = c.execute("SELECT COUNT(*), MAX(ts) FROM version WHERE doc=?", (doc,)).fetchone()
    merging = c.execute("SELECT 1 FROM merge WHERE doc=?", (doc,)).fetchone() is not None
    return {"id": doc, "name": r["name"], "kind": r["kind"], "created": r["created"], "default_branch": r["default_branch"], "branches": heads, "tags": tags, "head": default["head"] if default else "", "head_state": default["state"] if default else "", "head_revision": default["revision"] if default else "", "lock": commit.lock_rec(commit.lock_row(c, doc)), "paths": paths, "versions": count[0], "latest_ts": count[1] or 0, "merging": merging}


def docs(v: Vault, query: str = "") -> list:
    with v.read() as c:
        rows = c.execute("SELECT * FROM doc ORDER BY name LIMIT ?", (MAX_DOCS,)).fetchall()
        q = query.strip().lower()
        return [doc_record(c, r) for r in rows if not q or q in r["name"].lower() or q in r["id"].lower()]


def doc(v: Vault, doc_id: str) -> dict:
    with v.read() as c:
        return doc_record(c, history.doc_row(c, doc_id))


def version(v: Vault, h: str) -> dict:
    with v.read() as c:
        row = history.version_row(c, h)
        rec = history.vrec(c, row)
        rec["children"] = [x for x in _children(c, bytes(row["hash"]))]
        return rec


def _children(c, h: bytes) -> list:
    from app.vault import xrefs

    return xrefs.children(c, h)


def entity_list(v: Vault, h: str, kind: str = "", limit: int = 500) -> dict:
    limit = max(1, min(int(limit or 500), 5000))
    with v.read() as c:
        row = history.version_row(c, h)
        m = history.emap(v, c, bytes(row["hash"]))
        out = []
        total = 0
        for eid in m.items:
            k = entities.kind_of(eid)
            if kind and k != kind:
                continue
            total += 1
            if len(out) < limit:
                out.append({"id": eid, "kind": k, "name": entities.display(m, eid)})
        return {"version": bytes(row["hash"]).hex(), "entities": out, "total": total, "truncated": total > limit}


def diff(v: Vault, a: str, b: str, limit: int = 500) -> dict:
    limit = max(1, min(int(limit or 500), 5000))
    with v.read() as c:
        ra, rb = history.version_row(c, a), history.version_row(c, b)
        if ra["doc"] != rb["doc"]:
            raise VaultError("The two versions belong to different documents.")
        out = entities.diff(history.emap(v, c, bytes(ra["hash"])), history.emap(v, c, bytes(rb["hash"])), limit)
        out["a"] = bytes(ra["hash"]).hex()
        out["b"] = bytes(rb["hash"]).hex()
        return out
