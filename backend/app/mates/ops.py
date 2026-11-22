import copy
import math
import time

import numpy as np

from app.assembly import store as A
from app.assembly import xform
from app.mates import eqs, explain, joint_eq, pick, rig, timing
from app.mates import net as N
from app.mates import store as S
from app.param.units import mm_per_unit

ALIASES = {"concentric": "concentric", "coaxial": "concentric", "coincident": "coincident", "distance": "distance", "angle": "angle", "parallel": "parallel", "perpendicular": "perpendicular", "tangent": "tangent", "lock": "lock", "gear": "gear", "rack": "rackpinion", "rackpinion": "rackpinion", "rack_and_pinion": "rackpinion", "screw": "screw", "limitdistance": "limitdistance", "limit_distance": "limitdistance", "limitangle": "limitangle", "limit_angle": "limitangle", "symmetric": "symmetric", "symmetry": "symmetric", "width": "width", "path": "path", "slot": "slot", "cam": "cam", "camfollower": "cam"}
REF_COUNT = {"angle": (2, 3), "limitangle": (2, 3), "symmetric": (3, 3), "width": (4, 4)}
ANGLE_KINDS = ("angle", "limitangle")
STEP_DEG = 5.0
MAX_MATES = 5000


def kind_of(word) -> str:
    k = ALIASES.get(str(word or "").strip().lower().replace(" ", ""))
    if k is None:
        raise S.MateRefused("%s is not a mate kind; use %s." % (word, ", ".join(eqs.KINDS)))
    return k


def to_mate(rec: dict) -> eqs.Mate:
    kind = rec["kind"]
    sides = [pick.side_of(g) for g in rec["geom"]]
    if kind in joint_eq.KINDS:
        return eqs.Mate(int(rec["id"]), kind, sides, None, joint_eq.runtime(rec), rec.get("name", ""), bool(rec.get("suppressed")))
    value = rec.get("value")
    opt = copy.deepcopy(rec.get("opt") or {})
    if kind == "angle" and value is not None:
        value = math.radians(float(value))
    if kind == "limitangle":
        opt["min"] = math.radians(float(opt.get("min_user", opt.get("min", 0.0))))
        opt["max"] = math.radians(float(opt.get("max_user", opt.get("max", 0.0))))
    if kind == "limitdistance":
        opt["min"] = float(opt.get("min_user", opt.get("min", 0.0)))
        opt["max"] = float(opt.get("max_user", opt.get("max", 0.0)))
    m = eqs.Mate(int(rec["id"]), kind, sides, value, opt, rec.get("name", ""), bool(rec.get("suppressed")))
    return m


def clean_opt(m: eqs.Mate, rec: dict) -> dict:
    if m.kind in joint_eq.KINDS:
        return joint_eq.persist(m, rec)
    out = {}
    for k, v in m.opt.items():
        if k in ("min", "max") and m.kind.startswith("limit"):
            continue
        out[k] = _plain(v)
    if m.kind.startswith("limit"):
        out["min_user"] = rec["opt"].get("min_user")
        out["max_user"] = rec["opt"].get("max_user")
    return out


def _plain(v):
    if isinstance(v, np.ndarray):
        return [float(x) for x in v.reshape(-1)]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, (np.floating,)):
        return float(v)
    return v


class Model:
    def __init__(self, d):
        self.d = d
        self.mmu = mm_per_unit(d)
        self.crec = {r["id"]: r for r in A.components(d)}
        bodies = []
        for r in self.crec.values():
            if r.get("suppressed"):
                continue
            try:
                m = xform.as_matrix(r.get("transform"))
            except xform.TransformError:
                m = np.eye(4)
            bodies.append(N.Body(r["id"], m, bool(r.get("fixed"))))
        self.bodies = bodies
        self.ids = {b.id for b in bodies}
        self.recs = {r["id"]: copy.deepcopy(r) for r in S.records(d)}
        self.mates = []
        self.inactive = {}
        for r in self.recs.values():
            m = to_mate(r)
            miss = [c for c in m.comps() if c not in self.ids]
            if miss:
                m.suppressed = True
                self.inactive[m.id] = "component %s is suppressed or missing" % miss[0]
            self.mates.append(m)
        self.L = 100.0 / self.mmu
        self.net = N.Network(bodies, self.mates, scale=self.L)
        self.start = self.net.snapshot()

    def by_id(self, mid):
        for m in self.mates:
            if m.id == mid:
                return m
        raise S.MateRefused("There is no mate %s." % mid)

    def changed(self, since=None) -> list:
        ref = since or self.start
        out = []
        for c, (r, t) in ref.items():
            b = self.net.bodies[c]
            if np.max(np.abs(b.R - r)) > 1e-11 or np.max(np.abs(b.t - t)) > 1e-11:
                out.append(c)
        return out

    def write(self, ids) -> list:
        moved = []
        for c in ids:
            rec = copy.deepcopy(self.crec[c])
            rec["transform"] = xform.to_list(self.net.bodies[c].matrix())
            A.put(self.d, rec)
            moved.append(c)
        return moved

    def save_mate(self, m: eqs.Mate) -> None:
        rec = copy.deepcopy(self.recs[m.id])
        rec["opt"] = clean_opt(m, rec)
        rec["suppressed"] = bool(rec.get("suppressed"))
        self.recs[m.id] = rec
        S.put(self.d, rec)

    def save_states(self) -> None:
        for m in self.mates:
            if m.suppressed or (m.kind not in eqs.MECHANICAL and m.kind not in joint_eq.KINDS):
                continue
            self.save_mate(m)

    def component_of(self, mate_id: int) -> list:
        seed = set(self.by_id(mate_id).comps())
        act = self.net.active()
        grown = True
        picked = set()
        while grown:
            grown = False
            for m in act:
                cs = set(m.comps())
                if m.id not in picked and (cs & seed or (not cs)):
                    picked.add(m.id)
                    seed |= cs
                    grown = True
        return [m for m in act if m.id in picked]


def poses_of(model: Model, ids=None) -> dict:
    return {c: xform.to_list(b.matrix()) for c, b in model.net.bodies.items() if ids is None or c in ids}


def mate_rows(model: Model, an: dict) -> list:
    info = {r["id"]: r for r in an["mates"]}
    rows = []
    for m in model.mates:
        rec = model.recs[m.id]
        row = {"id": m.id, "name": rec["name"], "label": rec.get("label", ""), "kind": m.kind, "suppressed": bool(rec.get("suppressed")), "text": explain.text_of(rec)}
        if m.id in model.inactive:
            row.update(state="inactive", reason=model.inactive[m.id], removes=0, residual=0.0)
        elif m.suppressed:
            row.update(state="suppressed", removes=0, residual=0.0)
        else:
            i = info.get(m.id, {})
            res = model.net.mate_res(m)
            row.update(state=i.get("state", "active"), removes=i.get("removes", 0), added=i.get("added", 0), overlap=i.get("overlap", 0), redundant=i.get("redundant", False), residual=float(np.max(np.abs(res))) if res.size else 0.0)
            if m.kind.startswith("limit"):
                row["limit_active"] = bool(i.get("state") == "active")
        rows.append(row)
    return rows


def summary(model: Model, st: dict | None = None) -> dict:
    st = st or model.net.status()
    comps = {}
    for c, v in st["components"].items():
        comps[c] = {"dof": v["dof"], "state": v["state"], "modes": v["modes"]}
    return {"state": st["state"], "dof": st["dof"], "rank": st["rank"], "residual": st["residual"], "components": comps, "mates": mate_rows(model, st), "redundant": st["redundant"], "groups": [{"bodies": g["bodies"], "grounded": g["grounded"], "dof": g.get("internal", 0)} for g in st["groups"]]}


def solve_all(model: Model, label="solve") -> N.Report:
    rep = model.net.solve()
    timing.record(id(model.d), label, rep.ms, rep.iterations, len(model.bodies), len(model.net.active()))
    return rep


def conflict_explanation(model: Model, start, new_id=None) -> dict:
    pool = model.component_of(new_id) if new_id is not None else model.net.active()
    cand, exact = model.net.conflict_set(pool, start)
    fixes = model.net.fixes(model.net.active(), start, cand)
    return explain.conflict({m.id: model.recs[m.id] for m in model.mates}, cand, exact, fixes, new_id)


def weights_for(model: Model, m: eqs.Mate) -> dict:
    used = set()
    for o in model.net.active():
        if o.id != m.id:
            used.update(o.comps())
    saved = {c: b.weight for c, b in model.net.bodies.items()}
    cs = [c for c in m.comps() if c in model.net.bodies]
    for c in cs:
        model.net.bodies[c].weight = 1000.0 if c in used else 1.0
    if cs and all(model.net.bodies[c].weight == 1.0 for c in cs):
        model.net.bodies[cs[0]].weight = 1000.0
    return saved


def restore_weights(model: Model, saved: dict) -> None:
    for c, w in saved.items():
        model.net.bodies[c].weight = w


def new_record(d, kind, refs, geoms, value, opt, label, mid) -> dict:
    opt = dict(opt or {})
    if kind.startswith("limit"):
        if "min" in opt:
            opt["min_user"] = float(opt.pop("min"))
        if "max" in opt:
            opt["max_user"] = float(opt.pop("max"))
        opt.setdefault("min_user", 0.0)
        opt.setdefault("max_user", opt["min_user"])
    return {"id": mid, "name": S.key(mid), "label": label or "", "kind": kind, "refs": refs, "geom": geoms, "value": None if value is None else float(value), "opt": opt, "suppressed": False}


def resolve_refs(doc, kind, refs) -> tuple:
    lo, hi = REF_COUNT.get(kind, (2, 2))
    if not isinstance(refs, list) or not lo <= len(refs) <= hi:
        raise S.MateRefused("A %s mate needs %s references." % (kind, ("%d or %d" % (lo, hi)) if lo != hi else str(lo)))
    geoms = []
    for r in refs:
        if kind == "lock" and isinstance(r, dict) and not any(r.get(k) is not None for k in ("face", "edge", "vertex", "origin", "geom")):
            geoms.append({"comp": str(r.get("comp")), "kind": eqs.PT, "p": [0.0, 0.0, 0.0]})
            continue
        try:
            g = pick.resolve(doc, r)
            pick.finite(g)
        except pick.PickError as err:
            raise S.MateRefused(str(err), explain.unsupported(str(err)))
        geoms.append(g)
    return geoms


def add_mate(doc, kind, refs, value=None, opt=None, label="", force=False) -> dict:
    d = doc.drawing
    kind = kind_of(kind)
    if len(S.records(d)) >= MAX_MATES:
        raise S.MateRefused("The assembly has the most mates this version stores (%d)." % MAX_MATES)
    geoms = resolve_refs(doc, kind, refs)
    for g in geoms:
        if g.get("comp") is not None and A.get(d, g["comp"]) is None:
            raise S.MateRefused("There is no component %s." % g["comp"])
    mid = S.next_id(d)
    refs_clean = [dict(r) for r in refs]
    rec = new_record(d, kind, refs_clean, geoms, value, opt, label, mid)
    model = Model(d)
    for g in geoms:
        if g.get("comp") is not None and g["comp"] not in model.ids:
            raise S.MateRefused("Component %s is suppressed; unsuppress it first." % g["comp"])
    model.recs[mid] = rec
    m = to_mate(rec)
    try:
        model.net.mates.append(m)
        model.mates.append(m)
        model.net.prepare(m)
    except eqs.MateError as err:
        raise S.MateRefused(str(err), explain.unsupported(str(err)))
    saved = weights_for(model, m)
    start = model.net.snapshot()
    try:
        res = model.net.mate_res(m)
    except eqs.MateError as err:
        raise S.MateRefused(str(err), explain.unsupported(str(err)))
    rep = solve_all(model, "add")
    restore_weights(model, saved)
    if not rep.ok:
        model.net.restore(start)
        expl = conflict_explanation(model, start, mid)
        raise S.MateRefused(expl["message"], expl)
    st = model.net.status()
    row = next((r for r in st["mates"] if r["id"] == mid), None)
    if row is not None and row["redundant"] and not force:
        ids = model.net.redundant_set(model.net.active(), m)
        expl = explain.redundant({k: v for k, v in model.recs.items()}, ids, mid)
        raise S.MateRefused(expl["message"], expl)
    model.save_mate(m)
    moved = model.write(model.changed(start))
    model.save_states()
    return {"mate": model.recs[mid], "moved": moved, "poses": poses_of(model, moved), "status": summary(model, st), "ms": rep.ms, "iterations": rep.iterations}


def remove_mates(doc, ids) -> dict:
    d = doc.drawing
    model = Model(d)
    for mid in ids:
        r = S.get(d, mid)
        if r is None:
            raise S.MateRefused("There is no mate %s." % mid)
        S.drop(d, r["id"])
    model = Model(d)
    return {"removed": [int(i) if str(i).isdigit() else i for i in ids], "status": summary(model)}


def set_mate(doc, mid, value=None, opt=None, label=None, suppressed=None) -> dict:
    d = doc.drawing
    r = S.get(d, mid)
    if r is None:
        raise S.MateRefused("There is no mate %s." % mid)
    r = copy.deepcopy(r)
    old_value = r.get("value")
    if label is not None:
        r["label"] = str(label)
    if opt:
        for k, v in opt.items():
            if r["kind"].startswith("limit") and k in ("min", "max"):
                r["opt"][k + "_user"] = float(v)
            else:
                r["opt"][k] = v
    if suppressed is not None:
        r["suppressed"] = bool(suppressed)
    new_value = old_value if value is None else float(value)
    r["value"] = old_value
    S.put(d, r)
    model = Model(d)
    start = model.net.snapshot()
    if value is not None and new_value != old_value and old_value is not None and not r.get("suppressed") and r["kind"] in ("distance", "angle"):
        out = drive(doc, r["id"], value=new_value, commit=True, model=model)
        return out
    if value is not None:
        r["value"] = new_value
        S.put(d, r)
        model = Model(d)
        start = model.net.snapshot()
    if r.get("suppressed"):
        return {"mate": r, "moved": [], "status": summary(model)}
    rep = solve_all(model, "edit")
    if not rep.ok:
        model.net.restore(start)
        expl = conflict_explanation(model, start, r["id"])
        raise S.MateRefused(expl["message"], expl)
    moved = model.write(model.changed(start))
    model.save_states()
    return {"mate": model.recs[r["id"]], "moved": moved, "poses": poses_of(model, moved), "status": summary(model), "ms": rep.ms, "iterations": rep.iterations}


def resolve_all(doc) -> dict:
    model = Model(doc.drawing)
    start = model.net.snapshot()
    rep = solve_all(model, "solve")
    if not rep.ok:
        model.net.restore(start)
        expl = conflict_explanation(model, start)
        raise S.MateRefused(expl["message"], expl)
    moved = model.write(model.changed(start))
    model.save_states()
    return {"moved": moved, "poses": poses_of(model, moved), "status": summary(model), "ms": rep.ms, "iterations": rep.iterations}


def status(doc) -> dict:
    model = Model(doc.drawing)
    active = model.net.active()
    res = model.net.residual(active)
    unsolved = bool(res.size) and float(np.max(np.abs(res))) > max(model.net.tol * 100.0, 1e-7)
    out = {"solved": not unsolved}
    if unsolved:
        start = model.net.snapshot()
        rep = model.net.solve()
        if rep.ok:
            out["needs_solve"] = True
        else:
            model.net.restore(start)
            out["conflict"] = conflict_explanation(model, start)
    st = model.net.status()
    out.update(summary(model, st))
    if unsolved and "conflict" in out:
        out["state"] = "conflict"
    return out


def list_mates(doc) -> dict:
    model = Model(doc.drawing)
    return {"mates": [model.recs[m.id] for m in model.mates], "inactive": model.inactive}


def drag(doc, cid, point, target, commit=False) -> dict:
    model = Model(doc.drawing)
    b = model.net.bodies.get(cid)
    if b is None:
        raise S.MateRefused("Component %s is not in the solve." % cid)
    if b.fixed:
        raise S.MateRefused("Component %s is fixed, so it cannot be dragged." % cid)
    local = b.R.T @ (np.asarray(point, dtype=float) - b.t)
    rep = model.net.drag(cid, local, np.asarray(target, dtype=float))
    timing.record(id(model.d), "drag", rep.ms, rep.iterations, len(model.bodies), len(model.net.active()))
    ids = model.changed()
    out = {"ok": rep.ok, "message": rep.message, "moved": ids, "poses": poses_of(model, ids), "ms": rep.ms, "iterations": rep.iterations, "residual": rep.residual}
    if commit and rep.ok and ids:
        model.write(ids)
        model.save_states()
    return out


def sub_values(a: float, b: float, step: float) -> list:
    n = max(1, int(math.ceil(abs(b - a) / step - 1e-9)))
    return [a + (b - a) * (i + 1) / n for i in range(n)]


def drive(doc, mid, value=None, values=None, start=None, end=None, count=None, max_step=None, commit=True, report=False, comps=None, model=None) -> dict:
    d = doc.drawing
    model = model or Model(d)
    m = model.by_id(S.get(d, mid)["id"] if S.get(d, mid) else mid)
    rec = model.recs[m.id]
    if m.kind not in ("distance", "angle"):
        raise S.MateRefused("Only a distance or angle mate can be driven; %s is a %s mate." % (rec["name"], m.kind))
    if m.suppressed:
        raise S.MateRefused("%s is suppressed or has a suppressed component." % rec["name"])
    is_angle = m.kind == "angle"
    cur = float(rec["value"] if rec["value"] is not None else 0.0)
    if values is not None:
        targets = [float(v) for v in values]
    elif start is not None and end is not None:
        n = int(count or 2)
        if n < 2:
            raise S.MateRefused("A sweep needs at least 2 samples.")
        targets = [float(start) + (float(end) - float(start)) * i / (n - 1) for i in range(n)]
    elif value is not None:
        targets = [float(value)]
    else:
        raise S.MateRefused("Give a value, a list of values or start, end and count.")
    if len(targets) > 5000:
        raise S.MateRefused("A drive takes at most 5000 samples.")
    step = float(max_step) if max_step else (STEP_DEG if is_angle else 0.04 * model.L)
    if step <= 0:
        raise S.MateRefused("The step must be positive.")
    t0 = time.perf_counter()
    start_snap = model.net.snapshot()
    state0 = copy.deepcopy(m.opt.get("state", {}))
    samples = []
    ok_all = True
    message = ""
    last_val = cur

    def set_value(v):
        m.value = math.radians(v) if is_angle else v

    set_value(cur)
    lead = model.net.solve()
    if not lead.ok:
        model.net.restore(start_snap)
        expl = conflict_explanation(model, start_snap)
        raise S.MateRefused(expl["message"], expl)
    total_iter = 0
    for tv in targets:
        sample = {"value": tv, "ok": True, "ms": 0.0, "iterations": 0, "substeps": 0}
        good = model.net.snapshot()
        good_state = copy.deepcopy(m.opt.get("state", {}))
        for sv in sub_values(last_val, tv, step):
            set_value(sv)
            rep = model.net.solve(retries=1)
            sample["ms"] += rep.ms
            sample["iterations"] += rep.iterations
            sample["substeps"] += 1
            timing.record(id(d), "drive", rep.ms, rep.iterations, len(model.bodies), len(model.net.active()))
            if not rep.ok:
                sample.update(ok=False, residual=rep.residual, reached=sv - 0.0)
                break
        total_iter += sample["iterations"]
        if not sample["ok"]:
            model.net.restore(good)
            m.opt["state"] = good_state
            set_value(last_val)
            ok_all = False
            message = "The mechanism cannot reach %g %s; it stops at %g." % (tv, "degrees" if is_angle else "units", last_val)
            samples.append(sample)
            break
        last_val = tv
        if report:
            sample["poses"] = poses_of(model, comps)
        samples.append(sample)
    final = last_val
    ids = model.changed(start_snap)
    out = {"ok": ok_all, "message": message, "samples": samples, "final": final, "moved": ids, "ms": (time.perf_counter() - t0) * 1000.0, "iterations": total_iter}
    if commit:
        rec2 = copy.deepcopy(model.recs[m.id])
        rec2["value"] = final
        model.recs[m.id] = rec2
        model.save_mate(m)
        model.write(ids)
        model.save_states()
        out["mate"] = model.recs[m.id]
    else:
        model.net.restore(start_snap)
        m.opt["state"] = state0
    out["poses"] = poses_of(model, ids) if commit else {}
    out["status"] = summary(model) if commit else None
    return out
