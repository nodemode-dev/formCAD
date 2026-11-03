import json
import os

from app.vault.base import VaultError, hexed
from app.vault.history import version_row


def scan(doc_raw: bytes) -> list:
    if (b'"components"' not in doc_raw or b'"components":[]' in doc_raw) and b'"xref"' not in doc_raw:
        return []
    try:
        doc = json.loads(doc_raw)
    except ValueError:
        return []
    tables = doc.get("tables") if isinstance(doc, dict) else None
    if not isinstance(tables, dict):
        return []
    found = []
    for rec in tables.get("components") or []:
        if not isinstance(rec, dict) or rec.get("type") == "embedded":
            continue
        ref = rec.get("ref") if isinstance(rec.get("ref"), dict) else {}
        sig = rec.get("sig") if isinstance(rec.get("sig"), dict) else {}
        found.append({"comp": str(rec.get("id") or rec.get("name") or ""), "path": str(ref.get("path") or ref.get("abs") or ""), "sha256": str(sig.get("sha256") or ""), "vault": ref.get("vault") if isinstance(ref.get("vault"), dict) else None})
    for rec in tables.get("blocks") or []:
        x = rec.get("xref") if isinstance(rec, dict) else None
        if isinstance(x, dict) and x.get("path") and "|" not in str(rec.get("name", "")):
            found.append({"comp": "xref:" + str(rec.get("name")), "path": str(x.get("path")), "sha256": "", "vault": None})
    return found[:5000]


def resolve(c, from_path: str, item: dict, own_doc: str) -> dict:
    vref = item.get("vault")
    if vref and vref.get("doc"):
        to_doc = str(vref.get("doc"))
        if c.execute("SELECT 1 FROM doc WHERE id=?", (to_doc,)).fetchone():
            ver = str(vref.get("version") or "")
            if ver:
                try:
                    return {"to_doc": to_doc, "to_version": bytes(version_row(c, ver, to_doc)["hash"]), "mode": "pinned"}
                except VaultError:
                    pass
            return {"to_doc": to_doc, "to_version": None, "mode": "floating"}
    if item.get("sha256"):
        row = c.execute("SELECT hash, doc FROM version WHERE sha256=? ORDER BY ts DESC LIMIT 1", (item["sha256"],)).fetchone()
        if row and row["doc"] != own_doc:
            return {"to_doc": row["doc"], "to_version": bytes(row["hash"]), "mode": "pinned"}
    if item.get("path") and from_path:
        target = item["path"]
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(from_path), target)
        b = c.execute("SELECT doc FROM binding WHERE path=?", (os.path.realpath(target),)).fetchone()
        if b and b["doc"] != own_doc:
            return {"to_doc": b["doc"], "to_version": None, "mode": "floating"}
    return {"to_doc": None, "to_version": None, "mode": "outside"}


def record(c, version: bytes, doc: str, doc_raw: bytes, from_path: str) -> int:
    n = 0
    for item in scan(doc_raw):
        r = resolve(c, from_path, item, doc)
        c.execute("INSERT INTO extref(version, from_doc, comp, to_doc, to_version, to_path, mode) VALUES(?,?,?,?,?,?,?)", (version, doc, item["comp"], r["to_doc"], r["to_version"], item["path"], r["mode"]))
        n += 1
    return n


def children(c, version: bytes) -> list:
    out = []
    for r in c.execute("SELECT * FROM extref WHERE version=? ORDER BY comp", (version,)).fetchall():
        out.append({"comp": r["comp"], "doc": r["to_doc"], "version": hexed(r["to_version"]) if r["to_version"] else "", "path": r["to_path"], "mode": r["mode"]})
    return out
