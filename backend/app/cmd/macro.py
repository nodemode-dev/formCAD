import hashlib
import json
import os
import threading
import time

from app.cmd import registry, script
from app.doc import container

MAX_EVENTS = 100_000
SCR = ".scr"
PY = ".py"
SAVED: dict = {}


class MacroError(Exception):
    pass


def folder() -> str:
    from app.core import config

    path = os.path.join(str(config.data_dir()), "macros")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def pt_text(p) -> str:
    return "%.10g,%.10g" % (p[0], p[1])


class Recorder:
    def __init__(self, name: str):
        self.name = name or "macro"
        self.started = time.time()
        self.events: list = []

    def info(self) -> dict:
        return {"name": self.name, "events": len(self.events)}

    def push(self, kind: str, line: str, **data) -> None:
        if len(self.events) < MAX_EVENTS:
            self.events.append({"kind": kind, "line": line, **data})

    def add(self, runner, kind: str, *args) -> None:
        if kind == "text":
            text = str(args[0]).replace("\r", "").replace("\n", " ")
            if runner.run is None:
                word = text.strip().split(" ")[0] if text.strip() else ""
                if not word:
                    if runner.last_cmd:
                        self.push("text", runner.last_cmd.upper(), text=runner.last_cmd.upper())
                    return
                spec = registry.resolve(word.lstrip("'")) if "{" not in word else None
                if spec is not None and spec.group == "macro":
                    return
            self.push("text", text, text=text)
        elif kind == "point":
            self.push("point", pt_text(args[0]), point=[args[0][0], args[0][1]])
        elif kind == "pick":
            pt, pick = args
            shift = bool(isinstance(pick, dict) and pick.get("shift"))
            self.push("pick", "@pick %s%s" % (pt_text(pt), " shift" if shift else ""), point=[pt[0], pt[1]], shift=shift)
        elif kind == "area":
            akind, pts = args
            if akind == "auto":
                akind = "window" if pts[1][0] >= pts[0][0] else "crossing"
                self.push("text", "W" if akind == "window" else "C", text="W" if akind == "window" else "C")
            self.push("point", pt_text(pts[0]), point=[pts[0][0], pts[0][1]])
            self.push("point", pt_text(pts[1]), point=[pts[1][0], pts[1][1]])
        elif kind == "selection":
            handles, mode, box = args
            if mode == "remove":
                self.push("text", "R", text="R")
                self.push("handles", "#" + ",".join("%x" % h for h in handles), handles=list(handles))
                self.push("text", "A", text="A")
            elif isinstance(box, (list, tuple)) and len(box) == 4:
                self.push("box", "@box %s %s" % (pt_text(box[:2]), pt_text(box[2:])), box=[float(v) for v in box])
            elif handles:
                self.push("handles", "@handles " + ",".join("%x" % h for h in handles), handles=list(handles))
        elif kind == "cancel":
            self.push("cancel", "^C")
        elif kind == "command":
            spec, params = args
            if spec.group == "macro":
                return
            if isinstance(params.get("inputs"), list):
                line = spec.name + " " + " ".join(str(x) for x in params["inputs"])
                self.push("text", line, text=line)
            else:
                self.push("command", "%s %s" % (spec.name, json.dumps(params, separators=(",", ":"))), name=spec.name, args=params)


def start(runner, name: str = "") -> Recorder:
    if runner.recorder is not None:
        raise MacroError("A macro is already recording.")
    runner.recorder = Recorder(name)
    return runner.recorder


def stop(runner) -> Recorder:
    rec = runner.recorder
    if rec is None:
        raise MacroError("No macro is recording.")
    runner.recorder = None
    runner.macro_last = rec
    return rec


def current(runner):
    return runner.recorder or getattr(runner, "macro_last", None)


def scr_text(rec: Recorder) -> str:
    out = ["; FormCAD macro %s" % rec.name, "; %d recorded steps" % len(rec.events)]
    out.extend(e["line"] for e in rec.events)
    return "\n".join(out) + "\n"


def python_text(rec: Recorder) -> str:
    out = ["import formcad", "", "doc = formcad.active_document()", ""]
    for e in rec.events:
        kind = e["kind"]
        if kind in ("pick", "box", "handles", "cancel"):
            out.append("doc.script(%r)" % e["line"])
        elif kind == "command":
            out.append("doc.command(%r, **%r)" % (e["name"], e["args"]))
        else:
            out.append("doc.send(%r)" % e["line"])
    return "\n".join(out) + "\n"


def target_path(path: str, fmt: str) -> str:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw:
        raise MacroError("A file name is required.")
    ext = PY if fmt == "python" else SCR
    if os.path.dirname(raw) == "":
        raw = os.path.join(folder(), raw)
    root, _ = os.path.splitext(raw)
    from app.core import outputs

    try:
        return outputs.checked(root + ext, (ext,))
    except outputs.OutputRefused as err:
        raise MacroError(str(err))


def save(runner, path: str, fmt: str = "") -> str:
    rec = current(runner)
    if rec is None:
        raise MacroError("There is no recorded macro to save.")
    if not fmt:
        fmt = "python" if os.path.splitext(str(path))[1].lower() == PY else "scr"
    if fmt not in ("scr", "python"):
        raise MacroError("The macro format is scr or python.")
    full = target_path(path or rec.name, fmt)
    data = (python_text(rec) if fmt == "python" else scr_text(rec)).encode("utf-8")
    try:
        container.atomic_write(full, data, 0o600)
    except OSError as err:
        raise MacroError("Cannot write the macro: %s" % err)
    if fmt == "python":
        SAVED[full] = hashlib.sha256(data).hexdigest()
    return full


def engine_url() -> str:
    from app.core import config

    try:
        with open(os.path.join(str(config.data_dir()), "engine.port"), "r", encoding="utf-8") as fh:
            port = int(json.load(fh)["port"])
    except (OSError, ValueError, KeyError, TypeError):
        raise MacroError("The engine port is not known; Python macros run only inside the running app.")
    return "http://127.0.0.1:%d" % port


def run_python_macro(runner, full: str) -> str:
    from app.automation import macros

    try:
        digest = macros.file_hash(macros.check_file(full))
        if SAVED.get(full) == digest:
            macros.set_trust(full, True, {}, digest)
        if not macros.status(full)["trusted"]:
            raise MacroError("This macro is not trusted yet. Review its source and trust it first.")
        url = engine_url()
    except macros.MacroError as err:
        raise MacroError(str(err))
    doc = runner.doc

    def go():
        try:
            res = macros.run(full, url, doc.id)
            tail = ("ok" if res["ok"] else "failed (exit %s%s)" % (res["exit"], ", timed out" if res["timedOut"] else "")) + (": " + res["stderr"].strip().splitlines()[-1] if res["stderr"].strip() and not res["ok"] else "")
        except macros.MacroError as err:
            tail = "failed: %s" % err
        with doc.lock:
            runner.log("Python macro %s %s" % (os.path.basename(full), tail))
            doc.announce("macro")

    threading.Thread(target=go, name="formcad-macro", daemon=True).start()
    return os.path.basename(full)


def play(runner, source: str = "") -> str:
    if runner.recorder is not None:
        raise MacroError("Stop recording before playing a macro.")
    if not source or source.lower() == "last":
        rec = getattr(runner, "macro_last", None)
        if rec is None:
            raise MacroError("There is no recorded macro to play.")
        try:
            script.start(runner, rec.name, script.split_lines(scr_text(rec)))
        except script.ScriptError as err:
            raise MacroError(str(err))
        return rec.name
    raw = os.path.expanduser(source.strip())
    if os.path.dirname(raw) == "":
        raw = os.path.join(folder(), raw)
    if os.path.splitext(raw)[1].lower() == PY:
        return run_python_macro(runner, os.path.realpath(raw))
    try:
        name, lines = script.read_file(raw)
        script.start(runner, name, lines)
    except script.ScriptError as err:
        raise MacroError(str(err))
    return name


def listing() -> list:
    out = []
    base = folder()
    for n in sorted(os.listdir(base)):
        if os.path.splitext(n)[1].lower() in (SCR, PY):
            st = os.stat(os.path.join(base, n))
            out.append({"name": n, "size": st.st_size, "modified": st.st_mtime})
    return out
