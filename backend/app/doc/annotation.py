import copy
import re

from app.doc import tables as T

MAX_SCALES = 1000
CAPABLE = ("text", "mtext", "dimension", "mleader", "hatch", "insert")
MAX_NAME = 255
OFFSETS_KEY = "anno_pos"


class AnnotationError(Exception):
    pass


def _fraction(text: str):
    t = text.strip().replace("-", " ", 1) if re.search(r"\d\s*-\s*\d+/\d+", text) else text.strip()
    parts = t.split()
    total = 0.0
    for part in parts:
        if "/" in part:
            a, _, b = part.partition("/")
            if not re.fullmatch(r"\d+(\.\d+)?", a) or not re.fullmatch(r"\d+(\.\d+)?", b) or float(b) == 0:
                return None
            total += float(a) / float(b)
        elif re.fullmatch(r"\d+(\.\d+)?|\.\d+", part):
            total += float(part)
        else:
            return None
    return total if parts else None


def parse_length(text: str):
    t = text.strip()
    if not t:
        return None
    if "'" in t or '"' in t:
        feet, _, rest = t.partition("'")
        total = 0.0
        if "'" in t:
            f = _fraction(feet)
            if f is None:
                return None
            total += f * 12.0
        else:
            rest = t
        rest = rest.strip().lstrip("-").strip().rstrip('"').strip()
        if rest:
            inches = _fraction(rest)
            if inches is None:
                return None
            total += inches
        return total
    return _fraction(t)


def parse_ratio(text: str):
    t = str(text).strip()
    for sep in (":", "="):
        if sep in t:
            a, _, b = t.partition(sep)
            paper, drawing = parse_length(a), parse_length(b)
            if paper is None or drawing is None:
                return None
            return paper, drawing
    return None


def scale_names(d) -> list:
    return d.tables["scales"].names()


def get_scale(d, name):
    return d.tables["scales"].get(str(name))


def current_name(d) -> str:
    return str(d.header.get("CANNOSCALE", "1:1"))


def factor(d, name) -> float:
    rec = get_scale(d, name)
    if rec is None or not rec["paper"] or not rec["drawing"]:
        return 1.0
    return rec["drawing"] / rec["paper"]


def is_annotative(ent) -> bool:
    return bool(ent.annotation_scales)


def capable(ent) -> bool:
    return ent.kind in CAPABLE


def scale_in_use(d, name) -> bool:
    key = str(name).casefold()
    return any(str(s).casefold() == key for e in d.ents.values() for s in e.annotation_scales)


def add_scale(d, name: str, paper: float, drawing: float) -> dict:
    nm = str(name).strip()
    if not 1 <= len(nm) <= MAX_NAME:
        raise AnnotationError("The scale name must be 1 to %d characters." % MAX_NAME)
    if not (paper > 0 and drawing > 0):
        raise AnnotationError("Both scale units must be positive.")
    if d.tables["scales"].has(nm):
        raise AnnotationError("The scale name %s already exists." % nm)
    if len(d.tables["scales"]) >= MAX_SCALES:
        raise AnnotationError("The scale list is full.")
    rec = {"name": nm, "paper": float(paper), "drawing": float(drawing)}
    d.table_set("scales", rec)
    return rec


def delete_scale(d, name: str) -> None:
    rec = get_scale(d, name)
    if rec is None:
        raise AnnotationError("Scale %s is not in the list." % name)
    if rec["name"].casefold() == current_name(d).casefold():
        raise AnnotationError("The current scale cannot be deleted.")
    if scale_in_use(d, rec["name"]):
        raise AnnotationError("Scale %s is used by annotative objects." % rec["name"])
    d.table_remove("scales", rec["name"])


def reset_scales(d, metric=None) -> int:
    metric = d.metric if metric is None else bool(metric)
    keep = [r for r in d.tables["scales"].values() if scale_in_use(d, r["name"]) or r["name"].casefold() == current_name(d).casefold()]
    for r in list(d.tables["scales"].values()):
        d.table_remove("scales", r["name"])
    for r in T.scale_records(metric):
        d.table_set("scales", r)
    for r in keep:
        if not d.tables["scales"].has(r["name"]):
            d.table_set("scales", r)
    return len(d.tables["scales"])


def _style_flag(d, table: str, name) -> bool:
    rec = d.table_get(table, str(name)) if name else None
    if not rec:
        return False
    if rec.get("annotative"):
        return True
    return bool((rec.get("vars") or {}).get("DIMANNO"))


def style_annotative(d, ent) -> bool:
    k = ent.kind
    if k in ("text", "mtext"):
        return _style_flag(d, "textstyles", ent.style)
    if k == "dimension":
        return _style_flag(d, "dimstyles", ent.style)
    if k == "mleader":
        return _style_flag(d, "mleaderstyles", ent.style)
    if k == "insert":
        rec = d.table_get("blocks", ent.block)
        return bool(rec and rec.get("annotative"))
    return False


def stamp_new(d, ent) -> None:
    if ent.annotation_scales or not capable(ent):
        return
    if style_annotative(d, ent):
        ent.annotation_scales = [current_name(d)]


def add_scale_to(ent, name: str) -> bool:
    if not ent.annotation_scales or any(str(s).casefold() == str(name).casefold() for s in ent.annotation_scales):
        return False
    ent.annotation_scales = list(ent.annotation_scales) + [str(name)]
    return True


def remove_scale_from(ent, name: str) -> str:
    keys = [str(s).casefold() for s in ent.annotation_scales]
    if not keys:
        return "plain"
    if str(name).casefold() not in keys:
        return "absent"
    if len(keys) == 1:
        return "only"
    i = keys.index(str(name).casefold())
    gone = ent.annotation_scales[i]
    ent.annotation_scales = [s for s in ent.annotation_scales if s != gone]
    offs = ent.extra.get(OFFSETS_KEY)
    if offs and gone in offs:
        ent.extra = {**ent.extra, OFFSETS_KEY: {k: v for k, v in offs.items() if k != gone}}
    return "removed"


def offsets_of(ent) -> dict:
    return ent.extra.get(OFFSETS_KEY) or {}


def shift_representation(d, handle: int, vec, scale=None) -> bool:
    ent = d.modify(handle)
    name = scale or current_name(d)
    if not ent.annotation_scales or not any(str(s).casefold() == str(name).casefold() for s in ent.annotation_scales):
        return False
    key = next(s for s in ent.annotation_scales if str(s).casefold() == str(name).casefold())
    offs = dict(offsets_of(ent))
    old = offs.get(key, [0.0, 0.0])
    offs[key] = [old[0] + float(vec[0]), old[1] + float(vec[1])]
    ent.extra = {**ent.extra, OFFSETS_KEY: offs}
    return True


def reset_positions(d, handle: int) -> bool:
    ent = d.get(handle)
    if ent is None or not offsets_of(ent):
        return False
    ent = d.modify(handle)
    extra = dict(ent.extra)
    extra.pop(OFFSETS_KEY, None)
    ent.extra = extra
    return True


def display_scale(d, ent):
    if not ent.annotation_scales:
        return None
    cur = current_name(d)
    for s in ent.annotation_scales:
        if str(s).casefold() == cur.casefold():
            return s
    if int(d.header.get("ANNOALLVISIBLE", 1)):
        return ent.annotation_scales[0]
    return False


def _scaled_columns(cols: dict, f: float) -> dict:
    out = copy.deepcopy(cols)
    for k, v in list(out.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and any(w in k for w in ("gutter", "height", "width")):
            out[k] = v * f
        elif isinstance(v, list) and any(w in k for w in ("height", "heights")):
            out[k] = [x * f if isinstance(x, (int, float)) else x for x in v]
    return out


def display_entity(ctx, e):
    if not e.annotation_scales or not capable(e) or e.owner != "model":
        return e
    d = ctx.d
    which = display_scale(d, e)
    if which is False:
        return None
    if which is None:
        return e
    f = factor(d, which) if e.owner == "model" else 1.0
    off = offsets_of(e).get(which)
    if f == 1.0 and not off:
        return e
    c = e.copy_as_new()
    c.handle = e.handle
    c.owner = e.owner
    if off:
        c.move_by([off[0], off[1], 0.0])
    k = e.kind
    if k in ("text", "mtext"):
        rec = dict(ctx.textstyle(e.style))
        if rec.get("height"):
            rec["height"] = float(rec["height"]) * f
        name = "%s\x00%g" % (e.style, f)
        ctx.style_cache[name.casefold()] = rec
        c.style = name
        c.height = float(e.height) * f
        if k == "mtext":
            c.width = float(e.width) * f
            c.columns = _scaled_columns(e.columns or {}, f)
    elif k == "dimension":
        style = d.table_get("dimstyles", e.style) or {}
        base = float(e.overrides.get("DIMSCALE", (style.get("vars") or {}).get("DIMSCALE", 1.0)) or 1.0)
        c.overrides = {**e.overrides, "DIMSCALE": base * f}
        c.marks = {**e.marks, "regen": True}
    elif k == "insert":
        c.scale = [float(s) * f for s in e.scale]
    elif k == "hatch":
        if not e.solid and str(e.pattern).upper() != "SOLID":
            c.pattern_scale = float(e.pattern_scale) * f
    elif k == "mleader":
        c.anno_factor = f
    return c


def on_scale_changed(doc, name: str) -> int:
    d = doc.drawing
    if int(d.header.get("ANNOAUTOSCALE", -4)) <= 0:
        return 0
    n = 0
    for e in list(d.ents.values()):
        if e.owner != "model" or not e.annotation_scales or not d.layer_visible(e.layer) or d.layer_locked(e.layer):
            continue
        if any(str(s).casefold() == str(name).casefold() for s in e.annotation_scales):
            continue
        ent = d.modify(e.handle)
        add_scale_to(ent, name)
        n += 1
    return n


def update_annotative(d, ent) -> str:
    if not capable(ent) or ent.kind == "hatch":
        return ""
    want = style_annotative(d, ent)
    have = bool(ent.annotation_scales)
    if want and not have:
        ent.annotation_scales = [current_name(d)]
        return "on"
    if have and not want:
        ent.annotation_scales = []
        extra = dict(ent.extra)
        extra.pop(OFFSETS_KEY, None)
        ent.extra = extra
        return "off"
    return ""
