import time

import numpy as np

from app.param import store as S
from app.param import units as U
from app.solve import numeric as N

BUDGET = 2.0


def text_of(d, rec: dict) -> str:
    if rec.get("label"):
        shown = rec.get("expr") or U.format_value(float(rec.get("value") or 0.0))
        word = "driving" if rec.get("driving", True) else "reference"
        return "%s = %s (%s %s)" % (rec["label"], shown, rec["kind"], word)
    return "%s #%d" % (rec["kind"], rec["id"])


def item(d, net, cid: int) -> dict:
    if cid >= S.IMPLICIT_BASE:
        return {"id": cid, "kind": "joint", "label": "", "text": "a polyline vertex joint", "handles": []}
    rec = net.recs.get(cid) or S.get_con(d, cid) or {}
    handles = sorted({int(r[0]) for r in rec.get("refs", [])})
    return {"id": cid, "kind": rec.get("kind", "?"), "label": rec.get("label", ""), "text": text_of(d, rec) if rec else "constraint #%d" % cid, "handles": handles}


def _component(sk, ids):
    for ent_ids, cons in sk._components():
        if any(c.id in ids for c in cons):
            return cons
    return []


def _infeasible(cons, x0, w) -> bool:
    ok, _, _, _ = N.solve_system(cons, x0, w, max_it=60)
    if ok:
        return False
    rng = np.random.default_rng(7)
    scale = max(1.0, float(np.max(np.abs(x0)))) if x0.size else 1.0
    for _ in range(2):
        start = x0 + rng.normal(0.0, 0.03 * scale, x0.shape)
        ok, _, _, _ = N.solve_system(cons, start, w, max_it=60)
        if ok:
            return False
    return True


def _dependent(cons, x) -> bool:
    cols = sorted({int(i) for c in cons for i in c.vars})
    cmap = {c: k for k, c in enumerate(cols)}
    _, J = N.assemble(cons, x.copy(), cmap, len(cols), central=True)
    Jn, live = N.normalize_rows(J)
    if not live.all():
        return True
    return N.numeric_rank(Jn) < Jn.shape[0]


def conflict_set(net, rep, new_id, x0):
    sk = net.sk
    w = sk._weights()
    seeds = {c["id"] for c in rep.conflicts} | {new_id}
    comp = _component(sk, seeds)
    keep = {c["id"] for c in rep.conflicts}
    keep.add(new_id)
    cand = list(comp)
    t0 = time.perf_counter()
    exact = True
    for c in [c for c in comp if c.id not in keep]:
        if time.perf_counter() - t0 > BUDGET:
            exact = False
            break
        rest = [k for k in cand if k.id != c.id]
        if _infeasible(rest, x0, w):
            cand = rest
    return [c.id for c in cand], exact


def redundant_set(net, rep, new_id, x):
    entry = next((r for r in rep.redundant if r["id"] == new_id), None)
    if entry is None:
        return [new_id], True
    dups = [d["id"] for d in entry["duplicates"]]
    cons = {c.id: c for c in net.sk.cons.values()}
    cand = [i for i in dups if i in cons]
    t0 = time.perf_counter()
    exact = True
    for cid in list(cand):
        if time.perf_counter() - t0 > BUDGET:
            exact = False
            break
        rest = [i for i in cand if i != cid]
        if _dependent([cons[i] for i in rest + [new_id]], x):
            cand = rest
    return cand + [new_id], exact


def explain(d, net, rep, new_id, x_before) -> dict:
    x0 = np.array(x_before, dtype=float)
    if not rep.ok:
        ids, exact = conflict_set(net, rep, new_id, x0)
        kind = "conflict"
    else:
        ids, exact = redundant_set(net, rep, new_id, x0)
        kind = "redundant"
    ids = [i for i in ids]
    ids.sort(key=lambda i: (i == new_id, i))
    items = [item(d, net, i) for i in ids]
    for it in items:
        it["new"] = it["id"] == new_id
    names = ", ".join(it["text"] for it in items)
    if kind == "conflict":
        message = "These constraints cannot all hold at once: %s." % names
    else:
        message = "This constraint repeats what the others already fix: %s." % names
    return {"kind": kind, "constraints": items, "new": new_id, "minimal": exact, "message": message}
