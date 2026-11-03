import contextvars
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from types import SimpleNamespace

from app.cmd.context import Context
from app.doc.undo import Step
from app.lisp import bridge, support
from app.lisp.interp import Lisp, Limits, initial_symbols
from app.lisp.printer import prin1
from app.lisp.types import LispAbort, LispError, Sym, Usubr

STACK_BYTES = 512 * 1024 * 1024
GO = ("go",)
CANCEL = ("cancel",)
SHELL_SPEC = SimpleNamespace(name="lisp", transparent=False, repeatable=False, undoable=False, execute=None, aliases=(), extra={})
STARTUP_DONE = {"acad": False}
MAX_LINES = 5000


@dataclass
class EvalResult:
    value: str = ""
    lines: list = field(default_factory=list)
    error: str = ""
    finished: bool = True

    def as_dict(self) -> dict:
        return {"value": self.value, "lines": list(self.lines), "error": self.error, "finished": self.finished}


class Session:
    def __init__(self, doc):
        self.doc = doc
        self.syms = initial_symbols()
        self.L = Lisp(self.syms, Limits())
        self.L.session = self
        self.loaded: list = []
        self.grants: dict = {}
        self.hold = None
        self.running = False
        self.started = False

    @property
    def runner(self):
        return self.doc.get_runner()

    def grant(self, real: str) -> None:
        base = os.path.basename(real).lower()
        self.grants[base] = real
        stem = os.path.splitext(base)[0]
        self.grants.setdefault(stem, real)
        if real not in self.loaded:
            self.loaded.append(real)

    def granted(self, name):
        if not isinstance(name, str):
            return None
        key = os.path.basename(name.replace("\\", "/")).lower()
        real = self.grants.get(key)
        if real and os.path.isfile(real):
            return real
        return None

    def commands(self) -> list:
        out = []
        for k, v in self.syms.items():
            if isinstance(k, Sym) and k.name.startswith("C:") and type(v) is Usubr:
                out.append(k.name[2:])
        return sorted(out)

    def user_command(self, word: str):
        from app.lisp.types import sym

        v = self.syms.get(sym("C:" + word.upper()))
        return v if type(v) is Usubr else None


def get_session(doc) -> Session:
    s = getattr(doc, "lisp_session", None)
    if s is None:
        s = Session(doc)
        doc.lisp_session = s
    return s


class Ctx:
    def __init__(self, routine):
        self.r = routine
        self.runner = routine.s.runner

    def say(self, msg: str) -> None:
        self.runner.log(msg)

    def ask(self, prompt):
        r = self.r
        if r.canned:
            ans = r.canned.pop(0)
            return bridge.canned_input(self.runner, prompt, ans)
        if not r.interactive:
            return None
        reply = r.request(("input", prompt))
        if reply is CANCEL:
            raise LispAbort("Function cancelled", "cancel")
        return reply

    def pause(self) -> bool:
        r = self.r
        if r.canned:
            ans = r.canned.pop(0)
            bridge.run_command(r.s.L, [ans])
            return True
        if not r.interactive:
            return False
        reply = r.request(("pause",))
        if reply is CANCEL:
            raise LispAbort("Function cancelled", "cancel")
        return True


class Routine:
    def __init__(self, session, body, canned=None, interactive=False, echo=False, label="LISP", startup=True):
        self.s = session
        self.doc = session.doc
        self.body = body
        self.canned = list(canned or [])
        self.interactive = interactive
        self.echo = echo
        self.label = label
        self.startup = startup
        self.events = queue.Queue()
        self.replies = queue.Queue()
        self.value = None
        self.error = ""
        self.lines: list = []
        self.finished = False
        self.shell = None
        self.shell_live = False
        self.tap = None
        self.tap_base = 0

    def start(self) -> None:
        if self.interactive:
            self.s.hold = self
        old = threading.stack_size()
        try:
            threading.stack_size(STACK_BYTES)
        except (ValueError, RuntimeError):
            pass
        t = threading.Thread(target=contextvars.copy_context().run, args=(self._work,), name="lisp-routine", daemon=True)
        try:
            t.start()
        finally:
            try:
                threading.stack_size(old)
            except (ValueError, RuntimeError):
                pass
        self._handle(self._wait())

    def _wait(self):
        lock = self.doc.lock
        saved = lock._release_save()
        try:
            return self.events.get()
        finally:
            lock._acquire_restore(saved)

    def _resume(self, reply):
        lock = self.doc.lock
        saved = lock._release_save()
        try:
            self.replies.put(reply)
            return self.events.get()
        finally:
            lock._acquire_restore(saved)

    def request(self, ev):
        lock = self.doc.lock
        L = self.s.L
        t0 = time.monotonic()
        self.s.running = False
        saved = lock._release_save()
        try:
            self.events.put(ev)
            return self.replies.get()
        finally:
            lock._acquire_restore(saved)
            self.s.running = True
            L.deadline += time.monotonic() - t0

    def sink(self, line: str) -> None:
        if len(self.lines) < MAX_LINES:
            self.lines.append(line)
        self.s.runner.log(line)

    def _work(self) -> None:
        lock = self.doc.lock
        lock.acquire()
        try:
            self._execute()
        except BaseException as err:
            self.error = self.error or "Internal error: %s" % err
        finally:
            try:
                self.s.running = False
                lock._release_save()
            finally:
                self.events.put(("done",))

    def _execute(self) -> None:
        s = self.s
        L = s.L
        doc = self.doc
        runner = s.runner
        saved_state = (L.steps, L.depth, L.deadline, L.mem_base, L.cb_depth, L.init_bits, L.init_kw, L.ctx, L.out.sink, L.deleted, L.blockdef)
        L.ctx = Ctx(self)
        L.session = s
        L.out.sink = self.sink
        L.begin_run()
        L.blockdef = None
        s.running = True
        undo = doc.undo
        base = len(undo.steps)
        first = undo.steps[base - 1] if base else None
        try:
            try:
                if self.startup:
                    ensure_started(s, self)
                self.value = self.body(L)
                if self.echo:
                    text = prin1(self.value)
                    if text:
                        L.out.write(text)
                        L.out.write("\n")
            except LispError as err:
                self.error = err.msg
                self.cleanup()
                L.fail(err.msg)
            except LispAbort as err:
                self.error = err.msg
                self.cleanup()
                L.fail(err.msg, err.kind)
            except RecursionError:
                self.error = "internal stack limit reached"
                self.cleanup()
                L.fail(self.error, "limit")
            L.out.flush()
        finally:
            s.running = False
            self.close_files()
            merge_steps(doc, base, first, self.label)
            doc.announce("edit")
            (L.steps, L.depth, L.deadline, L.mem_base, L.cb_depth, L.init_bits, L.init_kw, L.ctx, L.out.sink, L.deleted, L.blockdef) = saved_state

    def cleanup(self) -> None:
        L = self.s.L
        runner = self.s.runner
        L.blockdef = None
        try:
            if runner.run is not None:
                runner.cancel_run(quiet=True)
        except Exception:
            pass

    def close_files(self) -> None:
        from app.lisp import lib_misc

        L = self.s.L
        for f in list(L.files.values()):
            try:
                if not f.closed:
                    lib_misc.flush_file(f)
                    f.closed = True
            except Exception:
                pass
        L.files.clear()

    def _dispatch(self, ev):
        runner = self.s.runner
        while True:
            k = ev[0]
            if k == "input":
                return ev[1]
            if k == "done":
                self.finished = True
                if self.s.hold is self:
                    self.s.hold = None
                self.tap = None
                return None
            tap = bridge.tap_current(runner)
            if tap is None:
                ev = self._resume(GO)
                continue
            self.tap = tap
            self.tap_base = tap.sends
            return None

    def _handle(self, ev) -> None:
        prompt = self._dispatch(ev)
        if prompt is not None:
            self._install(prompt)

    def _attach(self) -> None:
        runner = self.s.runner
        shell = self.shell
        shell.transparent = runner.run is not None
        if shell.transparent:
            runner.outer = runner.run
        runner.run = shell
        self.shell_live = True

    def _detach(self) -> None:
        runner = self.s.runner
        shell = self.shell
        if not self.shell_live:
            return
        self.shell_live = False
        if runner.run is shell:
            if shell.transparent:
                runner.run = runner.outer
                runner.outer = None
            else:
                runner.run = None
        elif runner.outer is shell:
            runner.outer = None

    def _install(self, prompt) -> None:
        runner = self.s.runner
        from app.cmd.runner import Run

        shell = Run(SHELL_SPEC)
        shell.ctx = Context(runner, self.doc)
        shell.gen = self._shell_gen(prompt)
        self.shell = shell
        self._attach()
        runner._advance(None)

    def _shell_gen(self, prompt):
        try:
            while True:
                inp = yield prompt
                self._detach()
                ev = self._resume(inp)
                nxt = self._dispatch(ev)
                if nxt is None:
                    self._attach()
                    return
                prompt = nxt
                self._attach()
        except GeneratorExit:
            self._abandon()
            raise

    def _abandon(self) -> None:
        if self.finished:
            return
        self.shell_live = False
        self.tap = None
        try:
            ev = self._resume(CANCEL)
            while not self.finished:
                if ev[0] == "done":
                    self._dispatch(ev)
                    break
                ev = self._resume(CANCEL)
        except Exception:
            pass

    def poll(self) -> None:
        if self.finished:
            return
        runner = self.s.runner
        if self.shell_live:
            shell = self.shell
            if runner.run is not shell and runner.outer is not shell:
                self.shell_live = False
                self._abandon()
            return
        tap = self.tap
        if tap is None:
            return
        run = runner.run
        live = run is not None and run.gen is tap
        if tap.sends > self.tap_base or not live or tap.closed or tap.done:
            self.tap = None
            reply = GO if tap.sends > self.tap_base else CANCEL
            self._handle(self._resume(reply))


def merge_steps(doc, base: int, first, label: str) -> None:
    u = doc.undo
    if u.control != "all" or u.group is not None:
        return
    steps = u.steps
    if len(steps) < base + 2:
        return
    if base and (len(steps) < base or steps[base - 1] is not first):
        return
    chunk = steps[base:]
    before: dict = {}
    for st in chunk:
        for k, v in st.before.items():
            before.setdefault(k, v)
    merged = Step(label, before, chunk[0].state_before, chunk[-1].state_after)
    del steps[base:]
    steps.append(merged)


def ensure_started(s: Session, routine) -> None:
    if s.started:
        return
    s.started = True
    from app.lisp import lib_misc
    from app.lisp.types import sym

    L = s.L
    names = []
    per_doc = False
    try:
        from app.sysvars import registry as sv

        per_doc = bool(sv.get_var(s.doc, "ACADLSPASDOC"))
    except Exception:
        per_doc = False
    if per_doc or not STARTUP_DONE["acad"]:
        names.append("acad.lsp")
    STARTUP_DONE["acad"] = True
    names.append("acaddoc.lsp")
    base = support.primary()
    for name in names:
        real = os.path.realpath(os.path.join(base, name))
        if os.path.dirname(real) != os.path.realpath(base) or not os.path.isfile(real):
            continue
        text = support.read_text(real)
        if text is None:
            continue
        try:
            lib_misc.run_text(L, text)
        except LispError as err:
            L.out.write("\n; error: %s\n" % err.msg)
        except LispAbort as err:
            L.out.write("\n; error: %s\n" % err.msg)
    hook = s.syms.get(sym("S::STARTUP"))
    if type(hook) is Usubr:
        try:
            L.call_user(hook, [])
        except LispError as err:
            L.out.write("\n; error: %s\n" % err.msg)
        except LispAbort as err:
            L.out.write("\n; error: %s\n" % err.msg)


def run_source(text: str):
    def body(L):
        from app.lisp import lib_misc

        return lib_misc.run_text(L, text)

    return body


def evaluate(doc, text: str, answers=None, echo: bool = False) -> EvalResult:
    s = get_session(doc)
    with doc.lock:
        if s.running:
            return EvalResult("", [], "A routine is already running.")
        retire(s)
        r = Routine(s, run_source(text), answers, False, False, "LISP")
        r.start()
        shown = prin1(r.value) if r.finished and not r.error else ""
        lines = list(r.lines)
        if echo and shown:
            lines.append(shown)
        return EvalResult(shown, lines, r.error, r.finished)


def load_file(doc, path: str, answers=None) -> EvalResult:
    s = get_session(doc)
    with doc.lock:
        if s.running:
            return EvalResult("", [], "A routine is already running.")
        retire(s)
        real = s.granted(path) or support.resolve_read(path)
        if real is None:
            return EvalResult("", [], 'LOAD failed: "%s"' % path)
        text = support.read_text(real)
        if text is None:
            return EvalResult("", [], 'LOAD failed: "%s"' % path)
        r = Routine(s, run_source(text), answers, False, False, "LISP")
        r.start()
        shown = prin1(r.value) if not r.error else ""
        return EvalResult(shown, list(r.lines), r.error, r.finished)


def retire(s: Session) -> None:
    h = s.hold
    if h is not None and not h.finished:
        try:
            h._abandon()
        except Exception:
            pass
    s.hold = None


def appload(doc, path: str) -> dict:
    s = get_session(doc)
    out = {"file": path, "loaded": False, "commands": [], "value": "", "lines": [], "error": ""}
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        out["error"] = "Enter the name of a LISP file."
        return out
    name = path.strip().strip('"')
    if not name.lower().endswith(".lsp"):
        out["error"] = "Only .lsp files can be loaded."
        return out
    real = None
    cand = os.path.abspath(os.path.expanduser(name.replace("\\", "/")))
    if os.path.isfile(cand):
        real = os.path.realpath(cand)
    else:
        real = support.resolve_read(name)
    if real is None:
        out["error"] = "Cannot find %s." % name
        return out
    text = support.read_text(real)
    if text is None:
        out["error"] = "Cannot read %s." % name
        return out
    before = set(s.commands())
    with doc.lock:
        if s.running:
            out["error"] = "A routine is already running."
            return out
        retire(s)
        s.grant(real)
        r = Routine(s, run_source(text), None, False, False, "APPLOAD")
        r.start()
    out["loaded"] = not r.error
    out["commands"] = sorted(set(s.commands()) - before)
    out["value"] = prin1(r.value) if not r.error else ""
    out["lines"] = list(r.lines)
    out["error"] = r.error
    out["file"] = real
    return out
