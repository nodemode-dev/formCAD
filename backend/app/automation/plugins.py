import hashlib
import importlib.metadata
import importlib.util
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

from app.automation import macros
from app.cmd import registry
from app.core import config

API_VERSION = 1
GROUP = "formcad.plugins"
MANIFEST = "plugin.json"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
MAX_FILE = 4_000_000
_lock = threading.RLock()
LOADED: dict = {}
FAILED: dict = {}


class PluginError(Exception):
    pass


def folder() -> Path:
    path = config.data_dir() / "plugins"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read(MAX_FILE + 1))
    return h.hexdigest()


def read_manifest(directory: Path) -> dict:
    try:
        data = json.loads((directory / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise PluginError("plugin.json cannot be read: %s" % err)
    if not isinstance(data, dict):
        raise PluginError("plugin.json must be an object.")
    pid = data.get("id")
    if not isinstance(pid, str) or not ID_PATTERN.match(pid):
        raise PluginError("The id is 2 to 64 characters: lower-case letters, digits, dot, dash, underscore.")
    if not isinstance(data.get("version"), str):
        raise PluginError("The manifest needs a version string.")
    entry = data.get("entry", "plugin.py")
    if not isinstance(entry, str) or not entry.endswith(".py") or os.path.isabs(entry) or ".." in Path(entry).parts:
        raise PluginError("The entry is a relative .py path inside the plugin folder.")
    files = data.get("files")
    if not isinstance(files, dict) or entry not in files:
        raise PluginError("The files table must list the entry file with its sha256.")
    for name, digest in files.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or os.path.isabs(name) or ".." in Path(name).parts:
            raise PluginError("The files table holds relative paths with sha256 values.")
    api = data.get("api", API_VERSION)
    low, high = (api, api) if isinstance(api, int) else (api[0], api[1]) if isinstance(api, list) and len(api) == 2 else (0, -1)
    if not (isinstance(low, int) and isinstance(high, int) and low <= API_VERSION <= high):
        raise PluginError("This plugin needs plugin API %s; FormCAD offers %d." % (api, API_VERSION))
    data["entry"] = entry
    return data


def check_hashes(directory: Path, manifest: dict) -> list:
    problems = []
    listed = set()
    for name, digest in manifest["files"].items():
        listed.add(os.path.normpath(name))
        target = directory / name
        if not target.is_file():
            problems.append("%s is missing" % name)
        elif sha256_of(target) != digest:
            problems.append("%s changed" % name)
    for item in directory.rglob("*"):
        if item.is_file() and item.suffix in (".py", ".pyc", ".so", ".pyd", ".dll") and os.path.normpath(str(item.relative_to(directory))) not in listed and "__pycache__" not in item.parts:
            problems.append("%s is not in the manifest" % item.relative_to(directory))
    return problems


def manifest_digest(directory: Path) -> str:
    return sha256_of(directory / MANIFEST)


def seal(directory: str) -> dict:
    root = Path(os.path.realpath(os.path.expanduser(directory)))
    path = root / MANIFEST
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        raise PluginError("plugin.json cannot be read: %s" % err)
    entry = data.get("entry", "plugin.py")
    files = {}
    for item in sorted(root.rglob("*.py")):
        if "__pycache__" in item.parts:
            continue
        files[item.relative_to(root).as_posix()] = sha256_of(item)
    if entry not in files:
        raise PluginError("The entry file %s does not exist." % entry)
    data["files"] = files
    data.setdefault("entry", entry)
    data.setdefault("api", API_VERSION)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return data


def _flags() -> dict:
    data = macros.load_settings().get("plugins", {})
    return data if isinstance(data, dict) else {}


def _store(plugin_id: str, record: dict | None) -> None:
    with _lock:
        data = macros.load_settings()
        table = data.setdefault("plugins", {})
        if record is None:
            table.pop(plugin_id, None)
        else:
            table[plugin_id] = record
        macros.save_settings(data)


def entry_point_items() -> list:
    try:
        found = importlib.metadata.entry_points(group=GROUP)
    except Exception:
        return []
    out = []
    for ep in found:
        dist = getattr(ep, "dist", None)
        out.append({"id": "ep:" + ep.name, "tier": "entry-point", "name": ep.name, "version": getattr(dist, "version", "") if dist else "", "package": getattr(dist, "name", "") if dist else "", "target": ep.value, "ep": ep})
    return out


def discover() -> list:
    flags = _flags()
    items = []
    for ep in entry_point_items():
        rec = flags.get(ep["id"], {})
        enabled = bool(rec.get("enabled")) and rec.get("version") == ep["version"]
        item = {k: v for k, v in ep.items() if k != "ep"}
        item.update({"description": "", "enabled": enabled, "problems": [] if not rec.get("enabled") or enabled else ["the installed version changed since it was enabled"], "permissions": []})
        items.append(item)
    base = folder()
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        item = {"tier": "folder", "path": str(directory), "id": directory.name, "name": directory.name, "version": "", "description": "", "permissions": [], "problems": [], "enabled": False}
        try:
            manifest = read_manifest(directory)
        except PluginError as err:
            item["problems"] = [str(err)]
            items.append(item)
            continue
        item.update({"id": manifest["id"], "name": manifest.get("name", manifest["id"]), "version": manifest["version"], "description": manifest.get("description", ""), "permissions": list(manifest.get("permissions", [])), "entry": manifest["entry"], "files": manifest["files"]})
        rec = flags.get(manifest["id"], {})
        problems = check_hashes(directory, manifest)
        digest = manifest_digest(directory)
        if rec.get("enabled") and rec.get("manifestSha256") != digest:
            problems.append("the manifest changed since it was enabled")
        item["problems"] = problems
        item["manifestSha256"] = digest
        item["enabled"] = bool(rec.get("enabled")) and not problems
        items.append(item)
    for item in items:
        pid = item["id"]
        was_enabled = bool(flags.get(pid, {}).get("enabled"))
        if pid in LOADED:
            item["state"] = "loaded"
        elif pid in FAILED:
            item["state"] = "failed"
        elif item["enabled"]:
            item["state"] = "enabled"
        elif item["problems"]:
            item["state"] = "mismatch" if was_enabled else "invalid"
        else:
            item["state"] = "disabled"
        item["error"] = FAILED.get(pid, "")
        item["commands"] = list(LOADED.get(pid, {}).get("commands", []))
    return items


class Api:
    def __init__(self, plugin_id: str):
        self.plugin_id = plugin_id
        self.commands: list = []
        self.api_version = API_VERSION

    def command(self, name, aliases=(), group="plugin", label="", description="", menu="", transparent=False, undoable=True, repeatable=True):
        key = name.lower()
        if key in registry.COMMANDS and key not in self.commands:
            raise PluginError("The command %s already exists." % key.upper())
        for a in aliases:
            if a.lower() in registry.ALIASES and registry.ALIASES[a.lower()] != key:
                raise PluginError("The alias %s is already used." % a.upper())
        inner = registry.command(name, aliases, group, label, description, menu, transparent, undoable, repeatable)

        def wrap(fn):
            out = inner(fn)
            self.commands.append(key)
            return out

        return wrap

    def executes(self, *names):
        for n in names:
            if n.lower() not in self.commands:
                raise PluginError("Declare the command %s with api.command first." % n)
        return registry.executes(*names)

    def log(self, message):
        sys.stderr.write("[plugin %s] %s\n" % (self.plugin_id, message))


def _unregister(commands: list) -> None:
    for name in commands:
        spec = registry.COMMANDS.pop(name, None)
        if spec is not None:
            for a in spec.aliases:
                if registry.ALIASES.get(a) == name:
                    registry.ALIASES.pop(a, None)


def _load_module(plugin_id: str, path: Path):
    spec = importlib.util.spec_from_file_location("formcad_plugin_" + re.sub(r"\W", "_", plugin_id), str(path), submodule_search_locations=[str(path.parent)])
    if spec is None or spec.loader is None:
        raise PluginError("The entry file cannot be imported.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load(plugin_id: str) -> dict:
    with _lock:
        if plugin_id in LOADED:
            return LOADED[plugin_id]
        item = next((i for i in discover() if i["id"] == plugin_id), None)
        if item is None:
            raise PluginError("No such plugin.")
        if not item["enabled"]:
            raise PluginError("The plugin is not enabled." if not item["problems"] else "Not loaded: " + "; ".join(item["problems"]))
        api = Api(plugin_id)
        try:
            if item["tier"] == "entry-point":
                ep = next(e for e in importlib.metadata.entry_points(group=GROUP) if "ep:" + e.name == plugin_id)
                target = ep.load()
                register = target if callable(target) else getattr(target, "register", None)
            else:
                module = _load_module(plugin_id, Path(item["path"]) / item["entry"])
                register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError("The plugin defines no register(api) function.")
            register(api)
        except Exception as err:
            _unregister(api.commands)
            FAILED[plugin_id] = "%s: %s" % (type(err).__name__, err)
            raise PluginError(FAILED[plugin_id])
        FAILED.pop(plugin_id, None)
        LOADED[plugin_id] = {"commands": list(api.commands), "loadedAt": time.time()}
        return LOADED[plugin_id]


def unload(plugin_id: str) -> None:
    with _lock:
        info = LOADED.pop(plugin_id, None)
        if info:
            _unregister(info["commands"])


def set_enabled(plugin_id: str, enabled: bool, manifest_sha256: str = "") -> dict:
    registry.load_modules()
    item = next((i for i in discover() if i["id"] == plugin_id), None)
    if item is None:
        raise PluginError("No such plugin.")
    if not enabled:
        unload(plugin_id)
        _store(plugin_id, None)
    else:
        if item.get("problems") and item.get("tier") == "folder" and not item.get("enabled"):
            raise PluginError("Not enabled: " + "; ".join(item["problems"]))
        if item["tier"] == "folder":
            if not manifest_sha256:
                raise PluginError("Enabling a plugin needs the manifest hash that was shown; use the plugin manager.")
            if manifest_sha256 != item["manifestSha256"]:
                raise PluginError("The plugin changed after it was shown. Review it again.")
            _store(plugin_id, {"enabled": True, "manifestSha256": item["manifestSha256"], "version": item["version"], "at": int(time.time())})
        else:
            _store(plugin_id, {"enabled": True, "version": item["version"], "at": int(time.time())})
        load(plugin_id)
    from app.automation import mcp

    mcp.reset_tools()
    return next(i for i in discover() if i["id"] == plugin_id)


def load_enabled() -> None:
    for item in discover():
        if item["enabled"] and item["id"] not in LOADED:
            try:
                load(item["id"])
            except PluginError:
                continue
