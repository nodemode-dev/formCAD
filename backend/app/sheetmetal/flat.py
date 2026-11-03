import copy
import hashlib
import json
import math

from app.sheetmetal import bend as B
from app.solid import work

HEADER = "SHEETFLAT"
MAX_BENDS = 400


class FlatError(ValueError):
    pass


def blank_state() -> dict:
    return {"on": False, "flip": False, "fixed_face": None, "align": "bbox", "rule": None}


def state(d) -> dict:
    out = blank_state()
    raw = d.header.get(HEADER)
    if isinstance(raw, dict):
        out.update(copy.deepcopy(raw))
    return out


def set_state(d, **changes) -> dict:
    cur = state(d)
    for k, v in changes.items():
        if k not in cur:
            raise FlatError("Unknown flat pattern setting %s." % k)
        cur[k] = v
    if cur["align"] not in ("bbox", "none"):
        raise FlatError("align is bbox or none.")
    d.set_header(HEADER, copy.deepcopy(cur))
    return cur


def sheet_body(d, handle=None):
    if handle is not None:
        b = d.get(int(handle))
        if b is None or b.kind != "solidbody":
            raise FlatError("There is no solid body with handle %s." % handle)
        return b
    try:
        from app.part import store as pstore

        t = pstore.tree(d)
        if t.get("body"):
            b = d.get(int(t["body"]))
            if b is not None and b.kind == "solidbody":
                return b
    except ImportError:
        pass
    bodies = [e for e in d.ents.values() if e.kind == "solidbody"]
    if len(bodies) == 1:
        return bodies[0]
    if not bodies:
        raise FlatError("There is no solid body to flatten.")
    raise FlatError("There are several bodies; give the body handle.")


def part_rule(d) -> dict | None:
    try:
        from app.sheetmetal import rule as smrule
    except ImportError:
        return None
    try:
        return smrule.rule_of_part(d)
    except Exception:
        return None


def part_bends(d) -> list:
    try:
        from app.sheetmetal import records
    except ImportError:
        return []
    try:
        return list(records.bends(d))
    except Exception:
        return []


def effective_rule(d, override=None) -> dict:
    rule = part_rule(d)
    st = state(d)["rule"]
    out = dict(rule) if rule else {}
    if isinstance(st, dict):
        out.update({k: v for k, v in st.items() if v is not None})
    if isinstance(override, dict):
        out.update({k: v for k, v in override.items() if v is not None})
    return out


def line_distance(p, o, dv):
    d = [p[i] - o[i] for i in range(3)]
    t = sum(d[i] * dv[i] for i in range(3))
    perp = [d[i] - t * dv[i] for i in range(3)]
    return math.sqrt(sum(x * x for x in perp)), t


def match_record(bend, records_):
    best = None
    ax = bend["axis"]
    for rec in records_:
        ra = rec.get("axis") or {}
        if not ra.get("origin") or not ra.get("dir"):
            continue
        if abs(sum(ra["dir"][i] * ax["dir"][i] for i in range(3))) < 1.0 - 1e-6:
            continue
        if abs(float(rec.get("radius", -1.0)) - bend["radius"]) > 1e-3 or abs(float(rec.get("angle", -1.0)) - bend["angle"]) > 1e-3:
            continue
        dist, t = line_distance(ra["origin"], ax["origin"], ax["dir"])
        if dist > 1e-3:
            continue
        mid = (ax.get("t0", 0.0) + ax.get("t1", 0.0)) / 2.0
        score = abs(t - mid)
        if best is None or score < best[0]:
            best = (score, rec)
    return best[1] if best else None


def ref_face_index(d, body, rule):
    key = (rule or {}).get("ref_key")
    if not key:
        return None
    try:
        from app.part import store as pstore

        pid = pstore.tree(d)["names"].get(key)
    except (ImportError, KeyError):
        return None
    ids = list(getattr(body, "face_ids", []) or [])
    return ids.index(pid) if pid in ids else None


def rule_key(rule) -> str:
    return hashlib.sha1(json.dumps(rule, sort_keys=True, default=str).encode()).hexdigest()[:16]


def compute(d, handle=None, rule=None, fixed_face=None, flip=None, align=None, force=False) -> dict:
    body = sheet_body(d, handle)
    st = state(d)
    fixed = st["fixed_face"] if fixed_face is None else fixed_face
    flipped = st["flip"] if flip is None else bool(flip)
    aligned = st["align"] if align is None else align
    rl = effective_rule(d, rule)
    if fixed is None:
        fixed = ref_face_index(d, body, rl)
    recs = part_bends(d)
    key = (body.handle, body.blob, tuple(body.offset), rule_key(rl), rule_key([r.get("id") for r in recs] + [r.get("k") for r in recs]), fixed, flipped, aligned)
    cache = getattr(d, "flat_cache", None)
    if cache is not None and cache[0] == key and not force:
        return copy.deepcopy(cache[1])
    wid = work.worker_id(d, body)
    thick = rl.get("thickness_mm")
    k0 = float(rl.get("k_factor", B.DEFAULT_K)) if rl.get("bend_method", "kfactor") in ("kfactor", "k") else B.DEFAULT_K
    params = {"id": wid, "k": k0, "fixed_face": fixed, "flip": flipped, "align": aligned}
    if thick is not None:
        params["thickness"] = float(thick)
    first = work.kcall("unfold_solid", params, work.LONG)
    if len(first["bends"]) > MAX_BENDS:
        raise FlatError("The part has more than %d bends." % MAX_BENDS)
    rule_for_bends = dict(rl)
    rule_for_bends.setdefault("thickness_mm", first["thickness"])
    bend_k = {}
    solved = {}
    for b in first["bends"]:
        rec = match_record(b, recs)
        inner = b["radius"]
        if rec is not None and rec.get("k") is not None:
            res = {"k": float(rec["k"]), "ba": rec.get("ba"), "method": rec.get("method", "kfactor"), "warnings": list(rec.get("warnings") or []), "record": rec.get("id")}
            res["record_ba"] = rec.get("ba")
        elif b["angle"] >= math.pi - 1e-9:
            res = {"k": k0, "method": "kfactor", "warnings": ["A bend of 180 degrees or more uses the rule K-factor."], "record": None}
        else:
            try:
                res = B.resolve_bend(rule_for_bends, b["angle"], inner, first["thickness"])
            except B.BendError as err:
                raise FlatError("Bend %s: %s" % (b["id"], err))
            res["record"] = None
        solved[b["key"]] = res
        bend_k[str(b["key"])] = res["k"]
    final = first
    if any(abs(v - k0) > 1e-12 for v in bend_k.values()):
        params["bend_k"] = bend_k
        final = work.kcall("unfold_solid", params, work.LONG)
    out = enrich(final, solved, rl, body)
    d.flat_cache = (key, copy.deepcopy(out))
    return out


def enrich(res, solved, rule, body) -> dict:
    thick = res["thickness"]
    bends = []
    for b in res["bends"]:
        info = solved.get(b["key"], {})
        rn = b["radius"] + b["k"] * thick
        ba = b["angle"] * rn
        t = math.tan(b["angle"] / 2.0) if b["angle"] < math.pi - 1e-9 else None
        ossb = t * (b["radius"] + thick) if t is not None else None
        row = dict(b)
        row.update(
            record=info.get("record"),
            method=info.get("method", "kfactor"),
            neutral_radius=rn,
            ba=ba,
            bd=(2.0 * ossb - ba) if ossb is not None else None,
            ossb=ossb,
            issb=(t * b["radius"]) if t is not None else None,
            included=math.pi - b["angle"],
            angle_deg=math.degrees(b["angle"]),
            warnings=list(info.get("warnings") or []),
        )
        if info.get("record_ba") is not None and abs(float(info["record_ba"]) - ba) > 1e-6:
            row["warnings"].append("The recorded allowance %.6g differs from the flat pattern allowance %.6g." % (float(info["record_ba"]), ba))
        bends.append(row)
    box = res["bbox"]
    out = dict(res)
    out["bends"] = bends
    out["handle"] = body.handle
    out["length"] = box[2] - box[0]
    out["width"] = box[3] - box[1]
    out["angle_report"] = rule.get("angle_report", "bend")
    out["material"] = body.material or ""
    return out


def cutlist(flat) -> dict:
    return {
        "thickness": flat["thickness"],
        "material": flat.get("material", ""),
        "bbox_length": flat["length"],
        "bbox_width": flat["width"],
        "blank_area": flat["blank_area"],
        "cutting_length_outside": flat["cut_outer"],
        "cutting_length_inside": flat["cut_inner"],
        "num_bends": len(flat["bends"]),
        "num_cutouts": flat["cutouts"],
        "bends": [{"id": b["id"], "record": b.get("record"), "direction": b["direction"], "angle": b["angle"], "radius": b["radius"], "k": b["k"], "ba": b["ba"], "bd": b["bd"], "length": b["length"]} for b in flat["bends"]],
    }


def is_sheet(d, body) -> bool:
    return part_rule(d) is not None or bool(state(d)["rule"])


def cutlist_of(d, handle=None) -> dict | None:
    try:
        return cutlist(compute(d, handle))
    except (FlatError, work.SolidError, B.BendError):
        return None
