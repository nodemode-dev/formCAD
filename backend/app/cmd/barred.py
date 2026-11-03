import os

from app.core import guard

MACRO_GROUPS = {"draw", "modify", "format", "annotate", "annotation", "constraints", "inquiry", "block", "layout", "solids", "edit", "view", "tools", "script", "settings", "extra"}
MACRO_NAMES = {"purge", "-purge", "audit"}
MACRO_BARRED = {"aliasedit", "reinit", "dsettings", "materiallib", "modeltol", "gdtstyle", "docprops", "asmsearch", "analysisramp", "matesettings"}
AGENT_BARRED = {"pluginenable", "aliasedit", "reinit", "appload", "macrosave", "macroplay", "materiallib", "modeltol", "gdtstyle", "docprops", "asmsearch", "analysisramp", "matesettings"}


def caller(runner=None) -> str:
    who = guard.CALLER.get()
    if who:
        return who
    script = getattr(runner, "script", None)
    return getattr(script, "caller", "") if script is not None else ""


PATH_NAMES = {"path", "paths", "file", "files", "filename", "folder", "dir", "out"}


def _granted(runner, who: str) -> list:
    if who == "macro":
        script = getattr(runner, "script", None)
        held = guard.FILES.get() or (getattr(script, "files", ()) if script is not None else ())
        return [os.path.realpath(str(p)) for p in held]
    try:
        from app.automation import macros

        extra = macros.load_settings().get("agentFolders", [])
    except Exception:
        extra = []
    return [os.path.realpath(os.path.expanduser(str(p))) for p in extra if isinstance(p, str) and p]


def _inside(value, roots) -> bool:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        return False
    real = os.path.realpath(os.path.expanduser(value.strip()))
    return any(real == r or real.startswith(r.rstrip(os.sep) + os.sep) for r in roots)


def _path_values(args, depth=0):
    if depth > 4 or not isinstance(args, dict):
        return
    for key, value in args.items():
        k = str(key).lower()
        if k in PATH_NAMES or k.endswith("_path") or k.endswith("_file"):
            for item in value if isinstance(value, list) else [value]:
                if item not in (None, "", False):
                    yield k, item
        elif isinstance(value, dict):
            yield from _path_values(value, depth + 1)
        elif isinstance(value, list):
            for item in value:
                yield from _path_values(item, depth + 1)


def args_refusal(runner, spec, args) -> str:
    who = caller(runner)
    if not who:
        return ""
    roots = _granted(runner, who)
    for key, value in _path_values(args):
        if not _inside(value, roots):
            return "%s may not use the file argument %s here; the folder was not granted to this %s." % (spec.name.upper(), key, "macro" if who == "macro" else "agent")
    return ""


FILE_EXT = (".dxf", ".dwg", ".dwt", ".svg", ".svgz", ".step", ".stp", ".iges", ".igs", ".3dm", ".stl", ".obj", ".fcad", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".txt", ".json", ".py", ".lsp", ".lisp", ".scr", ".xlsx", ".xls")


def looks_like_path(tok) -> bool:
    s = str(tok).strip()
    if not s or (" " in s and not s.startswith(("/", "~", "\\"))):
        return False
    if s.startswith(("/", "~", "\\", "./", "../", ".\\", "..\\")) or (len(s) > 2 and s[1] == ":" and s[2] in "/\\"):
        return True
    return s.lower().endswith(FILE_EXT)


def prompt_refusal(runner, prompt, tok=None) -> str:
    who = caller(runner)
    if not who:
        return ""
    words = str(getattr(prompt, "message", "")).lower()
    free = bool(getattr(prompt, "free_text", False))
    asks = free and any(w in words for w in ("file", "folder", "path", "directory"))
    typed = tok is not None and free and looks_like_path(tok)
    if not asks and not typed:
        return ""
    if tok is None or str(tok).strip() == "":
        return ""
    if _inside(str(tok), _granted(runner, who)):
        return ""
    return "A file name outside the granted folders cannot be typed for a prompt by %s." % ("a macro" if who == "macro" else "an outside agent")


def refusal(runner, spec) -> str:
    who = caller(runner)
    if not who:
        return ""
    name = spec.name
    if who == "agent":
        return "%s is not available to outside agents; use the FormCAD window." % name.upper() if name in AGENT_BARRED else ""
    if name in MACRO_NAMES:
        return ""
    if name in MACRO_BARRED or spec.group not in MACRO_GROUPS:
        return "%s is not available to a Python macro; use the FormCAD window." % name.upper()
    return ""


def lisp_refusal(runner) -> str:
    who = caller(runner)
    if who == "macro":
        return "LISP is not available to a Python macro; use the FormCAD window."
    if who == "agent":
        return "LISP is not available to outside agents; use the FormCAD window."
    return ""
