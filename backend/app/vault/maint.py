import json
import os

from app.vault import commit, history
from app.vault.base import MAX_LOG, VaultError, now
from app.vault.store import Vault


def verify(v: Vault, doc: str = "", version: str = "", deep: bool = False, limit: int = 2000) -> dict:
    limit = max(1, min(int(limit or 2000), MAX_LOG))
    results = []
    with v.read() as c:
        if version:
            rows = [history.version_row(c, version, doc)]
        elif doc:
            history.doc_row(c, doc)
            rows = c.execute("SELECT * FROM version WHERE doc=? ORDER BY ts LIMIT ?", (doc, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM version ORDER BY ts LIMIT ?", (limit,)).fetchall()
        for r in rows:
            h = bytes(r["hash"])
            rec = {"version": h.hex(), "short": h.hex()[:12], "doc": r["doc"], "ok": False, "identical": False, "problem": ""}
            try:
                data, same = commit.container_of(v, c, h)
                rec["ok"] = True
                rec["identical"] = same
                if not same:
                    rec["problem"] = "The rebuilt file differs from what was checked in."
                    rec["ok"] = False
            except VaultError as err:
                rec["problem"] = err.message
            except Exception as err:
                rec["problem"] = "Unreadable: %s" % err
            results.append(rec)
        objects = {"checked": 0, "bad": []}
        if deep:
            for r in c.execute("SELECT hash FROM object").fetchall():
                objects["checked"] += 1
                try:
                    v.get(c, bytes(r[0]))
                except VaultError as err:
                    objects["bad"].append({"object": bytes(r[0]).hex(), "problem": err.message})
                if objects["checked"] >= 200000:
                    break
    bad = [r for r in results if not r["ok"]]
    return {"versions": len(results), "ok": len(results) - len(bad), "identical": len([r for r in results if r["identical"]]), "bad": bad[:200], "objects": objects if deep else None}


def _keep_versions(c, grace: int) -> set:
    roots = {bytes(r[0]) for r in c.execute("SELECT version FROM ref").fetchall()}
    roots |= {bytes(r[0]) for r in c.execute("SELECT version FROM lifecycle").fetchall()}
    for r in c.execute("SELECT ours, theirs, base FROM merge").fetchall():
        roots |= {bytes(x) for x in r if x}
    roots |= {bytes(r[0]) for r in c.execute("SELECT base FROM binding").fetchall()}
    roots |= {bytes(r[0]) for r in c.execute("SELECT base FROM lock").fetchall()}
    roots |= {bytes(r[0]) for r in c.execute("SELECT version FROM comment").fetchall()}
    roots |= {bytes(r[0]) for r in c.execute("SELECT hash FROM version WHERE ts>?", (now() - grace * 86400,)).fetchall()}
    keep = set()
    for h in roots:
        if h not in keep:
            keep |= history.ancestors(c, h)
    for r in c.execute("SELECT to_version FROM extref WHERE to_version IS NOT NULL").fetchall():
        h = bytes(r[0])
        if h not in keep:
            keep |= history.ancestors(c, h)
    return keep


def _chunk_ids(v: Vault, c, h: bytes) -> list:
    row = c.execute("SELECT kind FROM object WHERE hash=?", (h,)).fetchone()
    if row is None or row["kind"] != "chunks":
        return []
    return [bytes.fromhex(x) for x in json.loads(v.get(c, h, False))["chunks"]]


def gc(v: Vault, dry_run: bool = True, grace_days: int = 30) -> dict:
    grace = max(0, min(int(grace_days if grace_days is not None else 30), 3650))
    with v.write() as c:
        keep = _keep_versions(c, grace)
        allv = [bytes(r[0]) for r in c.execute("SELECT hash FROM version").fetchall()]
        drop = [h for h in allv if h not in keep]
        live_objects: set = set()
        live_trees: set = set()
        for h in keep:
            row = c.execute("SELECT root, recipe, raw FROM version WHERE hash=?", (h,)).fetchone()
            if row is None:
                continue
            root = bytes(row["root"])
            if root not in live_trees:
                live_trees.add(root)
                for _n, mode, child in v.tree(c, root):
                    if mode == 2:
                        continue
                    live_objects.add(child)
                    if mode == 1:
                        live_objects.update(_chunk_ids(v, c, child))
            live_objects.add(bytes(row["recipe"]))
            if row["raw"] is not None:
                raw = bytes(row["raw"])
                live_objects.add(raw)
                live_objects.update(_chunk_ids(v, c, raw))
        for r in c.execute("SELECT markup FROM comment WHERE markup IS NOT NULL").fetchall():
            live_objects.add(bytes(r[0]))
        dead_objects = [(bytes(r["hash"]), r["stored"], r["path"]) for r in c.execute("SELECT hash, stored, path FROM object").fetchall() if bytes(r["hash"]) not in live_objects]
        dead_trees = [bytes(r[0]) for r in c.execute("SELECT DISTINCT hash FROM tree").fetchall() if bytes(r[0]) not in live_trees]
        freed = sum(x[1] for x in dead_objects)
        out = {"dry_run": dry_run, "grace_days": grace, "versions_dropped": len(drop), "objects_dropped": len(dead_objects), "trees_dropped": len(dead_trees), "bytes_freed": freed, "kept_versions": len(keep)}
        if dry_run:
            return out
        for h in drop:
            c.execute("DELETE FROM parent WHERE version=?", (h,))
            c.execute("DELETE FROM extref WHERE version=?", (h,))
            c.execute("DELETE FROM version WHERE hash=?", (h,))
        for t in dead_trees:
            c.execute("DELETE FROM tree WHERE hash=?", (t,))
        for h, _s, path in dead_objects:
            c.execute("DELETE FROM object WHERE hash=?", (h,))
            if path:
                try:
                    os.unlink(os.path.join(v.folder, path))
                except OSError:
                    pass
        v.audit(c, "vault", "", "", None, "gc", out)
        return out
