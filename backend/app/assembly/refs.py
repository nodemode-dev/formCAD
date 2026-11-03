import hashlib
import os
import re

from app.assembly import store
from app.doc import xref

HASH_LIMIT = 64 * 1024 * 1024
DEEP_DIRS = 4000
DEEP_DEPTH = 5
EXT = ".fcad"


def sig_of(path: str) -> dict:
    try:
        st = os.stat(path)
    except OSError:
        return {"size": 0, "mtime": 0, "sha256": ""}
    digest = ""
    if st.st_size <= HASH_LIMIT:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
            digest = h.hexdigest()
        except OSError:
            digest = ""
    return {"size": int(st.st_size), "mtime": int(st.st_mtime_ns), "sha256": digest}


def quick_sig(path: str):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (int(st.st_size), int(st.st_mtime_ns))


def same_sig(a: dict, b: dict) -> bool:
    if not a or not b or not a.get("size") and not a.get("mtime"):
        return False
    if a.get("sha256") and b.get("sha256"):
        return a["sha256"] == b["sha256"]
    return a.get("size") == b.get("size") and a.get("mtime") == b.get("mtime")


def _foreign(text: str, host_path: str) -> str:
    if "://" in text:
        return "path leads away from this computer"
    unc = xref._unc_host(text)
    if unc and unc != xref._unc_host(host_path or ""):
        return "path leads to another computer"
    if xref._foreign_abs(text):
        return "absolute path from another operating system"
    return ""


def _norm(text: str) -> str:
    s = str(text or "").strip()
    return s if os.name == "nt" else s.replace("\\", "/")


def _inside(real: str, bases) -> bool:
    return any(real == b or real.startswith(b.rstrip(os.sep) + os.sep) for b in bases)


def _try(log: list, step: str, path: str, bases=None) -> str:
    ok = bool(path) and os.path.isfile(path) and os.path.splitext(path)[1].lower() == EXT
    if ok and bases is not None and os.path.islink(path) and not _inside(os.path.realpath(path), bases):
        ok = False
    log.append({"step": step, "path": path, "found": ok})
    return os.path.realpath(path) if ok else ""


def _deep(roots: list, name: str, log: list) -> str:
    seen = 0
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        base = os.path.realpath(root)
        for cur, dirs, files in os.walk(base):
            depth = cur[len(base):].count(os.sep)
            if depth >= DEEP_DEPTH:
                dirs[:] = []
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            seen += 1
            if seen > DEEP_DIRS:
                log.append({"step": "deep", "path": base, "found": False, "note": "stopped after %d folders" % DEEP_DIRS})
                return ""
            if name in files:
                hit = os.path.join(cur, name)
                log.append({"step": "deep", "path": hit, "found": True})
                return os.path.realpath(hit)
        log.append({"step": "deep", "path": base, "found": False})
    return ""


def search(host_path: str, ref: dict, head: dict, folders=(), deep: bool = False) -> tuple:
    log: list = []
    if isinstance(ref.get("vault"), dict):
        from app.vault import registry

        pinned = registry.resolve_ref(ref["vault"], log)
        if pinned:
            return pinned, "vault", log
    stored = _norm(ref.get("path"))
    hint = _norm(ref.get("abs"))
    hostdir = os.path.dirname(os.path.realpath(host_path)) if host_path else ""
    name = os.path.basename(stored or hint)
    order = [s for s in (head.get("search_order") or store.DEFAULT_ORDER) if s in store.SEARCH_STEPS]
    if deep and "deep" not in order:
        order = list(order) + ["deep"]
    if not name:
        return "", "", [{"step": "relative", "path": "", "found": False, "note": "no path stored"}]
    extra = [os.path.expanduser(str(f)) for f in folders if str(f).strip()]
    roots = []
    for f in extra + [str(f) for f in head.get("search_folders") or []]:
        f = os.path.expanduser(_norm(f))
        if not os.path.isabs(f) and hostdir:
            f = os.path.join(hostdir, f)
        roots.append(os.path.realpath(f))
    bases = ([hostdir] if hostdir else []) + roots
    for step in order:
        if step == "relative":
            if stored and not os.path.isabs(stored):
                bad = _foreign(stored, host_path)
                if bad:
                    log.append({"step": step, "path": stored, "found": False, "note": bad})
                elif hostdir:
                    hit = _try(log, step, os.path.join(hostdir, stored), bases)
                    if hit:
                        return hit, step, log
                else:
                    log.append({"step": step, "path": stored, "found": False, "note": "the assembly has no folder yet"})
            else:
                log.append({"step": step, "path": stored, "found": False, "note": "not a relative path"})
        elif step == "absolute":
            for cand in dict.fromkeys(p for p in (stored if os.path.isabs(stored) else "", hint) if p):
                bad = _foreign(cand, host_path)
                if bad:
                    log.append({"step": step, "path": cand, "found": False, "note": bad})
                    continue
                hit = _try(log, step, cand, bases)
                if hit:
                    return hit, step, log
            if not stored and not hint:
                log.append({"step": step, "path": "", "found": False})
        elif step == "same_folder":
            if hostdir:
                hit = _try(log, step, os.path.join(hostdir, name), bases)
                if hit:
                    return hit, step, log
        elif step == "search_folders":
            for root in roots:
                hit = _try(log, step, os.path.join(root, name), bases)
                if hit:
                    return hit, step, log
        elif step == "deep":
            hit = _deep(([hostdir] if hostdir else []) + roots, name, log)
            if hit:
                return hit, step, log
    return "", "", log


def describe_order(head: dict) -> list:
    return [s for s in (head.get("search_order") or store.DEFAULT_ORDER) if s in store.SEARCH_STEPS]


def clean_order(values) -> list:
    out = []
    for v in values if isinstance(values, (list, tuple)) else [values]:
        s = str(v).strip().lower()
        if s not in store.SEARCH_STEPS:
            raise store.AssemblyError("%s is not a search step; use %s." % (v, ", ".join(store.SEARCH_STEPS)))
        if s not in out:
            out.append(s)
    if not out:
        raise store.AssemblyError("Give at least one search step.")
    return out


def stored_path(resolved: str, host_path: str, relative: bool = True) -> str:
    if relative and host_path:
        return xref.stored_path(resolved, host_path)
    return os.path.realpath(resolved)


SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")


def stem(path: str) -> str:
    return SAFE_NAME.sub("_", os.path.splitext(os.path.basename(path))[0]) or "Part"
