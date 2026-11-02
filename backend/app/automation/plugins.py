import hashlib
import importlib.abc
import importlib.machinery
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


CODE_SUFFIXES = (".py", ".so", ".pyd", ".dll", ".pth", ".json", ".txt")
MAX_DIGEST_FILES = 4000
_digests: dict = {}


def _digest_files(dist, target: str) -> list:
    paths = {}
    for rel in getattr(dist, "files", None) or []:
        name = str(rel)
        if "__pycache__" in name or name.endswith(".pyc") or name.endswith("RECORD"):
            continue
        try:
            full = Path(str(dist.locate_file(rel)))
        except Exception:
            continue
        if full.is_file():
            paths["dist/" + name.replace("\\", "/")] = full
    top = target.split(":")[0].split(".")[0].strip()
    if top:
        try:
            spec = importlib.util.find_spec(top)
        except Exception:
            spec = None
        if spec is not None:
            roots = [Path(p) for p in (spec.submodule_search_locations or [])]
            if not roots and spec.origin and spec.origin not in ("built-in", "frozen") and os.path.isfile(spec.origin):
                paths["module/" + Path(spec.origin).name] = Path(spec.origin)
            for root in roots:
                for item in sorted(root.rglob("*")):
                    if len(paths) > MAX_DIGEST_FILES:
                        break
                    if item.is_file() and item.suffix in CODE_SUFFIXES and "__pycache__" not in item.parts:
                        paths["module/" + item.relative_to(root).as_posix()] = item
    return sorted(paths.items())


def distribution_digest(dist, target: str) -> str:
    try:
        files = _digest_files(dist, target)
        key = (getattr(dist, "name", ""), getattr(dist, "version", ""), target, tuple((n, p.stat().st_mtime_ns, p.stat().st_size) for n, p in files))
    except OSError:
        return ""
    cached = _digests.get(key)
    if cached:
        return cached
    h = hashlib.sha256()
    for name, path in files:
        try:
            part = sha256_of(path)
        except OSError:
            return ""
        h.update(name.encode("utf-8") + b"\0" + part.encode("ascii") + b"\n")
    out = h.hexdigest()
    if len(_digests) > 32:
        _digests.clear()
    _digests[key] = out
    return out


def entry_point_items() -> list:
    try:
        found = importlib.metadata.entry_points(group=GROUP)
    except Exception:
        return []
    out = []
    for ep in found:
        dist = getattr(ep, "dist", None)
        digest = distribution_digest(dist, ep.value) if dist else ""
        out.append({"id": "ep:" + ep.name, "tier": "entry-point", "name": ep.name, "version": getattr(dist, "version", "") if dist else "", "package": getattr(dist, "name", "") if dist else "", "target": ep.value, "manifestSha256": digest, "ep": ep})
    return out


def discover() -> list:
    flags = _flags()
    items = []
    for ep in entry_point_items():
        rec = flags.get(ep["id"], {})
        problems = []
        if rec.get("enabled"):
            if rec.get("version") != ep["version"]:
                problems.append("the installed version changed since it was enabled")
            if not rec.get("distSha256"):
                problems.append("it was enabled before distribution hashes were recorded; enable it again")
            elif not ep["manifestSha256"] or rec.get("distSha256") != ep["manifestSha256"]:
                problems.append("the installed files changed since it was enabled")
        enabled = bool(rec.get("enabled")) and not problems
        item = {k: v for k, v in ep.items() if k != "ep"}
        item.update({"description": "", "enabled": enabled, "problems": problems, "permissions": []})
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


FINDERS: dict = {}


def read_verified(directory: Path, expected_manifest: str) -> tuple:
    try:
        raw = (directory / MANIFEST).read_bytes()
    except OSError as err:
        raise PluginError("plugin.json cannot be read: %s" % err)
    if hashlib.sha256(raw).hexdigest() != expected_manifest:
        raise PluginError("The manifest changed since it was enabled.")
    try:
        files = json.loads(raw.decode("utf-8"))["files"]
    except (ValueError, KeyError, TypeError):
        raise PluginError("plugin.json cannot be read.")
    blobs = {}
    for name, digest in files.items():
        try:
            data = (directory / name).read_bytes()
        except OSError:
            raise PluginError("%s is missing" % name)
        if len(data) > MAX_FILE or hashlib.sha256(data).hexdigest() != digest:
            raise PluginError("%s changed" % name)
        blobs[os.path.normpath(name)] = data
    return files, blobs


class VerifiedImporter(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(self, root: str, directory: Path, entry: str, blobs: dict):
        self.root = root
        self.directory = directory
        self.entry = os.path.normpath(entry)
        self.blobs = blobs
        self.base = os.path.dirname(self.entry)

    def locate(self, fullname: str):
        if fullname == self.root:
            return self.entry, True
        if not fullname.startswith(self.root + "."):
            return None
        rel = os.path.join(self.base, *fullname[len(self.root) + 1:].split("."))
        for cand, pkg in ((rel + ".py", False), (os.path.join(rel, "__init__.py"), True)):
            if os.path.normpath(cand) in self.blobs:
                return os.path.normpath(cand), pkg
        return None

    def find_spec(self, fullname, path=None, target=None):
        hit = self.locate(fullname)
        if hit is None:
            return None
        name, pkg = hit
        origin = str(self.directory / name)
        spec = importlib.machinery.ModuleSpec(fullname, self, origin=origin, is_package=pkg)
        spec.has_location = True
        if pkg:
            spec.submodule_search_locations = [os.path.dirname(origin)]
        return spec

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        name, _pkg = self.locate(module.__spec__.name)
        code = compile(self.blobs[name], module.__spec__.origin, "exec", dont_inherit=True)
        exec(code, module.__dict__)


def _forget(plugin_id: str) -> None:
    root = "formcad_plugin_" + re.sub(r"\W", "_", plugin_id)
    finder = FINDERS.pop(plugin_id, None)
    if finder is not None and finder in sys.meta_path:
        sys.meta_path.remove(finder)
    for name in [n for n in sys.modules if n == root or n.startswith(root + ".")]:
        sys.modules.pop(name, None)


def _load_module(plugin_id: str, directory: Path, entry: str, expected_manifest: str):
    _forget(plugin_id)
    _files, blobs = read_verified(directory, expected_manifest)
    root = "formcad_plugin_" + re.sub(r"\W", "_", plugin_id)
    finder = VerifiedImporter(root, directory, entry, blobs)
    sys.meta_path.insert(0, finder)
    FINDERS[plugin_id] = finder
    try:
        return importlib.import_module(root)
    except Exception:
        _forget(plugin_id)
        raise


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
                module = _load_module(plugin_id, Path(item["path"]), item["entry"], item["manifestSha256"])
                register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError("The plugin defines no register(api) function.")
            register(api)
        except Exception as err:
            _unregister(api.commands)
            _forget(plugin_id)
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
        _forget(plugin_id)


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
            if not item.get("manifestSha256"):
                raise PluginError("The installed files of this plugin cannot be read, so no hash can be recorded.")
            if not manifest_sha256:
                raise PluginError("Enabling a plugin needs the distribution hash that was shown; use the plugin manager.")
            if manifest_sha256 != item["manifestSha256"]:
                raise PluginError("The installed files changed after they were shown. Review the plugin again.")
            _store(plugin_id, {"enabled": True, "distSha256": item["manifestSha256"], "version": item["version"], "at": int(time.time())})
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
