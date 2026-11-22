import copy

from app.assembly import cfg, patterns, refs, store, walk, xform
from app.param.units import mm_per_unit


def brief_status(st: dict, with_log: bool = True) -> dict:
    out = {k: st[k] for k in ("status", "stale", "source", "reason", "resolved", "found_by", "message", "nested")}
    out["lightweight"] = bool(st.get("lightweight"))
    if with_log:
        out["log"] = st.get("log", [])
    return out


def component_view(rec: dict, st: dict | None) -> dict:
    out = copy.deepcopy(rec)
    cache = out.get("cache") or {}
    out["cache"] = {"bodies": len(cache.get("bodies") or []), "taken": cache.get("taken", ""), "props": cache.get("props", {}), "configs": cache.get("configs", [])}
    out["status"] = brief_status(st) if st else None
    return out


def listing(doc) -> dict:
    d = doc.drawing
    head = store.header(d)
    insts = walk.instances(doc, True)
    sts = {}
    for i in insts:
        if i.depth == 0 and i.cid not in sts:
            sts[i.cid] = i.status
    comps = [component_view(r, sts.get(r["id"])) for r in store.components(d)]
    live = [i for i in insts if not i.suppressed]
    counts = {
        "components": len(comps), "instances": len(live), "missing": sum(1 for c in comps if c["status"] and c["status"]["status"] == "missing"),
        "outofdate": sum(1 for c in comps if c["status"] and c["status"]["status"] == "outofdate"), "stale": sum(1 for c in comps if c["status"] and c["status"]["stale"]),
        "lightweight": sum(1 for i in live if i.status.get("lightweight")),
    }
    return {
        "rev": doc.rev, "kind": doc.kind, "schema": head["schema"], "units_mm": mm_per_unit(d), "path": doc.path,
        "settings": {"search_folders": head["search_folders"], "search_order": refs.describe_order(head), "embed_cache": head["embed_cache"], "lightweight": bool(head.get("lightweight", True)), "active_config": cfg.active_name(d)},
        "components": comps, "patterns": [copy.deepcopy(p) for p in store.patterns(d)], "configs": cfg.listing(d), "counts": counts,
    }


def instances_view(doc, include_suppressed: bool = False) -> dict:
    insts = walk.instances(doc, include_suppressed)
    return {"rev": doc.rev, "units_mm": mm_per_unit(doc.drawing), "instances": [i.brief() for i in insts]}


def tree_view(doc) -> dict:
    insts = walk.instances(doc, True)
    nodes: dict = {}
    roots = []
    for i in insts:
        node = {**i.brief(), "children": []}
        nodes[i.key] = node
        parent = i.key.rsplit("/", 1)[0] if "/" in i.key else ""
        if parent and parent in nodes:
            nodes[parent]["children"].append(node)
        else:
            roots.append(node)
    return {"rev": doc.rev, "tree": roots}


def component_detail(doc, cid: str) -> dict:
    d = doc.drawing
    rec = store.need(d, cid)
    st = walk.status_of(doc, rec)
    out = component_view(rec, st)
    out["frame"] = xform.frame_of(xform.as_matrix(rec["transform"]))
    out["axis_angle"] = xform.axis_angle(xform.as_matrix(rec["transform"]))
    return out


def patterns_view(doc) -> dict:
    d = doc.drawing
    return {"patterns": [{**copy.deepcopy(p), "count": patterns.count_of(p)} for p in store.patterns(d)]}
