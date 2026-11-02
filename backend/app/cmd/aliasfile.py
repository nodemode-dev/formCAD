import json
import os
import re

from app.cmd import registry
from app.doc import container

EXT = ".fcalias"
READ_EXT = (".fcalias", ".pgp")
MAX_ALIASES = 2000
MAX_ALIAS_LEN = 32
MAX_LINE = 256
MAX_WARNINGS = 50
MAX_BYTES = 1_000_000
VALID = re.compile(r"^[^\s,;*\[\]{}]{1,%d}$" % MAX_ALIAS_LEN)

state = {"file": ""}


class AliasError(Exception):
    pass


def known(name: str):
    w = name.strip().lower()
    if w in registry.COMMANDS:
        return w
    if w in registry.ALIASES:
        return registry.ALIASES[w]
    return None


def is_command_name(word: str) -> bool:
    return word.lower() in registry.COMMANDS


def check_alias(alias: str, command: str, count: int = 0, replacing: bool = False) -> tuple:
    a = str(alias or "").strip().lower()
    c = str(command or "").strip().lstrip("*").strip()
    if not a:
        raise AliasError("Type an alias name.")
    if not c:
        raise AliasError("Choose the command the alias starts.")
    if len(a) > MAX_ALIAS_LEN or not VALID.match(a):
        raise AliasError("An alias is one word of up to %d printable characters, without commas or semicolons." % MAX_ALIAS_LEN)
    if is_command_name(a):
        raise AliasError("%s is a command name; it stays the command." % a.upper())
    target = known(c)
    if target is None:
        raise AliasError("alias: unknown command %s; skipped" % c.upper())
    if not replacing and a not in registry.USER_ALIASES and count >= MAX_ALIASES:
        raise AliasError("More than %d aliases." % MAX_ALIASES)
    return a, target


def parse(text: str) -> tuple:
    entries = {}
    warnings = []
    omitted = 0

    def warn(n, msg):
        nonlocal omitted
        if len(warnings) < MAX_WARNINGS:
            warnings.append("line %d: %s" % (n, msg))
        else:
            omitted += 1

    for n, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
        line = raw.strip()
        if not line or line.startswith(";") or (line.startswith("[") and line.endswith("]")):
            continue
        if len(line) > MAX_LINE:
            warn(n, "the line is too long; skipped")
            continue
        if "," not in line:
            warn(n, "expected ALIAS, *COMMAND; skipped")
            continue
        alias, _, rest = line.partition(",")
        rest = rest.strip()
        if not rest.startswith("*"):
            warn(n, "%s is an external command; FormCAD does not run programs from alias files" % alias.strip().upper())
            continue
        command = rest[1:].split(",")[0].strip()
        try:
            a, target = check_alias(alias, command, len(entries), alias.strip().lower() in entries)
        except AliasError as err:
            warn(n, str(err))
            continue
        entries[a] = target
    if omitted:
        warnings.append("... and %d more warnings" % omitted)
    return entries, warnings


def profile_path():
    from app.core import config

    return os.path.join(str(config.data_dir()), "aliases.json")


def remember(path: str) -> None:
    state["file"] = path
    try:
        container.atomic_write(profile_path(), json.dumps({"file": path}).encode("utf-8"), 0o600)
    except OSError:
        pass


def read_file(path: str) -> str:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw:
        raise AliasError("An alias file name is required.")
    full = os.path.realpath(raw)
    if os.path.splitext(full)[1].lower() not in READ_EXT:
        raise AliasError("Alias files end in %s or .pgp." % EXT)
    if not os.path.isfile(full):
        raise AliasError('Cannot find the alias file "%s".' % path)
    if os.path.getsize(full) > MAX_BYTES:
        raise AliasError("The alias file is too large.")
    try:
        with open(full, "rb") as fh:
            return full, fh.read().decode("utf-8-sig", errors="replace")
    except OSError as err:
        raise AliasError("Cannot read the alias file: %s" % err)


def load(path: str, persist: bool = True) -> dict:
    full, text = read_file(path)
    entries, warnings = parse(text)
    registry.USER_ALIASES.clear()
    registry.USER_ALIASES.update(entries)
    if persist:
        remember(full)
    else:
        state["file"] = full
    n = len(entries)
    return {"count": n, "file": full, "warnings": warnings, "message": "%d command alias%s loaded from %s." % (n, "" if n == 1 else "es", full)}


def reinit() -> dict:
    if not state["file"]:
        raise AliasError("No command alias file is loaded")
    return load(state["file"])


def clear() -> dict:
    n = len(registry.USER_ALIASES)
    registry.USER_ALIASES.clear()
    state["file"] = ""
    try:
        os.unlink(profile_path())
    except OSError:
        pass
    return {"count": 0, "removed": n, "message": "%d command alias%s cleared." % (n, "" if n == 1 else "es")}


def set_one(alias: str, command: str) -> dict:
    a, target = check_alias(alias, command, len(registry.USER_ALIASES))
    registry.USER_ALIASES[a] = target
    return {"alias": a, "command": target, "count": len(registry.USER_ALIASES)}


def remove_one(alias: str) -> dict:
    a = str(alias or "").strip().lower()
    if a not in registry.USER_ALIASES:
        raise AliasError("%s is not a user alias." % (a.upper() or "That name"))
    del registry.USER_ALIASES[a]
    return {"alias": a, "count": len(registry.USER_ALIASES)}


def replace_all(pairs: dict) -> dict:
    out = {}
    for alias, command in pairs.items():
        a, t = check_alias(alias, command, len(out), str(alias).strip().lower() in out)
        out[a] = t
    registry.USER_ALIASES.clear()
    registry.USER_ALIASES.update(out)
    return {"count": len(out)}


def listing() -> dict:
    registry.load_modules()
    built = [{"alias": a, "command": c, "note": "built-in"} for a, c in sorted(registry.ALIASES.items())]
    user = [{"alias": a, "command": c, "note": "overrides built-in" if a in registry.ALIASES else ""} for a, c in sorted(registry.USER_ALIASES.items())]
    return {"file": state["file"], "builtin": built, "user": user, "limit": MAX_ALIASES, "aliasLength": MAX_ALIAS_LEN}


def suggest(text: str, limit: int = 8) -> list:
    registry.load_modules()
    p = str(text or "").strip().lstrip("*").lower()
    if not p or p in registry.COMMANDS:
        return []
    names = sorted((n for n in registry.COMMANDS if n.startswith(p) and "." not in n), key=lambda n: (len(n), n))
    return [n.upper() for n in names[:limit]]


def save(path: str) -> str:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw:
        raise AliasError("An alias file name is required.")
    if os.path.dirname(raw) == "":
        from app.core import config

        folder = os.path.join(str(config.data_dir()), "aliases")
        os.makedirs(folder, mode=0o700, exist_ok=True)
        raw = os.path.join(folder, raw)
    from app.core import outputs

    try:
        full = outputs.checked(os.path.splitext(raw)[0] + EXT, (EXT,))
    except outputs.OutputRefused as err:
        raise AliasError(str(err))
    lines = ["; FormCAD command aliases", "; ALIAS, *COMMAND"]
    lines.extend("%s, *%s" % (a.upper(), c.upper()) for a, c in sorted(registry.USER_ALIASES.items()))
    try:
        container.atomic_write(full, ("\n".join(lines) + "\n").encode("utf-8"), 0o600)
    except OSError as err:
        raise AliasError("Cannot write the alias file: %s" % err)
    return full


def startup() -> None:
    try:
        with open(profile_path(), "r", encoding="utf-8") as fh:
            path = json.load(fh).get("file", "")
    except (OSError, ValueError, AttributeError):
        return
    if not path:
        return
    try:
        load(path, False)
    except AliasError:
        state["file"] = ""
