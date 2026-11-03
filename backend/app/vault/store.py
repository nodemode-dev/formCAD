import contextlib
import json
import os
import sqlite3
import threading
import zlib

from app.vault import cdc
from app.vault.base import CHUNK_FROM, FORMAT, INLINE, VaultError, digest, hexed, now

SCHEMA = [
    "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS object(hash BLOB PRIMARY KEY, kind TEXT NOT NULL, size INTEGER NOT NULL, stored INTEGER NOT NULL, codec TEXT NOT NULL, blob BLOB, path TEXT)",
    "CREATE TABLE IF NOT EXISTS tree(hash BLOB NOT NULL, name TEXT NOT NULL, mode INTEGER NOT NULL, child BLOB NOT NULL, PRIMARY KEY(hash, name))",
    "CREATE TABLE IF NOT EXISTS doc(id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, created INTEGER NOT NULL, default_branch TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS version(hash BLOB PRIMARY KEY, doc TEXT NOT NULL REFERENCES doc(id), root BLOB NOT NULL, author TEXT NOT NULL, ts INTEGER NOT NULL, message TEXT NOT NULL, format INTEGER NOT NULL, size INTEGER NOT NULL, members INTEGER NOT NULL, container BLOB NOT NULL, sha256 TEXT NOT NULL, recipe BLOB NOT NULL, raw BLOB)",
    "CREATE TABLE IF NOT EXISTS parent(version BLOB NOT NULL REFERENCES version(hash), parent BLOB NOT NULL, ord INTEGER NOT NULL, PRIMARY KEY(version, ord))",
    "CREATE TABLE IF NOT EXISTS ref(doc TEXT NOT NULL REFERENCES doc(id), name TEXT NOT NULL, version BLOB NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(doc, name))",
    "CREATE TABLE IF NOT EXISTS lifecycle(version BLOB PRIMARY KEY, state TEXT NOT NULL, revision TEXT NOT NULL, ts INTEGER NOT NULL, author TEXT NOT NULL, note TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, author TEXT NOT NULL, machine TEXT NOT NULL, doc TEXT NOT NULL, version BLOB, action TEXT NOT NULL, detail TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS lock(doc TEXT PRIMARY KEY REFERENCES doc(id), owner TEXT NOT NULL, machine TEXT NOT NULL, since INTEGER NOT NULL, base BLOB NOT NULL, path TEXT NOT NULL, note TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS binding(path TEXT PRIMARY KEY, doc TEXT NOT NULL REFERENCES doc(id), branch TEXT NOT NULL, base BLOB NOT NULL, hash BLOB NOT NULL, edit INTEGER NOT NULL, ts INTEGER NOT NULL)",
    "CREATE TABLE IF NOT EXISTS comment(id INTEGER PRIMARY KEY, doc TEXT NOT NULL REFERENCES doc(id), version BLOB NOT NULL, entity TEXT NOT NULL, anchor TEXT NOT NULL, author TEXT NOT NULL, ts INTEGER NOT NULL, parent INTEGER, status TEXT NOT NULL, body TEXT NOT NULL, markup BLOB, camera TEXT)",
    "CREATE TABLE IF NOT EXISTS extref(version BLOB NOT NULL, from_doc TEXT NOT NULL, comp TEXT NOT NULL, to_doc TEXT, to_version BLOB, to_path TEXT NOT NULL, mode TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS merge(doc TEXT PRIMARY KEY REFERENCES doc(id), branch TEXT NOT NULL, ours BLOB NOT NULL, theirs BLOB NOT NULL, base BLOB, report TEXT NOT NULL, choices TEXT NOT NULL, started INTEGER NOT NULL, author TEXT NOT NULL)",
    "CREATE INDEX IF NOT EXISTS extref_to ON extref(to_doc)",
    "CREATE INDEX IF NOT EXISTS extref_ver ON extref(version)",
    "CREATE INDEX IF NOT EXISTS version_doc ON version(doc, ts)",
    "CREATE INDEX IF NOT EXISTS comment_doc ON comment(doc)",
    "CREATE INDEX IF NOT EXISTS parent_p ON parent(parent)",
]
STRICT_TABLES = {"meta", "object", "tree", "doc", "version", "parent", "ref", "lifecycle", "audit", "lock", "binding", "comment", "extref", "merge"}
DB_NAME = "vault.sqlite"


def _schema_sql() -> list:
    strict = sqlite3.sqlite_version_info >= (3, 37, 0)
    out = []
    for stmt in SCHEMA:
        if strict and stmt.startswith("CREATE TABLE"):
            name = stmt.split("(", 1)[0].split()[-1]
            if name in STRICT_TABLES:
                stmt += " STRICT"
        out.append(stmt)
    return out


class Vault:
    def __init__(self, folder: str, create: bool = False):
        self.folder = os.path.realpath(folder)
        self.db_path = os.path.join(self.folder, DB_NAME)
        self.lock = threading.RLock()
        if create:
            os.makedirs(self.folder, exist_ok=True)
        elif not os.path.isfile(self.db_path):
            raise VaultError("There is no vault in %s." % self.folder, 404)
        os.makedirs(os.path.join(self.folder, "objects"), exist_ok=True)
        os.makedirs(os.path.join(self.folder, "materialized"), exist_ok=True)
        with self.write() as c:
            for stmt in _schema_sql():
                c.execute(stmt)
            row = c.execute("SELECT value FROM meta WHERE key='format'").fetchone()
            if row is None:
                c.execute("INSERT INTO meta(key, value) VALUES('format', ?)", (str(FORMAT),))
                c.execute("INSERT INTO meta(key, value) VALUES('created', ?)", (str(now()),))
            elif int(row[0]) > FORMAT:
                raise VaultError("This vault was written by a newer FormCAD (format %s)." % row[0])

    def _open(self):
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    @contextlib.contextmanager
    def read(self):
        conn = self._open()
        try:
            yield conn
        finally:
            conn.close()

    @contextlib.contextmanager
    def write(self):
        with self.lock:
            conn = self._open()
            try:
                conn.execute("BEGIN IMMEDIATE")
                try:
                    yield conn
                except BaseException:
                    conn.execute("ROLLBACK")
                    raise
                else:
                    conn.execute("COMMIT")
            finally:
                conn.close()

    def meta(self, key: str, default: str = "") -> str:
        with self.read() as c:
            row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self.write() as c:
            c.execute("INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def _object_file(self, h: bytes) -> str:
        x = h.hex()
        return os.path.join(self.folder, "objects", x[:2], x[2:4], x[4:])

    def _write_file(self, path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp%d" % threading.get_ident()
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def put(self, conn, data: bytes, kind: str = "member") -> bytes:
        h = digest(data)
        if conn.execute("SELECT 1 FROM object WHERE hash=?", (h,)).fetchone():
            return h
        codec, payload = "raw", data
        if len(data) > 256:
            packed = zlib.compress(data, 6)
            if len(packed) < len(data) * 0.9:
                codec, payload = "zlib", packed
        if len(payload) <= INLINE:
            conn.execute("INSERT INTO object(hash, kind, size, stored, codec, blob, path) VALUES(?,?,?,?,?,?,NULL)", (h, kind, len(data), len(payload), codec, payload))
        else:
            path = self._object_file(h)
            self._write_file(path, payload)
            conn.execute("INSERT INTO object(hash, kind, size, stored, codec, blob, path) VALUES(?,?,?,?,?,NULL,?)", (h, kind, len(data), len(payload), codec, os.path.relpath(path, self.folder)))
        return h

    def get(self, conn, h: bytes, check: bool = True) -> bytes:
        row = conn.execute("SELECT codec, blob, path, size FROM object WHERE hash=?", (h,)).fetchone()
        if row is None:
            raise VaultError("The vault is missing object %s." % h.hex()[:12], 500)
        payload = row["blob"]
        if payload is None:
            try:
                with open(self._object_file(h), "rb") as fh:
                    payload = fh.read()
            except OSError as err:
                raise VaultError("The vault cannot read object %s: %s" % (h.hex()[:12], err.strerror or "unreadable"), 500)
        try:
            if row["codec"] == "zlib":
                inflater = zlib.decompressobj()
                data = inflater.decompress(payload, row["size"] + 1)
                if inflater.unconsumed_tail:
                    raise zlib.error("larger than recorded")
            else:
                data = bytes(payload)
        except zlib.error:
            raise VaultError("Object %s is damaged." % h.hex()[:12], 500)
        if check and (len(data) != row["size"] or digest(data) != h):
            raise VaultError("Object %s fails its hash check." % h.hex()[:12], 500)
        return data

    def put_member(self, conn, data: bytes) -> tuple:
        if len(data) < CHUNK_FROM:
            return 0, self.put(conn, data, "member")
        ends = cdc.cut(data)
        ids = []
        start = 0
        for end in ends:
            ids.append(self.put(conn, data[start:end], "chunk").hex())
            start = end
        listing = json.dumps({"chunker": cdc.NAME, "size": len(data), "chunks": ids}, separators=(",", ":")).encode()
        return 1, self.put(conn, listing, "chunks")

    def get_member(self, conn, mode: int, h: bytes) -> bytes:
        if mode == 0:
            return self.get(conn, h)
        listing = json.loads(self.get(conn, h))
        data = b"".join(self.get(conn, bytes.fromhex(x)) for x in listing["chunks"])
        if len(data) != listing["size"]:
            raise VaultError("A chunked member is shorter than recorded.", 500)
        return data

    def put_tree(self, conn, entries: list) -> bytes:
        rows = sorted(entries, key=lambda e: e[0])
        text = "".join("%d %s %s\n" % (mode, child.hex(), name) for name, mode, child in rows).encode("utf-8")
        h = digest(text)
        if not conn.execute("SELECT 1 FROM tree WHERE hash=? LIMIT 1", (h,)).fetchone():
            conn.executemany("INSERT INTO tree(hash, name, mode, child) VALUES(?,?,?,?)", [(h, name, mode, child) for name, mode, child in rows])
        return h

    def tree(self, conn, h: bytes) -> list:
        rows = conn.execute("SELECT name, mode, child FROM tree WHERE hash=? ORDER BY name", (h,)).fetchall()
        return [(r["name"], r["mode"], bytes(r["child"])) for r in rows]

    def audit(self, conn, who: str, machine: str, doc: str, version, action: str, detail) -> None:
        conn.execute("INSERT INTO audit(ts, author, machine, doc, version, action, detail) VALUES(?,?,?,?,?,?,?)", (now(), who, machine, doc, version, action, json.dumps(detail, separators=(",", ":")) if not isinstance(detail, str) else detail))

    def stats(self) -> dict:
        with self.read() as c:
            g = lambda sql: c.execute(sql).fetchone()[0] or 0
            return {"docs": g("SELECT COUNT(*) FROM doc"), "versions": g("SELECT COUNT(*) FROM version"), "objects": g("SELECT COUNT(*) FROM object"), "bytes": g("SELECT SUM(stored) FROM object")}


def hexrow(value) -> str:
    return hexed(bytes(value)) if value is not None else ""
