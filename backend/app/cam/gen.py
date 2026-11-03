import copy
import threading

from app.cam import ctx as ctx_mod
from app.cam import model, registry, store, toolpath as T
from app.cam.limits import CamError, Cancelled
from app.cam import limits

CACHE: dict = {}
_lock = threading.Lock()


def cached(doc_id: str, oid: str):
    with _lock:
        return CACHE.get((doc_id, oid))


def put_cache(doc_id: str, oid: str, sig: str, path) -> None:
    with _lock:
        CACHE[(doc_id, oid)] = (sig, path)


def drop_cache(doc_id: str, oid: str = None) -> None:
    with _lock:
        for k in [k for k in CACHE if k[0] == doc_id and (oid is None or k[1] == oid)]:
            CACHE.pop(k, None)


def prepare(doc, oid: str):
    d = doc.drawing
    op = copy.deepcopy(model.get_op(d, oid))
    setup = copy.deepcopy(model.get_setup(d, op["setup"]))
    tool_row = copy.deepcopy(model.get_tool(d, op["tool"]))
    typ = registry.get(op["type"])
    params = typ.clean(op["params"])
    c = ctx_mod.GenCtx(doc, setup, op, store.tool_record(tool_row), params, None, typ.default_geometry)
    gk = (op.get("geometry") or typ.default_geometry or {}).get("kind")
    if typ.needs_model or gk in ("section", "removal", "model_holes"):
        c.triangles()
    if gk and gk != "ruled":
        if gk in ("points", "model_holes") or (gk == "entities" and typ.kind == "drill"):
            c._points_cache = c.points()
        else:
            c.region()
    sig = store.signature_of(doc, setup, op, tool_row)
    return c, typ, sig


def run_prepared(c, typ, job=None):
    c.job = job
    if hasattr(c, "_points_cache"):
        cache = c._points_cache
        c.points = lambda: cache
    out = typ.generate(c)
    if isinstance(out, list):
        out = T.Toolpath(out, getattr(c, "meta", {}))
    limits.need(len(out.moves), "moves", "Toolpath")
    return out


def finish_state(doc, oid: str, sig: str, path, warnings: list, message: str, status: str) -> dict:
    d = doc.drawing
    op = model.get_op(d, oid)
    setup = model.get_setup(d, op["setup"])
    rec = copy.deepcopy(op)
    st = {"status": status, "sig": sig, "message": message, "warnings": warnings, "summary": {}}
    if path is not None:
        machine = setup.get("machine_profile") or {}
        ct = T.cycle_time(path.moves, machine)
        st["summary"] = path.summary(ct["trapezoid_s"])
        st["summary"]["time_simple_s"] = round(ct["simple_s"], 2)
        st["summary"]["meta"] = path.meta
        w = model.resolve_wcs(doc, setup)["wcs"]
        st["summary"]["wcs"] = {"origin": w["origin"], "x": w.get("x", [1.0, 0.0, 0.0]), "z": w.get("z", [0.0, 0.0, 1.0])}
    rec["state"] = st
    d.table_set(model.TABLE, rec)
    return st


def generate_one(doc, oid: str, job=None) -> dict:
    with doc.lock:
        try:
            c, typ, sig = prepare(doc, oid)
        except CamError as err:
            with doc.transaction("CAM GENERATE", undoable=False):
                finish_state(doc, oid, "", None, [], str(err), "failed")
            raise
    try:
        path = run_prepared(c, typ, job)
    except Cancelled:
        raise
    except CamError as err:
        with doc.lock:
            with doc.transaction("CAM GENERATE", undoable=False):
                finish_state(doc, oid, "", None, [], str(err), "failed")
        drop_cache(doc.id, oid)
        raise
    status = "ok" if path.moves and path.lengths()["cut"] > 0 or any(m[0] == "cycle" for m in path.moves) else "empty"
    put_cache(doc.id, oid, sig, path)
    with doc.lock:
        with doc.transaction("CAM GENERATE", undoable=False):
            st = finish_state(doc, oid, sig, path, c.warnings, "" if status == "ok" else "The operation produced no cutting moves.", status)
    return st


def toolpath_of(doc, oid: str, regenerate: bool = True):
    hit = cached(doc.id, oid)
    with doc.lock:
        d = doc.drawing
        op = model.get_op(d, oid)
        setup = model.get_setup(d, op["setup"])
        tool_row = model.get_tool(d, op["tool"])
        sig = store.signature_of(doc, setup, op, tool_row)
    if hit is not None and hit[0] == sig:
        return hit[1]
    if not regenerate:
        raise CamError("The toolpath for %s is not generated, or is out of date. Generate it first." % oid)
    generate_one(doc, oid)
    hit = cached(doc.id, oid)
    if hit is None:
        raise CamError("The operation %s produced no toolpath." % oid)
    return hit[1]


def mark_stale(doc) -> None:
    d = doc.drawing
    for op in model.ops(d):
        st = op.get("state") or {}
        if st.get("status") not in ("ok", "empty"):
            continue
        try:
            setup = model.get_setup(d, op["setup"])
            tool_row = model.get_tool(d, op["tool"])
        except CamError:
            continue
        if store.signature_of(doc, setup, op, tool_row) != st.get("sig"):
            rec = copy.deepcopy(op)
            rec["state"]["status"] = "stale"
            d.table_set(model.TABLE, rec)
