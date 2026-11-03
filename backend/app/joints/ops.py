import copy
import math
import time

import numpy as np

from app.joints.drive import Driver
from app.mates import eqs, joint_eq, pick, rig
from app.mates import ops as M
from app.mates import store as S

LIMIT_PARTS = ("min", "max", "rest")
MAX_JOINTS = 2000


def comp_of(ref) -> str | None:
    c = ref.get("comp") if isinstance(ref, dict) else None
    return None if c in (None, "", "world", "ground") else str(c)


def local_frame(doc, model, ref: dict) -> dict:
    comp = comp_of(ref)
    pose = model.net.pose(comp)
    if comp is not None and comp not in model.ids:
        raise S.MateRefused("Component %s is missing or suppressed." % comp)
    if ref.get("frame"):
        f = ref["frame"]
        try:
            o = np.asarray(f["origin"], dtype=float).reshape(3)
            z = rig.unit(f["z"]) if f.get("z") is not None else None
            x = np.asarray(f["x"], dtype=float).reshape(3) if f.get("x") is not None else None
        except (KeyError, TypeError, ValueError) as err:
            raise S.MateRefused("A frame needs an origin and a z direction: %s" % err)
        r, t = pose
        return {"comp": comp, "o": r.T @ (o - t), "z": None if z is None else r.T @ z, "x": None if x is None else r.T @ x}
    try:
        g = pick.resolve(doc, ref)
        pick.finite(g)
    except pick.PickError as err:
        raise S.MateRefused(str(err))
    z = None if g["kind"] == eqs.PT else np.asarray(g["d"], dtype=float)
    return {"comp": comp, "o": np.asarray(g["p"], dtype=float), "z": z, "x": None}


def complete_frames(model, fa: dict, fb: dict) -> None:
    ra = model.net.pose(fa["comp"])[0]
    rb = model.net.pose(fb["comp"])[0]
    if fa["z"] is None and fb["z"] is None:
        fa["z"] = ra.T @ np.array([0.0, 0.0, 1.0])
    if fa["z"] is None:
        fa["z"] = ra.T @ (rb @ rig.unit(fb["z"]))
    if fb["z"] is None:
        fb["z"] = rb.T @ (ra @ rig.unit(fa["z"]))
    fa["z"], fb["z"] = rig.unit(fa["z"]), rig.unit(fb["z"])
    fa_r, _ = joint_eq.frame_matrix({"o": fa["o"], "z": fa["z"], "x": fa["x"]})
    fa["x"] = fa_r[:, 0]
    if fb["x"] is None:
        xw = ra @ fa["x"]
        zw = rb @ fb["z"]
        xw = xw - float(xw @ zw) * zw
        fb["x"] = rb.T @ (joint_eq.default_x(zw) if float(np.linalg.norm(xw)) < 1e-6 else xw)
    fr_b, _ = joint_eq.frame_matrix({"o": fb["o"], "z": fb["z"], "x": fb["x"]})
    fb["x"] = fr_b[:, 0]


def clean_limits(kind: str, limits) -> dict:
    out = {}
    for key, v in (limits or {}).items():
        if key == "cone":
            if kind != "ball":
                raise S.MateRefused("Only a ball joint has a cone limit.")
            mx = None if v is None else v.get("max")
            if mx is not None:
                if not 0.0 < float(mx) <= 180.0:
                    raise S.MateRefused("The cone limit is between 0 and 180 degrees.")
                out["cone"] = {"max": float(mx)}
            continue
        if key not in joint_eq.COORDS[kind]:
            raise S.MateRefused("A %s joint has no %s; its coordinates are %s." % (kind, key, ", ".join(joint_eq.COORDS[kind]) or "none"))
        row = {}
        for part in LIMIT_PARTS:
            val = (v or {}).get(part)
            row[part] = None if val is None else float(val)
        if row["min"] is not None and row["max"] is not None and row["min"] > row["max"]:
            raise S.MateRefused("The minimum of %s is above its maximum." % key)
        for part in ("rest",):
            r = row[part]
            if r is not None and ((row["min"] is not None and r < row["min"] - 1e-9) or (row["max"] is not None and r > row["max"] + 1e-9)):
                raise S.MateRefused("The rest value of %s lies outside its range." % key)
        out[key] = row
    return out


def check_start(kind: str, limits: dict) -> None:
    for key, row in limits.items():
        if key == "cone":
            continue
        if (row["min"] is not None and row["min"] > 1e-9) or (row["max"] is not None and row["max"] < -1e-9):
            raise S.MateRefused("The joint starts at 0 on %s, which is outside its range %s to %s; the range is measured from the position the joint is made in." % (key, row["min"], row["max"]))


def free_rel0(kind: str, dt, dr) -> tuple:
    return joint_eq.compose(kind, joint_eq.coord_map(kind, dt, dr))


def raw_rel(model, fa: dict, fb: dict) -> tuple:
    ra, ta = model.net.pose(fa["comp"])
    rb, tb = model.net.pose(fb["comp"])
    ma, oa = joint_eq.frame_matrix(fa)
    mb, ob = joint_eq.frame_matrix(fb)
    wra, wta = ra @ ma, ra @ oa + ta
    wrb, wtb = rb @ mb, rb @ ob + tb
    return wra.T @ wrb, wra.T @ (wtb - wta)


def as_lists(f: dict) -> dict:
    return {"o": [float(v) for v in f["o"]], "z": [float(v) for v in f["z"]], "x": [float(v) for v in f["x"]]}


def new_joint(model, kind, fa, fb, as_built, limits, label, mid) -> dict:
    r, t = raw_rel(model, fa, fb)
    if as_built:
        r0, t0 = r, t
    else:
        r0, t0 = free_rel0(kind, t, r)
    side = lambda f: {"comp": f["comp"], "kind": eqs.PT, "p": [float(v) for v in f["o"]]}
    return {
        "id": mid, "name": S.key(mid), "label": label or "", "kind": "joint", "refs": [{"comp": fa["comp"]}, {"comp": fb["comp"]}],
        "geom": [side(fa), side(fb)], "value": None, "suppressed": False,
        "opt": {"type": kind, "as_built": bool(as_built), "fa": as_lists(fa), "fb": as_lists(fb), "rel0": {"r": [float(v) for v in np.asarray(r0).reshape(-1)], "t": [float(v) for v in t0]}, "limits": limits, "state": {}},
    }


def attach(model, rec: dict):
    model.recs[rec["id"]] = rec
    m = M.to_mate(rec)
    model.net.mates.append(m)
    model.mates.append(m)
    return m


def add_joint(doc, kind, a, b, as_built=False, limits=None, label="") -> dict:
    d = doc.drawing
    kind = joint_eq.type_of(kind)
    if len(S.records(d)) >= MAX_JOINTS:
        raise S.MateRefused("The assembly has the most joints this version stores (%d)." % MAX_JOINTS)
    model = M.Model(d)
    fa = local_frame(doc, model, a)
    fb = local_frame(doc, model, b)
    if fa["comp"] == fb["comp"]:
        raise S.MateRefused("A joint joins two different components.")
    complete_frames(model, fa, fb)
    lim = clean_limits(kind, limits)
    check_start(kind, lim)
    mid = S.next_id(d)
    rec = new_joint(model, kind, fa, fb, as_built, lim, label, mid)
    m = attach(model, rec)
    saved = M.weights_for(model, m)
    start = model.net.snapshot()
    rep = M.solve_all(model, "joint")
    M.restore_weights(model, saved)
    if not rep.ok:
        model.net.restore(start)
        expl = M.conflict_explanation(model, start, mid)
        raise S.MateRefused(expl["message"], expl)
    model.save_mate(m)
    moved = model.write(model.changed(start))
    model.save_states()
    out = {"joint": joint_view(model, m), "moved": moved, "poses": M.poses_of(model, moved), "status": status_view(model), "ms": rep.ms, "iterations": rep.iterations}
    rests = {k: row["rest"] for k, row in lim.items() if k != "cone" and row.get("rest") not in (None, 0.0)}
    if rests:
        run = drive_set(model, {(mid, k): joint_eq.to_internal(k, v) for k, v in rests.items()})
        if run["ok"]:
            moved2 = model.write(model.changed(start))
            model.save_states()
            out["moved"] = sorted(set(moved) | set(moved2))
            out["poses"] = M.poses_of(model, out["moved"])
            out["joint"] = joint_view(model, m)
        else:
            out["rest_message"] = "The rest position could not be reached: it stays at 0."
    return out


def drive_set(model, targets: dict, max_step=None) -> dict:
    drv = Driver(model)
    out = drv.goto(targets, max_step)
    drv.clear()
    return out


def joint_of(model, jid) -> eqs.Mate:
    for m in model.mates:
        if m.kind == "joint" and (str(m.id) == str(jid) or model.recs[m.id]["name"].casefold() == str(jid).casefold()):
            return m
    raise S.MateRefused("There is no joint %s." % jid)


def coord_state(spec, key, v) -> str:
    lim = spec["lim"].get(key)
    if lim is None:
        return "free"
    lo, hi = lim
    if lo is not None and v < lo - 1e-5:
        return "outside"
    if hi is not None and v > hi + 1e-5:
        return "outside"
    if lo is not None and abs(v - lo) <= 1e-6:
        return "at_min"
    if hi is not None and abs(v - hi) <= 1e-6:
        return "at_max"
    return "free"


def joint_view(model, m) -> dict:
    rec = model.recs[m.id]
    opt = rec["opt"]
    spec = m.opt["spec"]
    kind = spec["type"]
    out = {"id": m.id, "name": rec["name"], "label": rec.get("label", ""), "type": kind, "a": {"comp": rec["refs"][0]["comp"], "frame": opt["fa"]}, "b": {"comp": rec["refs"][1]["comp"], "frame": opt["fb"]}, "as_built": bool(opt.get("as_built")), "suppressed": bool(rec.get("suppressed")), "coords": [], "cone": None, "dof": len(joint_eq.COORDS[kind]), "links": []}
    if m.id in model.inactive:
        out["inactive"] = model.inactive[m.id]
    drv = m.opt.get("drive") or {}
    try:
        w = model.net.worlds(m)
        vals = joint_eq.values_of(spec, w[0], w[1], (m.opt.get("state") or {}).get("q"))
    except (eqs.MateError, KeyError):
        vals = None
    saved = (opt.get("state") or {}).get("q") or {}
    for key in joint_eq.COORDS[kind]:
        row = (opt.get("limits") or {}).get(key) or {}
        item = {"key": key, "kind": joint_eq.kind_of(key), "name": joint_eq.NAMES[key], "min": row.get("min"), "max": row.get("max"), "rest": row.get("rest"), "driven": key in drv}
        if vals is not None:
            item["value"] = joint_eq.to_user(key, vals[key])
            item["state"] = coord_state(spec, key, vals[key])
        else:
            item["value"] = joint_eq.to_user(key, saved.get(key, 0.0))
            item["state"] = "free"
        out["coords"].append(item)
    if kind == "ball":
        cone = (opt.get("limits") or {}).get("cone") or {}
        cur = 0.0
        if vals is not None:
            cur = math.degrees(math.sqrt(vals["rx"] ** 2 + vals["ry"] ** 2 + vals["rz"] ** 2))
        out["cone"] = {"value": cur, "max": cone.get("max")}
    for r in model.recs.values():
        if r["kind"] == "jointlink" and m.id in (r["opt"].get("id1"), r["opt"].get("id2")):
            out["links"].append(r["id"])
    return out


def link_view(model, rec: dict) -> dict:
    o = rec["opt"]
    return {"id": rec["id"], "name": rec["name"], "label": rec.get("label", ""), "first": {"joint": o["id1"], "coord": o["c1"]}, "second": {"joint": o["id2"], "coord": o["c2"]}, "ratio": o["ratio"], "reverse": bool(o.get("reverse")), "suppressed": bool(rec.get("suppressed"))}


def status_view(model) -> dict:
    st = model.net.status()
    rows = sum(r["removes"] for r in st["mates"])
    redundant_rows = max(0, rows - st["rank"])
    if st["state"] == "conflict":
        state = "conflict"
    elif not model.net.active():
        state = "none"
    elif st["dof"] == 0:
        state = "fully"
    else:
        state = "under"
    return {
        "state": state, "dof": st["dof"], "rank": st["rank"], "redundant_rows": redundant_rows, "residual": st["residual"],
        "components": {c: {"dof": v["dof"], "state": v["state"]} for c, v in st["components"].items()},
    }


def listing(doc) -> dict:
    model = M.Model(doc.drawing)
    joints = [joint_view(model, m) for m in model.mates if m.kind == "joint"]
    links = [link_view(model, r) for r in model.recs.values() if r["kind"] == "jointlink"]
    return {"joints": joints, "links": links, "status": status_view(model)}


def set_joint(doc, jid, label=None, suppressed=None, limits=None) -> dict:
    d = doc.drawing
    model = M.Model(d)
    m = joint_of(model, jid)
    rec = copy.deepcopy(model.recs[m.id])
    if label is not None:
        rec["label"] = str(label)
    if suppressed is not None:
        rec["suppressed"] = bool(suppressed)
    if limits is not None:
        rec["opt"]["limits"] = clean_limits(rec["opt"]["type"], limits)
    S.put(d, rec)
    model = M.Model(d)
    m = joint_of(model, jid)
    start = model.net.snapshot()
    moved = []
    if not rec["suppressed"]:
        rep = M.solve_all(model, "jointedit")
        if not rep.ok:
            model.net.restore(start)
            expl = M.conflict_explanation(model, start, rec["id"])
            raise S.MateRefused(expl["message"], expl)
        moved = model.write(model.changed(start))
        model.save_states()
    return {"joint": joint_view(model, m), "moved": moved, "poses": M.poses_of(model, moved), "status": status_view(model)}


def remove_joint(doc, jid) -> dict:
    d = doc.drawing
    model = M.Model(d)
    m = joint_of(model, jid)
    gone = [m.id]
    for r in list(model.recs.values()):
        if r["kind"] == "jointlink" and m.id in (r["opt"].get("id1"), r["opt"].get("id2")):
            gone.append(r["id"])
    for i in gone:
        S.drop(d, i)
    model = M.Model(d)
    return {"removed": gone, "status": status_view(model)}


def coord_key(rec: dict, key: str) -> str:
    kind = rec["opt"]["type"]
    if key not in joint_eq.COORDS[kind]:
        raise S.MateRefused("A %s joint has no %s; its coordinates are %s." % (kind, key, ", ".join(joint_eq.COORDS[kind]) or "none"))
    return key


def add_link(doc, first: dict, second: dict, ratio: float, reverse=False, label="") -> dict:
    d = doc.drawing
    model = M.Model(d)
    j1 = joint_of(model, first.get("joint"))
    j2 = joint_of(model, second.get("joint"))
    r1, r2 = model.recs[j1.id], model.recs[j2.id]
    c1, c2 = coord_key(r1, str(first.get("coord"))), coord_key(r2, str(second.get("coord")))
    if (j1.id, c1) == (j2.id, c2):
        raise S.MateRefused("A link needs two different joint coordinates.")
    ratio = float(ratio)
    if not math.isfinite(ratio) or abs(ratio) < 1e-12:
        raise S.MateRefused("The ratio must be a number other than zero.")
    f1, f2 = (math.pi / 180.0 if c1 in joint_eq.ANGLES else 1.0), (math.pi / 180.0 if c2 in joint_eq.ANGLES else 1.0)
    k = (-ratio if reverse else ratio) * f2 / f1
    w1, w2 = model.net.worlds(j1), model.net.worlds(j2)
    v1 = joint_eq.values_of(j1.opt["spec"], w1[0], w1[1], (j1.opt.get("state") or {}).get("q"))[c1]
    v2 = joint_eq.values_of(j2.opt["spec"], w2[0], w2[1], (j2.opt.get("state") or {}).get("q"))[c2]
    mid = S.next_id(d)
    strip = lambda r: {kk: copy.deepcopy(vv) for kk, vv in r["opt"].items() if kk != "state"}
    comps = [r1["refs"][0]["comp"], r1["refs"][1]["comp"], r2["refs"][0]["comp"], r2["refs"][1]["comp"]]
    rec = {
        "id": mid, "name": S.key(mid), "label": label or "", "kind": "jointlink", "refs": [{"comp": c} for c in comps],
        "geom": [{"comp": c, "kind": eqs.PT, "p": [0.0, 0.0, 0.0]} for c in comps], "value": None, "suppressed": False,
        "opt": {"id1": j1.id, "id2": j2.id, "j1": strip(r1), "j2": strip(r2), "c1": c1, "c2": c2, "ratio": ratio, "reverse": bool(reverse), "k": k, "q10": v1, "q20": v2, "state": {"q1": v1, "q2": v2}},
    }
    m = attach(model, rec)
    start = model.net.snapshot()
    rep = M.solve_all(model, "jointlink")
    if not rep.ok:
        model.net.restore(start)
        expl = M.conflict_explanation(model, start, mid)
        raise S.MateRefused(expl["message"], expl)
    model.save_mate(m)
    model.write(model.changed(start))
    model.save_states()
    return {"link": link_view(model, model.recs[mid]), "status": status_view(model)}


def set_link(doc, lid, ratio=None, reverse=None, label=None, suppressed=None) -> dict:
    d = doc.drawing
    rec = S.get(d, lid)
    if rec is None or rec["kind"] != "jointlink":
        raise S.MateRefused("There is no link %s." % lid)
    rec = copy.deepcopy(rec)
    o = rec["opt"]
    if ratio is not None:
        if not math.isfinite(float(ratio)) or abs(float(ratio)) < 1e-12:
            raise S.MateRefused("The ratio must be a number other than zero.")
        o["ratio"] = float(ratio)
    if reverse is not None:
        o["reverse"] = bool(reverse)
    f1, f2 = (math.pi / 180.0 if o["c1"] in joint_eq.ANGLES else 1.0), (math.pi / 180.0 if o["c2"] in joint_eq.ANGLES else 1.0)
    o["k"] = (-o["ratio"] if o["reverse"] else o["ratio"]) * f2 / f1
    if label is not None:
        rec["label"] = str(label)
    if suppressed is not None:
        rec["suppressed"] = bool(suppressed)
    model = M.Model(d)
    j1, j2 = joint_of(model, o["id1"]), joint_of(model, o["id2"])
    w1, w2 = model.net.worlds(j1), model.net.worlds(j2)
    o["q10"] = joint_eq.values_of(j1.opt["spec"], w1[0], w1[1], (j1.opt.get("state") or {}).get("q"))[o["c1"]]
    o["q20"] = joint_eq.values_of(j2.opt["spec"], w2[0], w2[1], (j2.opt.get("state") or {}).get("q"))[o["c2"]]
    o["state"] = {"q1": o["q10"], "q2": o["q20"]}
    S.put(d, rec)
    model = M.Model(d)
    start = model.net.snapshot()
    moved = []
    if not rec["suppressed"]:
        rep = M.solve_all(model, "jointlink")
        if not rep.ok:
            model.net.restore(start)
            expl = M.conflict_explanation(model, start, rec["id"])
            raise S.MateRefused(expl["message"], expl)
        moved = model.write(model.changed(start))
        model.save_states()
    return {"link": link_view(model, model.recs[rec["id"]]), "moved": moved, "poses": M.poses_of(model, moved), "status": status_view(model)}


def remove_link(doc, lid) -> dict:
    d = doc.drawing
    rec = S.get(d, lid)
    if rec is None or rec["kind"] != "jointlink":
        raise S.MateRefused("There is no link %s." % lid)
    S.drop(d, rec["id"])
    return {"removed": [rec["id"]], "status": status_view(M.Model(d))}


def drive_joint(doc, jid, coord, value=None, values=None, start=None, end=None, count=None, max_step=None, commit=True, report=False, comps=None) -> dict:
    d = doc.drawing
    model = M.Model(d)
    m = joint_of(model, jid)
    rec = model.recs[m.id]
    if m.suppressed:
        raise S.MateRefused("%s is suppressed or has a suppressed component." % rec["name"])
    key = coord_key(rec, str(coord))
    drv = Driver(model)
    reach = joint_eq.MAX_ANGLE if key in joint_eq.ANGLES else joint_eq.MAX_LENGTH

    def within(v) -> float:
        out = float(v)
        if not math.isfinite(out) or abs(out) > reach:
            raise S.MateRefused("A value for %s must be a number between %g and %g." % (key, -reach, reach))
        return out

    if values is not None:
        if len(values) > 5000:
            raise S.MateRefused("A drive takes at most 5000 samples.")
        targets = [within(v) for v in values]
    elif start is not None and end is not None:
        n = int(count or 2)
        if n < 2:
            raise S.MateRefused("A sweep needs at least 2 samples.")
        if n > 5000:
            raise S.MateRefused("A drive takes at most 5000 samples.")
        a, z = within(start), within(end)
        targets = [a + (z - a) * i / (n - 1) for i in range(n)]
    elif value is not None:
        targets = [within(value)]
    else:
        raise S.MateRefused("Give a value, a list of values or start, end and count.")
    step = None if not max_step else {(m.id, key): joint_eq.to_internal(key, float(max_step))}
    t0 = time.perf_counter()
    start_snap = model.net.snapshot()
    states0 = {x.id: copy.deepcopy(x.opt.get("state") or {}) for x in model.net.mates}
    samples = []
    ok_all, message = True, ""
    last = joint_eq.to_user(key, drv.measured(m.id, key))
    for tv in targets:
        want, clamped = drv.clamp(m.id, key, joint_eq.to_internal(key, tv))
        res = drv.goto({(m.id, key): want}, step)
        sample = {"value": tv, "ok": res["ok"], "ms": res["ms"], "iterations": res["iterations"], "substeps": res["substeps"], "reached": joint_eq.to_user(key, drv.measured(m.id, key))}
        if clamped:
            sample["limited"] = True
            sample["value"] = joint_eq.to_user(key, want)
            message = "%s stops at its limit %g." % (rec["name"], joint_eq.to_user(key, want))
        if not res["ok"]:
            ok_all = False
            message = "The mechanism cannot reach %g; it stays at %g." % (tv, last)
            samples.append(sample)
            break
        last = joint_eq.to_user(key, want)
        if report:
            sample["poses"] = M.poses_of(model, comps)
        samples.append(sample)
    drv.clear()
    ids = model.changed(start_snap)
    out = {"ok": ok_all, "message": message, "samples": samples, "final": last, "moved": ids, "ms": (time.perf_counter() - t0) * 1000.0}
    if commit:
        model.write(ids)
        model.save_states()
        out["poses"] = M.poses_of(model, ids)
        out["joint"] = joint_view(model, m)
        out["status"] = status_view(model)
    else:
        out["poses"] = {}
        model.net.restore(start_snap)
        for x in model.net.mates:
            x.opt["state"] = states0[x.id]
        out["joint"] = joint_view(model, m)
    return out


def rest_joint(doc, jid) -> dict:
    d = doc.drawing
    model = M.Model(d)
    m = joint_of(model, jid)
    lim = model.recs[m.id]["opt"].get("limits") or {}
    keys = [k for k in joint_eq.COORDS[model.recs[m.id]["opt"]["type"]] if (lim.get(k) or {}).get("rest") is not None]
    if not keys:
        return {"ok": True, "message": "%s has no rest position set." % model.recs[m.id]["name"], "samples": [], "moved": [], "poses": {}, "joint": joint_view(model, m)}
    start = model.net.snapshot()
    targets = {(m.id, k): joint_eq.to_internal(k, float(lim[k]["rest"])) for k in keys}
    res = drive_set(model, targets)
    if not res["ok"]:
        raise S.MateRefused("The rest position cannot be reached.")
    ids = model.changed(start)
    model.write(ids)
    model.save_states()
    return {"ok": True, "message": "", "samples": [{"value": lim[k]["rest"], "ok": True} for k in keys], "final": lim[keys[0]]["rest"], "moved": ids, "poses": M.poses_of(model, ids), "joint": joint_view(model, m), "status": status_view(model)}
