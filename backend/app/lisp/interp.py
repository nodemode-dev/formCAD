import math
import os
import sys
import time
from dataclasses import dataclass

from app.lisp.printer import prin1
from app.lisp.registry import BUILTIN, SPECIAL, bad_type, special
from app.lisp.types import AutoStub, Cons, ERROR_SYM, LAMBDA, LispAbort, LispError, MISSING, NULL, SLASH, Subr, Sym, T, Usubr, sym


@dataclass
class Limits:
    max_steps: int = 500_000_000
    max_depth: int = 100_000
    max_seconds: float = 60.0
    max_blocks: int = 9_000_000
    max_bytes: int = 128 * 1024 * 1024
    max_output: int = 2_000_000_000
    max_callback_depth: int = 32


_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096


def process_bytes() -> int:
    try:
        with open("/proc/self/statm", "rb") as fh:
            return int(fh.read().split()[1]) * _PAGE
    except (OSError, ValueError, IndexError):
        return sys.getallocatedblocks() * 64


class Out:
    def __init__(self, sink, limits: Limits):
        self.sink = sink
        self.partial = ""
        self.total = 0
        self.limits = limits

    def write(self, s: str) -> None:
        if not s:
            return
        self.total += len(s)
        if self.total > self.limits.max_output:
            raise LispAbort("out of memory: more text than the per-run budget", "limit")
        if "\n" not in s and "\r" not in s:
            self.partial += s
            return
        parts = s.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        for part in parts[:-1]:
            self.partial += part
            if self.partial:
                self.sink(self.partial)
                self.partial = ""
        self.partial += parts[-1]

    def flush(self) -> None:
        if self.partial:
            text, self.partial = self.partial, ""
            self.sink(text)


class Lisp:
    def __init__(self, syms: dict, limits: Limits | None = None):
        self.syms = syms
        self.limits = limits or Limits()
        self.out = Out(lambda line: None, self.limits)
        self.steps = 0
        self.depth = 0
        self.deadline = 0.0
        self.mem_base = 0
        self.byte_base = 0
        self.cancel_flag = False
        self.cb_depth = 0
        self.running = 0
        self.ctx = None
        self.init_bits = 0
        self.init_kw = ""
        self.files: dict = {}
        self.file_seq = 0
        self.deleted: dict = {}
        self.blockdef = None
        self.tbl_pos: dict = {}
        self.last_error = ""
        self.session = None
        self.load_depth = 0
        need = self.limits.max_depth * 12 + 20000
        if sys.getrecursionlimit() < need:
            sys.setrecursionlimit(need)

    def begin_run(self) -> None:
        self.steps = 0
        self.depth = 0
        self.cancel_flag = False
        self.deadline = time.monotonic() + self.limits.max_seconds
        self.mem_base = sys.getallocatedblocks()
        self.byte_base = process_bytes()
        try:
            from app.lisp import support

            self.limits.max_bytes = support.memory_mb() * 1024 * 1024
        except Exception:
            pass
        self.out.total = 0
        self.deleted = {}
        self.init_bits = 0
        self.init_kw = ""
        self.cb_depth = 0

    def check(self) -> None:
        if self.cancel_flag:
            raise LispAbort("Function cancelled", "cancel")
        if self.steps > self.limits.max_steps:
            raise LispAbort("execution step limit reached", "budget")
        if time.monotonic() > self.deadline:
            raise LispAbort("execution time limit reached", "budget")
        if sys.getallocatedblocks() - self.mem_base > self.limits.max_blocks:
            raise LispAbort("out of memory: too many live objects", "limit")
        if process_bytes() - self.byte_base > self.limits.max_bytes:
            raise LispAbort("out of memory: the routine grew past its %d MB budget" % (self.limits.max_bytes >> 20), "limit")

    def tick(self) -> None:
        self.steps += 1
        if not self.steps & 4095:
            self.check()

    def ev(self, x):
        t = type(x)
        if t is Sym:
            v = self.syms.get(x, MISSING)
            if v is MISSING:
                return BUILTIN.get(x)
            return v
        if t is not Cons:
            return x
        self.steps += 1
        if not self.steps & 4095:
            self.check()
        head = x.a
        if type(head) is Sym:
            sf = SPECIAL.get(head)
            if sf is not None:
                return sf(self, x.d)
            f = self.syms.get(head, MISSING)
            if f is MISSING:
                f = BUILTIN.get(head)
            if f is None:
                raise LispError("no function definition: %s" % head.name)
        else:
            f = self.ev(head)
        args = []
        a = x.d
        while type(a) is Cons:
            args.append(self.ev(a.a))
            a = a.d
        tf = type(f)
        if tf is Subr:
            n = len(args)
            if n < f.lo:
                raise LispError("too few arguments")
            if f.hi is not None and n > f.hi:
                raise LispError("too many arguments")
            return f.fn(self, *args)
        if tf is Usubr:
            return self.call_user(f, args)
        if tf is AutoStub:
            return self.run_stub(f, args)
        raise LispError("bad function: %s" % prin1(f))

    def apply(self, f, args: list):
        tf = type(f)
        if tf is Subr:
            n = len(args)
            if n < f.lo:
                raise LispError("too few arguments")
            if f.hi is not None and n > f.hi:
                raise LispError("too many arguments")
            return f.fn(self, *args)
        if tf is Usubr:
            return self.call_user(f, args)
        if tf is AutoStub:
            return self.run_stub(f, args)
        raise LispError("bad function: %s" % prin1(f))

    def call_user(self, f: Usubr, args: list):
        params = f.params
        if len(args) < len(params):
            raise LispError("too few arguments")
        if len(args) > len(params):
            raise LispError("too many arguments")
        if self.depth >= self.limits.max_depth:
            raise LispAbort("internal stack limit reached", "limit")
        syms = self.syms
        saved = []
        for p, v in zip(params, args):
            saved.append((p, syms.get(p, MISSING)))
            syms[p] = v
        for p in f.locals:
            saved.append((p, syms.get(p, MISSING)))
            syms[p] = None
        self.depth += 1
        try:
            r = None
            b = f.body
            while b is not None:
                r = self.ev(b.a)
                b = b.d
            return r
        finally:
            self.depth -= 1
            for p, v in reversed(saved):
                if v is MISSING:
                    syms.pop(p, None)
                else:
                    syms[p] = v

    def run_stub(self, f: AutoStub, args: list):
        key = sym("C:" + f.cmd.upper())
        if self.syms.get(key) is f:
            self.syms.pop(key, None)
        self.host_load(f.file, None, True)
        g = self.syms.get(key)
        if type(g) is not Usubr:
            raise LispError("file did not define %s" % f.cmd.upper())
        return self.call_user(g, args)

    def host_load(self, name, onfail, strict):
        from app.lisp import lib_misc

        return lib_misc.do_load(self, name, onfail, strict)

    def function_of(self, f):
        t = type(f)
        if t is Subr or t is Usubr or t is AutoStub:
            return f
        if t is Sym:
            v = self.syms.get(f, MISSING)
            if v is MISSING:
                v = BUILTIN.get(f)
            if type(v) in (Subr, Usubr, AutoStub):
                return v
            raise LispError("no function definition: %s" % f.name)
        if t is Cons and f.a is LAMBDA:
            return make_lambda(f.d)
        raise LispError("bad function: %s" % prin1(f))

    def call(self, f, args: list):
        return self.apply(self.function_of(f), args)

    def callback(self, f, args: list):
        func = self.function_of(f)
        if self.cb_depth >= self.limits.max_callback_depth:
            raise LispError("callback nested too deeply")
        self.cb_depth += 1
        try:
            return self.apply(func, args)
        finally:
            self.cb_depth -= 1

    def get(self, s: Sym):
        v = self.syms.get(s, MISSING)
        if v is MISSING:
            return BUILTIN.get(s)
        return v

    def fail(self, msg: str, kind: str = "error") -> None:
        self.last_error = msg
        handler = self.syms.get(ERROR_SYM)
        try:
            if kind != "budget" and type(handler) is Usubr:
                self.depth = 0
                self.cb_depth = 0
                self.steps = 0
                self.deadline = time.monotonic() + 10.0
                args = [msg] if handler.params else []
                self.call_user(handler, args)
            else:
                self.out.write("\n; error: %s\n" % msg)
        except LispError as err:
            self.out.write("\n; error: %s\n" % err.msg)
        except LispAbort as err:
            self.out.write("\n; error: %s\n" % err.msg)
        except RecursionError:
            self.out.write("\n; error: internal stack limit reached\n")


def make_lambda(rest) -> Usubr:
    if type(rest) is not Cons:
        raise LispError("too few arguments")
    params, locs = parse_params(rest.a)
    return Usubr(None, params, locs, rest.d)


def parse_params(plist):
    params = []
    locs = []
    cur = params
    x = plist
    while type(x) is Cons:
        p = x.a
        if p is SLASH:
            cur = locs
        elif type(p) is not Sym or p is T or p is NULL:
            raise bad_type("symbolp", p)
        else:
            cur.append(p)
        x = x.d
    if x is not None:
        raise bad_type("listp", plist)
    return params, locs


@special("quote")
def sf_quote(L, a):
    if a is None:
        raise LispError("too few arguments")
    return a.a


@special("function")
def sf_function(L, a):
    if a is None:
        raise LispError("too few arguments")
    x = a.a
    if type(x) is Cons and x.a is LAMBDA:
        return make_lambda(x.d)
    return x


@special("lambda")
def sf_lambda(L, a):
    return make_lambda(a)


@special("setq")
def sf_setq(L, a):
    if a is None:
        raise LispError("too few arguments")
    v = None
    syms = L.syms
    while a is not None:
        target = a.a
        if type(target) is not Sym or target is T or target is NULL:
            raise bad_type("symbolp", target)
        if a.d is None:
            v = None
            nxt = None
        else:
            v = L.ev(a.d.a)
            nxt = a.d.d
        syms[target] = v
        a = nxt
    return v


@special("if")
def sf_if(L, a):
    if a is None or a.d is None:
        raise LispError("too few arguments")
    rest = a.d.d
    if rest is not None and rest.d is not None:
        raise LispError("too many arguments")
    if L.ev(a.a) is not None:
        return L.ev(a.d.a)
    if rest is not None:
        return L.ev(rest.a)
    return None


@special("cond")
def sf_cond(L, a):
    while type(a) is Cons:
        clause = a.a
        if type(clause) is Cons:
            v = L.ev(clause.a)
            if v is not None:
                b = clause.d
                while type(b) is Cons:
                    v = L.ev(b.a)
                    b = b.d
                return v
        elif clause is not None:
            raise bad_type("listp", clause)
        a = a.d
    return None


@special("while")
def sf_while(L, a):
    if a is None:
        raise LispError("too few arguments")
    test = a.a
    body = a.d
    ev = L.ev
    while ev(test) is not None:
        b = body
        while type(b) is Cons:
            ev(b.a)
            b = b.d
        L.steps += 1
        if not L.steps & 4095:
            L.check()
    return None


@special("repeat")
def sf_repeat(L, a):
    if a is None:
        raise LispError("too few arguments")
    n = L.ev(a.a)
    if type(n) is not int:
        raise bad_type("fixnump", n)
    body = a.d
    ev = L.ev
    for _ in range(max(n, 0)):
        b = body
        while type(b) is Cons:
            ev(b.a)
            b = b.d
        L.steps += 1
        if not L.steps & 4095:
            L.check()
    return None


@special("foreach")
def sf_foreach(L, a):
    if a is None or a.d is None:
        raise LispError("too few arguments")
    var = a.a
    if type(var) is not Sym:
        raise bad_type("symbolp", var)
    seq = L.ev(a.d.a)
    body = a.d.d
    syms = L.syms
    old = syms.get(var, MISSING)
    try:
        cur = seq
        while type(cur) is Cons:
            syms[var] = cur.a
            b = body
            while type(b) is Cons:
                L.ev(b.a)
                b = b.d
            L.steps += 1
            if not L.steps & 4095:
                L.check()
            cur = cur.d
        if cur is not None:
            raise bad_type("listp", seq)
    finally:
        if old is MISSING:
            syms.pop(var, None)
        else:
            syms[var] = old
    return None


@special("progn")
def sf_progn(L, a):
    v = None
    while type(a) is Cons:
        v = L.ev(a.a)
        a = a.d
    return v


@special("and")
def sf_and(L, a):
    while type(a) is Cons:
        if L.ev(a.a) is None:
            return None
        a = a.d
    return T


@special("or")
def sf_or(L, a):
    while type(a) is Cons:
        if L.ev(a.a) is not None:
            return T
        a = a.d
    return None


@special("defun")
def sf_defun(L, a):
    if a is None or a.d is None:
        raise LispError("too few arguments")
    name = a.a
    if type(name) is not Sym or name is T or name is NULL:
        raise bad_type("symbolp", name)
    params, locs = parse_params(a.d.a)
    L.syms[name] = Usubr(name.name, params, locs, a.d.d)
    return name


SPECIAL[sym("defun-q")] = sf_defun


def initial_symbols() -> dict:
    return {T: T, sym("PI"): math.pi, sym("PAUSE"): "\\"}
