import json
import os

from app.vault import commit, history, xrefs
from app.vault.base import MAX_DEPTH, STATES, VaultError, author as me_author, clean_text, digest, hexed, machine as me_machine, now
from app.vault.store import Vault

TRANSITIONS = {"wip": ("review", "released", "obsolete"), "review": ("wip", "released", "obsolete"), "released": ("obsolete",), "obsolete": ()}


def _letters(n: int) -> str:
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _index(rev: str) -> int:
    if not rev.isalpha() or not rev.isupper():
        return -1
    n = 0
    for ch in rev:
        n = n * 26 + ord(ch) - 64
    return n - 1


def next_revision(c, doc: str) -> str:
    top = -1
    for r in c.execute("SELECT lifecycle.revision FROM lifecycle JOIN version ON version.hash=lifecycle.version WHERE version.doc=? AND lifecycle.state IN ('released','obsolete')", (doc,)).fetchall():
        top = max(top, _index(r[0]))
    return _letters(top + 1)


def child_target(c, ref) -> tuple:
    doc = ref["to_doc"]
    if not doc:
        return None, None
    if ref["to_version"]:
        return doc, bytes(ref["to_version"])
    d = c.execute("SELECT default_branch FROM doc WHERE id=?", (doc,)).fetchone()
    return doc, (history.head_of(c, doc, d["default_branch"]) if d else None)


def _release_checks(v, c, h: bytes, cascade: bool, who: str, depth: int, chain: tuple, released: list) -> None:
    if depth > MAX_DEPTH:
        raise VaultError("The assembly nests deeper than %d levels." % MAX_DEPTH)
    for ref in c.execute("SELECT * FROM extref WHERE version=?", (h,)).fetchall():
        doc, child = child_target(c, ref)
        if doc is None:
            continue
        if child is None:
            raise VaultError("Component %s refers to document %s, which has no versions." % (ref["comp"], doc))
        state, _rev = history.state_of(c, child)
        if state == "obsolete":
            raise VaultError("Component %s uses an obsolete version of %s; replace it before releasing." % (ref["comp"], doc), 409)
        if state != "released":
            if not cascade:
                raise VaultError("Component %s uses %s, which is not released (%s). Release it first, or release with its children." % (ref["comp"], doc, state), 409)
            if child in chain:
                raise VaultError("The references form a cycle through %s." % doc)
            _release_checks(v, c, child, True, who, depth + 1, chain + (child,), released)
            _apply(v, c, child, "released", "", "Released with its parent", who)
            released.append(child.hex())


def _apply(v: Vault, c, h: bytes, state: str, revision: str, note: str, who: str) -> None:
    row = c.execute("SELECT doc FROM version WHERE hash=?", (h,)).fetchone()
    doc = row["doc"]
    old, oldrev = history.state_of(c, h)
    if state == "released":
        revision = revision or next_revision(c, doc)
        clash = c.execute("SELECT 1 FROM lifecycle JOIN version ON version.hash=lifecycle.version WHERE version.doc=? AND lifecycle.revision=? AND lifecycle.version!=? AND lifecycle.state IN ('released','obsolete')", (doc, revision, h)).fetchone()
        if clash:
            raise VaultError("Revision %s is already used by another version of this document." % revision, 409)
        commit.set_ref(c, doc, "rev/" + revision, h)
    elif state == "wip":
        revision = ""
    else:
        revision = oldrev
    c.execute("INSERT INTO lifecycle(version, state, revision, ts, author, note) VALUES(?,?,?,?,?,?) ON CONFLICT(version) DO UPDATE SET state=excluded.state, revision=excluded.revision, ts=excluded.ts, author=excluded.author, note=excluded.note", (h, state, revision, now(), who, note))
    v.audit(c, who, me_machine(), doc, h, "state", {"from": old, "to": state, "revision": revision, "note": note})


def set_state(v: Vault, version: str, state: str, revision: str = "", note: str = "", cascade: bool = False, who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    state = str(state or "").strip().lower()
    if state not in STATES:
        raise VaultError("The state must be one of: %s." % ", ".join(STATES))
    note = clean_text(note, 400, "The note")
    revision = clean_text(revision, 20, "The revision")
    if revision and not all(ch.isalnum() or ch in ".-_" for ch in revision):
        raise VaultError("A revision may hold letters, digits and . - _ only.")
    with v.write() as c:
        row = history.version_row(c, version)
        h = bytes(row["hash"])
        cur, _rev = history.state_of(c, h)
        if state == cur:
            raise VaultError("The version is already %s." % cur)
        if state not in TRANSITIONS[cur]:
            raise VaultError("A %s version cannot become %s. %s" % (cur, state, "Revise it to work on a new version." if cur == "released" else "Allowed next states: %s." % (", ".join(TRANSITIONS[cur]) or "none")), 409)
        released: list = []
        if state == "released":
            _release_checks(v, c, h, cascade, who, 0, (h,), released)
        _apply(v, c, h, state, revision, note, who)
        rec = history.vrec(c, c.execute("SELECT * FROM version WHERE hash=?", (h,)).fetchone())
        rec["cascaded"] = released
        return rec


def revise(v: Vault, doc: str, branch: str = "", who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    with v.write() as c:
        d = history.doc_row(c, doc)
        branch = branch or d["default_branch"]
        head = history.head_of(c, doc, branch)
        if head is None:
            raise VaultError("The document has no branch %s." % branch)
        state, rev = history.state_of(c, head)
        if state != "released":
            raise VaultError("Only a released version is revised; the latest version is %s." % state, 409)
        commit.check_lock(c, doc, who, mach)
        row = c.execute("SELECT * FROM version WHERE hash=?", (head,)).fetchone()
        message = "Revise after revision %s" % rev
        ident = json.dumps({"doc": doc, "root": hexed(row["root"]), "parents": [head.hex()], "author": who, "ts": now(), "message": message, "nonce": os.urandom(4).hex()}, sort_keys=True).encode()
        h = digest(ident)
        c.execute("INSERT INTO version(hash, doc, root, author, ts, message, format, size, members, container, sha256, recipe, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (h, doc, row["root"], who, now(), message, row["format"], row["size"], row["members"], row["container"], row["sha256"], row["recipe"], row["raw"]))
        c.execute("INSERT INTO parent(version, parent, ord) VALUES(?,?,0)", (h, head))
        c.execute("INSERT INTO extref(version, from_doc, comp, to_doc, to_version, to_path, mode) SELECT ?, from_doc, comp, to_doc, to_version, to_path, mode FROM extref WHERE version=?", (h, head))
        commit.set_ref(c, doc, "heads/" + branch, h)
        v.audit(c, who, mach, doc, h, "revise", {"branch": branch, "after": rev})
        return history.vrec(c, c.execute("SELECT * FROM version WHERE hash=?", (h,)).fetchone())


def whereused(v: Vault, doc: str, version: str = "", scope: str = "heads") -> dict:
    scope = scope if scope in ("heads", "all") else "heads"
    with v.read() as c:
        history.doc_row(c, doc)
        want = bytes(history.version_row(c, version, doc)["hash"]) if version else None
        rows = c.execute("SELECT * FROM extref WHERE to_doc=? ORDER BY version", (doc,)).fetchall()
        out = []
        cache: dict = {}
        for r in rows:
            if want is not None and r["to_version"] and bytes(r["to_version"]) != want:
                continue
            fv = bytes(r["version"])
            if fv not in cache:
                vr = c.execute("SELECT * FROM version WHERE hash=?", (fv,)).fetchone()
                if vr is None:
                    continue
                refs = history.ref_map(c, vr["doc"])
                rec = history.vrec(c, vr, refs)
                dn = c.execute("SELECT name FROM doc WHERE id=?", (vr["doc"],)).fetchone()
                rec["doc_name"] = dn["name"] if dn else ""
                rec["is_head"] = bool(rec["branches"])
                cache[fv] = rec
            rec = cache[fv]
            if scope == "heads" and not (rec["is_head"] or rec["state"] != "wip"):
                continue
            out.append({"from_doc": rec["doc"], "from_name": rec["doc_name"], "from_version": rec["id"], "short": rec["short"], "state": rec["state"], "revision": rec["revision"], "branches": rec["branches"], "comp": r["comp"], "mode": r["mode"], "to_version": hexed(r["to_version"]) if r["to_version"] else "", "path": r["to_path"]})
            if len(out) >= 2000:
                break
        return {"doc": doc, "version": want.hex() if want else "", "scope": scope, "used_by": out, "truncated": len(out) >= 2000}


def uses(v: Vault, doc: str, version: str = "") -> dict:
    with v.read() as c:
        d = history.doc_row(c, doc)
        h = bytes(history.version_row(c, version, doc)["hash"]) if version else history.head_of(c, doc, d["default_branch"])
        if h is None:
            raise VaultError("The document has no versions.")
        out = []
        for r in c.execute("SELECT * FROM extref WHERE version=? ORDER BY comp", (h,)).fetchall():
            target, ver = child_target(c, r)
            rec = {"comp": r["comp"], "doc": target, "name": "", "mode": r["mode"], "path": r["to_path"], "version": hexed(ver) if ver else "", "state": "", "revision": "", "in_vault": target is not None}
            if target:
                rec["name"] = c.execute("SELECT name FROM doc WHERE id=?", (target,)).fetchone()["name"]
                if ver:
                    rec["state"], rec["revision"] = history.state_of(c, ver)
            out.append(rec)
        return {"doc": doc, "version": h.hex(), "uses": out}


def audit(v: Vault, doc: str = "", limit: int = 200) -> list:
    limit = max(1, min(int(limit or 200), 5000))
    with v.read() as c:
        if doc:
            rows = c.execute("SELECT * FROM audit WHERE doc=? ORDER BY id DESC LIMIT ?", (doc, limit)).fetchall()
        else:
            rows = c.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "author": r["author"], "machine": r["machine"], "doc": r["doc"], "version": hexed(r["version"]) if r["version"] else "", "action": r["action"], "detail": json.loads(r["detail"]) if r["detail"][:1] in "{[" else r["detail"]} for r in rows]


def children_of(v: Vault, version: str) -> list:
    with v.read() as c:
        return xrefs.children(c, bytes(history.version_row(c, version)["hash"]))
