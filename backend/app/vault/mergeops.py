import json
import os
import tempfile
import time
from datetime import datetime, timezone

from app.vault import commit, entities, history, members as M, merge as G, xrefs
from app.vault.base import VaultError, clean_text, digest, hexed, machine as me_machine, author as me_author, now, MAX_MESSAGE
from app.vault.store import Vault

ALLOWED = {
    "field": ("ours", "theirs", "base", "value"),
    "edit_delete": ("ours", "theirs"),
    "delete_edit": ("ours", "theirs"),
    "both_added": ("ours", "theirs", "keep_both"),
    "order": ("ours", "theirs", "base"),
    "blob": ("ours", "theirs", "base"),
    "reference_broken": ("accept", "restore"),
}
SKIP_MEMBERS = ("document.json", "manifest.json")
CHECK_ITEMS = 20000


def _compute(v: Vault, c, ours: bytes, theirs: bytes, base: bytes | None, choices: dict) -> dict:
    om, tm = history.emap(v, c, ours), history.emap(v, c, theirs)
    bm = history.emap(v, c, base) if base else entities.EMap()
    ctx = G.Ctx(choices)
    res = G.merge_maps(bm, om, tm, ctx)
    G.reference_checks(bm, om, tm, res["items"], ctx)
    orders = G.finish_orders(bm, om, tm, res["items"], res["extra_order"], ctx)
    rows = {k: history.tree_dict(v, c, bytes(c.execute("SELECT root FROM version WHERE hash=?", (x,)).fetchone()[0])) if x else {} for k, x in (("o", ours), ("t", theirs), ("b", base))}
    skip = lambda d: {n: e for n, e in d.items() if n not in SKIP_MEMBERS}
    mem = G.merge_members(skip(rows["b"]), skip(rows["o"]), skip(rows["t"]), ctx)
    keys = list(om.meta.get("root_order") or [])
    keys += [k for k in tm.meta.get("root_order") or [] if k not in keys]
    return {"ctx": ctx, "items": res["items"], "orders": orders, "next_handle": res["next_handle"], "members": mem, "keys": keys, "rows": rows}


def _build(v: Vault, c, ours: bytes, comp: dict) -> bytes:
    orow = c.execute("SELECT * FROM version WHERE hash=?", (ours,)).fetchone()
    recipe = json.loads(v.get(c, bytes(orow["recipe"])))
    doc = entities.assemble(comp["keys"], comp["items"], comp["orders"], comp["next_handle"])
    doc_bytes = json.dumps(doc, separators=(",", ":"), allow_nan=False).encode("utf-8")
    man = json.loads(history_member(v, c, comp["rows"]["o"], "manifest.json"))
    man["modified"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    man_bytes = json.dumps(man, indent=2, allow_nan=False).encode("utf-8")
    tree = dict(comp["members"])
    tree["document.json"] = (0, digest(doc_bytes))
    tree["manifest.json"] = (0, digest(man_bytes))
    names = [n for n in recipe["order"] if n in tree] + sorted(n for n in tree if n not in recipe["order"])
    t = time.localtime()
    stamp = [max(t.tm_year, 1980), t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec]
    info, data = {}, {}
    for n in names:
        mode, child = tree[n]
        if n == "document.json":
            data[n] = doc_bytes
        elif n == "manifest.json":
            data[n] = man_bytes
        else:
            data[n] = b"" if mode == 2 else v.get_member(c, mode, child)
        r = dict(recipe["info"].get(n) or {"dt": stamp, "ct": 0 if mode == 2 else 8, "lv": 6, "ea": (0o40755 << 16 | 0x10) if mode == 2 else (0o600 << 16), "ia": 0, "cs": 3, "cv": 20, "xv": 20, "fb": 0, "ex": "", "cm": ""})
        if n in SKIP_MEMBERS or comp["rows"]["o"].get(n) != tree[n]:
            r["dt"] = stamp
        r["lv"] = 6 if r["ct"] == 8 else 0
        info[n] = r
    return M.rebuild(data, {"v": 1, "order": names, "info": info, "comment": recipe.get("comment", "")})


def history_member(v: Vault, c, rowtree: dict, name: str) -> bytes:
    mode, child = rowtree[name]
    return v.get_member(c, mode, child)


def _validate(v: Vault, data: bytes) -> list:
    from app.doc import container

    tmpdir = os.path.join(v.folder, "tmp")
    os.makedirs(tmpdir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".fcad", dir=tmpdir)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        container.load(tmp)
        return []
    except container.ContainerError as err:
        return ["The merged file does not open: " + err.message]
    except Exception as err:
        return ["The merged file does not rebuild: %s" % err]
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _record(v: Vault, c, row, comp, with_check: bool = True) -> dict:
    conflicts = comp["ctx"].conflicts
    unresolved = [x for x in conflicts if x["choice"] is None]
    status = "clean" if not conflicts else "conflicts" if unresolved else "ready"
    rep = json.loads(row["report"])
    out = {"doc": row["doc"], "branch": row["branch"], "ours": bytes(row["ours"]).hex(), "theirs": bytes(row["theirs"]).hex(), "base": hexed(row["base"]) if row["base"] else "", "status": status, "conflicts": conflicts, "merged": comp["ctx"].stats, "unresolved": len(unresolved), "started": row["started"], "author": row["author"], "source": rep.get("source", ""), "criss_cross": rep.get("criss_cross", False), "valid": True, "problems": [], "rebuild": comp["ctx"].rebuild}
    if with_check and not unresolved:
        if len(comp["items"]) > CHECK_ITEMS:
            out["valid"] = None
            out["problems"] = ["The merged file is checked when the merge is completed; it is too large to check for every change."]
        else:
            problems = _validate(v, _build(v, c, bytes(row["ours"]), comp))
            out["valid"] = not problems
            out["problems"] = problems
    return out


def start(v: Vault, doc: str, source: str, branch: str = "", who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    with v.write() as c:
        d = history.doc_row(c, doc)
        branch = branch or d["default_branch"]
        ours = history.head_of(c, doc, branch)
        if ours is None:
            raise VaultError("The document has no branch %s." % branch)
        theirs = history.resolve_ref(c, doc, source)
        c.execute("DELETE FROM merge WHERE doc=?", (doc,))
        if theirs == ours or history.is_ancestor(c, theirs, ours):
            return {"doc": doc, "branch": branch, "ours": ours.hex(), "theirs": theirs.hex(), "base": theirs.hex(), "status": "up_to_date", "conflicts": [], "merged": {}, "unresolved": 0, "started": now(), "author": who, "source": source, "criss_cross": False, "valid": True, "problems": []}
        if history.is_ancestor(c, ours, theirs):
            rec = {"doc": doc, "branch": branch, "ours": ours.hex(), "theirs": theirs.hex(), "base": ours.hex(), "status": "fast_forward", "conflicts": [], "merged": {}, "unresolved": 0, "started": now(), "author": who, "source": source, "criss_cross": False, "valid": True, "problems": []}
            c.execute("INSERT INTO merge(doc, branch, ours, theirs, base, report, choices, started, author) VALUES(?,?,?,?,?,?,?,?,?)", (doc, branch, ours, theirs, ours, json.dumps({"source": source, "criss_cross": False, "ff": True}), "{}", rec["started"], who))
            return rec
        base, crisscross = history.lca(c, ours, theirs)
        comp = _compute(v, c, ours, theirs, base, {})
        c.execute("INSERT INTO merge(doc, branch, ours, theirs, base, report, choices, started, author) VALUES(?,?,?,?,?,?,?,?,?)", (doc, branch, ours, theirs, base, json.dumps({"source": source, "criss_cross": crisscross}), "{}", now(), who))
        row = c.execute("SELECT * FROM merge WHERE doc=?", (doc,)).fetchone()
        v.audit(c, who, me_machine(), doc, theirs, "merge-start", {"branch": branch, "source": source, "conflicts": len(comp["ctx"].conflicts)})
        return _record(v, c, row, comp)


def state(v: Vault, doc: str) -> dict:
    with v.read() as c:
        row = c.execute("SELECT * FROM merge WHERE doc=?", (doc,)).fetchone()
        if row is None:
            raise VaultError("No merge is in progress for this document.", 404)
        rep = json.loads(row["report"])
        if rep.get("ff"):
            return {"doc": doc, "branch": row["branch"], "ours": bytes(row["ours"]).hex(), "theirs": bytes(row["theirs"]).hex(), "base": bytes(row["base"]).hex(), "status": "fast_forward", "conflicts": [], "merged": {}, "unresolved": 0, "started": row["started"], "author": row["author"], "source": rep.get("source", ""), "criss_cross": False, "valid": True, "problems": []}
        comp = _compute(v, c, bytes(row["ours"]), bytes(row["theirs"]), bytes(row["base"]) if row["base"] else None, json.loads(row["choices"]))
        return _record(v, c, row, comp)


def resolve(v: Vault, doc: str, choices: dict) -> dict:
    if not isinstance(choices, dict) or not choices:
        raise VaultError("Give choices as an object of conflict id to ours, theirs, base or a value.")
    with v.write() as c:
        row = c.execute("SELECT * FROM merge WHERE doc=?", (doc,)).fetchone()
        if row is None:
            raise VaultError("No merge is in progress for this document.", 404)
        if json.loads(row["report"]).get("ff"):
            raise VaultError("This merge is a fast-forward and has no conflicts.")
        stored = json.loads(row["choices"])
        comp = _compute(v, c, bytes(row["ours"]), bytes(row["theirs"]), bytes(row["base"]) if row["base"] else None, stored)
        known = {x["id"]: x for x in comp["ctx"].conflicts}
        for cid, choice in choices.items():
            if cid not in known:
                raise VaultError("There is no conflict %s in this merge." % cid)
            kind = known[cid]["kind"]
            if isinstance(choice, dict):
                if kind != "field" or "value" not in choice:
                    raise VaultError("Conflict %s cannot take a typed value." % cid)
                if len(json.dumps(choice["value"])) > 65536:
                    raise VaultError("The value for conflict %s is too large." % cid)
            elif choice not in ALLOWED[kind]:
                raise VaultError("Conflict %s (%s) accepts: %s." % (cid, kind, ", ".join(ALLOWED[kind])))
            elif choice == "keep_both" and known[cid]["entity"].split(":", 1)[0] != "entity":
                raise VaultError("Only drawing entities can keep both.")
            stored[cid] = choice
        c.execute("UPDATE merge SET choices=? WHERE doc=?", (json.dumps(stored), doc))
        row = c.execute("SELECT * FROM merge WHERE doc=?", (doc,)).fetchone()
        comp = _compute(v, c, bytes(row["ours"]), bytes(row["theirs"]), bytes(row["base"]) if row["base"] else None, stored)
        return _record(v, c, row, comp)


def abort(v: Vault, doc: str) -> dict:
    with v.write() as c:
        if c.execute("DELETE FROM merge WHERE doc=?", (doc,)).rowcount == 0:
            raise VaultError("No merge is in progress for this document.", 404)
    return {"doc": doc, "aborted": True}


def complete(v: Vault, doc: str, message: str = "", who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    message = clean_text(message, MAX_MESSAGE, "The message")
    with v.write() as c:
        row = c.execute("SELECT * FROM merge WHERE doc=?", (doc,)).fetchone()
        if row is None:
            raise VaultError("No merge is in progress for this document.", 404)
        branch, ours, theirs = row["branch"], bytes(row["ours"]), bytes(row["theirs"])
        if history.head_of(c, doc, branch) != ours:
            raise VaultError("The branch %s moved since the merge started; abort and start again." % branch, 409)
        commit.check_lock(c, doc, who, mach)
        commit.check_editable(c, doc, ours)
        rep = json.loads(row["report"])
        if rep.get("ff"):
            commit.set_ref(c, doc, "heads/" + branch, theirs)
            c.execute("DELETE FROM merge WHERE doc=?", (doc,))
            v.audit(c, who, mach, doc, theirs, "merge-fast-forward", {"branch": branch})
            return {"doc": doc, "branch": branch, "fast_forward": True, "version": history.vrec(c, c.execute("SELECT * FROM version WHERE hash=?", (theirs,)).fetchone())}
        comp = _compute(v, c, ours, theirs, bytes(row["base"]) if row["base"] else None, json.loads(row["choices"]))
        unresolved = [x for x in comp["ctx"].conflicts if x["choice"] is None]
        if unresolved:
            raise VaultError("%d conflict(s) have no recorded choice yet." % len(unresolved), 409)
        data = _build(v, c, ours, comp)
        problems = _validate(v, data)
        if problems:
            raise VaultError(problems[0], 409)
        p = commit.prepare(data)
        h = commit.store_version(v, c, doc, p, [ours, theirs], message or "Merge %s into %s" % (rep.get("source", "branch"), branch), who)
        commit.set_ref(c, doc, "heads/" + branch, h)
        xrefs.record(c, h, doc, p.doc_raw, "")
        c.execute("DELETE FROM merge WHERE doc=?", (doc,))
        side = rep.get("source", "")
        if side.startswith(branch + "~"):
            c.execute("DELETE FROM ref WHERE doc=? AND name=?", (doc, "heads/" + side))
        v.audit(c, who, mach, doc, h, "merge", {"branch": branch, "source": rep.get("source", ""), "choices": len(comp["ctx"].conflicts)})
        return {"doc": doc, "branch": branch, "fast_forward": False, "version": history.vrec(c, c.execute("SELECT * FROM version WHERE hash=?", (h,)).fetchone()), "identical": p.identical}
