import csv
import io
import math
import os

from app.doc import attribs, blockdefs, wildcard
from app.doc.entities import Insert

MAX_TABLE_ROWS = 1000
MAX_TABLE_COLS = 30


class ExtractError(Exception):
    pass


def _fmt(v) -> str:
    if isinstance(v, float):
        r = round(v, 6)
        return str(int(r)) if r == int(r) else repr(r)
    return str(v)


def collect(d, spec: str = "*", space: str = "model") -> list:
    pat = wildcard.compile_spec(spec or "*")
    out = []
    for e in d.entities(space):
        if isinstance(e, Insert) and wildcard.matches(pat, e.block):
            out.append(e)
    return out


def values_of(d, ins) -> dict:
    vals = {}
    for adef in attribs.constant_defs(d, ins.block):
        vals[adef.tag] = adef.default
    for att in ins.attributes or []:
        vals[att["tag"]] = att.get("value", "")
    return vals


def tags_for(d, inserts) -> list:
    seen = []
    keys = set()
    for ins in inserts:
        for adef in attribs.definitions(d, ins.block):
            k = adef.tag.casefold()
            if k not in keys:
                keys.add(k)
                seen.append(adef.tag)
    return seen


def table_rows(d, inserts, combine: bool = True, tags=None) -> tuple:
    tags = list(tags) if tags is not None else tags_for(d, inserts)
    if combine:
        head = ["Count", "Name"] + tags
        groups = {}
        order = []
        for ins in inserts:
            vals = values_of(d, ins)
            key = (ins.block.casefold(),) + tuple(vals.get(t, "") for t in tags)
            if key not in groups:
                groups[key] = [0, ins.block, [vals.get(t, "") for t in tags]]
                order.append(key)
            groups[key][0] += 1
        body = [[str(groups[k][0]), groups[k][1]] + groups[k][2] for k in order]
        return head, body
    head = ["Handle", "Name", "Layer", "Position X", "Position Y", "Rotation"] + tags
    body = []
    for ins in inserts:
        vals = values_of(d, ins)
        body.append(["%X" % ins.handle, ins.block, ins.layer, _fmt(ins.position[0]), _fmt(ins.position[1]), _fmt(math.degrees(ins.rotation))] + [vals.get(t, "") for t in tags])
    return head, body


def render(head, body, tab: bool = False) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t" if tab else ",", lineterminator="\n")
    w.writerow(head)
    for r in body:
        w.writerow(r)
    return buf.getvalue()


def write_file(path: str, head, body) -> str:
    raw = os.path.expanduser(str(path).strip())
    if not raw:
        raise ExtractError("A file name is required.")
    ext = os.path.splitext(raw)[1].lower()
    if ext not in (".csv", ".txt"):
        raw += ".csv"
        ext = ".csv"
    tmp = raw + ".part"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(render(head, body, ext == ".txt"))
        os.replace(tmp, raw)
    except OSError as err:
        raise ExtractError("Cannot write %s: %s." % (raw, err.strerror or err))
    return raw


def check_table(head, body) -> None:
    if len(body) > MAX_TABLE_ROWS or len(head) > MAX_TABLE_COLS:
        raise ExtractError("Too much data for a table (%d rows, %d columns)." % (len(body), len(head)))


def extract(d, spec: str = "*", combine: bool = True, space: str = "model") -> dict:
    inserts = collect(d, spec, space)
    head, body = table_rows(d, inserts, combine)
    return {"columns": head, "rows": body, "references": len(inserts)}


def blocks_used(d, space: str = "model") -> list:
    seen = []
    for e in d.entities(space):
        if isinstance(e, Insert) and e.block not in seen:
            seen.append(e.block)
    return seen


def exists(d, name: str) -> bool:
    return blockdefs.lookup(d, name) is not None
