import json
import os
import re
import threading

from app.core import config
from app.vault import commit, history
from app.vault.base import MAX_VAULTS, VaultError, author as me_author, clean_text, digest, machine as me_machine, now
from app.vault.store import DB_NAME, Vault

_lock = threading.RLock()
_open: dict = {}
DEFAULT_ID = "default"


def _registry_file() -> str:
    folder = os.path.join(str(config.data_dir()), "vaults")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "registry.json")


def _default_folder() -> str:
    return os.path.join(str(config.data_dir()), "vaults", DEFAULT_ID)


def _load() -> list:
    try:
        with open(_registry_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = data.get("vaults", []) if isinstance(data, dict) else []
    except (OSError, ValueError):
        items = []
    return [x for x in items if isinstance(x, dict) and x.get("id") and x.get("folder")]


def _save(items: list) -> None:
    from app.doc import container

    container.atomic_write(_registry_file(), json.dumps({"vaults": items}, indent=1).encode("utf-8"))


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:24] or "vault"
    return s


def checked_folder(folder: str, must_exist: bool) -> str:
    raw = os.path.expanduser(str(folder or "").strip())
    if not raw or "\x00" in raw:
        raise VaultError("A vault folder is required.")
    full = os.path.abspath(raw)
    if os.path.exists(full) and not os.path.isdir(full):
        raise VaultError("The vault folder name is a file.")
    if must_exist:
        if not os.path.isfile(os.path.join(full, DB_NAME)):
            raise VaultError("There is no vault in %s." % full)
        return os.path.realpath(full)
    if not os.path.isdir(os.path.dirname(full)):
        raise VaultError("The folder %s does not exist." % os.path.dirname(full))
    if os.path.isdir(full) and os.listdir(full):
        if os.path.isfile(os.path.join(full, DB_NAME)):
            raise VaultError("There is already a vault in %s; attach it instead." % full)
        raise VaultError("The folder %s is not empty." % full)
    return os.path.realpath(os.path.dirname(full)) + os.sep + os.path.basename(full)


def _instance(folder: str, create: bool = False) -> Vault:
    key = os.path.realpath(folder)
    with _lock:
        v = _open.get(key)
        if v is None:
            v = Vault(key, create)
            _open[key] = v
        return v


def vault_record(item: dict, v: Vault | None = None) -> dict:
    rec = {"id": item["id"], "name": item.get("name") or item["id"], "folder": item["folder"], "default": item["id"] == DEFAULT_ID, "created": item.get("created", 0), "author": me_author(), "machine": me_machine(), "available": True, "docs": 0, "versions": 0, "objects": 0, "bytes": 0}
    try:
        v = v or _instance(item["folder"])
        rec.update(v.stats())
    except VaultError as err:
        rec["available"] = False
        rec["problem"] = err.message
    return rec


def listing() -> list:
    get(DEFAULT_ID)
    return [vault_record(x) for x in _load()]


def get(vid: str = "") -> Vault:
    vid = (vid or DEFAULT_ID).strip()
    with _lock:
        items = _load()
        item = next((x for x in items if x["id"] == vid), None)
        if item is None and vid == DEFAULT_ID:
            item = {"id": DEFAULT_ID, "name": "Local vault", "folder": _default_folder(), "created": now()}
            v = _instance(item["folder"], True)
            items.insert(0, item)
            _save(items)
            return v
        if item is None:
            raise VaultError("There is no vault %s." % vid, 404)
        if not os.path.isfile(os.path.join(item["folder"], DB_NAME)):
            raise VaultError("The vault folder %s is not available." % item["folder"], 404)
        return _instance(item["folder"])


def create(name: str, folder: str = "", attach: bool = False) -> dict:
    name = clean_text(name, 80, "The vault name", True)
    with _lock:
        items = _load()
        if len(items) >= MAX_VAULTS:
            raise VaultError("There are already %d vaults." % MAX_VAULTS)
        if folder:
            full = checked_folder(folder, attach)
        else:
            if attach:
                raise VaultError("Give the folder of the vault to attach.")
            full = os.path.join(str(config.data_dir()), "vaults", _slug(name) + "-" + digest(os.urandom(8)).hex()[:4])
        if any(os.path.realpath(x["folder"]) == os.path.realpath(full) for x in items):
            raise VaultError("That folder is already a registered vault.")
        v = _instance(full, not attach)
        vid = _slug(name)
        while any(x["id"] == vid for x in items) or vid == DEFAULT_ID:
            vid = _slug(name) + "-" + digest(os.urandom(8)).hex()[:4]
        item = {"id": vid, "name": name, "folder": v.folder, "created": now()}
        items.append(item)
        _save(items)
        return vault_record(item, v)


def forget(vid: str) -> dict:
    if vid == DEFAULT_ID:
        raise VaultError("The local vault cannot be removed.")
    with _lock:
        items = _load()
        item = next((x for x in items if x["id"] == vid), None)
        if item is None:
            raise VaultError("There is no vault %s." % vid, 404)
        _save([x for x in items if x["id"] != vid])
        _open.pop(os.path.realpath(item["folder"]), None)
    return {"forgotten": vid, "folder": item["folder"]}


def record_of(v: Vault) -> dict:
    for x in _load():
        if os.path.realpath(x["folder"]) == v.folder:
            return vault_record(x, v)
    return vault_record({"id": DEFAULT_ID, "name": "Local vault", "folder": v.folder}, v)


def vault_id_of(v: Vault) -> str:
    for x in _load():
        if os.path.realpath(x["folder"]) == v.folder:
            return x["id"]
    return DEFAULT_ID


def resolve_ref(vref: dict, log: list) -> str:
    try:
        v = get(str(vref.get("id") or vref.get("vault") or DEFAULT_ID))
        doc = str(vref.get("doc") or "")
        with v.read() as c:
            d = history.doc_row(c, doc)
            ver = str(vref.get("version") or "")
            if ver:
                h = bytes(history.version_row(c, ver, doc)["hash"])
            elif str(vref.get("follow") or "head") == "released":
                row = c.execute("SELECT version.hash FROM version JOIN lifecycle ON lifecycle.version=version.hash WHERE version.doc=? AND lifecycle.state='released' ORDER BY version.ts DESC LIMIT 1", (doc,)).fetchone()
                h = bytes(row[0]) if row else history.head_of(c, doc, d["default_branch"])
            else:
                h = history.head_of(c, doc, d["default_branch"])
            if h is None:
                raise VaultError("The document has no versions.")
            data, same = commit.container_of(v, c, h)
        folder = os.path.join(v.folder, "materialized", doc)
        target = os.path.join(folder, h.hex()[:16] + ".fcad")
        if not (os.path.isfile(target) and digest(open(target, "rb").read()) == digest(data)):
            os.makedirs(folder, exist_ok=True)
            from app.doc import container

            container.atomic_write(target, data, 0o444)
        log.append({"step": "vault", "path": target, "found": True})
        return os.path.realpath(target)
    except (VaultError, OSError) as err:
        log.append({"step": "vault", "path": "", "found": False, "note": getattr(err, "message", str(err))})
        return ""
