import math

from app.doc import blockxf, geom, rename
from app.doc.entities import Insert, entity_from_dict
from app.doc.model import block_space
from app.text.model import affine, compose

MAX_DEPTH = 8
MAX_DESCRIPTION = 255
MAX_NAME = 255

edit_locks: list = []


class BlockError(Exception):
    pass


def lookup(d, name):
    return d.table_get("blocks", str(name).strip()) if name is not None else None


def check_name(name) -> str:
    n = str(name if name is not None else "").strip()
    if not n or n.startswith("*") or len(n) > MAX_NAME or not rename.valid_name(n):
        raise BlockError("Invalid block name.")
    return n


def space_of(name: str) -> str:
    return block_space(name)


def names(d, anonymous: bool = False, xrefs: bool = True) -> list:
    out = []
    for rec in d.tables["blocks"].values():
        if rec.get("anonymous") and not anonymous:
            continue
        if rec.get("xref") and not xrefs:
            continue
        out.append(rec["name"])
    return out


def children(d, name: str) -> list:
    rec = lookup(d, name)
    if rec is None:
        return []
    return list(d.entities(block_space(rec["name"])))


def used_blocks(e) -> list:
    k = e.kind
    if k in ("insert", "dimension"):
        return [e.block] if getattr(e, "block", "") else []
    if k == "mleader":
        out = [e.block] if getattr(e, "block", "") else []
        for mb in getattr(e, "more_blocks", None) or []:
            if isinstance(mb, dict) and mb.get("block"):
                out.append(mb["block"])
        return out
    return []


def uses(d, name: str) -> set:
    out = set()
    for e in children(d, name):
        for b in used_blocks(e):
            out.add(str(b).casefold())
    return out


def reaches(d, start: str, target: str) -> bool:
    goal = str(target).casefold()
    seen = set()
    stack = [str(start).casefold()]
    while stack:
        cur = stack.pop()
        if cur == goal:
            return True
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(uses(d, cur) - seen)
    return False


def would_self_reference(d, name: str, entities) -> bool:
    goal = str(name).casefold()
    for e in entities:
        for b in used_blocks(e):
            if str(b).casefold() == goal or reaches(d, b, goal):
                return True
    return False


def all_inserts(d):
    for e in list(d.ents.values()):
        if e.kind == "insert":
            yield e


def references(d, name: str) -> list:
    key = str(name).casefold()
    return [e for e in all_inserts(d) if str(e.block).casefold() == key]


def reference_counts(d) -> dict:
    out = {}
    for e in all_inserts(d):
        key = str(e.block).casefold()
        out[key] = out.get(key, 0) + 1
    return out


def attribute_definitions(d, name: str) -> list:
    return [e for e in children(d, name) if e.kind == "attdef"]


def description_of(d, name: str) -> str:
    rec = lookup(d, name)
    return rec.get("description", "") if rec else ""


def listing(d, anonymous: bool = False) -> list:
    counts = reference_counts(d)
    rows = []
    for rec in d.tables["blocks"].values():
        if rec.get("anonymous") and not anonymous:
            continue
        kids = list(d.entities(block_space(rec["name"])))
        rows.append(
            {
                "name": rec["name"],
                "base": list(rec.get("base", [0.0, 0.0, 0.0])),
                "description": rec.get("description", ""),
                "references": counts.get(rec["name"].casefold(), 0),
                "objects": len(kids),
                "attributes": sum(1 for e in kids if e.kind == "attdef"),
                "anonymous": bool(rec.get("anonymous")),
                "xref": rec.get("xref"),
                "explodable": bool(rec.get("explodable", True)),
                "annotative": bool(rec.get("annotative", False)),
                "insunits": rec.get("insunits", 0),
                "uses": sorted(uses(d, rec["name"])),
            }
        )
    return rows


def lock_reason(d, name: str) -> str:
    for fn in list(edit_locks):
        msg = fn(d, name)
        if msg:
            return msg
    return ""


def touch(d, name: str) -> None:
    d._rec_space(block_space(name))


def clones_of(d, handles) -> list:
    out = []
    for h in handles:
        e = d.get(h)
        if e is None:
            continue
        c = e.copy_as_new()
        c.owner = "model"
        out.append(c)
    return out


def _fill(d, name: str, entities) -> list:
    space = block_space(name)
    made = []
    for e in entities:
        c = entity_from_dict(e.to_dict()) if hasattr(e, "to_dict") else e
        c.handle = 0
        c.reactors = []
        made.append(d.add_entity(c, space))
    return made


def define(d, name: str, entities, base=None, description: str = "", annotative: bool = False, explodable: bool = True, redefine: bool = False) -> dict:
    name = check_name(name)
    existing = lookup(d, name)
    entities = list(entities)
    if existing is not None:
        if not redefine:
            raise BlockError('Block "%s" already exists.' % existing["name"])
        if existing.get("xref"):
            raise BlockError('Block "%s" is an external reference.' % existing["name"])
        why = lock_reason(d, existing["name"])
        if why:
            raise BlockError(why)
        name = existing["name"]
    if would_self_reference(d, name, entities):
        raise BlockError('Block "%s" references itself.' % name)
    if len(description or "") > MAX_DESCRIPTION:
        raise BlockError("The description is longer than %d characters." % MAX_DESCRIPTION)
    pt = geom.as_pt(base) if base is not None else [0.0, 0.0, 0.0]
    if existing is not None:
        for h in list(d.spaces.get(block_space(name), ())):
            d.erase_entity(h)
        rec = d.modify_record("blocks", name)
        rec["base"] = [pt[0], pt[1], pt[2] if len(pt) > 2 else 0.0]
        if description is not None:
            rec["description"] = str(description)
        rec["annotative"] = bool(annotative)
        rec["explodable"] = bool(explodable)
        d.ensure_space(block_space(name))
        touch(d, name)
    else:
        rec = d.define_block(name, pt, str(description or ""))
        rec["annotative"] = bool(annotative)
        rec["explodable"] = bool(explodable)
        d.table_set("blocks", rec)
    _fill(d, name, entities)
    return lookup(d, name)


def redefine(d, name: str, entities, base=None, description=None, annotative=None, explodable=None, sync: bool = True) -> dict:
    rec = lookup(d, name)
    if rec is None:
        raise BlockError('Block "%s" not found.' % name)
    pt = base if base is not None else rec["base"]
    desc = rec.get("description", "") if description is None else description
    ann = rec.get("annotative", False) if annotative is None else annotative
    exp = rec.get("explodable", True) if explodable is None else explodable
    out = define(d, rec["name"], entities, pt, desc, ann, exp, redefine=True)
    if sync:
        from app.doc import attribs

        attribs.sync_block(d, out["name"])
    return out


def set_description(d, name: str, text: str) -> dict:
    rec = lookup(d, name)
    if rec is None:
        raise BlockError('Block "%s" not found.' % name)
    text = str(text or "")
    if len(text) > MAX_DESCRIPTION or "\n" in text:
        raise BlockError("The description must be one line of at most %d characters." % MAX_DESCRIPTION)
    d.modify_record("blocks", rec["name"])["description"] = text
    return rec


def set_base(d, name: str, base) -> dict:
    rec = lookup(d, name)
    if rec is None:
        raise BlockError('Block "%s" not found.' % name)
    pt = geom.as_pt(base)
    d.modify_record("blocks", rec["name"])["base"] = [pt[0], pt[1], pt[2] if len(pt) > 2 else 0.0]
    touch(d, rec["name"])
    return rec


def remove(d, name: str) -> int:
    rec = lookup(d, name)
    if rec is None:
        return 0
    n = 0
    for h in list(d.spaces.get(block_space(rec["name"]), ())):
        d.erase_entity(h)
        n += 1
    d._rec_space(block_space(rec["name"]))
    d.spaces.pop(block_space(rec["name"]), None)
    d.table_remove("blocks", rec["name"])
    return n


def reachable(d) -> set:
    roots = []
    for space, handles in d.spaces.items():
        if space.startswith("block:"):
            continue
        for h in handles:
            e = d.ents.get(h)
            if e is not None:
                roots.extend(str(b).casefold() for b in used_blocks(e))
    for rec in d.tables["dimstyles"].values():
        for key in ("DIMBLK", "DIMBLK1", "DIMBLK2", "DIMLDRBLK"):
            v = rec.get("vars", {}).get(key)
            if v:
                roots.append(str(v).casefold())
    for key in ("DIMBLK", "DIMBLK1", "DIMBLK2", "DIMLDRBLK"):
        v = d.header.get(key)
        if v:
            roots.append(str(v).casefold())
    for rec in d.tables["mleaderstyles"].values():
        v = rec.get("block")
        if v:
            roots.append(str(v).casefold())
    seen = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(uses(d, cur) - seen)
    return seen


def unused(d) -> list:
    live = reachable(d)
    out = []
    for rec in d.tables["blocks"].values():
        if rec.get("xref"):
            continue
        if rec["name"].casefold() not in live:
            out.append(rec["name"])
    return out


def purge(d, spec: str = "*") -> list:
    from app.doc import wildcard

    want = wildcard.filter_names(spec, unused(d))
    gone = []
    for n in want:
        if lock_reason(d, n):
            continue
        remove(d, n)
        gone.append(n)
    return gone


def insert_matrices(ins, rec) -> list:
    return blockxf.insert_matrices(ins, rec)


def insert_matrix(ins, rec) -> tuple:
    return blockxf.insert_matrices(ins, rec)[0]


def insert_point(m, p) -> list:
    return [m[0] * p[0] + m[2] * p[1] + m[4], m[1] * p[0] + m[3] * p[1] + m[5]]


def resolve_props(ref, ent):
    if ent.layer == "0":
        ent.layer = ref.layer
    if ent.color == 0:
        ent.color = ref.color
    if str(ent.linetype).lower() == "byblock":
        ent.linetype = ref.linetype
    if ent.lineweight == -2:
        ent.lineweight = ref.lineweight
    return ent


def expand_block(d, name: str, matrix, owner: str = "model", ref=None, limit: int = blockxf.MAX_COPIES) -> list:
    rec = lookup(d, name)
    if rec is None:
        return []
    out = []
    for child in children(d, rec["name"]):
        c = blockxf.clone_through(child, matrix)
        if c is None:
            continue
        c.handle = 0
        c.owner = owner
        if ref is not None:
            resolve_props(ref, c)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def expand_insert(d, ins, include_attdefs: bool = True) -> list:
    rec = lookup(d, ins.block)
    if rec is None:
        return []
    out = []
    for m in blockxf.insert_matrices(ins, rec):
        for c in expand_block(d, rec["name"], m, ins.owner, ins):
            if c.kind == "attdef" and not include_attdefs:
                continue
            out.append(c)
            if len(out) >= blockxf.MAX_COPIES:
                return out
    return out


def _corners(box, m):
    pts = [insert_point(m, (box[0], box[1])), insert_point(m, (box[2], box[1])), insert_point(m, (box[2], box[3])), insert_point(m, (box[0], box[3]))]
    return geom.bounds_of_points(pts)


def block_bounds(d, name: str, depth: int = 0):
    if depth > MAX_DEPTH:
        return None
    box = None
    for c in children(d, name):
        if c.kind == "insert":
            b = insert_bounds(d, c, depth + 1)
        else:
            try:
                b = c.bounds()
            except Exception:
                b = None
        if b is not None:
            box = geom.union_bounds(box, b)
    return box


def insert_bounds(d, ins, depth: int = 0):
    rec = lookup(d, ins.block)
    if rec is None or depth > MAX_DEPTH:
        return geom.bounds_of_points([ins.position])
    inner = block_bounds(d, rec["name"], depth)
    if inner is None:
        return geom.bounds_of_points([ins.position])
    box = None
    for m in blockxf.insert_matrices(ins, rec):
        box = geom.union_bounds(box, _corners(inner, m))
    return box


def new_insert(d, name: str, position, scale=None, rotation: float = 0.0, base_override=None, array=None, attributes=True):
    rec = lookup(d, name)
    if rec is None:
        raise BlockError('Block "%s" not found.' % name)
    sc = [1.0, 1.0, 1.0]
    if scale is not None:
        vals = [float(v) for v in scale]
        if len(vals) == 1:
            vals = [vals[0], vals[0], vals[0]]
        elif len(vals) == 2:
            vals = [vals[0], vals[1], abs(vals[0])]
        sc = vals[:3]
    if any(abs(v) < 1e-12 or not math.isfinite(v) for v in sc):
        raise BlockError("Requires a non-zero number.")
    pos = geom.as_pt(position)
    if base_override is not None:
        bo = geom.as_pt(base_override)
        db = [rec["base"][0] - bo[0], rec["base"][1] - bo[1]]
        ca, sa = math.cos(rotation), math.sin(rotation)
        x, y = db[0] * sc[0], db[1] * sc[1]
        pos = [pos[0] + x * ca - y * sa, pos[1] + x * sa + y * ca, pos[2] if len(pos) > 2 else 0.0]
    ins = Insert(block=rec["name"], position=[pos[0], pos[1], pos[2] if len(pos) > 2 else 0.0], scale=sc, rotation=float(rotation))
    if array:
        ins.array = dict(array)
    if attributes is not False:
        from app.doc import attribs

        values = attributes if isinstance(attributes, dict) else {}
        ins.attributes = attribs.instances_for(d, rec["name"], values)
    return ins
