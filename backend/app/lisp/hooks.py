from app.lisp import bridge
from app.lisp.printer import prin1
from app.lisp.session import Routine, get_session, retire, run_source
from app.lisp.types import Cons, NULL, point_of, sym


def _close(text: str, i: int) -> int:
    n = len(text)
    depth = 0
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            if c == "\\":
                i += 1
            elif c == '"':
                in_str = False
        elif c == '"':
            in_str = True
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth <= 0:
                return i + 1
        i += 1
    return n


def split_tokens(text: str) -> list:
    out = []
    i = 0
    n = len(text)
    while True:
        k = _close(text, i) if i < n and text[i] == "(" else i
        while k < n and text[k] not in " \t":
            k += 1
        out.append(text[i:k])
        i = k
        if i >= n:
            break
        i += 1
        if i >= n:
            out.append("")
            break
    return out


def _bang(name: str):
    key = sym(name.strip())

    def body(L):
        return L.get(key)

    return body


def run_line(runner, text: str) -> None:
    s = get_session(runner.doc)
    if s.running:
        runner._fail("A routine is already running.")
        return
    retire(s)
    line = text.strip()
    body = _bang(line[1:]) if line.startswith("!") else run_source(line)
    Routine(s, body, None, True, True, "LISP").start()


def answer(runner, tok: str):
    s = get_session(runner.doc)
    if s.running:
        runner._fail("A routine is already running.")
        return None
    body = _bang(tok[1:]) if tok.startswith("!") else run_source(tok)
    r = Routine(s, body, None, False, False, "LISP", False)
    r.start()
    if r.error:
        return None
    v = r.value
    if v is None or v is NULL:
        return None
    t = type(v)
    if t is int:
        return str(v)
    if t is float:
        try:
            return bridge.real_text(v)
        except Exception:
            runner._fail("bad argument type: command argument")
            return None
    if t is str:
        return v
    if t is Cons:
        pt = point_of(v)
        if pt is not None:
            return bridge.point_text(pt)
    runner._fail("bad argument type: %s" % prin1(v))
    return None


def lisp_command(runner, word: str, rest: list) -> bool:
    doc = runner.doc
    s = get_session(doc)
    if s.running or not word or not word.replace("-", "").replace("_", "").isalnum():
        return False
    f = s.user_command(word)
    if f is None:
        return False
    retire(s)
    runner.log("Command: %s" % word.upper())

    def body(L):
        return L.call_user(f, [])

    Routine(s, body, None, True, False, word.upper()).start()
    return True


def poll(runner) -> None:
    s = getattr(runner.doc, "lisp_session", None)
    if s is None or s.hold is None:
        return
    with runner.doc.lock:
        h = s.hold
        if h is not None:
            h.poll()
