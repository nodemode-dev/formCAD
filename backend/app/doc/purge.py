from app.doc import blockdefs, geom, wildcard

CATEGORIES = ("blocks", "layers", "linetypes", "dimstyles", "textstyles", "groups", "mlinestyles", "tablestyles", "mleaderstyles", "zerolength", "emptytext")
NOTHING = ("materials", "plotstyles", "shapes", "visualstyles", "regapps", "detailstyles", "sectionstyles")
ALL_ORDER = ("blocks", "layers", "linetypes", "dimstyles", "textstyles", "groups", "mlinestyles", "tablestyles", "mleaderstyles", "zerolength", "emptytext")
LABELS = {
    "blocks": "block",
    "layers": "layer",
    "linetypes": "linetype",
    "dimstyles": "dimension style",
    "textstyles": "text style",
    "groups": "group",
    "mlinestyles": "multiline style",
    "tablestyles": "table style",
    "mleaderstyles": "multileader style",
    "zerolength": "zero-length object",
    "emptytext": "empty text object",
}
KEEP = {
    "layers": ("0", "defpoints"),
    "linetypes": ("bylayer", "byblock", "continuous"),
    "textstyles": ("standard",),
    "dimstyles": ("standard",),
    "mlinestyles": ("standard",),
    "tablestyles": ("standard",),
    "mleaderstyles": ("standard",),
}
ALIASES = {
    "all": "all",
    "blocks": "blocks",
    "block": "blocks",
    "dimstyles": "dimstyles",
    "dimstyle": "dimstyles",
    "groups": "groups",
    "group": "groups",
    "layers": "layers",
    "layer": "layers",
    "linetypes": "linetypes",
    "linetype": "linetypes",
    "ltypes": "linetypes",
    "multileaderstyles": "mleaderstyles",
    "mleaderstyles": "mleaderstyles",
    "textstyles": "textstyles",
    "textstyle": "textstyles",
    "styles": "textstyles",
    "mlinestyles": "mlinestyles",
    "tablestyles": "tablestyles",
    "zerolength": "zerolength",
    "zero-length": "zerolength",
    "emptytext": "emptytext",
    "empty-text": "emptytext",
    "materials": "materials",
    "plotstyles": "plotstyles",
    "shapes": "shapes",
    "visualstyles": "visualstyles",
    "regapps": "regapps",
}


class PurgeError(Exception):
    pass


def canonical(word) -> str:
    key = str(word).strip().lower().replace(" ", "")
    got = ALIASES.get(key)
    if got is None:
        raise PurgeError("Unknown object type: %s." % word)
    return got


def label(cat: str, n: int) -> str:
    base = LABELS[cat]
    return base if n == 1 else base + "s"


def _eq(a, b) -> bool:
    return str(a).casefold() == str(b).casefold()


def _all_entities(d):
    return list(d.ents.values())


def _layer_refs(d) -> set:
    out = {str(e.layer).casefold() for e in _all_entities(d)}
    out.add(str(d.header.get("CLAYER", "0")).casefold())
    return out


def _linetype_refs(d) -> set:
    out = {str(e.linetype).casefold() for e in _all_entities(d)}
    for rec in d.tables["layers"].values():
        out.add(str(rec.get("linetype", "")).casefold())
    for ms in d.tables["mlinestyles"].values():
        for el in ms.get("elements", []):
            out.add(str(el.get("linetype", "")).casefold())
    for ds in d.tables["dimstyles"].values():
        for key in ("DIMLTYPE", "DIMLTEX1", "DIMLTEX2"):
            out.add(str(ds.get("vars", {}).get(key, "")).casefold())
    out.add(str(d.header.get("CELTYPE", "ByLayer")).casefold())
    return out


def _dimstyle_refs(d) -> set:
    out = {str(e.style).casefold() for e in _all_entities(d) if e.kind in ("dimension", "leader")}
    out.add(str(d.header.get("DIMSTYLE", "Standard")).casefold())
    for e in _all_entities(d):
        if e.kind == "dimension":
            ov = e.overrides.get("style") if isinstance(e.overrides, dict) else None
            if ov:
                out.add(str(ov).casefold())
    return out


def _textstyle_refs(d) -> set:
    out = set()
    for e in _all_entities(d):
        if e.kind in ("text", "mtext", "attdef"):
            out.add(str(e.style).casefold())
        elif e.kind == "mleader" and getattr(e, "text_style", None):
            out.add(str(e.text_style).casefold())
    out.add(str(d.header.get("TEXTSTYLE", "Standard")).casefold())
    for ds in d.tables["dimstyles"].values():
        out.add(str(ds.get("vars", {}).get("DIMTXSTY", "")).casefold())
    for ms in d.tables["mleaderstyles"].values():
        out.add(str(ms.get("text_style", "")).casefold())
    for ts in d.tables["tablestyles"].values():
        for cs in ts.get("cell_styles", []):
            out.add(str(cs.get("text_style", "")).casefold())
    for lt in d.tables["linetypes"].values():
        for el in lt.get("elements", []):
            if el.get("style"):
                out.add(str(el["style"]).casefold())
    return out


def _simple_refs(d, kind, attr, header_key, default) -> set:
    out = {str(getattr(e, attr)).casefold() for e in _all_entities(d) if e.kind == kind}
    out.add(str(d.header.get(header_key, default)).casefold())
    return out


def referenced(d, cat: str) -> set:
    if cat == "layers":
        return _layer_refs(d)
    if cat == "linetypes":
        return _linetype_refs(d)
    if cat == "dimstyles":
        return _dimstyle_refs(d)
    if cat == "textstyles":
        return _textstyle_refs(d)
    if cat == "mlinestyles":
        return _simple_refs(d, "mline", "style", "CMLSTYLE", "STANDARD")
    if cat == "tablestyles":
        return _simple_refs(d, "table", "style", "CTABLESTYLE", "Standard")
    if cat == "mleaderstyles":
        return _simple_refs(d, "mleader", "style", "CMLEADERSTYLE", "Standard")
    return set()


TABLE_OF = {"layers": "layers", "linetypes": "linetypes", "dimstyles": "dimstyles", "textstyles": "textstyles", "mlinestyles": "mlinestyles", "tablestyles": "tablestyles", "mleaderstyles": "mleaderstyles", "groups": "groups", "blocks": "blocks"}


def zero_length(d, e) -> bool:
    k = e.kind
    tol = d.tolerances["absolute"]
    if k == "line":
        return geom.dist(e.start, e.end) <= tol
    if k == "circle" or k == "arc":
        return e.radius <= tol
    if k == "lwpolyline":
        pts = [v["p"] for v in e.vertices]
        if not pts:
            return True
        return all(geom.dist(pts[0], p) <= tol for p in pts) and all(abs(v.get("bulge", 0.0)) < 1e-12 for v in e.vertices)
    if k == "polyline3d":
        pts = e.points
        return not pts or all(geom.dist(pts[0], p) <= tol for p in pts)
    return False


def empty_text(e) -> bool:
    if e.kind == "text":
        return not str(e.text).strip()
    if e.kind == "mtext":
        return not str(e.contents).strip()
    return False


def candidates(d, cat: str) -> list:
    if cat == "blocks":
        return blockdefs.unused(d)
    if cat == "groups":
        out = []
        for g in d.tables["groups"].values():
            if not [h for h in g.get("members", []) if h in d.ents]:
                out.append(g["name"])
        return out
    if cat in ("zerolength", "emptytext"):
        test = (lambda e: zero_length(d, e)) if cat == "zerolength" else empty_text
        return ["#%X" % e.handle for e in _all_entities(d) if test(e) and not d.layer_locked(e.layer)]
    if cat not in TABLE_OF:
        return []
    live = referenced(d, cat)
    keep = KEEP.get(cat, ())
    out = []
    for rec in d.tables[TABLE_OF[cat]].values():
        low = rec["name"].casefold()
        if low in keep or low in live:
            continue
        if rec.get("xref") or "|" in rec["name"]:
            continue
        out.append(rec["name"])
    return out


def listing(d, cat: str, spec: str = "*") -> list:
    cands = candidates(d, cat)
    if cat in ("zerolength", "emptytext"):
        return cands
    return wildcard.filter_names(spec, cands)


def delete(d, cat: str, name: str) -> None:
    if cat == "blocks":
        blockdefs.remove(d, name)
    elif cat in ("zerolength", "emptytext"):
        d.erase_entity(int(name[1:], 16))
    elif cat == "groups":
        d.table_remove("groups", name)
    else:
        d.table_remove(TABLE_OF[cat], name)


def run(d, cat: str, spec: str = "*", pick=None) -> dict:
    cats = list(ALL_ORDER) if cat == "all" else [cat]
    res = {}
    lines = []
    for c in cats:
        if c in NOTHING:
            res[c] = []
            lines.append("No unreferenced %s found." % c)
            continue
        names = listing(d, c, spec)
        gone = []
        for n in names:
            if pick is not None and not pick(c, n):
                continue
            delete(d, c, n)
            gone.append(n)
            if c in ("zerolength", "emptytext"):
                lines.append("Deleting %s %s." % (LABELS[c], n))
            else:
                lines.append('Deleting %s "%s".' % (LABELS[c], n))
        res[c] = gone
        plural = label(c, 2)
        if not gone:
            lines.append("No unreferenced %s found." % plural)
        else:
            lines.append("%d %s deleted." % (len(gone), label(c, len(gone))))
    return {"purged": res, "count": sum(len(v) for v in res.values()), "lines": lines}
