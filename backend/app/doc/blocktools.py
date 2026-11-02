import re

from app.doc.model import block_space
from app.text.model import affine

BAD_NAME = set('<>/\\":;?*|=`')
MAX_NEST = 16
STYLE_FIELDS = ("layer", "linetype", "style", "block")
DIM_KINDS = ("dimension", "leader")
TEXT_KINDS = ("text", "mtext", "attdef")


class EditError(Exception):
    pass


def valid_name(name: str) -> bool:
    return bool(name) and len(name) <= 255 and not any(c in BAD_NAME for c in name) and name == name.strip()


def inverse(m):
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-18:
        return None
    ia, ib, ic, idd = m[3] / det, -m[1] / det, -m[2] / det, m[0] / det
    return affine(ia, ib, ic, idd, -(ia * m[4] + ic * m[5]), -(ib * m[4] + idd * m[5]))


def block_entities(d, name):
    return list(d.entities(block_space(name)))


def used_blocks(d, name):
    out = []
    for e in d.entities(block_space(name)):
        b = getattr(e, "block", "")
        if e.kind in ("insert", "dimension", "mleader") and b:
            rec = d.table_get("blocks", b)
            nm = rec["name"] if rec else b
            if nm.casefold() not in [x.casefold() for x in out]:
                out.append(nm)
    return out


def closure(d, name, limit=MAX_NEST * 64):
    seen = []
    todo = [name]
    while todo and len(seen) < limit:
        cur = todo.pop()
        if cur.casefold() in [s.casefold() for s in seen]:
            continue
        seen.append(cur)
        todo.extend(used_blocks(d, cur))
    return seen


def would_self_reference(d, host, block_names) -> bool:
    low = host.casefold()
    for nm in block_names:
        if nm.casefold() == low:
            return True
        if low in [c.casefold() for c in closure(d, nm)]:
            return True
    return False


def depth_of(d, name, depth=0, seen=None):
    seen = seen or set()
    if depth > MAX_NEST or name.casefold() in seen:
        return depth
    seen = seen | {name.casefold()}
    best = depth
    for sub in used_blocks(d, name):
        best = max(best, depth_of(d, sub, depth + 1, seen))
    return best


def references_to(d, name):
    low = name.casefold()
    return [e for e in d.ents.values() if e.kind == "insert" and e.block.casefold() == low]


def wildcard(spec: str, names):
    out = []
    for raw in spec.split(","):
        pat = raw.strip()
        if not pat:
            continue
        if any(c in pat for c in "*?#@[~"):
            rx = re.escape(pat).replace(r"\*", ".*").replace(r"\?", ".").replace(r"\#", "[0-9]").replace(r"\@", "[A-Za-z]")
            hits = [n for n in names if re.fullmatch(rx, n, re.I)]
        else:
            hits = [n for n in names if n.casefold() == pat.casefold()]
        out.extend(h for h in hits if h not in out)
    return out


def retarget(ent, maps):
    for fld in STYLE_FIELDS:
        v = getattr(ent, fld, None)
        if not isinstance(v, str) or not v:
            continue
        if fld == "layer":
            table = "layers"
        elif fld == "linetype":
            table = "linetypes"
        elif fld == "block":
            table = "blocks"
        elif ent.kind in DIM_KINDS:
            table = "dimstyles"
        elif ent.kind in TEXT_KINDS:
            table = "textstyles"
        else:
            continue
        new = maps.get(table, {}).get(v.casefold())
        if new is not None and new != v:
            setattr(ent, fld, new)
