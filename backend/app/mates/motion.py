import time

from app.mates import interf, ops
from app.mates import store as S


def interference_sweep(doc, mid, start=0.0, end=350.0, count=36, clearance=None, fuzzy=None, max_step=None, ignore=None) -> dict:
    t0 = time.perf_counter()
    run = ops.drive(doc, mid, start=start, end=end, count=count, report=True, commit=False, max_step=max_step)
    rows = []
    worst = 0.0
    total = 0
    for s in run["samples"]:
        if not s.get("poses"):
            continue
        res = interf.check(doc, clearance=clearance, fuzzy=fuzzy, poses=s["poses"], ignore=ignore)
        total += res["count"]
        mx = max([r["volume"] for r in res["interferences"]], default=0.0)
        worst = max(worst, mx)
        near = min([r["distance"] for r in res["clearances"] if not r["contact"]], default=None)
        rows.append({"value": s["value"], "interferences": res["interferences"], "count": res["count"], "min_clearance": near, "solve_ms": s["ms"], "check_ms": res["ms"], "stats": res["stats"]})
    return {"ok": run["ok"] and total == 0, "driven_ok": run["ok"], "message": run["message"], "samples": len(rows), "interference_total": total, "worst_volume": worst, "rows": rows, "solve_ms": run["ms"], "ms": (time.perf_counter() - t0) * 1000.0}


def require_drivable(d, mid) -> None:
    if S.get(d, mid) is None:
        raise S.MateRefused("There is no mate %s." % mid)
