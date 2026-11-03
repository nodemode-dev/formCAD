import hashlib
import os

from app.doc.model import SPACE_MODEL
from app.param.units import mm_per_unit
from app.solid import work
from app.views.model import ViewError

MAX_ITEMS = 2000


class Item:
    def __init__(self, key, kind, wid, matrix, version, body=None, component="", sig=""):
        self.key = key
        self.kind = kind
        self.wid = wid
        self.matrix = matrix
        self.version = version
        self.body = body
        self.component = component
        self.sig = sig

    def record(self) -> dict:
        out = {"key": self.key, "kind": self.kind, "version": self.version, "matrix": self.matrix}
        if self.kind == "body":
            out["handle"] = self.body.handle
        else:
            out["component"] = self.component
        return out


def _sig(parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(repr(p).encode("utf-8"))
    return h.hexdigest()[:20]


def _body_sig(body, d) -> tuple:
    return (body.handle, body.blob, tuple(round(float(v), 9) for v in body.offset), mm_per_unit(d))


def _doc_items(d, comp: str, label_prefix: str = "") -> list:
    out = []
    for e in d.ordered_entities():
        if e.kind != "solidbody" or e.owner != SPACE_MODEL or not d.visible(e):
            continue
        if comp and str(e.handle) != comp:
            continue
        out.append(e)
    return out


def _assembly_items(doc, comp: str, load: bool = True) -> list:
    from app.assembly import walk, xform

    d = doc.drawing
    k = mm_per_unit(d)
    items = []
    for inst in walk.instances(doc):
        if inst.suppressed or not inst.visible or inst.part is None:
            continue
        if comp and not (inst.key == comp or inst.key.startswith(comp + "/") or inst.key.startswith(comp + "#")):
            continue
        m = inst.world.copy()
        m[0:3, 3] = m[0:3, 3] * k
        flat = [float(v) for v in m[0:3, :].reshape(-1)]
        for body in inst.part.bodies:
            if not body.closed and not body.summary.get("faces"):
                continue
            from app.assembly import parts

            wid = parts.shapes(inst.part, body) if load else ""
            items.append(Item("%s:%d" % (inst.key, body.handle), "component", wid, flat, int(body.version), body, inst.key, _sig([(inst.key, body.blob, tuple(round(v, 9) for v in flat))])))
            if len(items) >= MAX_ITEMS:
                raise ViewError("The assembly has more than %d bodies; show a sub-assembly." % MAX_ITEMS)
    return items


def external_path(doc, rel: str) -> str:
    base = os.path.dirname(os.path.realpath(doc.path)) if getattr(doc, "path", "") else ""
    if not base:
        raise ViewError("Save the drawing before a view can use another document.")
    full = os.path.realpath(os.path.join(base, str(rel)))
    if os.path.commonpath([base, full]) != base or not full.lower().endswith(".fcad") or not os.path.isfile(full):
        raise ViewError("A view source must be a .fcad file inside the drawing's folder.")
    return full


def resolve(doc, source: dict, load: bool = True) -> list:
    d = doc.drawing
    src = source or {}
    comp = str(src.get("component") or "").strip()
    rel = str(src.get("doc") or "").strip()
    if rel:
        from app.assembly import parts

        lp = parts.load(external_path(doc, rel))
        if lp.is_assembly:
            raise ViewError("Point the view at the assembly document itself; nested file sources hold parts only.")
        items = []
        k = lp.mm_per_unit
        for body in lp.bodies:
            if comp and str(body.handle) != comp:
                continue
            wid = parts.shapes(lp, body) if load else ""
            items.append(Item("%s:%d" % (rel, body.handle), "body", wid, None, int(body.version), body, "", _sig([(body.handle, body.blob, k)])))
        if not items:
            raise ViewError("The source document has no solid body to show.")
        return items
    from app.assembly import store as astore

    if astore.is_assembly(d):
        items = _assembly_items(doc, comp, load)
        if not items:
            raise ViewError("The assembly has nothing to show%s." % (" for component %s" % comp if comp else ""))
        return items
    items = []
    for e in _doc_items(d, comp):
        if not e.blob:
            continue
        wid = work.worker_id(d, e) if load else ""
        items.append(Item(str(e.handle), "body", wid, None, int(e.version), e, "", _sig([_body_sig(e, d)])))
    if not items:
        raise ViewError("There is no solid body to show%s." % (" with handle %s" % comp if comp else ""))
    return items


def signature(items: list) -> str:
    return _sig([i.sig for i in items])


def current_signature(doc, source: dict) -> str:
    try:
        return signature(resolve(doc, source, False))
    except Exception:
        return ""


def worker_items(items: list) -> list:
    return [{"id": i.wid, "matrix": i.matrix, "key": i.key} for i in items]
