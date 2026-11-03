import os

import numpy as np

from app.assembly import cfg, parts, patterns, refs, store, xform
from app.assembly.store import AssemblyError
from app.param.units import mm_per_unit

MAX_DEPTH = 12
MAX_INSTANCES = 20000


class Instance:
    def __init__(self, key, cid, path, depth, record, world, local, suppressed, visible, status, part, pattern, index, host):
        self.key = key
        self.cid = cid
        self.path = path
        self.depth = depth
        self.record = record
        self.world = world
        self.local = local
        self.suppressed = suppressed
        self.visible = visible
        self.status = status
        self.part = part
        self.pattern = pattern
        self.index = index
        self.host = host
        self.config = ""

    def brief(self) -> dict:
        return {
            "config": self.config, "key": self.key, "cid": self.cid, "path": list(self.path), "depth": self.depth, "label": self.record["label"], "type": self.record["type"],
            "suppressed": self.suppressed, "visible": self.visible, "pattern": self.pattern, "index": self.index, "world": xform.to_list(self.world),
            "local": xform.to_list(self.local), "status": self.status["status"], "stale": self.status["stale"], "source": self.status["source"],
        }


def new_status() -> dict:
    return {"status": "loaded", "stale": False, "source": "file", "reason": "found", "resolved": "", "found_by": "", "message": "", "nested": [], "log": []}


def resolve(host_d, host_path: str, rec: dict, stack=(), depth=0, folders=(), deep=False) -> tuple:
    st = new_status()
    kind = rec["type"]
    if kind == "embedded":
        st["source"] = "embedded"
        return st, parts.EmbeddedPart(host_d, rec)
    head = store.header(host_d)
    cached = parts.CachedPart(host_d, rec) if kind == "part" and (rec.get("cache") or {}).get("bodies") else None
    real, by, log = refs.search(host_path, rec.get("ref") or {}, head, folders, deep)
    st["log"] = log

    def fall(reason: str, message: str) -> tuple:
        st.update(status="missing", reason=reason, message=message, found_by="", resolved="")
        if cached is not None:
            st.update(stale=True, source="cache")
            return st, cached
        st["source"] = "none"
        return st, None

    unavailable = "The file %s is not available. %s" % (os.path.basename((rec.get("ref") or {}).get("path") or "") or "", "The picture is the copy kept in this assembly." if cached is not None else "Nothing can be drawn until it is found.")
    if not real:
        return fall("notfound", unavailable)
    if real in stack or (host_path and os.path.realpath(host_path) == real):
        return fall("cycle", "That file would contain itself, so it is not opened.")
    if depth >= MAX_DEPTH:
        return fall("toodeep", "Sub-assemblies are nested more than %d levels deep." % MAX_DEPTH)
    try:
        lp = parts.load(real)
    except parts.PartLoadError:
        return fall("unreadable", unavailable)
    if kind == "assembly" and not lp.is_assembly:
        return fall("unreadable", unavailable)
    if kind == "part" and lp.is_assembly:
        return fall("unreadable", unavailable)
    st.update(resolved=real, found_by=by)
    recorded = rec.get("sig") or {}
    if recorded and (recorded.get("size") or recorded.get("mtime")) and not refs.same_sig(recorded, lp.sig):
        st.update(status="outofdate", reason="changed", message="The file changed after it was last accepted into this assembly. Reload the component to take the new version.")
        if cached is not None:
            st.update(stale=True, source="cache")
            return st, cached
    return st, lp


def _matrix(rec) -> np.ndarray:
    try:
        return xform.as_matrix(rec.get("transform"))
    except xform.TransformError:
        return xform.identity()


def _expand(host_d, host_path, parent_world, prefix, parent_path, stack, depth, overlay, out, opts, cache):
    comps = store.components(host_d)
    pats = {}
    for p in store.patterns(host_d):
        pats.setdefault(p["seed"], []).append(p)
    host_mmu = mm_per_unit(host_d)
    by_id = {r["id"]: r for r in comps}
    for rec in comps:
        cid = rec["id"]
        sup = bool(overlay["suppress"].get(cid, rec.get("suppressed"))) if overlay else bool(rec.get("suppressed"))
        vis = bool(overlay["visible"].get(cid, rec.get("visible", True))) if overlay else bool(rec.get("visible", True))
        conf = str(overlay["component_config"].get(cid, rec.get("config") or "")) if overlay else str(rec.get("config") or "")
        local = _matrix(rec)
        ckey = (id(host_d), cid, stack)
        if ckey not in cache:
            cache[ckey] = resolve(host_d, host_path, rec, stack, depth, opts.get("folders", ()), opts.get("deep", False))
        status, lp = cache[ckey]
        copies = [(0, xform.identity(), None)]
        for p in pats.get(cid, []):
            psup = bool(overlay["patterns"].get(p["id"], p.get("suppressed"))) if overlay else bool(p.get("suppressed"))
            if psup:
                continue
            target = by_id.get(p["params"].get("target")) if p["kind"] == "feature" else None
            tl = _matrix(target) if target else None
            for idx, m in patterns.transforms(p, local, tl, 1.0 / host_mmu):
                copies.append((idx, m, p["id"]))
        for idx, pm, pid in copies:
            if sup and not opts.get("include_suppressed"):
                continue
            if len(out) >= MAX_INSTANCES:
                raise AssemblyError("The assembly holds more than %d instances." % MAX_INSTANCES)
            key = prefix + cid + ("#%d" % idx if idx else "")
            world = parent_world @ pm @ local
            part = lp
            if lp is not None and rec["type"] == "part" and conf and conf != (lp.active_config or "") and conf in lp.configs:
                try:
                    from app.assembly import variants

                    part = variants.variant(lp, conf)
                except Exception as err:
                    status = dict(status, message=(status.get("message") + " " if status.get("message") else "") + "Configuration %s could not be built: %s" % (conf, err))
                    cache[ckey] = (status, lp)
            inst = Instance(key, cid, parent_path + (key,), depth, rec, world, pm @ local, sup, vis, status, part, pid, idx, host_d)
            inst.config = conf
            out.append(inst)
            if sup or lp is None or rec["type"] != "assembly" or not lp.is_assembly:
                continue
            mark = len(out)
            ov = cfg.overlay(lp.drawing, conf) if conf else None
            _expand(lp.drawing, lp.path, world, key + "/", inst.path, stack + (lp.path,), depth + 1, ov, out, opts, cache)
            bad = [{"key": o.key, "status": o.status["status"], "message": o.status["message"]} for o in out[mark:] if o.status["status"] != "loaded"]
            if bad and not status["nested"]:
                status["nested"] = bad[:50]


def instances(doc, include_suppressed: bool = False, folders=(), deep: bool = False) -> list:
    d = doc.drawing
    host_path = getattr(doc, "path", "") or ""
    stack = (os.path.realpath(host_path),) if host_path else ()
    out: list = []
    _expand(d, host_path, xform.identity(), "", (), stack, 0, None, out, {"include_suppressed": include_suppressed, "folders": folders, "deep": deep}, {})
    return out


def top_statuses(doc, folders=(), deep=False) -> dict:
    res = {}
    for inst in instances(doc, True, folders, deep):
        if inst.depth == 0 and inst.cid not in res:
            res[inst.cid] = inst.status
    return res


def status_of(doc, rec, folders=(), deep=False) -> dict:
    d = doc.drawing
    host_path = getattr(doc, "path", "") or ""
    stack = (os.path.realpath(host_path),) if host_path else ()
    st, _lp = resolve(d, host_path, rec, stack, 0, folders, deep)
    return st
