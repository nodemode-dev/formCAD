import json
import os
import stat
import tempfile
import zipfile
from datetime import datetime, timezone

from app import __version__
from app.doc import tables as T
from app.doc.model import Drawing

FORMAT = "formcad"
SCHEMA = 1
MAX_FILE = 512 * 1024 * 1024
MAX_PART = 512 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MAX_ENTRIES = 20000
RESERVED_DIRS = ("parts/", "assemblies/", "graphs/", "cache/")
MANIFEST = "manifest.json"
DOCUMENT = "document.json"


class ContainerError(Exception):
    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.message = message
        self.code = code


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _reject_constant(name):
    raise ValueError("non-finite number " + name)


def build_manifest(drawing: Drawing, title: str, created: str, modified: str | None = None, kind: str = "drawing") -> dict:
    h = drawing.header
    return {
        "format": FORMAT,
        "schema": SCHEMA,
        "app": {"name": "FormCAD", "version": __version__},
        "kind": kind,
        "title": title,
        "units": {"insunits": h.get("INSUNITS", 0), "lunits": h.get("LUNITS", 2), "luprec": h.get("LUPREC", 4), "aunits": h.get("AUNITS", 0), "aprec": h.get("AUPREC", 0), "measurement": h.get("MEASUREMENT", 1)},
        "created": created,
        "modified": modified or _now(),
        "contents": {"document": DOCUMENT, "reserved": list(RESERVED_DIRS)},
    }


def encode(drawing: Drawing, title: str, created: str, kind: str = "drawing", keep_edits: bool = False) -> bytes:
    import io

    from app.doc import editstate

    try:
        doc_bytes = json.dumps(editstate.persistent_dict(drawing, keep_edits), separators=(",", ":"), allow_nan=False).encode("utf-8")
        man_bytes = json.dumps(build_manifest(drawing, title, created, None, kind), indent=2, allow_nan=False).encode("utf-8")
    except ValueError as err:
        raise ContainerError("The drawing holds numbers that cannot be stored: " + str(err), "nonfinite")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        zf.writestr(MANIFEST, man_bytes)
        zf.writestr(DOCUMENT, doc_bytes)
        for name in RESERVED_DIRS:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
            zf.writestr(info, b"")
        from app.solid import blobs

        for name, data in blobs.container_entries(drawing):
            zf.writestr(name, data)
    return buf.getvalue()


def _complete(path: str) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            return MANIFEST in names and DOCUMENT in names
    except (OSError, zipfile.BadZipFile):
        return False


def _fsync_dir(folder: str) -> None:
    try:
        fd = os.open(folder, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write(dest: str, data: bytes, mode: int | None = None) -> None:
    dest = os.path.realpath(dest)
    folder = os.path.dirname(dest) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".fcad-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is None and os.path.exists(dest):
            mode = stat.S_IMODE(os.stat(dest).st_mode)
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _fsync_dir(folder)


def save(path: str, drawing: Drawing, title: str, created: str, backup: bool = True, kind: str = "drawing") -> str:
    if not path:
        raise ContainerError("No file name given.", "nopath")
    dest = os.path.realpath(os.path.expanduser(path))
    if os.path.isdir(dest):
        raise ContainerError("The path is a folder.", "isdir")
    data = encode(drawing, title, created, kind)
    try:
        if backup and os.path.isfile(dest) and _complete(dest):
            with open(dest, "rb") as fh:
                old = fh.read()
            atomic_write(dest + ".bak", old)
        atomic_write(dest, data)
    except OSError as err:
        raise ContainerError("Could not write the file: " + str(err), "io")
    return dest


def read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        info = zf.getinfo(MANIFEST)
    except KeyError:
        raise ContainerError("The file has no manifest.json and is not a FormCAD project.", "nomanifest")
    if info.file_size > MAX_MANIFEST:
        raise ContainerError("The manifest is too large.", "toolarge")
    try:
        man = json.loads(zf.read(info), parse_constant=_reject_constant)
    except ValueError as err:
        raise ContainerError("The manifest is not valid JSON: " + str(err), "badjson")
    if not isinstance(man, dict) or man.get("format") != FORMAT:
        raise ContainerError("Not a FormCAD project (format is " + repr(man.get("format") if isinstance(man, dict) else None) + ").", "badformat")
    schema = man.get("schema")
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 1:
        raise ContainerError("The manifest has an invalid schema number.", "badschema")
    if schema > SCHEMA:
        raise ContainerError("This project uses schema " + str(schema) + " from a newer FormCAD; this version reads schema " + str(SCHEMA) + ".", "newer")
    return man


def validate_document(data) -> None:
    if not isinstance(data, dict):
        raise ContainerError("document.json must hold an object.", "baddoc")
    if not isinstance(data.get("header", {}), dict):
        raise ContainerError("document.json: header must be an object.", "baddoc")
    tables = data.get("tables", {})
    if not isinstance(tables, dict):
        raise ContainerError("document.json: tables must be an object.", "baddoc")
    for name, items in tables.items():
        if not isinstance(items, list):
            raise ContainerError("document.json: table " + str(name) + " must be a list.", "baddoc")
        for i, rec in enumerate(items):
            if not isinstance(rec, dict) or not isinstance(rec.get("name"), str):
                raise ContainerError("document.json: table " + str(name) + " record " + str(i) + " has no name.", "baddoc")
    ents = data.get("entities", [])
    if not isinstance(ents, list):
        raise ContainerError("document.json: entities must be a list.", "baddoc")
    for i, e in enumerate(ents):
        if not isinstance(e, dict) or not isinstance(e.get("kind"), str):
            raise ContainerError("document.json: entity " + str(i) + " has no kind.", "baddoc")
        h = e.get("handle")
        if not isinstance(h, int) or isinstance(h, bool) or h <= 0:
            raise ContainerError("document.json: entity " + str(i) + " has an invalid handle.", "baddoc")
        if not isinstance(e.get("owner", "model"), str):
            raise ContainerError("document.json: entity " + str(i) + " has an invalid owner.", "baddoc")
    for key in ("parts", "assemblies", "pmi", "graphs"):
        if not isinstance(data.get(key, []), list):
            raise ContainerError("document.json: " + key + " must be a list.", "baddoc")


def repair(d: Drawing) -> None:
    if not d.tables["layers"].has("0"):
        d.tables["layers"].put(T.new_layer("0"))
    for rec in T.standard_linetypes(d.metric)[:3]:
        if not d.tables["linetypes"].has(rec["name"]):
            d.tables["linetypes"].put(rec)
    if not d.tables["textstyles"].has("Standard"):
        d.tables["textstyles"].put(T.new_textstyle("Standard"))
    if not d.tables["dimstyles"].has("Standard"):
        d.tables["dimstyles"].put(T.new_dimstyle("Standard"))
    for e in d.ents.values():
        if not e.layer:
            e.layer = "0"
        if not d.tables["layers"].has(e.layer):
            d.tables["layers"].put(T.new_layer(e.layer))
    if not d.tables["layers"].has(str(d.header.get("CLAYER", "0"))):
        d.header["CLAYER"] = "0"


def load(path: str):
    src = os.path.realpath(os.path.expanduser(path))
    try:
        st = os.stat(src)
    except OSError as err:
        raise ContainerError("Cannot open the file: " + str(err), "io")
    if not stat.S_ISREG(st.st_mode):
        raise ContainerError("The path is not a regular file.", "notfile")
    if st.st_size > MAX_FILE:
        raise ContainerError("The file is larger than the 512 MB limit.", "toolarge")
    try:
        zf = zipfile.ZipFile(src)
    except zipfile.BadZipFile:
        raise ContainerError("The file is not a FormCAD container (not a zip archive).", "notzip")
    except OSError as err:
        raise ContainerError("Cannot open the file: " + str(err), "io")
    with zf:
        if len(zf.namelist()) > MAX_ENTRIES:
            raise ContainerError("The container has too many entries.", "toolarge")
        man = read_manifest(zf)
        try:
            info = zf.getinfo(DOCUMENT)
        except KeyError:
            raise ContainerError("The container has no document.json.", "nodoc")
        if info.file_size > MAX_PART:
            raise ContainerError("document.json is too large.", "toolarge")
        try:
            raw = zf.read(info)
        except (zipfile.BadZipFile, OSError, RuntimeError) as err:
            raise ContainerError("document.json cannot be read: " + str(err), "corrupt")
        from app.solid import blobs

        try:
            stored = blobs.read_entries(zf)
        except (zipfile.BadZipFile, OSError, RuntimeError) as err:
            raise ContainerError("A stored 3D part cannot be read: " + str(err), "corrupt")
    try:
        data = json.loads(raw, parse_constant=_reject_constant)
    except ValueError as err:
        raise ContainerError("document.json is not valid JSON: " + str(err), "badjson")
    validate_document(data)
    try:
        d = Drawing.from_dict(data)
    except (KeyError, TypeError, ValueError) as err:
        raise ContainerError("document.json could not be built: " + str(err), "baddoc")
    d.blobs.update(stored)
    repair(d)
    return d, man
