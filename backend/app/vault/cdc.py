import bisect

import numpy as np

from blake3 import blake3

MIN_SIZE = 64 * 1024
AVG_SIZE = 256 * 1024
MAX_SIZE = 1024 * 1024
WINDOW = 48
BLOCK = 4 * 1024 * 1024
MASK_STRICT = 20
MASK_LOOSE = 16
NAME = "window-cdc-1"

_MUL = np.uint64(0x9E3779B97F4A7C15)
_TABLE = None
_POWERS = None


def _table():
    global _TABLE
    if _TABLE is None:
        vals = [int.from_bytes(blake3(b"formcad-vault-gear" + bytes([i])).digest()[:8], "little") for i in range(256)]
        _TABLE = np.array(vals, dtype=np.uint64)
    return _TABLE


def _powers(count: int):
    global _POWERS
    if _POWERS is None or len(_POWERS[0]) < count:
        base = int(_MUL)
        inv = pow(base, -1, 1 << 64)
        fwd = np.full(count, base, dtype=np.uint64)
        fwd[0] = 1
        back = np.full(count, inv, dtype=np.uint64)
        back[0] = 1
        _POWERS = (np.cumprod(fwd, dtype=np.uint64), np.cumprod(back, dtype=np.uint64))
    return _POWERS


def _candidates(data: bytes):
    n = len(data)
    strict, loose = [], []
    if n < MIN_SIZE:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=np.int64)
    fwd, back = _powers(BLOCK + WINDOW + 1)
    table = _table()
    pos = 0
    shift =np.uint64(64 - MASK_STRICT)
    shift_l = np.uint64(64 - MASK_LOOSE)
    while pos < n:
        end = min(n, pos + BLOCK)
        lo = max(0, pos - (WINDOW - 1))
        arr = np.frombuffer(data, dtype=np.uint8, count=end - lo, offset=lo)
        g = table[arr]
        terms = g * back[: len(g)]
        s = np.cumsum(terms, dtype=np.uint64)
        k = len(g)
        w = np.empty(k, dtype=np.uint64)
        w[:WINDOW] = s[:WINDOW]
        w[WINDOW:] = s[WINDOW:] - s[:-WINDOW]
        w *= fwd[:k]
        valid = np.arange(k) + lo
        keep = (valid >= pos) & (valid >= WINDOW - 1)
        top = w >> shift
        top_l = w >> shift_l
        strict.append(valid[keep & (top == 0)] + 1)
        loose.append(valid[keep & (top_l == 0)] + 1)
        pos = end
    return np.concatenate(strict) if strict else np.zeros(0, dtype=np.int64), np.concatenate(loose) if loose else np.zeros(0, dtype=np.int64)


def cut(data: bytes) -> list:
    n = len(data)
    if n <= MIN_SIZE:
        return [n] if n else []
    strict, loose = _candidates(data)
    strict = strict.tolist()
    loose = loose.tolist()
    out = []
    start = 0
    while start < n:
        rest = n - start
        if rest <= MIN_SIZE:
            out.append(n)
            break
        lo = start + MIN_SIZE
        mid = min(start + AVG_SIZE, n)
        hi = min(start + MAX_SIZE, n)
        i = bisect.bisect_left(strict, lo)
        if i < len(strict) and strict[i] < mid:
            end = strict[i]
        else:
            j = bisect.bisect_left(loose, mid)
            end = loose[j] if j < len(loose) and loose[j] <= hi else hi
        out.append(end)
        start = end
    return out
