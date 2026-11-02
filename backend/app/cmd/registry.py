import importlib
import pkgutil
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional

_lock = threading.Lock()
_loaded = False


@dataclass
class CommandEntry:
    name: str
    fn: Callable
    aliases: tuple = ()
    group: str = ""
    label: str = ""
    description: str = ""
    menu: str = ""
    transparent: bool = False
    undoable: bool = True
    repeatable: bool = True
    execute: Optional[Callable] = None
    extra: dict = field(default_factory=dict)

    def entry(self) -> dict:
        return {"name": self.name, "aliases": list(self.aliases), "group": self.group, "label": self.label or self.name.title(), "description": self.description, "menu": self.menu, "transparent": self.transparent, "undoable": self.undoable}


COMMANDS: dict = {}
ALIASES: dict = {}
USER_ALIASES: dict = {}


def command(name: str, aliases=(), group="", label="", description="", menu="", transparent=False, undoable=True, repeatable=True):
    def wrap(fn):
        spec = CommandEntry(name.lower(), fn, tuple(a.lower() for a in aliases), group, label, description, menu, transparent, undoable, repeatable)
        COMMANDS[spec.name] = spec
        for a in spec.aliases:
            ALIASES[a] = spec.name
        fn.spec = spec
        return fn

    return wrap


def executes(*names):
    def wrap(fn):
        for n in names:
            COMMANDS[n.lower()].execute = fn
        return fn

    return wrap


def load_modules() -> None:
    global _loaded
    with _lock:
        if _loaded:
            return
        from app.cmd import commands

        for info in pkgutil.iter_modules(commands.__path__):
            importlib.import_module("app.cmd.commands." + info.name)
        _loaded = True
        from app.cmd import aliasfile

        aliasfile.startup()


def resolve(word: str):
    load_modules()
    w = word.strip().lower()
    while w.startswith("_") or w.startswith("."):
        w = w[1:]
    if w in COMMANDS:
        return COMMANDS[w]
    if w in USER_ALIASES and USER_ALIASES[w] in COMMANDS:
        return COMMANDS[USER_ALIASES[w]]
    if w in ALIASES:
        return COMMANDS[ALIASES[w]]
    return None


def catalogue() -> list:
    load_modules()
    return [s.entry() for s in sorted(COMMANDS.values(), key=lambda s: (s.group, s.name))]


def suggest(prefix: str, limit: int = 8) -> list:
    load_modules()
    p = prefix.strip().lower()
    if not p:
        return []
    out = []
    if p in COMMANDS:
        out.append(p.upper())
    elif p in ALIASES:
        out.append("%s (%s)" % (p.upper(), ALIASES[p].upper()))
    names = sorted((n for n in COMMANDS if n.startswith(p) and n != p and "." not in n), key=lambda n: (len(n), n))
    out.extend(n.upper() for n in names)
    al = sorted((a for a in ALIASES if a.startswith(p) and a != p), key=lambda a: (len(a), a))
    out.extend("%s (%s)" % (a.upper(), ALIASES[a].upper()) for a in al)
    return out[:limit]
