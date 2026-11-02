import re

from app.lisp.types import Cons, INT_MAX, INT_MIN, LispError, QUOTE, sym, T

MAX_NESTING = 2000
MAX_STRING = 8 * 1024 * 1024
_INT = re.compile(r"[+-]?\d+\Z")
_REAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
_DELIMS = set(' \t\r\n\f\v()";')
_EOF = object()
_DOT = object()


class ReadError(LispError):
    pass


def _skip(text: str, i: int, n: int) -> int:
    while i < n:
        c = text[i]
        if c in " \t\r\n\f\v":
            i += 1
        elif c == ";":
            if i + 1 < n and text[i + 1] == "|":
                j = text.find("|;", i + 2)
                i = n if j < 0 else j + 2
            else:
                j = text.find("\n", i)
                i = n if j < 0 else j + 1
        else:
            break
    return i


def _string(text: str, i: int, n: int):
    out = []
    i += 1
    while i < n:
        c = text[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\":
            i += 1
            if i >= n:
                break
            e = text[i]
            if e == "n":
                out.append("\n")
            elif e == "r":
                out.append("\r")
            elif e == "t":
                out.append("\t")
            elif e == "e":
                out.append("\x1b")
            elif e in "01234567":
                j = i
                while j < n and j < i + 3 and text[j] in "01234567":
                    j += 1
                out.append(chr(int(text[i:j], 8) & 0xFF))
                i = j
                continue
            else:
                out.append(e)
            i += 1
            continue
        out.append(c)
        if len(out) > MAX_STRING:
            raise ReadError("out of memory: string longer than %d" % MAX_STRING)
        i += 1
    raise ReadError("malformed string on input")


def _atom(tok: str):
    if _INT.match(tok):
        v = int(tok)
        if INT_MIN <= v <= INT_MAX:
            return v
        return float(v)
    if _REAL.match(tok):
        return float(tok)
    low = tok.lower()
    if low == "nil":
        return None
    if low == "t":
        return T
    return sym(tok)


def read_one(text: str, pos: int = 0):
    n = len(text)
    i = _skip(text, pos, n)
    stack: list = []
    quotes: list = []
    while True:
        i = _skip(text, i, n)
        if i >= n:
            if stack or quotes:
                raise ReadError("malformed quote on input" if quotes and not stack else "malformed list on input")
            return _EOF, n
        c = text[i]
        value = _EOF
        if c == "'":
            quotes.append(len(stack))
            i += 1
            continue
        if c == "(":
            if len(stack) >= MAX_NESTING:
                raise ReadError("too deeply nested input")
            stack.append([[], None, False, len(quotes)])
            i += 1
            continue
        if c == ")":
            if not stack:
                i += 1
                continue
            if quotes and quotes[-1] == len(stack):
                raise ReadError("malformed quote on input")
            items, tail, dotted, _q = stack.pop()
            if dotted and tail is _EOF:
                raise ReadError("misplaced dot on input")
            out = tail if dotted else None
            for v in reversed(items):
                out = Cons(v, out)
            value = out
            i += 1
        elif c == '"':
            s, i = _string(text, i, n)
            value = s
        else:
            j = i
            while j < n and text[j] not in _DELIMS:
                j += 1
            tok = text[i:j]
            i = j
            if tok == ".":
                if not stack or not stack[-1][0] or stack[-1][2]:
                    raise ReadError("misplaced dot on input")
                stack[-1][2] = True
                stack[-1][1] = _EOF
                continue
            value = _atom(tok)
        while True:
            while quotes and quotes[-1] == len(stack):
                quotes.pop()
                value = Cons(QUOTE, Cons(value, None))
            if not stack:
                return value, i
            top = stack[-1]
            if top[2]:
                if top[1] is not _EOF:
                    raise ReadError("misplaced dot on input")
                top[1] = value
            else:
                top[0].append(value)
            break


def read_all(text: str) -> list:
    forms = []
    pos = 0
    while True:
        v, pos = read_one(text, pos)
        if v is _EOF:
            return forms
        forms.append(v)


def is_eof(v) -> bool:
    return v is _EOF
