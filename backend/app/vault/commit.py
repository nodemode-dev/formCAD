import hashlib
import json
import os

from app.vault import cdc, history, members as M, xrefs
from app.vault.base import AGENT_CONTAINER, AGENT_UNPACKED, FORMAT, MAX_CONTAINER, MAX_MESSAGE, MAX_UNPACKED, MAX_VERSIONS, VaultError, author as me_author, clean_text, digest, file_digests, hexed, machine as me_machine, now, ref_name
from app.vault.store import Vault

STATE_BLOCKS = {"review": "in review", "released": "released", "obsolete": "obsolete"}


class Prepared:
    pass


def read_container(path: str, agent: bool) -> tuple:
    full = os.path.realpath(os.path.expanduser(str(path or "")))
    if not str(path or "").strip() or "\x00" in str(path):
        raise VaultError("A file name is required.")
    if not os.path.isfile(full):
        raise VaultError("The file %s does not exist." % os.path.basename(full))
    if os.path.splitext(full)[1].lower() != ".fcad":
        raise VaultError("Only .fcad files are checked in.")
    limit = AGENT_CONTAINER if agent else MAX_CONTAINER
    file_digests(full, limit)
    with open(full, "rb") as fh:
        data = fh.read(limit + 1)
    if len(data) > limit:
        raise VaultError("The file is larger than the %d MB limit." % (limit // (1024 * 1024)))
    return full, data


def prepare(data: bytes, agent: bool = False) -> Prepared:
    p = Prepared()
    limit = AGENT_CONTAINER if agent else MAX_CONTAINER
    if len(data) > limit:
        raise VaultError("The file is larger than the %d MB limit." % (limit // (1024 * 1024)))
    p.members, p.recipe = M.split(data, AGENT_UNPACKED if agent else MAX_UNPACKED)
    by = {m.name: m for m in p.members}
    if "manifest.json" not in by or "document.json" not in by:
        raise VaultError("The file has no manifest.json and document.json, so it is not a FormCAD project.")
    try:
        man = json.loads(by["manifest.json"].data)
    except ValueError:
        raise VaultError("The manifest is not valid JSON.")
    if not isinstance(man, dict) or man.get("format") != "formcad":
        raise VaultError("Not a FormCAD project (the manifest format is not formcad).")
    p.kind = str(man.get("kind") or "drawing")
    p.title = str(man.get("title") or "")
    p.doc_raw = by["document.json"].data
    p.container = digest(data)
    p.sha256 = hashlib.sha256(data).hexdigest()
    p.size = len(data)
    p.identical = M.reproduces(p.members, p.recipe, p.container)
    p.data = data
    return p


def new_doc_id(c, name: str) -> str:
    base = digest(("%s|%s|%s" % (name, now(), os.urandom(8).hex())).encode()).hex()[:8]
    while c.execute("SELECT 1 FROM doc WHERE id=?", ("D-" + base,)).fetchone():
        base = digest(os.urandom(16)).hex()[:8]
    return "D-" + base


def store_version(v: Vault, c, doc: str, p: Prepared, parents: list, message: str, who: str) -> bytes:
    entries = []
    for m in p.members:
        if m.is_dir:
            entries.append((m.name, 2, digest(b"")))
        else:
            mode, h = v.put_member(c, m.data)
            entries.append((m.name, mode, h))
    root = v.put_tree(c, entries)
    recipe_id = v.put(c, M.recipe_bytes(p.recipe), "recipe")
    raw = None
    if not p.identical:
        ids, start = [], 0
        for end in cdc.cut(p.data):
            ids.append(v.put(c, p.data[start:end], "chunk").hex())
            start = end
        listing = json.dumps({"chunker": cdc.NAME, "size": len(p.data), "chunks": ids}, separators=(",", ":")).encode()
        raw = v.put(c, listing, "chunks")
    ts = now()
    ident = json.dumps({"doc": doc, "root": root.hex(), "parents": [x.hex() for x in parents], "author": who, "ts": ts, "message": message, "container": p.container.hex(), "recipe": recipe_id.hex(), "raw": raw.hex() if raw else "", "format": FORMAT, "nonce": os.urandom(4).hex()}, sort_keys=True).encode()
    h = digest(ident)
    if c.execute("SELECT COUNT(*) FROM version").fetchone()[0] >= MAX_VERSIONS:
        raise VaultError("The vault holds %d versions, which is its limit; run garbage collection." % MAX_VERSIONS)
    c.execute("INSERT INTO version(hash, doc, root, author, ts, message, format, size, members, container, sha256, recipe, raw) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (h, doc, root, who, ts, message, FORMAT, p.size, len(p.recipe["order"]), p.container, p.sha256, recipe_id, raw))
    for i, parent in enumerate(parents):
        c.execute("INSERT INTO parent(version, parent, ord) VALUES(?,?,?)", (h, parent, i))
    return h


def set_ref(c, doc: str, name: str, version: bytes) -> None:
    c.execute("INSERT INTO ref(doc, name, version, ts) VALUES(?,?,?,?) ON CONFLICT(doc, name) DO UPDATE SET version=excluded.version, ts=excluded.ts", (doc, name, version, now()))


def lock_row(c, doc: str):
    return c.execute("SELECT * FROM lock WHERE doc=?", (doc,)).fetchone()


def lock_rec(r) -> dict | None:
    if r is None:
        return None
    return {"doc": r["doc"], "owner": r["owner"], "machine": r["machine"], "since": r["since"], "base": hexed(r["base"]), "path": r["path"], "note": r["note"]}


def check_lock(c, doc: str, who: str, mach: str) -> None:
    r = lock_row(c, doc)
    if r and (r["owner"] != who or r["machine"] != mach):
        raise VaultError("%s is checked out by %s on %s since %s. Ask them to check it in, or break the lock." % (doc, r["owner"], r["machine"], r["since"]), 409)


def check_editable(c, doc: str, head: bytes) -> None:
    state, rev = history.state_of(c, head)
    if state in STATE_BLOCKS:
        raise VaultError("The latest version is %s%s, so it cannot be changed. Revise it to start a new working version." % (STATE_BLOCKS[state], " (revision %s)" % rev if rev else ""), 409)


def checkin(v: Vault, path: str = "", data: bytes | None = None, doc: str = "", name: str = "", branch: str = "", message: str = "", who: str = "", keep_lock: bool = False, auto_merge: bool = True, base: str = "", agent: bool = False) -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    message = clean_text(message, MAX_MESSAGE, "The message") or "Check-in"
    full = ""
    if data is None:
        full, data = read_container(path, agent)
    elif path:
        full = os.path.realpath(os.path.expanduser(path))
    p = prepare(data, agent)
    side = None
    with v.write() as c:
        bound = c.execute("SELECT * FROM binding WHERE path=?", (full,)).fetchone() if full else None
        if not doc and bound:
            doc = bound["doc"]
        created = False
        if doc:
            d = history.doc_row(c, doc)
            branch = ref_name(branch or (bound["branch"] if bound and bound["doc"] == doc else d["default_branch"]), "branch")
        else:
            label = clean_text(name or p.title or (os.path.splitext(os.path.basename(full))[0] if full else ""), 120, "The document name") or "Untitled"
            if c.execute("SELECT COUNT(*) FROM doc").fetchone()[0] >= 5000:
                raise VaultError("The vault holds 5000 documents, which is its limit.")
            doc = new_doc_id(c, label)
            branch = ref_name(branch or "main", "branch")
            c.execute("INSERT INTO doc(id, name, kind, created, default_branch) VALUES(?,?,?,?,?)", (doc, label, p.kind, now(), branch))
            created = True
        head = history.head_of(c, doc, branch)
        if head is None and not created:
            raise VaultError("The document has no branch %s; create it first." % branch)
        want = None
        if base:
            want = bytes(history.version_row(c, base, doc)["hash"])
        elif bound and bound["doc"] == doc and bound["branch"] == branch:
            want = bytes(bound["base"])
        elif head is not None:
            want = head
        check_lock(c, doc, who, mach)
        if head is not None and want == head:
            check_editable(c, doc, head)
        if want is not None and bytes(c.execute("SELECT container FROM version WHERE hash=?", (want,)).fetchone()[0]) == p.container:
            raise VaultError("Nothing changed since version %s." % want.hex()[:12])
        parents = [want] if want else []
        diverged = head is not None and want is not None and want != head
        h = store_version(v, c, doc, p, parents, message, who)
        if diverged:
            side = "%s~%s" % (branch, h.hex()[:6])
            set_ref(c, doc, "heads/" + side, h)
        else:
            set_ref(c, doc, "heads/" + branch, h)
        xrefs.record(c, h, doc, p.doc_raw, full or (bound["path"] if bound else ""))
        if not keep_lock:
            c.execute("DELETE FROM lock WHERE doc=? AND owner=? AND machine=?", (doc, who, mach))
        if full:
            c.execute("INSERT INTO binding(path, doc, branch, base, hash, edit, ts) VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET doc=excluded.doc, branch=excluded.branch, base=excluded.base, hash=excluded.hash, edit=excluded.edit, ts=excluded.ts", (full, doc, side or branch, h, p.container, 1 if keep_lock else 0, now()))
        v.audit(c, who, mach, doc, h, "checkin", {"branch": side or branch, "message": message, "created": created, "diverged": diverged})
        row = c.execute("SELECT * FROM version WHERE hash=?", (h,)).fetchone()
        result = {"status": "diverged" if diverged else "ok", "created": created, "doc": doc, "branch": side or branch, "target": branch, "version": history.vrec(c, row), "identical": p.identical, "merge": None, "merged": None}
    if diverged and auto_merge:
        from app.vault import mergeops

        m = mergeops.start(v, doc, side, branch, who)
        result["merge"] = m
        if m["status"] in ("clean", "ready") and not m["unresolved"]:
            done = mergeops.complete(v, doc, "Merge %s into %s" % (side, branch), who)
            result["merged"] = done["version"]
            result["status"] = "merged"
    return result


def container_of(v: Vault, c, h: bytes) -> tuple:
    row = c.execute("SELECT * FROM version WHERE hash=?", (h,)).fetchone()
    if row is None:
        raise VaultError("There is no such version.", 404)
    want = bytes(row["container"])
    if row["raw"] is not None:
        data = v.get_member(c, 1, bytes(row["raw"]))
        if digest(data) != want:
            raise VaultError("The stored container of version %s fails its hash check." % h.hex()[:12], 500)
        return data, True
    members = {}
    for name, mode, child in v.tree(c, bytes(row["root"])):
        members[name] = b"" if mode == 2 else v.get_member(c, mode, child)
    recipe = json.loads(v.get(c, bytes(row["recipe"])))
    data = M.rebuild(members, recipe)
    return data, digest(data) == want


def write_out(path: str, data: bytes, readonly: bool) -> str:
    from app.core import outputs
    from app.doc import container

    try:
        full = outputs.checked(path, (".fcad",), ".fcad")
    except outputs.OutputRefused as err:
        raise VaultError(str(err))
    container.atomic_write(full, data, 0o444 if readonly else 0o644)
    return os.path.realpath(full)


def binding_rec(c, r) -> dict:
    status = "clean"
    try:
        h, _s, _n = file_digests(r["path"], MAX_CONTAINER)
        if h != bytes(r["hash"]):
            status = "modified"
    except (OSError, VaultError):
        status = "missing"
    head = history.head_of(c, r["doc"], r["branch"])
    if status == "clean" and head is not None and head != bytes(r["base"]):
        status = "behind"
    return {"path": r["path"], "doc": r["doc"], "branch": r["branch"], "base": hexed(r["base"]), "hash": hexed(r["hash"]), "edit": bool(r["edit"]), "ts": r["ts"], "status": status}


def binding_of(v: Vault, path: str) -> dict | None:
    full = os.path.realpath(os.path.expanduser(str(path or "")))
    with v.read() as c:
        r = c.execute("SELECT * FROM binding WHERE path=?", (full,)).fetchone()
        if r is None:
            return None
        rec = binding_rec(c, r)
        lk = lock_row(c, r["doc"])
        rec["lock"] = lock_rec(lk)
        return rec


def checkout(v: Vault, doc: str, path: str, ref: str = "", edit: bool = True, lock: bool = True, who: str = "", overwrite: bool = False, agent: bool = False) -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    with v.write() as c:
        d = history.doc_row(c, doc)
        want_ref = ref or d["default_branch"]
        h = history.resolve_ref(c, doc, want_ref)
        branch = want_ref if history.head_of(c, doc, want_ref) is not None else d["default_branch"]
        if edit:
            head = history.head_of(c, doc, branch)
            check_editable(c, doc, head if head is not None else h)
            if lock:
                check_lock(c, doc, who, mach)
        data, same = container_of(v, c, h)
        full_target = os.path.realpath(os.path.expanduser(str(path or "")))
        existing = c.execute("SELECT * FROM binding WHERE path=?", (full_target,)).fetchone()
        if os.path.isfile(full_target) and not overwrite:
            if existing is None or existing["doc"] != doc:
                raise VaultError("%s already exists and is not a checkout of this document; choose another name or allow overwrite." % os.path.basename(full_target))
            if binding_rec(c, existing)["status"] == "modified":
                raise VaultError("%s has changes that are not checked in; check them in, undo the checkout, or allow overwrite." % os.path.basename(full_target))
        out = write_out(path, data, not edit)
        if edit and lock:
            c.execute("INSERT INTO lock(doc, owner, machine, since, base, path, note) VALUES(?,?,?,?,?,?,?) ON CONFLICT(doc) DO UPDATE SET base=excluded.base, path=excluded.path", (doc, who, mach, now(), h, out, ""))
        c.execute("INSERT INTO binding(path, doc, branch, base, hash, edit, ts) VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET doc=excluded.doc, branch=excluded.branch, base=excluded.base, hash=excluded.hash, edit=excluded.edit, ts=excluded.ts", (out, doc, branch, h, digest(data), 1 if edit else 0, now()))
        v.audit(c, who, mach, doc, h, "checkout", {"path": out, "edit": edit})
        return {"path": out, "doc": doc, "branch": branch, "version": h.hex(), "identical": same, "bytes": len(data), "edit": edit, "locked": bool(edit and lock)}


def undo_checkout(v: Vault, path: str, restore: bool = False, who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    mach = me_machine()
    full = os.path.realpath(os.path.expanduser(str(path or "")))
    with v.write() as c:
        r = c.execute("SELECT * FROM binding WHERE path=?", (full,)).fetchone()
        if r is None:
            raise VaultError("%s is not a checkout from this vault." % os.path.basename(full))
        restored = False
        if restore:
            data, _same = container_of(v, c, bytes(r["base"]))
            write_out(full, data, True)
            restored = True
        c.execute("DELETE FROM binding WHERE path=?", (full,))
        c.execute("DELETE FROM lock WHERE doc=? AND owner=? AND machine=?", (r["doc"], who, mach))
        v.audit(c, who, mach, r["doc"], bytes(r["base"]), "undo-checkout", {"path": full, "restored": restored})
    return {"path": full, "doc": r["doc"], "restored": restored}

