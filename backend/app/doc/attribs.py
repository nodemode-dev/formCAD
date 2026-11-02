import math
import re

from app.doc import blockdefs, blockxf, geom
from app.doc.entities import AttDef, Text

MAX_VALUE = 2048
MAX_TAG = 255
MODE_KEYS = ("invisible", "constant", "verify", "preset", "lock_position", "annotative", "multiline")


class AttribError(Exception):
    pass


def normalize_tag(tag) -> str:
    t = re.sub(r"\s+", "_", str(tag if tag is not None else "").strip()).upper()
    if not t:
        raise AttribError("Tag cannot be null.")
    if len(t) > MAX_TAG:
        raise AttribError("The tag is too long.")
    return t


def check_value(value) -> str:
    v = str(value if value is not None else "")
    if len(v) > MAX_VALUE:
        raise AttribError("The new value is too long.")
    return v


def mode_of(adef, key: str) -> bool:
    return bool((adef.modes or {}).get(key, False))


def definitions(d, block: str) -> list:
    return [e for e in blockdefs.children(d, block) if e.kind == "attdef"]


def definition(d, block: str, tag: str):
    key = str(tag).casefold()
    for e in definitions(d, block):
        if e.tag.casefold() == key:
            return e
    return None


def find(ins, tag: str):
    key = str(tag).casefold()
    for a in ins.attributes or []:
        if str(a.get("tag", "")).casefold() == key:
            return a
    return None


def new_instance(adef, value=None) -> dict:
    return {
        "tag": adef.tag,
        "value": check_value(adef.default if value is None else value),
        "lock_position": mode_of(adef, "lock_position"),
        "layer": None,
        "color": None,
        "linetype": None,
        "lineweight": None,
        "shift": None,
        "at": None,
        "vis": not mode_of(adef, "invisible"),
    }


def instances_for(d, block: str, values: dict | None = None) -> list:
    given = {str(k).casefold(): v for k, v in (values or {}).items()}
    out = []
    for adef in definitions(d, block):
        if mode_of(adef, "constant"):
            continue
        out.append(new_instance(adef, given.get(adef.tag.casefold())))
    return out


def asked(d, block: str) -> list:
    return [a for a in definitions(d, block) if not mode_of(a, "constant") and not mode_of(a, "preset")]


def sync_insert(d, ins, renames: dict | None = None) -> int:
    old = {str(a.get("tag", "")).casefold(): a for a in (ins.attributes or [])}
    fresh = []
    for adef in definitions(d, ins.block):
        if mode_of(adef, "constant"):
            continue
        key = adef.tag.casefold()
        prev = old.get(key)
        if prev is None and renames:
            prev = old.get(str(renames.get(key, "")).casefold())
        fresh.append(new_instance(adef, prev["value"] if prev is not None else None))
    ins.attributes = fresh
    return len(fresh)


def sync_block(d, name: str, renames: dict | None = None) -> int:
    rec = blockdefs.lookup(d, name)
    if rec is None:
        raise AttribError('Block "%s" not found.' % name)
    n = 0
    for ref in blockdefs.references(d, rec["name"]):
        live = d.modify(ref.handle)
        sync_insert(d, live, renames)
        refresh_cache(d, live)
        n += 1
    return n


def is_shown(adef, attmode: int) -> bool:
    if attmode == 0:
        return False
    if attmode == 2:
        return True
    return not mode_of(adef, "invisible")


def _inverse_linear(m):
    det = m[0] * m[3] - m[1] * m[2]
    if abs(det) < 1e-300:
        return None
    return (m[3] / det, -m[1] / det, -m[2] / det, m[0] / det)


def reference_text(adef, value, m, att=None, ref_layer: str | None = None) -> Text:
    shift = (att or {}).get("shift") or [0.0, 0.0]
    p = [adef.position[0] + shift[0], adef.position[1] + shift[1]]
    pos = blockdefs.insert_point(m, p)
    ap = None
    if adef.align_point is not None:
        ap = blockdefs.insert_point(m, [adef.align_point[0] + shift[0], adef.align_point[1] + shift[1]])
    sx = math.hypot(m[0], m[1])
    sy = math.hypot(m[2], m[3])
    det = m[0] * m[3] - m[1] * m[2]
    rot = math.atan2(m[1], m[0])
    if det < 0 and m[0] < 0:
        rot = math.atan2(-m[1], -m[0])
    t = Text(position=[pos[0], pos[1], 0.0], align_point=([ap[0], ap[1], 0.0] if ap is not None else None), height=float(adef.height) * sy, text=str(value), rotation=float(adef.rotation) + rot, width_factor=float(adef.width_factor) * (sx / sy if sy > 1e-300 else 1.0), oblique=float(adef.oblique), style=adef.style, halign=int(adef.halign), valign=int(adef.valign))
    t.layer = (att or {}).get("layer") or adef.layer
    col = (att or {}).get("color")
    t.color = adef.color if col is None else col
    lt = (att or {}).get("linetype")
    t.linetype = adef.linetype if lt is None else lt
    lw = (att or {}).get("lineweight")
    t.lineweight = adef.lineweight if lw is None else lw
    t.ltscale = adef.ltscale
    t.transparency = adef.transparency
    return t


def constant_defs(d, block: str) -> list:
    return [a for a in definitions(d, block) if mode_of(a, "constant")]


def shown_texts(d, ins, attmode: int | None = None, m=None) -> list:
    rec = blockdefs.lookup(d, ins.block)
    if rec is None:
        return []
    if attmode is None:
        attmode = int(d.header.get("ATTMODE", 1))
    if m is None:
        m = blockxf.insert_matrices(ins, rec)[0]
    out = []
    defs = {a.tag.casefold(): a for a in definitions(d, rec["name"])}
    for att in ins.attributes or []:
        adef = defs.get(str(att.get("tag", "")).casefold())
        if adef is None or not is_shown(adef, attmode):
            continue
        out.append((att, reference_text(adef, att.get("value", ""), m, att)))
    for adef in constant_defs(d, rec["name"]):
        if is_shown(adef, attmode):
            out.append((None, reference_text(adef, adef.default, m)))
    return out


def cache_rows(d, ins) -> list:
    rec = blockdefs.lookup(d, ins.block)
    if rec is None:
        return []
    m = blockxf.insert_matrices(ins, rec)[0]
    defs = {a.tag.casefold(): a for a in definitions(d, rec["name"])}
    rows = []
    for att in ins.attributes or []:
        adef = defs.get(str(att.get("tag", "")).casefold())
        if adef is None:
            rows.append({"at": None, "vis": False, "lock_position": bool(att.get("lock_position", False))})
            continue
        t = reference_text(adef, att.get("value", ""), m, att)
        anchor = t.align_point if t.align_point is not None else t.position
        rows.append({"at": [float(anchor[0]), float(anchor[1])], "vis": not mode_of(adef, "invisible"), "lock_position": bool(att.get("lock_position", False)) or mode_of(adef, "lock_position")})
    return rows


def cache_current(ins) -> list:
    return [{"at": a.get("at"), "vis": a.get("vis", True), "lock_position": bool(a.get("lock_position", False))} for a in (ins.attributes or [])]


def refresh_cache(d, ins) -> None:
    rows = cache_rows(d, ins)
    for att, row in zip(ins.attributes or [], rows):
        att.update(row)


def move_attribute(ins, tag: str, to) -> None:
    att = find(ins, tag)
    if att is None:
        raise AttribError('No attribute "%s".' % tag)
    if att.get("lock_position"):
        raise AttribError("The attribute position is locked.")
    if not att.get("at"):
        raise AttribError("The attribute has no placement yet.")
    sx = ins.scale[0] if ins.scale else 1.0
    sy = ins.scale[1] if ins.scale and len(ins.scale) > 1 else sx
    ca, sa = math.cos(ins.rotation), math.sin(ins.rotation)
    m = (ca * sx, sa * sx, -sa * sy, ca * sy, 0.0, 0.0)
    inv = _inverse_linear(m)
    if inv is None:
        raise AttribError("The block reference is degenerate.")
    dx, dy = to[0] - att["at"][0], to[1] - att["at"][1]
    lx = inv[0] * dx + inv[2] * dy
    ly = inv[1] * dx + inv[3] * dy
    old = att.get("shift") or [0.0, 0.0]
    att["shift"] = [old[0] + lx, old[1] + ly]
    att["at"] = [float(to[0]), float(to[1])]


def burst_texts(d, ins) -> list:
    out = []
    for _att, t in shown_texts(d, ins, 1):
        t.handle = 0
        t.owner = ins.owner
        out.append(t)
    return out


def adef_from_text_args(position, tag, prompt, default, height, rotation, style, modes, halign=0, valign=0, align_point=None) -> AttDef:
    m = {k: False for k in MODE_KEYS}
    for k, v in (modes or {}).items():
        if k in m:
            m[k] = bool(v)
    return AttDef(position=[position[0], position[1], 0.0], align_point=([align_point[0], align_point[1], 0.0] if align_point is not None else None), tag=normalize_tag(tag), prompt=str(prompt or ""), default=str(default if default is not None else ""), height=float(height), rotation=float(rotation), style=style, modes=m, halign=int(halign), valign=int(valign))


def display_text(adef) -> Text:
    t = Text(position=list(adef.position), align_point=(list(adef.align_point) if adef.align_point is not None else None), height=adef.height, text=adef.tag, rotation=adef.rotation, width_factor=adef.width_factor, oblique=adef.oblique, style=adef.style, halign=adef.halign, valign=adef.valign)
    t.layer, t.color, t.linetype, t.lineweight, t.ltscale, t.transparency = adef.layer, adef.color, adef.linetype, adef.lineweight, adef.ltscale, adef.transparency
    return t


def unique_tag(d, block: str, tag: str, skip=None) -> bool:
    key = tag.casefold()
    for a in definitions(d, block):
        if a is skip or (skip is not None and a.handle == skip.handle):
            continue
        if a.tag.casefold() == key:
            return False
    return True
