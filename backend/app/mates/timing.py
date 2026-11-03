import threading
import time
from collections import deque

LIMIT = 500
_lock = threading.Lock()
_log: dict = {}


def record(doc_key, kind: str, ms: float, iterations: int, bodies: int, mates: int) -> None:
    with _lock:
        q = _log.setdefault(str(doc_key), deque(maxlen=LIMIT))
        q.append({"at": time.time(), "kind": kind, "ms": round(float(ms), 3), "iterations": int(iterations), "bodies": int(bodies), "mates": int(mates)})


def read(doc_key, kind: str = "") -> dict:
    with _lock:
        rows = [r for r in _log.get(str(doc_key), []) if not kind or r["kind"] == kind]
    ms = sorted(r["ms"] for r in rows)
    out = {"count": len(rows), "rows": rows[-100:]}
    if ms:
        out.update(mean_ms=sum(ms) / len(ms), median_ms=ms[len(ms) // 2], max_ms=ms[-1], p95_ms=ms[min(len(ms) - 1, int(0.95 * len(ms)))])
    return out


def clear(doc_key) -> None:
    with _lock:
        _log.pop(str(doc_key), None)
