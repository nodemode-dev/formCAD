import re

MAX_SPEC = 4096


def _split(spec: str) -> list:
    parts = []
    cur = []
    i = 0
    n = len(spec)
    while i < n:
        ch = spec[i]
        if ch == "`" and i + 1 < n:
            cur.append(spec[i : i + 2])
            i += 2
            continue
        if ch == ",":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


def _one(pat: str):
    negate = False
    if pat.startswith("~"):
        negate = True
        pat = pat[1:]
    out = []
    i = 0
    n = len(pat)
    while i < n:
        ch = pat[i]
        if ch == "`" and i + 1 < n:
            out.append(re.escape(pat[i + 1]))
            i += 2
            continue
        if ch == "*":
            out.append(".*")
        elif ch == "?":
            out.append(".")
        elif ch == "#":
            out.append("[0-9]")
        elif ch == "@":
            out.append("[^\\W\\d_]")
        elif ch == ".":
            out.append("[^\\w]")
        elif ch == "[":
            j = i + 1
            neg = False
            if j < n and pat[j] == "~":
                neg = True
                j += 1
            k = j
            while k < n and pat[k] != "]":
                k += 2 if pat[k] == "`" and k + 1 < n else 1
            if k >= n:
                out.append(re.escape("["))
            else:
                body = []
                m = j
                while m < k:
                    c = pat[m]
                    if c == "`" and m + 1 < k:
                        body.append(re.escape(pat[m + 1]))
                        m += 2
                        continue
                    if m + 2 < k and pat[m + 1] == "-":
                        body.append("%s-%s" % (re.escape(c), re.escape(pat[m + 2])))
                        m += 3
                        continue
                    body.append(re.escape(c))
                    m += 1
                out.append("[%s%s]" % ("^" if neg else "", "".join(body)))
                i = k + 1
                continue
        else:
            out.append(re.escape(ch))
        i += 1
    return negate, re.compile("^" + "".join(out) + "$", re.IGNORECASE | re.DOTALL)


def compile_spec(spec: str) -> list:
    spec = str(spec if spec is not None else "*")[:MAX_SPEC]
    return [_one(p) for p in _split(spec)]


def matches(compiled, text: str) -> bool:
    if isinstance(compiled, str):
        compiled = compile_spec(compiled)
    text = str(text)
    positives = [rx for neg, rx in compiled if not neg]
    negatives = [rx for neg, rx in compiled if neg]
    if any(rx.match(text) for rx in negatives):
        return False
    if not positives:
        return bool(negatives)
    return any(rx.match(text) for rx in positives)


def filter_names(spec: str, names) -> list:
    compiled = compile_spec(spec)
    return [n for n in names if matches(compiled, n)]
