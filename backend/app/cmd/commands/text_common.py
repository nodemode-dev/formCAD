import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.display import shapes
from app.display.resolve import Context as DisplayContext
from app.display.state import session_values
from app.doc.entities import MText, Text

PITCH = 5.0 / 3.0
MAX_TEXT = 4096
MAX_CONTENTS = 1000000

JUSTIFY = {
    "Left": (0, 0, "Specify start point of text"),
    "Center": (1, 0, "Specify center point of text"),
    "Right": (2, 0, "Specify right endpoint of text baseline"),
    "Align": (3, 0, "Specify first endpoint of text baseline"),
    "Middle": (4, 0, "Specify middle point of text"),
    "Fit": (5, 0, "Specify first endpoint of text baseline"),
    "TL": (0, 3, "Specify top-left point of text"),
    "TC": (1, 3, "Specify top-center point of text"),
    "TR": (2, 3, "Specify top-right point of text"),
    "ML": (0, 2, "Specify middle-left point of text"),
    "MC": (1, 2, "Specify middle-center point of text"),
    "MR": (2, 2, "Specify middle-right point of text"),
    "BL": (0, 1, "Specify bottom-left point of text"),
    "BC": (1, 1, "Specify bottom-center point of text"),
    "BR": (2, 1, "Specify bottom-right point of text"),
}
JUSTIFY_WORDS = {
    "l": "Left", "left": "Left", "c": "Center", "center": "Center", "centre": "Center", "r": "Right", "right": "Right", "a": "Align", "align": "Align",
    "m": "Middle", "middle": "Middle", "f": "Fit", "fit": "Fit", "tl": "TL", "tc": "TC", "tr": "TR", "ml": "ML", "mc": "MC", "mr": "MR", "bl": "BL", "bc": "BC", "br": "BR",
}
ATTACH = {"TL": 1, "TC": 2, "TR": 3, "ML": 4, "MC": 5, "MR": 6, "BL": 7, "BC": 8, "BR": 9}
ATTACH_NAMES = {v: k for k, v in ATTACH.items()}
TEXT_KINDS = ("text", "mtext", "attdef", "dimension")
BAD_NAME = set('<>/\\":;?*|,=`')


def style_record(ctx, name=None):
    d = ctx.d
    want = name or d.header.get("TEXTSTYLE", "Standard")
    return d.table_get("textstyles", want) or d.table_get("textstyles", "Standard") or {"name": "Standard", "height": 0.0, "annotative": False}


def default_height(ctx):
    v = ctx.d.header.get("TEXTSIZE")
    try:
        v = float(v)
    except (TypeError, ValueError):
        v = 0.0
    if v <= 0:
        v = 2.5 if ctx.d.metric else 0.2
    return v


def echo(ctx, rec, justify="Left"):
    ctx.say('Current text style: "%s"  Text height: %s  Annotative: %s' % (rec["name"], ctx.fd(rec["height"] or default_height(ctx)), "Yes" if rec.get("annotative") else "No"))
    if justify:
        ctx.say("Justify: %s" % justify)


def check_name(name):
    n = str(name).strip()
    if not n or len(n) > 255 or any(c in BAD_NAME for c in n) or any(ord(c) < 32 for c in n):
        raise CommandError("Invalid text style name.")
    return n


def check_text(text, limit=MAX_TEXT):
    t = str(text)
    if len(t) > limit:
        raise CommandError("Text is too long.")
    return t


def display_context(ctx):
    return DisplayContext(ctx.doc, session_values())


def shape_of(ctx, ent):
    return shapes.build(ent, display_context(ctx))


def preview_item(ctx, ent):
    try:
        g, prims, _grips, bounds = shape_of(ctx, ent)
    except Exception:
        return None
    it = jig.item(g, "text")
    it["prims"] = prims
    if bounds:
        it["bounds"] = list(bounds)
    return it


def settle_insertion(ctx, handle):
    ent = ctx.d.modify(handle)
    if ent.kind != "text" or ent.align_point is None or int(ent.halign) in (3, 5):
        return
    g = shape_of(ctx, ent)[0]
    ent.position = [float(g["insert"][0]), float(g["insert"][1]), 0.0]


def annotative_scales(ctx, rec):
    if rec.get("annotative"):
        return [str(ctx.var("CANNOSCALE"))]
    return []


def frame(rot):
    c, s = math.cos(rot), math.sin(rot)
    return (c, s), (-s, c)


def shifted(p, v):
    return [p[0] + v[0], p[1] + v[1], p[2] if len(p) > 2 else 0.0]


def new_text(ctx, text, pos, align, height, rot, style, halign, valign):
    rec = style_record(ctx, style)
    ent = Text(position=[pos[0], pos[1], 0.0], align_point=([align[0], align[1], 0.0] if align is not None else None), height=float(height), text=text, rotation=float(rot), style=rec["name"], halign=int(halign), valign=int(valign))
    ent.annotation_scales = annotative_scales(ctx, rec)
    return ent


def mtext_props(ent):
    return {
        "position": [float(ent.position[0]), float(ent.position[1])],
        "height": float(ent.height),
        "width": float(ent.width),
        "attachment": int(ent.attachment),
        "rotation": float(ent.rotation),
        "style": ent.style,
        "line_spacing": float(ent.line_spacing),
        "exact": int(ent.line_spacing_style) == 2,
        "columns": dict(ent.columns or {}),
    }


def apply_mtext_props(ctx, ent, props):
    if "position" in props and props["position"] is not None:
        p = props["position"]
        ent.position = [float(p[0]), float(p[1]), 0.0]
    if props.get("height") is not None:
        h = float(props["height"])
        if not h > 0 or not math.isfinite(h):
            raise CommandError("Height must be positive.")
        ent.height = h
    if props.get("width") is not None:
        w = float(props["width"])
        if w < 0 or not math.isfinite(w):
            raise CommandError("Width must not be negative.")
        ent.width = w
    att = props.get("attachment", props.get("justify"))
    if att is not None:
        if isinstance(att, str):
            key = att.strip().upper()
            if key not in ATTACH:
                raise CommandError("Invalid justification.")
            att = ATTACH[key]
        att = int(att)
        if not 1 <= att <= 9:
            raise CommandError("Attachment must be 1 to 9.")
        ent.attachment = att
    if props.get("rotation") is not None:
        ent.rotation = math.radians(float(props["rotation"])) if props.get("degrees", True) else float(props["rotation"])
    if props.get("style"):
        rec = ctx.d.table_get("textstyles", str(props["style"]))
        if rec is None:
            raise CommandError("Text style %s not found." % props["style"])
        ent.style = rec["name"]
        ent.annotation_scales = annotative_scales(ctx, rec)
    if props.get("line_spacing") is not None:
        f = float(props["line_spacing"])
        if not 0.25 <= f <= 4.0:
            raise CommandError("Requires a spacing between 0.25x and 4x.")
        ent.line_spacing = f
    if props.get("exact") is not None:
        ent.line_spacing_style = 2 if props["exact"] else 1
    cols = props.get("columns")
    if cols is not None:
        ent.columns = clean_columns(cols)


def clean_columns(cols):
    if not cols:
        return {}
    kind = str(cols.get("type", "none")).lower()
    if kind in ("none", "no", ""):
        return {}
    if kind not in ("static", "dynamic"):
        raise CommandError("Column type must be static, dynamic or none.")
    out = {"type": kind, "count": int(cols.get("count", 2 if kind == "static" else 0)), "gutter": float(cols.get("gutter", 0.0)), "height": float(cols.get("height", 0.0)), "heights": [float(v) for v in cols.get("heights", [])], "reversed": bool(cols.get("reversed", False))}
    if out["count"] < 0 or out["count"] > 16 or out["gutter"] < 0 or out["height"] < 0:
        raise CommandError("Invalid column settings.")
    return out


def list_prefix(props, height):
    kind = props.get("list")
    indent = float(props.get("indent", 3.0 if kind else 0.0)) * height
    first = float(props.get("first_indent", -(3.0 if kind else 0.0))) * height
    right = float(props.get("right_indent", 0.0)) * height
    tabs = [float(t) * height for t in props.get("tabs", [])]
    align = props.get("alignment")
    parts = []
    if first:
        parts.append("i%g" % first)
    if indent:
        parts.append("l%g" % indent)
    if right:
        parts.append("r%g" % right)
    if align:
        code = {"left": "l", "center": "c", "right": "r", "justify": "j", "distributed": "d"}.get(str(align).lower())
        if code is None:
            raise CommandError("Alignment must be left, center, right, justify or distributed.")
        parts.append("q" + code)
    if kind and not tabs:
        tabs = [indent]
    if tabs:
        parts.append("t" + ",".join("%g" % t for t in tabs))
    return ("\\p" + ",".join(parts) + ";") if parts else ""


def letters(n, upper):
    s = ""
    n += 1
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(97 + r) + s
    return s.upper() if upper else s


def label_for(kind, k):
    if kind == "bullet":
        return "•"
    if kind == "number":
        return "%d." % (k + 1)
    if kind == "lower":
        return letters(k, False) + "."
    if kind == "upper":
        return letters(k, True) + "."
    raise CommandError("List must be bullet, number, lower or upper.")


def compose_contents(text, props, height):
    lines = str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n")
    kind = props.get("list")
    if kind:
        lines = ["%s\t%s" % (label_for(kind, k), ln) for k, ln in enumerate(lines)]
    body = "\\P".join(lines)
    return list_prefix(props, height) + body


def create_mtext(ctx, contents, props):
    c = check_text(contents, MAX_CONTENTS)
    if not c.strip():
        raise CommandError("Text is empty.")
    ent = MText()
    ent.style = style_record(ctx)["name"]
    ent.height = default_height(ctx)
    apply_mtext_props(ctx, ent, props)
    ent.contents = c
    ent.annotation_scales = annotative_scales(ctx, style_record(ctx, ent.style))
    return ctx.add(ent)


def first_line(text, limit=40):
    t = str(text).replace("\n", " ")
    return t[:limit]


def is_outline(font):
    from app.text import fonts

    try:
        return not fonts.resolve(font).is_stroke
    except Exception:
        return False


def style_rows(ctx, pattern="*"):
    import fnmatch

    cur = str(ctx.d.header.get("TEXTSTYLE", "Standard")).casefold()
    rows = []
    for rec in sorted(ctx.d.tables["textstyles"].values(), key=lambda r: r["name"].casefold()):
        if not fnmatch.fnmatchcase(rec["name"].casefold(), str(pattern).casefold()):
            continue
        rows.append(
            {
                "name": rec["name"],
                "font": rec.get("font", "txt"),
                "big_font": rec.get("big_font", ""),
                "outline": is_outline(rec.get("font", "txt")),
                "current": rec["name"].casefold() == cur,
                "height": float(rec.get("height", 0.0)),
                "width_factor": float(rec.get("width_factor", 1.0)),
                "oblique": math.degrees(float(rec.get("oblique", 0.0))),
                "backwards": bool(rec.get("backwards")),
                "upside_down": bool(rec.get("upside_down")),
                "vertical": bool(rec.get("vertical")),
                "annotative": bool(rec.get("annotative")),
            }
        )
    return rows


def say_styles(ctx, pattern="*"):
    rows = style_rows(ctx, pattern)
    if not rows:
        ctx.say("No matching text styles.")
    for r in rows:
        ctx.say("%-24s %-28s %-8s %s" % (r["name"], r["font"], "outline" if r["outline"] else "stroke", "current" if r["current"] else ""))
    return rows
