import os

from app.vault import commit, history
from app.vault.base import VaultError, author as me_author, clean_text, machine as me_machine, now, ref_name
from app.vault.store import Vault


def listing(v: Vault, doc: str) -> dict:
    with v.read() as c:
        history.doc_row(c, doc)
        heads, tags = [], []
        for r in c.execute("SELECT name, version, ts FROM ref WHERE doc=? ORDER BY name", (doc,)).fetchall():
            h = bytes(r["version"])
            state, rev = history.state_of(c, h)
            rec = {"name": r["name"].split("/", 1)[1], "head": h.hex(), "state": state, "revision": rev, "ts": r["ts"]}
            (heads if r["name"].startswith("heads/") else tags).append(rec)
        return {"branches": heads, "tags": tags}


def create(v: Vault, doc: str, name: str, start: str = "", who: str = "") -> dict:
    name = ref_name(name, "branch name")
    if "~" in name:
        raise VaultError("The branch name cannot contain ~.")
    with v.write() as c:
        d = history.doc_row(c, doc)
        if history.head_of(c, doc, name) is not None:
            raise VaultError("The branch %s already exists." % name)
        h = history.resolve_ref(c, doc, start or d["default_branch"])
        commit.set_ref(c, doc, "heads/" + name, h)
        v.audit(c, clean_text(who or me_author(), 100, "The author"), me_machine(), doc, h, "branch-create", {"name": name})
    return {"name": name, "head": h.hex()}


def delete(v: Vault, doc: str, name: str, force: bool = False, who: str = "") -> dict:
    with v.write() as c:
        d = history.doc_row(c, doc)
        if name == d["default_branch"]:
            raise VaultError("The default branch cannot be deleted.")
        h = history.head_of(c, doc, name)
        if h is None:
            raise VaultError("There is no branch %s." % name, 404)
        m = c.execute("SELECT 1 FROM merge WHERE doc=? AND branch=?", (doc, name)).fetchone()
        if m:
            raise VaultError("A merge into %s is in progress." % name, 409)
        if c.execute("SELECT 1 FROM binding WHERE doc=? AND branch=? AND edit=1", (doc, name)).fetchone() and not force:
            raise VaultError("A checkout is still open on %s." % name, 409)
        if not force:
            others = [bytes(r[0]) for r in c.execute("SELECT version FROM ref WHERE doc=? AND name!=?", (doc, "heads/" + name)).fetchall()]
            if not any(h in history.ancestors(c, o) for o in others):
                raise VaultError("The branch %s has work that no other branch or tag holds; merge it first or delete it with force." % name, 409)
        c.execute("DELETE FROM ref WHERE doc=? AND name=?", (doc, "heads/" + name))
        v.audit(c, clean_text(who or me_author(), 100, "The author"), me_machine(), doc, h, "branch-delete", {"name": name, "force": force})
    return {"deleted": name}


def rename(v: Vault, doc: str, name: str, to: str, who: str = "") -> dict:
    to = ref_name(to, "branch name")
    if "~" in to:
        raise VaultError("The branch name cannot contain ~.")
    with v.write() as c:
        d = history.doc_row(c, doc)
        h = history.head_of(c, doc, name)
        if h is None:
            raise VaultError("There is no branch %s." % name, 404)
        if history.head_of(c, doc, to) is not None:
            raise VaultError("The branch %s already exists." % to)
        if c.execute("SELECT 1 FROM merge WHERE doc=?", (doc,)).fetchone():
            raise VaultError("A merge is in progress; finish or abort it first.", 409)
        c.execute("UPDATE ref SET name=? WHERE doc=? AND name=?", ("heads/" + to, doc, "heads/" + name))
        c.execute("UPDATE binding SET branch=? WHERE doc=? AND branch=?", (to, doc, name))
        if d["default_branch"] == name:
            c.execute("UPDATE doc SET default_branch=? WHERE id=?", (to, doc))
        v.audit(c, clean_text(who or me_author(), 100, "The author"), me_machine(), doc, h, "branch-rename", {"from": name, "to": to})
    return {"name": to, "head": h.hex()}


def tag(v: Vault, doc: str, name: str, version: str, who: str = "") -> dict:
    name = ref_name(name, "tag name")
    if name.startswith("rev/") or "~" in name:
        raise VaultError("That tag name is reserved.")
    with v.write() as c:
        history.doc_row(c, doc)
        if c.execute("SELECT 1 FROM ref WHERE doc=? AND name=?", (doc, "tags/" + name)).fetchone():
            raise VaultError("The tag %s already exists; tags do not move." % name)
        h = history.resolve_ref(c, doc, version)
        commit.set_ref(c, doc, "tags/" + name, h)
        v.audit(c, clean_text(who or me_author(), 100, "The author"), me_machine(), doc, h, "tag", {"name": name})
    return {"name": name, "version": h.hex()}


def lock(v: Vault, doc: str, who: str = "", note: str = "", path: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    note = clean_text(note, 400, "The note")
    with v.write() as c:
        d = history.doc_row(c, doc)
        commit.check_lock(c, doc, who, mach)
        head = history.head_of(c, doc, d["default_branch"])
        commit.check_editable(c, doc, head)
        c.execute("INSERT INTO lock(doc, owner, machine, since, base, path, note) VALUES(?,?,?,?,?,?,?) ON CONFLICT(doc) DO UPDATE SET note=excluded.note", (doc, who, mach, now(), head, os.path.realpath(path) if path else "", note))
        v.audit(c, who, mach, doc, head, "lock", {"note": note})
        return commit.lock_rec(commit.lock_row(c, doc))


def unlock(v: Vault, doc: str, who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    with v.write() as c:
        history.doc_row(c, doc)
        r = commit.lock_row(c, doc)
        if r is None:
            raise VaultError("The document is not locked.", 404)
        commit.check_lock(c, doc, who, mach)
        c.execute("DELETE FROM lock WHERE doc=?", (doc,))
        v.audit(c, who, mach, doc, bytes(r["base"]), "unlock", {})
    return {"doc": doc, "unlocked": True}


def break_lock(v: Vault, doc: str, who: str = "", note: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    with v.read() as c:
        history.doc_row(c, doc)
        r = commit.lock_row(c, doc)
        if r is None:
            raise VaultError("The document is not locked.", 404)
        owner, omach, opath, base = r["owner"], r["machine"], r["path"], bytes(r["base"])
    kept = ""
    if opath and omach == mach and os.path.isfile(opath):
        name = "locked-%s-%s" % ("".join(ch for ch in owner if ch.isalnum() or ch in "-_")[:30] or "user", base.hex()[:6])
        try:
            with v.write() as c:
                if history.head_of(c, doc, name) is None:
                    commit.set_ref(c, doc, "heads/" + name, base)
            res = commit.checkin(v, path=opath, doc=doc, branch=name, message="Work kept when %s broke the lock" % who, who=owner, base=base.hex(), auto_merge=False)
            kept = res["branch"]
        except VaultError as err:
            kept = "not kept: " + err.message
    with v.write() as c:
        c.execute("DELETE FROM lock WHERE doc=?", (doc,))
        c.execute("DELETE FROM binding WHERE doc=? AND edit=1 AND path=?", (doc, opath))
        v.audit(c, who, mach, doc, base, "lock-break", {"owner": owner, "machine": omach, "note": clean_text(note, 400, "The note"), "kept": kept})
    return {"doc": doc, "broken": True, "owner": owner, "kept": kept}


def locks(v: Vault) -> list:
    with v.read() as c:
        out = []
        for r in c.execute("SELECT lock.*, doc.name AS dname FROM lock JOIN doc ON doc.id=lock.doc ORDER BY since DESC").fetchall():
            rec = commit.lock_rec(r)
            rec["name"] = r["dname"]
            out.append(rec)
        return out


def doc_lock(v: Vault, doc: str) -> dict | None:
    with v.read() as c:
        history.doc_row(c, doc)
        return commit.lock_rec(commit.lock_row(c, doc))
