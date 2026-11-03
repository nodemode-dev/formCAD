from app.assembly import bom, walk
from app.core import guard

MAX_PARTS = 300
MAX_PARTS_AGENT = 60


class ScopeError(ValueError):
    pass


def limit() -> int:
    return MAX_PARTS_AGENT if guard.CALLER.get() else MAX_PARTS


def targets(doc, mode: str = "auto") -> list:
    d = doc.drawing
    is_asm = doc.kind == "assembly" or bool(d.header.get("ASSEMBLY"))
    if mode == "part" or (mode == "auto" and not is_asm):
        return [{"label": doc.name, "qty": 1, "drawing": d, "doc": doc, "part_number": "", "file": getattr(doc, "path", "") or ""}]
    info = bom.build(doc, "flat")
    insts = {i.key: i for i in walk.instances(doc)}
    out = []
    for row in info["rows"]:
        inst = None
        for k in row["keys"]:
            inst = insts.get(k)
            if inst is not None:
                break
        if inst is None or inst.part is None or inst.part.is_assembly:
            continue
        out.append({"label": row["name"], "qty": int(row["ext_qty"]), "drawing": inst.part.drawing, "doc": None, "part_number": row["part_number"], "file": row["file"], "item": row["item"], "props": bom.props_of(inst)})
    if len(out) > limit():
        raise ScopeError("The assembly has %d distinct parts; at most %d are costed in one call here." % (len(out), limit()))
    if not out:
        raise ScopeError("The assembly has no loadable part to cost.")
    return out
