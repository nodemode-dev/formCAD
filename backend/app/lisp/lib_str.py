import re
import sys

from app.lisp import reader
from app.lisp.printer import princ, prin1
from app.lisp.registry import bad_value, fn, integer, string, symbol, truth
from app.lisp.types import LispError, Sym, from_list, to_list, wrap32

MAX_STRING = 8 * 1024 * 1024
_NUMTOK = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")
_INTTOK = re.compile(r"\s*([+-]?\d+)")


@fn("strcat", 0)
def f_strcat(L, *args):
    total = 0
    for a in args:
        string(a)
        total += len(a)
        if total > MAX_STRING:
            from app.lisp.types import LispAbort

            raise LispAbort("out of memory: string longer than %d" % MAX_STRING, "limit")
    return "".join(args)


@fn("strlen", 0)
def f_strlen(L, *args):
    n = 0
    for a in args:
        n += len(string(a))
    return n


@fn("substr", 2, 3)
def f_substr(L, s, start, length=None):
    string(s)
    integer(start)
    if start < 1:
        raise bad_value(start)
    if length is not None:
        integer(length)
        if length < 0:
            raise bad_value(length)
        return s[start - 1 : start - 1 + length]
    return s[start - 1 :]


@fn("strcase", 1, 2)
def f_strcase(L, s, lower=None):
    string(s)
    return s.lower() if lower is not None else s.upper()


@fn("itoa", 1, 1)
def f_itoa(L, n):
    integer(n)
    return str(n)


@fn("atoi", 1, 1)
def f_atoi(L, s):
    string(s)
    m = _INTTOK.match(s)
    return wrap32(int(m.group(1))) if m else 0


@fn("atof", 1, 1)
def f_atof(L, s):
    string(s)
    m = _NUMTOK.match(s)
    if not m:
        return 0.0
    v = float(m.group(1))
    if v == float("inf"):
        return sys.float_info.max
    if v == float("-inf"):
        return -sys.float_info.max
    return v


@fn("chr", 1, 1)
def f_chr(L, n):
    integer(n)
    if n < 1 or n > 255:
        raise bad_value(n)
    return chr(n)


@fn("ascii", 1, 1)
def f_ascii(L, s):
    string(s)
    return ord(s[0]) if s else 0


@fn("read", 0, 1)
def f_read(L, s=""):
    string(s)
    v, _ = reader.read_one(s, 0)
    return None if reader.is_eof(v) else v


def _tokens(pat: str) -> list:
    alts = []
    cur = []
    i = 0
    n = len(pat)
    while i < n:
        c = pat[i]
        if c == "`" and i + 1 < n:
            cur.append(("lit", pat[i + 1]))
            i += 2
            continue
        if c == ",":
            alts.append(cur)
            cur = []
            i += 1
            continue
        if c == "[":
            j = i + 1
            neg = False
            if j < n and pat[j] == "~":
                neg = True
                j += 1
            items = []
            while j < n and pat[j] != "]":
                if pat[j] == "`" and j + 1 < n:
                    ch = pat[j + 1]
                    j += 2
                else:
                    ch = pat[j]
                    j += 1
                if j + 1 < n and pat[j] == "-" and pat[j + 1] != "]":
                    hi = pat[j + 1]
                    j += 2
                    items.append((ch, hi))
                else:
                    items.append((ch, ch))
            if j >= n:
                cur.append(("lit", "["))
                i += 1
                continue
            cur.append(("set", neg, items))
            i = j + 1
            continue
        if c == "*":
            cur.append(("star",))
        elif c == "?":
            cur.append(("any",))
        elif c == "#":
            cur.append(("digit",))
        elif c == "@":
            cur.append(("alpha",))
        elif c == ".":
            cur.append(("punct",))
        else:
            cur.append(("lit", c))
        i += 1
    alts.append(cur)
    return alts


def _one(tok, ch: str) -> bool:
    k = tok[0]
    if k == "lit":
        return ch == tok[1]
    if k == "any":
        return True
    if k == "digit":
        return ch.isdigit()
    if k == "alpha":
        return ch.isalpha()
    if k == "punct":
        return not ch.isalnum()
    hit = any(lo <= ch <= hi for lo, hi in tok[2])
    return hit != tok[1]


def _match(toks: list, s: str, budget: list) -> bool:
    i = j = 0
    star = -1
    mark = 0
    n, m = len(s), len(toks)
    while i < n:
        budget[0] -= 1
        if budget[0] < 0:
            raise LispError("wcmatch: pattern too complex")
        if j < m and toks[j][0] == "star":
            star = j
            mark = i
            j += 1
        elif j < m and _one(toks[j], s[i]):
            i += 1
            j += 1
        elif star >= 0:
            mark += 1
            i = mark
            j = star + 1
        else:
            return False
    while j < m and toks[j][0] == "star":
        j += 1
    return j == m


def wc_match(s: str, pat: str, fold: bool = False) -> bool:
    if fold:
        s = s.lower()
        pat = pat.lower()
    neg = False
    if pat.startswith("~"):
        neg = True
        pat = pat[1:]
    budget = [200000 + 50 * len(pat) * max(len(s), 1)]
    budget[0] = min(budget[0], 5_000_000)
    hit = any(_match(a, s, budget) for a in _tokens(pat))
    return hit != neg


@fn("wcmatch", 2, 2)
def f_wcmatch(L, s, pat):
    string(s)
    string(pat)
    return truth(wc_match(s, pat))


@fn("vl-prin1-to-string", 1, 1)
def f_prin1_str(L, x):
    return prin1(x)


@fn("vl-princ-to-string", 1, 1)
def f_princ_str(L, x):
    return princ(x)


@fn("vl-symbol-name", 1, 1)
def f_sym_name(L, s):
    return symbol(s).name


@fn("vl-symbolp", 1, 1)
def f_symbolp(L, s):
    return truth(type(s) is Sym)


@fn("vl-string-search", 2, 3)
def f_str_search(L, pat, s, start=0):
    string(pat)
    string(s)
    integer(start)
    if start < 0:
        raise bad_value(start)
    i = s.find(pat, start)
    return None if i < 0 else i


@fn("vl-string-subst", 3, 4)
def f_str_subst(L, new, old, s, start=0):
    string(new)
    string(old)
    string(s)
    integer(start)
    if start < 0:
        raise bad_value(start)
    i = s.find(old, start) if old else -1
    if i < 0:
        return s
    return s[:i] + new + s[i + len(old) :]


@fn("vl-string-trim", 2, 2)
def f_trim(L, chars, s):
    return string(s).strip(string(chars))


@fn("vl-string-left-trim", 2, 2)
def f_ltrim(L, chars, s):
    return string(s).lstrip(string(chars))


@fn("vl-string-right-trim", 2, 2)
def f_rtrim(L, chars, s):
    return string(s).rstrip(string(chars))


@fn("vl-string-translate", 3, 3)
def f_translate(L, src, dst, s):
    string(src)
    string(dst)
    string(s)
    table = {}
    for i, ch in enumerate(src):
        if i < len(dst):
            table.setdefault(ch, dst[i])
    return "".join(table.get(ch, ch) for ch in s)


@fn("vl-string->list", 1, 1)
def f_str_to_list(L, s):
    return from_list([ord(c) for c in string(s)])


@fn("vl-list->string", 1, 1)
def f_list_to_str(L, a):
    codes = to_list(a)
    out = []
    for c in codes:
        integer(c)
        if c < 0 or c > 0x10FFFF:
            raise bad_value(c)
        out.append(chr(c))
    return "".join(out)


def _split_path(p: str):
    p = p.replace("\\", "/")
    i = p.rfind("/")
    return (p[:i], p[i + 1 :]) if i >= 0 else ("", p)


@fn("vl-filename-base", 1, 1)
def f_fbase(L, p):
    _, name = _split_path(string(p))
    i = name.rfind(".")
    return name[:i] if i > 0 else name


@fn("vl-filename-extension", 1, 1)
def f_fext(L, p):
    _, name = _split_path(string(p))
    i = name.rfind(".")
    return name[i:] if i > 0 else None


@fn("vl-filename-directory", 1, 1)
def f_fdir(L, p):
    d, _ = _split_path(string(p))
    return d
