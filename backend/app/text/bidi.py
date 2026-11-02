import unicodedata

MAX_DEPTH = 125

OPENERS = "([{༺༼᚛⁅⁽₍⌈⌊〈❨❪❬❮❰❲❴⟅⟦⟨⟪⟬⟮⦃⦅⦇⦉⦋⦍⦏⦑⦓⦕⦗⧘⧚⧼⸢⸤⸦⸨〈《「『【〔〖〘〚﹙﹛﹝（［｛｟｢"
CLOSERS = ")]}༻༽᚜⁆⁾₎⌉⌋〉❩❫❭❯❱❳❵⟆⟧⟩⟫⟭⟯⦄⦆⦈⦊⦌⦎⦐⦒⦔⦖⦘⧙⧛⧽⸣⸥⸧⸩〉》」』】〕〗〙〛﹚﹜﹞）］｝｠｣"
CLOSE_OF = dict(zip(OPENERS, CLOSERS))
OPEN_OF = dict(zip(CLOSERS, OPENERS))
CANON = {"〈": "〈", "〉": "〉"}
MIRROR = {}
for _a, _b in zip(OPENERS + "<«‹≤≥", CLOSERS + ">»›≥≤"):
    MIRROR[_a] = _b
    MIRROR[_b] = _a

ISOLATE_OPEN = ("LRI", "RLI", "FSI")
REMOVED = ("LRE", "RLE", "LRO", "RLO", "PDF", "BN")
NEUTRAL = ("B", "S", "WS", "ON", "FSI", "LRI", "RLI", "PDI")


def bidi_class(ch):
    c = unicodedata.bidirectional(ch)
    if c:
        return c
    cp = ord(ch)
    if 0x0590 <= cp <= 0x05FF or 0x07C0 <= cp <= 0x085F or 0xFB1D <= cp <= 0xFB4F or 0x10800 <= cp <= 0x10FFF or 0x1E800 <= cp <= 0x1EFFF:
        return "R"
    if 0x0600 <= cp <= 0x07BF or 0x0860 <= cp <= 0x08FF or 0xFB50 <= cp <= 0xFDFF or 0xFE70 <= cp <= 0xFEFF:
        return "AL"
    return "L"


def mirror(ch):
    return MIRROR.get(ch, ch)


def _match(orig):
    n = len(orig)
    fwd = [n] * n
    back = [-1] * n
    stack = []
    for i, c in enumerate(orig):
        if c in ISOLATE_OPEN:
            stack.append(i)
        elif c == "PDI" and stack:
            j = stack.pop()
            fwd[j] = i
            back[i] = j
    return fwd, back


def _first_strong(orig, start, end, fwd):
    i = start
    while i < end:
        c = orig[i]
        if c == "L":
            return 0
        if c in ("R", "AL"):
            return 1
        if c in ISOLATE_OPEN:
            i = fwd[i]
        i += 1
    return None


def _next_level(level, rtl):
    if rtl:
        return level + 1 if level % 2 == 0 else level + 2
    return level + 2 if level % 2 == 0 else level + 1


def _explicit(orig, para, fwd):
    n = len(orig)
    levels = [para] * n
    cls = list(orig)
    stack = [(para, None, False)]
    over_iso = 0
    over_emb = 0
    valid_iso = 0
    for i in range(n):
        c = orig[i]
        top = stack[-1]
        if c in ("RLE", "LRE", "RLO", "LRO"):
            levels[i] = top[0]
            nl = _next_level(top[0], c in ("RLE", "RLO"))
            if nl <= MAX_DEPTH and over_iso == 0 and over_emb == 0:
                ov = "R" if c == "RLO" else ("L" if c == "LRO" else None)
                stack.append((nl, ov, False))
            elif over_iso == 0:
                over_emb += 1
        elif c in ISOLATE_OPEN:
            levels[i] = top[0]
            if top[1]:
                cls[i] = top[1]
            if c == "FSI":
                rtl = _first_strong(orig, i + 1, fwd[i], fwd) == 1
            else:
                rtl = c == "RLI"
            nl = _next_level(top[0], rtl)
            if nl <= MAX_DEPTH and over_iso == 0 and over_emb == 0:
                valid_iso += 1
                stack.append((nl, None, True))
            else:
                over_iso += 1
        elif c == "PDI":
            if over_iso > 0:
                over_iso -= 1
            elif valid_iso > 0:
                over_emb = 0
                while not stack[-1][2]:
                    stack.pop()
                stack.pop()
                valid_iso -= 1
            top = stack[-1]
            levels[i] = top[0]
            if top[1]:
                cls[i] = top[1]
        elif c == "PDF":
            levels[i] = top[0]
            if over_iso > 0:
                pass
            elif over_emb > 0:
                over_emb -= 1
            elif not top[2] and len(stack) >= 2:
                stack.pop()
        elif c == "B":
            levels[i] = para
        elif c == "BN":
            levels[i] = top[0]
        else:
            levels[i] = top[0]
            if top[1]:
                cls[i] = top[1]
    return levels, cls


def _sequences(idx, levels, orig, fwd, back):
    runs = []
    cur = []
    for i in idx:
        if cur and levels[i] != levels[cur[-1]]:
            runs.append(cur)
            cur = []
        cur.append(i)
    if cur:
        runs.append(cur)
    start_of = {r[0]: k for k, r in enumerate(runs)}
    seqs = []
    for r in runs:
        first = r[0]
        if orig[first] == "PDI" and back[first] >= 0:
            continue
        seq = list(r)
        while orig[seq[-1]] in ISOLATE_OPEN and fwd[seq[-1]] < len(orig) and fwd[seq[-1]] in start_of:
            seq.extend(runs[start_of[fwd[seq[-1]]]])
        seqs.append(seq)
    return seqs


def _strong_before(t, k, sos):
    j = k - 1
    while j >= 0:
        if t[j] in ("L", "R", "AL"):
            return t[j]
        j -= 1
    return sos


def _weak(t, sos):
    n = len(t)
    for k in range(n):
        if t[k] == "NSM":
            if k == 0:
                t[k] = sos
            else:
                p = t[k - 1]
                t[k] = "ON" if p in ISOLATE_OPEN or p == "PDI" else p
    for k in range(n):
        if t[k] == "EN" and _strong_before(t, k, sos) == "AL":
            t[k] = "AN"
    for k in range(n):
        if t[k] == "AL":
            t[k] = "R"
    for k in range(1, n - 1):
        if t[k] == "ES" and t[k - 1] == "EN" and t[k + 1] == "EN":
            t[k] = "EN"
        elif t[k] == "CS" and t[k - 1] == t[k + 1] and t[k - 1] in ("EN", "AN"):
            t[k] = t[k - 1]
    k = 0
    while k < n:
        if t[k] == "ET":
            j = k
            while j < n and t[j] == "ET":
                j += 1
            if (k > 0 and t[k - 1] == "EN") or (j < n and t[j] == "EN"):
                for m in range(k, j):
                    t[m] = "EN"
            k = j
        else:
            k += 1
    for k in range(n):
        if t[k] in ("ES", "ET", "CS"):
            t[k] = "ON"
    last = sos
    for k in range(n):
        if t[k] in ("L", "R"):
            last = t[k]
        elif t[k] == "EN" and last == "L":
            t[k] = "L"


def _pairs(text, seq, t):
    stack = []
    out = []
    for k, i in enumerate(seq):
        if t[k] != "ON":
            continue
        ch = text[i]
        if ch in CLOSE_OF:
            if len(stack) >= 63:
                break
            stack.append((CANON.get(CLOSE_OF[ch], CLOSE_OF[ch]), k))
        elif ch in OPEN_OF:
            c = CANON.get(ch, ch)
            for s in range(len(stack) - 1, -1, -1):
                if stack[s][0] == c:
                    out.append((stack[s][1], k))
                    del stack[s:]
                    break
    out.sort()
    return out


def _strong_of(x):
    if x == "L":
        return "L"
    if x in ("R", "EN", "AN"):
        return "R"
    return None


def _brackets(text, seq, t, orig, level, sos):
    e = "R" if level % 2 else "L"
    o = "L" if e == "R" else "R"
    for a, b in _pairs(text, seq, t):
        found_e = False
        found_o = False
        for k in range(a + 1, b):
            s = _strong_of(t[k])
            if s == e:
                found_e = True
                break
            if s == o:
                found_o = True
        if found_e:
            new = e
        elif found_o:
            ctx = sos
            for k in range(a - 1, -1, -1):
                s = _strong_of(t[k])
                if s:
                    ctx = s
                    break
            new = o if ctx == o else e
        else:
            continue
        for pos in (a, b):
            t[pos] = new
            k = pos + 1
            while k < len(seq) and orig[seq[k]] == "NSM":
                t[k] = new
                k += 1


def _neutral(t, sos, eos, level):
    n = len(t)
    e = "R" if level % 2 else "L"
    k = 0
    while k < n:
        if t[k] in NEUTRAL:
            j = k
            while j < n and t[j] in NEUTRAL:
                j += 1
            before = sos if k == 0 else _strong_of(t[k - 1])
            after = eos if j == n else _strong_of(t[j])
            new = before if before == after and before else e
            for m in range(k, j):
                t[m] = new
            k = j
        else:
            k += 1


def resolve(text, base=None):
    n = len(text)
    if n == 0:
        return [], 0 if base is None else base
    orig = [bidi_class(c) for c in text]
    fwd, back = _match(orig)
    if base is None:
        base = _first_strong(orig, 0, n, fwd) or 0
    explicit, cls = _explicit(orig, base, fwd)
    levels = list(explicit)
    kept = [i for i in range(n) if orig[i] not in REMOVED]
    for seq in _sequences(kept, explicit, orig, fwd, back):
        level = explicit[seq[0]]
        pos = _locate(kept, seq[0])
        prev = explicit[kept[pos - 1]] if pos > 0 else base
        last = seq[-1]
        lp = _locate(kept, last)
        if orig[last] in ISOLATE_OPEN and fwd[last] >= n:
            nxt = base
        else:
            nxt = explicit[kept[lp + 1]] if lp + 1 < len(kept) else base
        sos = "R" if max(level, prev) % 2 else "L"
        eos = "R" if max(level, nxt) % 2 else "L"
        t = [cls[i] for i in seq]
        _weak(t, sos)
        _brackets(text, seq, t, orig, level, sos)
        _neutral(t, sos, eos, level)
        for k, i in enumerate(seq):
            c = t[k]
            if level % 2 == 0:
                levels[i] = level + (1 if c == "R" else (2 if c in ("AN", "EN") else 0))
            else:
                levels[i] = level + (1 if c in ("L", "EN", "AN") else 0)
    last = base
    for i in range(n):
        if orig[i] in REMOVED:
            levels[i] = last
        else:
            last = levels[i]
    return levels, base


def _locate(kept, i):
    lo, hi = 0, len(kept)
    while lo < hi:
        mid = (lo + hi) // 2
        if kept[mid] < i:
            lo = mid + 1
        else:
            hi = mid
    return lo


def line_levels(text, levels, base, start=0, end=None):
    n = len(text) if end is None else end
    out = list(levels[start:n])
    cls = [bidi_class(c) for c in text[start:n]]
    ws = ("WS", "FSI", "LRI", "RLI", "PDI", "LRE", "RLE", "LRO", "RLO", "PDF", "BN")
    run_end = True
    for k in range(len(cls) - 1, -1, -1):
        c = cls[k]
        if c in ("S", "B"):
            out[k] = base
            run_end = True
        elif c in ws and run_end:
            out[k] = base
        else:
            run_end = False
    return out


def visual_order(levels):
    n = len(levels)
    order = list(range(n))
    if n == 0:
        return order
    top = max(levels)
    low_odd = min((v for v in levels if v % 2), default=None)
    if low_odd is None:
        return order
    for lvl in range(top, low_odd - 1, -1):
        k = 0
        while k < n:
            if levels[order[k]] >= lvl:
                j = k
                while j < n and levels[order[j]] >= lvl:
                    j += 1
                order[k:j] = order[k:j][::-1]
                k = j
            else:
                k += 1
    return order


def reorder(text, levels, base, start=0, end=None):
    n = len(text) if end is None else end
    ll = line_levels(text, levels, base, start, n)
    return [start + i for i in visual_order(ll)]
