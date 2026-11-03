import json
import re

from app.vault import history
from app.vault.base import MAX_ANCHOR, MAX_BODY, MAX_COMMENTS, MAX_MARKUP, VaultError, author as me_author, clean_text, hexed, now
from app.vault.store import Vault

UNSAFE_SVG = re.compile(r"<\s*script|<\s*foreignObject|<\s*iframe|<\s*object|<\s*embed|<!ENTITY|\son[a-z]+\s*=|javascript:|data:text/html|(?:xlink:)?href\s*=\s*[\"']\s*(?:https?:|//|file:)", re.I)


def clean_svg(text: str) -> bytes:
    s = str(text or "").strip()
    if len(s.encode("utf-8")) > MAX_MARKUP:
        raise VaultError("The markup is larger than %d KB." % (MAX_MARKUP // 1024))
    head = s[:400].lower()
    if "<svg" not in head or UNSAFE_SVG.search(s):
        raise VaultError("The markup must be plain SVG without scripts, event handlers or links.")
    return s.encode("utf-8")


def _rec(r, attached=None, note: str = "") -> dict:
    return {"id": r["id"], "doc": r["doc"], "version": hexed(r["version"]), "entity": r["entity"], "anchor": json.loads(r["anchor"]), "author": r["author"], "ts": r["ts"], "parent": r["parent"], "status": r["status"], "body": r["body"], "markup": hexed(r["markup"]) if r["markup"] else None, "camera": json.loads(r["camera"]) if r["camera"] else None, "attached": attached, "orphan_note": note}


def add(v: Vault, doc: str, version: str, entity: str, body: str, anchor=None, parent=None, markup_svg: str = "", camera=None, who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    body = clean_text(body, MAX_BODY, "The comment", True)
    entity = clean_text(entity or "doc:", 300, "The entity")
    anchor = anchor if isinstance(anchor, dict) else {}
    if len(json.dumps(anchor)) > MAX_ANCHOR:
        raise VaultError("The anchor is larger than %d characters." % MAX_ANCHOR)
    cam = None
    if camera is not None:
        if not isinstance(camera, dict) or len(json.dumps(camera)) > 2000:
            raise VaultError("The camera must be a small object.")
        cam = json.dumps(camera, separators=(",", ":"))
    svg = clean_svg(markup_svg) if markup_svg else None
    with v.write() as c:
        history.doc_row(c, doc)
        row = history.version_row(c, version, doc)
        h = bytes(row["hash"])
        if entity != "doc:" and entity not in history.emap(v, c, h).items:
            raise VaultError("The entity %s is not in that version." % entity)
        if parent is not None:
            p = c.execute("SELECT 1 FROM comment WHERE id=? AND doc=?", (int(parent), doc)).fetchone()
            if not p:
                raise VaultError("There is no comment %s to reply to." % parent, 404)
        if c.execute("SELECT COUNT(*) FROM comment WHERE doc=?", (doc,)).fetchone()[0] >= MAX_COMMENTS:
            raise VaultError("The document has %d comments, which is the limit." % MAX_COMMENTS)
        mk = v.put(c, svg, "markup") if svg else None
        cur = c.execute("INSERT INTO comment(doc, version, entity, anchor, author, ts, parent, status, body, markup, camera) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (doc, h, entity, json.dumps(anchor, separators=(",", ":")), who, now(), int(parent) if parent is not None else None, "open", body, mk, cam))
        r = c.execute("SELECT * FROM comment WHERE id=?", (cur.lastrowid,)).fetchone()
        return _rec(r, True)


def listing(v: Vault, doc: str, version: str = "", status: str = "") -> list:
    with v.read() as c:
        history.doc_row(c, doc)
        items = None
        if version:
            h = bytes(history.version_row(c, version, doc)["hash"])
            items = history.emap(v, c, h).items
        q = "SELECT * FROM comment WHERE doc=?"
        args: list = [doc]
        if status in ("open", "resolved"):
            q += " AND status=?"
            args.append(status)
        out = []
        for r in c.execute(q + " ORDER BY ts, id LIMIT 5000", args).fetchall():
            if items is None or r["entity"] == "doc:":
                out.append(_rec(r, True if items is not None else None))
            elif r["entity"] in items:
                out.append(_rec(r, True))
            else:
                out.append(_rec(r, False, "The entity %s is not in this version; the comment was made on %s." % (r["entity"], bytes(r["version"]).hex()[:12])))
        return out


def update(v: Vault, cid: int, status: str = "", body: str = "", who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    with v.write() as c:
        r = c.execute("SELECT * FROM comment WHERE id=?", (int(cid),)).fetchone()
        if r is None:
            raise VaultError("There is no comment %s." % cid, 404)
        if status:
            if status not in ("open", "resolved"):
                raise VaultError("The status is open or resolved.")
            c.execute("UPDATE comment SET status=? WHERE id=? OR parent=?", (status, r["id"], r["id"]) if r["parent"] is None else (status, r["id"], -1))
        if body:
            if r["author"] != who:
                raise VaultError("Only %s can edit this comment." % r["author"], 403)
            c.execute("UPDATE comment SET body=? WHERE id=?", (clean_text(body, MAX_BODY, "The comment", True), r["id"]))
        return _rec(c.execute("SELECT * FROM comment WHERE id=?", (r["id"],)).fetchone())


def delete(v: Vault, cid: int, who: str = "") -> dict:
    who = clean_text(who or me_author(), 100, "The author")
    with v.write() as c:
        r = c.execute("SELECT * FROM comment WHERE id=?", (int(cid),)).fetchone()
        if r is None:
            raise VaultError("There is no comment %s." % cid, 404)
        if r["author"] != who:
            raise VaultError("Only %s can delete this comment." % r["author"], 403)
        n = c.execute("DELETE FROM comment WHERE id=? OR parent=?", (r["id"], r["id"])).rowcount
    return {"deleted": n}


def markup(v: Vault, cid: int) -> str:
    with v.read() as c:
        r = c.execute("SELECT markup FROM comment WHERE id=?", (int(cid),)).fetchone()
        if r is None or not r["markup"]:
            raise VaultError("The comment has no markup.", 404)
        return v.get(c, bytes(r["markup"])).decode("utf-8")
