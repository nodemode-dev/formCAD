import copy
import os
import re

from app.doc import blockdefs, container
from app.doc.entities import entity_from_dict
from app.doc.model import SPACE_MODEL, Drawing, block_space

NATIVE_EXT = ".fcad"
FOREIGN_EXT = (".dxf", ".dwg")
MERGED_TABLES = ("layers", "linetypes", "textstyles", "dimstyles", "mleaderstyles", "tablestyles", "mlinestyles", "scales")
READERS: dict = {}
DXF_WRITER = None
DWG_WRITER = None


class BlockIOError(Exception):
    pass


def register_reader(ext: str, fn) -> None:
    READERS[ext.lower()] = fn


def write_dxf(drawing, path: str, precision: int = 16, fmt: str = ".dxf") -> None:
    fn = DXF_WRITER if fmt == ".dxf" else DWG_WRITER
    if fn is None:
        raise BlockIOError("%s output is not available in this build yet." % fmt[1:].upper())
    fn(drawing, path, precision)


def output_path(text: str) -> str:
    raw = os.path.expanduser(str(text).strip())
    if not raw:
        raise BlockIOError("A file name is required.")
    ext = os.path.splitext(raw)[1].lower()
    if ext not in (NATIVE_EXT,) + FOREIGN_EXT:
        raw += NATIVE_EXT
    return raw


def resolve_input(text: str):
    raw = os.path.expanduser(str(text).strip().strip('"'))
    if not raw:
        return None
    if os.path.isfile(raw):
        return raw
    if not os.path.splitext(raw)[1]:
        for ext in (NATIVE_EXT, ".dwg", ".dxf"):
            if os.path.isfile(raw + ext):
                return raw + ext
    return None


def looks_like_file(text: str) -> bool:
    t = str(text).strip()
    return bool(t) and (("/" in t) or ("\\" in t) or os.path.splitext(t)[1].lower() in (NATIVE_EXT,) + FOREIGN_EXT)


def stem_name(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r'[<>/\\":;?*|,=`]', "_", stem).strip()
    return stem or "Block"


def read_drawing(path: str) -> Drawing:
    ext = os.path.splitext(path)[1].lower()
    if ext == NATIVE_EXT or not ext:
        try:
            drawing, _manifest = container.load(path)
        except container.ContainerError as err:
            raise BlockIOError(err.message)
        return drawing
    fn = READERS.get(ext)
    if fn is None:
        raise BlockIOError("Reading %s files is not available in this build yet." % ext[1:].upper())
    try:
        return fn(path)
    except BlockIOError:
        raise
    except Exception as err:
        raise BlockIOError("Could not read %s: %s" % (os.path.basename(path), err))


def _clone(e):
    c = entity_from_dict(e.to_dict())
    c.handle = 0
    c.reactors = []
    return c


def _fresh_anonymous(d, name: str, taken: set) -> str:
    prefix = re.match(r"^\*[A-Za-z]*", name).group(0) or "*U"
    n = 1
    while True:
        cand = "%s%d" % (prefix, n)
        if not d.tables["blocks"].has(cand) and cand.casefold() not in taken:
            return cand
        n += 1


def import_as_block(d, name: str | None, path: str, redefine: bool = False) -> dict:
    full = resolve_input(path)
    if full is None:
        raise BlockIOError('Cannot find the file "%s".' % path)
    src = read_drawing(full)
    block_name = blockdefs.check_name(name if name else stem_name(full))
    existing = blockdefs.lookup(d, block_name)
    if existing is not None and not redefine:
        raise BlockIOError('Block "%s" already exists.' % existing["name"])
    added = {"tables": 0, "blocks": 0}
    for tname in MERGED_TABLES:
        for rec in src.tables[tname].values():
            if not d.tables[tname].has(rec["name"]):
                d.table_set(tname, copy.deepcopy(rec))
                added["tables"] += 1
    remap = {}
    taken = set()
    for rec in src.tables["blocks"].values():
        if rec.get("xref"):
            continue
        low = rec["name"].casefold()
        if low == block_name.casefold():
            continue
        if d.tables["blocks"].has(rec["name"]):
            if rec["name"].startswith("*"):
                fresh = _fresh_anonymous(d, rec["name"], taken)
                taken.add(fresh.casefold())
                remap[low] = fresh
            continue
        remap[low] = rec["name"]

    def fix(c):
        if c.kind == "insert" or c.kind == "dimension":
            if c.block and c.block.casefold() in remap:
                c.block = remap[c.block.casefold()]
        if c.kind == "dimension":
            c.associativity = {}
        return c

    for rec in list(src.tables["blocks"].values()):
        low = rec["name"].casefold()
        if low not in remap or rec.get("xref"):
            continue
        target = remap[low]
        if d.tables["blocks"].has(target):
            continue
        new_rec = d.define_block(target, rec.get("base"), rec.get("description", ""))
        new_rec["annotative"] = bool(rec.get("annotative", False))
        new_rec["explodable"] = bool(rec.get("explodable", True))
        new_rec["insunits"] = rec.get("insunits", 0)
        d.table_set("blocks", new_rec)
        for e in src.entities(block_space(rec["name"])):
            d.add_entity(fix(_clone(e)), block_space(target))
        added["blocks"] += 1
    ents = [fix(_clone(e)) for e in src.entities(SPACE_MODEL)]
    base = src.header.get("INSBASE") or [0.0, 0.0]
    rec = blockdefs.define(d, block_name, ents, [float(base[0]), float(base[1]), 0.0], "", False, True, redefine=existing is not None)
    d.modify_record("blocks", rec["name"])["insunits"] = src.header.get("INSUNITS", 0)
    return {"name": rec["name"], "objects": len(ents), "added": added, "path": full, "base": list(rec["base"])}


def _needed_blocks(src, entities) -> list:
    seen = []
    stack = []
    for e in entities:
        stack.extend(blockdefs.used_blocks(e))
    while stack:
        n = stack.pop()
        rec = src.table_get("blocks", n)
        if rec is None or rec["name"] in seen:
            continue
        seen.append(rec["name"])
        for child in src.entities(block_space(rec["name"])):
            stack.extend(blockdefs.used_blocks(child))
    return seen


def _carry_tables(src, out: Drawing) -> None:
    for tname in MERGED_TABLES:
        out.tables[tname].load_list(src.tables[tname].to_list())
    out.header = copy.deepcopy(src.header)


def _copy_blocks(src, out: Drawing, names) -> None:
    for n in names:
        rec = src.table_get("blocks", n)
        out.tables["blocks"].put(copy.deepcopy(rec))
        out.ensure_space(block_space(rec["name"]))
        for e in src.entities(block_space(rec["name"])):
            out.add_entity(_clone(e), block_space(rec["name"]))


def build_from_objects(src, handles, base) -> Drawing:
    ents = [src.get(h) for h in handles if src.get(h) is not None]
    out = Drawing(src.metric)
    _carry_tables(src, out)
    out.header["INSBASE"] = [0.0, 0.0]
    _copy_blocks(src, out, _needed_blocks(src, ents))
    bx, by = float(base[0]), float(base[1])
    for e in ents:
        c = _clone(e)
        c.move_by([-bx, -by, 0.0])
        out.add_entity(c, SPACE_MODEL)
    _refresh(out)
    return out


def build_from_block(src, name) -> Drawing:
    rec = blockdefs.lookup(src, name)
    if rec is None:
        raise BlockIOError('Block "%s" not found.' % name)
    kids = list(src.entities(block_space(rec["name"])))
    out = Drawing(src.metric)
    _carry_tables(src, out)
    out.header["INSBASE"] = [rec["base"][0], rec["base"][1]]
    _copy_blocks(src, out, [n for n in _needed_blocks(src, kids) if n.casefold() != rec["name"].casefold()])
    for e in kids:
        out.add_entity(_clone(e), SPACE_MODEL)
    _refresh(out)
    return out


def build_whole(src) -> Drawing:
    return Drawing.from_dict(src.to_dict())


def _refresh(out: Drawing) -> None:
    from app.doc.kinds import blockcache

    blockcache.refresh_all(out)


def write(drawing: Drawing, path: str, title: str = "", precision: int = 16) -> str:
    dest = output_path(path)
    ext = os.path.splitext(dest)[1].lower()
    name = title or os.path.splitext(os.path.basename(dest))[0]
    if ext in FOREIGN_EXT:
        write_dxf(drawing, dest, precision, ext)
        return dest
    from app.doc.document import now_iso

    try:
        return container.save(dest, drawing, name, now_iso(), False, "drawing")
    except container.ContainerError as err:
        raise BlockIOError(err.message)
