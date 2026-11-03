import math
from collections import OrderedDict

from app.param.units import mm_per_unit
from app.pmi import store
from app.solid import work
from app.solid.work import SolidError

_cache: OrderedDict = OrderedDict()
CACHE_LIMIT = 512
UP = (0.0, 0.0, 1.0)


def sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def add(a, b, k=1.0):
    return [a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2]]


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def norm(a):
    return math.sqrt(dot(a, a))


def unit(a, fallback=UP):
    n = norm(a)
    return [x / n for x in a] if n > 1e-12 else list(fallback)


def fmt(v: float) -> str:
    text = ("%.4f" % v).rstrip("0").rstrip(".")
    return text if text not in ("", "-0") else "0"


def indices(body, refs):
    out = []
    for r in refs:
        i = store.index_of(body, r)
        if i is None:
            raise store.PmiError("A feature of this item no longer exists on the body.")
        out.append({"kind": r["kind"], "index": i})
    return out


def kernel_measure(d, body, dtype, refs, refs2):
    key = (body.blob, mm_per_unit(d), tuple(body.offset), dtype, tuple((r["kind"], r["pid"]) for r in refs), tuple((r["kind"], r["pid"]) for r in refs2))
    got = _cache.get(key)
    if got is not None:
        _cache.move_to_end(key)
        return got
    wid = work.worker_id(d, body)
    raw = work.kcall("pmi_measure", {"id": wid, "dtype": dtype, "refs": indices(body, refs), "refs2": indices(body, refs2)})
    s = mm_per_unit(d)
    out = dict(raw)
    if dtype != "angle":
        out["value"] = raw["value"] / s
    for k in ("from", "to", "centre"):
        out[k] = [c / s for c in raw[k]]
    if raw.get("radius") is not None:
        out["radius"] = raw["radius"] / s
    _cache[key] = out
    while len(_cache) > CACHE_LIMIT:
        _cache.popitem(last=False)
    return out


def measure(d, handle, dtype, refs, refs2):
    body = store.body_of(d, handle)
    try:
        return kernel_measure(d, body, dtype, store.clean_refs(body, refs, "refs"), store.clean_refs(body, refs2, "refs2"))
    except SolidError as err:
        raise store.PmiError(str(err))


def anchors(d, body, refs):
    wid = work.worker_id(d, body)
    raw = work.kcall("pmi_anchors", {"id": wid, "refs": indices(body, refs)})["features"]
    s = mm_per_unit(d)
    out = []
    for f in raw:
        if f is None:
            out.append(None)
            continue
        g = dict(f)
        g["centre"] = [c / s for c in f["centre"]]
        out.append(g)
    return out


def features(d, handle):
    body = store.body_of(d, handle)
    s = mm_per_unit(d)
    raw = work.kcall("pmi_features", {"id": work.worker_id(d, body)})
    out = {"faces": [], "edges": []}
    for name, ids_list in (("faces", body.face_ids), ("edges", body.edge_ids)):
        for row in raw[name]:
            if row["index"] >= len(ids_list):
                continue
            r = dict(row)
            r["pid"] = ids_list[row["index"]]
            r["centre"] = [c / s for c in row["centre"]]
            if row.get("radius") is not None:
                r["radius"] = row["radius"] / s
            if row.get("area") is not None:
                r["area"] = row["area"] / (s * s)
            out[name].append(r)
    return out


def diagonal(d, body):
    box = (body.summary or {}).get("bbox")
    if not box:
        return 1.0
    return max(math.dist(box[:3], box[3:]) / mm_per_unit(d), 1e-9)


def dim_label(rec, value):
    t = rec["dtype"]
    base = fmt(value)
    if t == "diameter":
        base = "⌀" + base
    elif t == "radius":
        base = "R" + base
    elif t == "angle":
        base = base + "°"
    plus, minus = rec.get("plus", 0.0), rec.get("minus", 0.0)
    if plus or minus:
        if abs(plus - minus) < 1e-12:
            base += " ±" + fmt(plus)
        else:
            base += " +%s/-%s" % (fmt(plus), fmt(minus))
    if rec.get("text"):
        base += " " + rec["text"]
    return base


def tol_label(rec):
    zone = {"diameter": "⌀", "sphere": "S⌀"}.get(rec.get("zone"), "")
    mod = " " + rec["modifier"] if rec.get("modifier") else ""
    frame = {"char": rec["char"], "tol": rec["tol"], "zone": rec["zone"], "modifier": rec["modifier"], "datums": list(rec.get("datums") or [])}
    text = "%s %s%s%s" % (rec["char"].replace("_", " "), zone, fmt(rec["tol"]), mod)
    if rec.get("datums"):
        text += " | " + " | ".join(rec["datums"])
    if rec.get("text"):
        text += " " + rec["text"]
    return text, frame


def effective_offset(rec, default):
    o = rec.get("offset") or [0.0, 0.0, 0.0]
    return add(default, o)


def dimension_item(d, body, rec):
    m = kernel_measure(d, body, rec["dtype"], rec["refs"], rec["refs2"])
    value = rec["value"] if rec.get("value") is not None else m["value"]
    diag = diagonal(d, body)
    lines, arrows = [], []
    p1, p2 = m["from"], m["to"]
    if rec["dtype"] == "distance" or rec["dtype"] == "thickness":
        u = unit(sub(p2, p1))
        ref = UP if abs(dot(u, UP)) < 0.9 else (1.0, 0.0, 0.0)
        w = unit(cross(u, ref))
        o = effective_offset(rec, [c * diag * 0.1 for c in w])
        q1, q2 = add(p1, o), add(p2, o)
        lines = [[p1, q1], [p2, q2], [q1, q2]]
        arrows = [q1 + [-u[0], -u[1], -u[2]], q2 + u]
        text_at = add([(q1[i] + q2[i]) / 2 for i in range(3)], w, diag * 0.02)
        anchor = [(p1[i] + p2[i]) / 2 for i in range(3)]
    elif rec["dtype"] in ("diameter", "radius"):
        u = unit(sub(p2, p1))
        o = effective_offset(rec, [c * diag * 0.12 for c in u])
        if rec["dtype"] == "diameter":
            lines = [[p1, p2], [p2, add(p2, o)]]
            arrows = [p1 + [-u[0], -u[1], -u[2]], p2 + u]
        else:
            lines = [[m["centre"], p2], [p2, add(p2, o)]]
            arrows = [p2 + u]
        text_at = add(p2, o, 1.0)
        anchor = m["centre"]
    else:
        c = m["centre"]
        da = unit(m.get("normal") or UP)
        other = unit(m.get("normal2") or UP)
        axis = unit(cross(da, other))
        r = diag * 0.2
        ex = unit(cross(axis, da))
        ang = math.radians(max(min(value, 180.0), 0.0))
        pts = []
        for k in range(17):
            a = ang * k / 16.0
            pts.append([c[i] + r * (math.cos(a) * da[i] + math.sin(a) * ex[i]) for i in range(3)])
        o = effective_offset(rec, [0.0, 0.0, 0.0])
        lines = [[add(q, o) for q in pts]]
        mid = pts[8]
        text_at = add(add(mid, o), unit(sub(mid, c)), diag * 0.03)
        anchor = c
    return {"anchor": anchor, "text_at": text_at, "lines": lines, "arrows": arrows, "label": dim_label(rec, value), "measured": m["value"], "frame": None, "letter": None}


def feature_leader(d, body, rec):
    feats = anchors(d, body, rec["refs"])
    f = feats[0] if feats else None
    if f is None:
        raise store.PmiError("A feature of this item no longer exists on the body.")
    n = unit(f.get("normal") or UP)
    diag = diagonal(d, body)
    o = effective_offset(rec, [c * diag * 0.1 for c in n])
    tip = f["centre"]
    end = add(tip, o)
    return tip, end, n


def tolerance_item(d, body, rec):
    tip, end, n = feature_leader(d, body, rec)
    label, frame = tol_label(rec)
    return {"anchor": tip, "text_at": end, "lines": [[tip, end]], "arrows": [tip + [-n[0], -n[1], -n[2]]], "label": label, "measured": None, "frame": frame, "letter": None}


def datum_item(d, body, rec):
    tip, end, n = feature_leader(d, body, rec)
    return {"anchor": tip, "text_at": end, "lines": [[tip, end]], "arrows": [], "label": rec["letter"] + (" " + rec["text"] if rec.get("text") else ""), "measured": None, "frame": None, "letter": rec["letter"]}


def describe(d, rec):
    out = dict(rec)
    out.update(state=store.state_of(d, rec), measured=None, label="")
    if out["state"] != "ok":
        return out
    try:
        if rec["type"] == "dimension":
            body = store.body_of(d, rec["body"])
            m = kernel_measure(d, body, rec["dtype"], rec["refs"], rec["refs2"])
            out["measured"] = m["value"]
            out["label"] = dim_label(rec, rec["value"] if rec.get("value") is not None else m["value"])
        elif rec["type"] == "tolerance":
            out["label"] = tol_label(rec)[0]
        else:
            out["label"] = rec["letter"]
    except (store.PmiError, SolidError) as err:
        out.update(state="unsupported", note=str(err))
    return out


def display_item(d, rec):
    base = {"id": rec["id"], "type": rec["type"], "state": store.state_of(d, rec), "body": rec.get("body")}
    if base["state"] != "ok":
        base.update(label="", anchor=None, text_at=None, lines=[], arrows=[], frame=None, letter=None, measured=None)
        return base
    body = store.body_of(d, rec["body"])
    try:
        if rec["type"] == "dimension":
            base.update(dimension_item(d, body, rec))
        elif rec["type"] == "tolerance":
            base.update(tolerance_item(d, body, rec))
        else:
            base.update(datum_item(d, body, rec))
    except (store.PmiError, SolidError) as err:
        base.update(state="unsupported", note=str(err), label="", anchor=None, text_at=None, lines=[], arrows=[], frame=None, letter=None, measured=None)
    return base


MAX_DRAWN = 1000


def display(d) -> tuple:
    recs = store.items(d)
    return [display_item(d, rec) for rec in recs[:MAX_DRAWN]], len(recs) > MAX_DRAWN
