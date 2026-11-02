import math

from app.cmd import jig
from app.cmd.commands import text_common as tc
from app.cmd.commands.draw import anum, dnum
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom

JUSTIFY_OPTIONS = ["Left", "Center", "Right", "Align", "Middle", "Fit", "TL", "TC", "TR", "ML", "MC", "MR", "BL", "BC", "BR"]
ATTACH_OPTIONS = ["TL", "TC", "TR", "ML", "MC", "MR", "BL", "BC", "BR"]


def _ask_style(ctx):
    while True:
        r = yield ctx.text("Enter style name or [?]", str(ctx.d.header.get("TEXTSTYLE", "Standard")))
        if r.kind != "text":
            return None
        name = str(r.value).strip()
        if name == "?":
            p = yield ctx.text("Enter text style(s) to list", "*")
            tc.say_styles(ctx, str(p.value) if p.kind == "text" else "*")
            continue
        rec = ctx.d.table_get("textstyles", name)
        if rec is None:
            ctx.say('Style "%s" not found.' % name)
            continue
        return rec["name"]


def _ask_justify(ctx):
    p = ctx.keyword("Enter an option", JUSTIFY_OPTIONS)
    p.hint = "bare"
    r = yield p
    return r.value if r.kind == "keyword" else None


def _tick(ctx, rec, rot=0.0):
    h = rec["height"] or tc.default_height(ctx)
    u, _v = tc.frame(rot)
    return lambda p: [jig.line(p, [p[0] + u[0] * h, p[1] + u[1] * h])]


def _ask_height(ctx, rec, base):
    if rec["height"]:
        return rec["height"]
    default = tc.default_height(ctx)
    r = yield ctx.distance("Specify height", base=base, default=default, positive=True, jig=lambda p: jig.rubber(base, p))
    if r.kind == "enter":
        return default
    v = dnum(r, base)
    if v is None:
        return None
    if r.kind == "number" and not r.from_default:
        ctx.d.set_header("TEXTSIZE", float(v))
    return float(v)


def _line_vector(rot, h):
    _u, v = tc.frame(rot)
    return (v[0] * -tc.PITCH * h, v[1] * -tc.PITCH * h)


def _continue_spec(ctx):
    last = ctx.d.get(ctx.mem.get("last_text", 0))
    if last is None or last.kind != "text":
        return None
    g = tc.shape_of(ctx, last)[0]
    h = float(g.get("height", last.height))
    vec = _line_vector(last.rotation, h)
    return {
        "pos": tc.shifted(last.position, vec),
        "ap": tc.shifted(last.align_point, vec) if last.align_point is not None else None,
        "height": last.height,
        "rot": last.rotation,
        "style": last.style,
        "ha": last.halign,
        "va": last.valign,
    }


@command("text", aliases=("dt", "dtext"), group="draw", label="Single Line Text", description="Single-line text with justification, height, rotation, repeating lines.", menu="Draw > Text > Single Line Text")
def text(ctx):
    rec = tc.style_record(ctx)
    just = "Left"
    tc.echo(ctx, rec, just)
    spec = None
    while spec is None:
        rec = tc.style_record(ctx)
        msg = tc.JUSTIFY[just][2]
        r = yield ctx.point(msg, ["Justify", "Style"], jig=_tick(ctx, rec))
        if r.kind == "keyword" and r.value == "Style":
            name = yield from _ask_style(ctx)
            if name:
                ctx.setvar("TEXTSTYLE", name)
                tc.echo(ctx, tc.style_record(ctx), just)
            continue
        if r.kind == "keyword":
            got = yield from _ask_justify(ctx)
            if got:
                just = got
            continue
        if r.kind == "enter":
            spec = _continue_spec(ctx)
            if spec is None:
                return
            break
        if r.kind != "point":
            return
        p1 = r.value
        ha, va, _m = tc.JUSTIFY[just]
        ap = None
        pos = p1
        rot = 0.0
        height = None
        if just in ("Align", "Fit"):
            second = yield ctx.point("Specify second endpoint of text baseline", base=p1, jig=lambda p: jig.rubber(p1, p))
            if second.kind != "point":
                return
            if geom.dist(p1, second.value) < ctx.d.tolerances["absolute"]:
                ctx.say("The endpoints must differ.")
                continue
            ap = second.value
            rot = geom.angle_of(p1, ap)
            height = rec["height"] or tc.default_height(ctx)
            if just == "Fit":
                got = yield from _ask_height(ctx, rec, p1)
                if got is None:
                    return
                height = got
        else:
            if just != "Left":
                ap = p1
            got = yield from _ask_height(ctx, rec, p1)
            if got is None:
                return
            height = got
            a = yield ctx.angle("Specify rotation angle of text", default=0.0, base=p1, jig=lambda p: jig.rubber(p1, p))
            if a.kind == "enter":
                rot = 0.0
            else:
                v = anum(a, p1)
                if v is None:
                    return
                rot = float(v)
        spec = {"pos": pos, "ap": ap, "height": height, "rot": rot, "style": rec["name"], "ha": ha, "va": va}
    while True:
        t = yield ctx.text("Enter text")
        if t.kind != "text":
            return
        try:
            body = tc.check_text(t.value)
        except CommandError as err:
            ctx.say(str(err))
            continue
        ent = tc.new_text(ctx, body, spec["pos"], spec["ap"], spec["height"], spec["rot"], spec["style"], spec["ha"], spec["va"])
        h = ctx.add(ent)
        tc.settle_insertion(ctx, h)
        ctx.mem["last_text"] = h
        g = tc.shape_of(ctx, ctx.d.get(h))[0]
        vec = _line_vector(spec["rot"], float(g.get("height", spec["height"])))
        spec["pos"] = tc.shifted(spec["pos"], vec)
        if spec["ap"] is not None:
            spec["ap"] = tc.shifted(spec["ap"], vec)


def _justify_code(value):
    key = str(value or "L").strip().lower()
    got = tc.JUSTIFY_WORDS.get(key)
    if got is None:
        raise CommandError("Invalid justification.")
    return got


@executes("text")
def text_exec(ctx, args):
    body = args.get("text")
    if not isinstance(body, str) or not body.strip():
        raise CommandError("Text is required.")
    style = args.get("style")
    rec = ctx.d.table_get("textstyles", str(style)) if style else tc.style_record(ctx)
    if rec is None:
        raise CommandError("Text style %s not found." % style)
    height = args.get("height")
    height = float(height) if height is not None else (rec["height"] or tc.default_height(ctx))
    if not height > 0 or not math.isfinite(height):
        raise CommandError("Height must be positive.")
    just = _justify_code(args.get("justify"))
    ha, va, _m = tc.JUSTIFY[just]
    if "point" not in args:
        raise CommandError("An insertion point is required.")
    pos = geom.as_pt(args["point"])
    ap = None
    rot = math.radians(float(args.get("rotation", 0.0)))
    if just in ("Align", "Fit"):
        if "point2" not in args:
            raise CommandError("A second point is required.")
        ap = geom.as_pt(args["point2"])
        if geom.dist(pos, ap) < ctx.d.tolerances["absolute"]:
            raise CommandError("The endpoints must differ.")
        rot = geom.angle_of(pos, ap)
    elif just != "Left":
        ap = pos
    handles = []
    for line in body.replace("\r\n", "\n").split("\n"):
        ent = tc.new_text(ctx, tc.check_text(line), pos, ap, height, rot, rec["name"], ha, va)
        ent.width_factor = float(args.get("width_factor", 1.0))
        ent.oblique = math.radians(float(args.get("oblique", 0.0)))
        h = ctx.add(ent)
        tc.settle_insertion(ctx, h)
        handles.append(h)
        g = tc.shape_of(ctx, ctx.d.get(h))[0]
        vec = _line_vector(rot, float(g.get("height", height)))
        pos = tc.shifted(pos, vec)
        if ap is not None:
            ap = tc.shifted(ap, vec)
    ctx.mem["last_text"] = handles[-1]
    return {"handle": handles[0], "handles": handles}


def box_from_corners(p1, p2, rot, attach):
    u, v = tc.frame(rot)
    dx = (p2[0] - p1[0]) * u[0] + (p2[1] - p1[1]) * u[1]
    dy = (p2[0] - p1[0]) * v[0] + (p2[1] - p1[1]) * v[1]
    x0, x1 = min(0.0, dx), max(0.0, dx)
    y0, y1 = min(0.0, dy), max(0.0, dy)
    col = (attach - 1) % 3
    row = (attach - 1) // 3
    x = (x0, (x0 + x1) / 2.0, x1)[col]
    y = (y1, (y0 + y1) / 2.0, y0)[row]
    pos = [p1[0] + u[0] * x + v[0] * y, p1[1] + u[1] * x + v[1] * y, 0.0]
    corners = [[p1[0] + u[0] * a + v[0] * b, p1[1] + u[1] * a + v[1] * b] for a, b in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
    return pos, x1 - x0, corners


def _spacing(ctx, st):
    r = yield ctx.keyword("Enter line spacing type", ["At least", "Exactly"], "At least" if not st["exact"] else "Exactly")
    if r.kind != "keyword":
        return
    st["exact"] = r.value == "Exactly"
    cur = st["spacing"]
    while True:
        a = yield ctx.text("Enter line spacing factor or distance", "%gx" % cur)
        if a.kind != "text":
            return
        raw = str(a.value).strip().lower()
        try:
            if raw.endswith("x"):
                f = float(raw[:-1])
            else:
                f = float(raw) / (tc.PITCH * st["height"])
        except ValueError:
            ctx.say("Requires a spacing between 0.25x and 4x.")
            continue
        if not 0.25 <= f <= 4.0:
            ctx.say("Requires a spacing between 0.25x and 4x.")
            continue
        st["spacing"] = f
        return


def _columns(ctx, st):
    r = yield ctx.keyword("Enter column type", ["Dynamic", "Static", "No columns"], "Dynamic")
    if r.kind != "keyword":
        return
    if r.value == "No columns":
        st["columns"] = {}
        return
    if r.value == "Static":
        total = yield ctx.distance("Specify total width", positive=True)
        count = yield ctx.number("Specify number of columns", default=2, integer=True, minimum=1, maximum=16)
        gutter = yield ctx.distance("Specify gutter width", nonneg=True, default=0.0)
        ch = yield ctx.distance("Specify column height", nonneg=True, default=0.0)
        if total.kind != "number" or count.kind != "number":
            return
        n = int(count.value)
        g = float(gutter.value) if gutter.kind == "number" else 0.0
        width = (float(total.value) - g * (n - 1)) / n
        if width <= 0:
            ctx.say("The gutter leaves no room for the columns.")
            return
        st["columns"] = {"type": "static", "count": n, "gutter": g, "height": float(ch.value) if ch.kind == "number" else 0.0, "heights": [], "reversed": False}
        st["width"] = width
        return
    cw = yield ctx.distance("Specify column width", positive=True)
    gutter = yield ctx.distance("Specify gutter width", nonneg=True, default=0.0)
    ch = yield ctx.distance("Specify column height", nonneg=True, default=0.0)
    if cw.kind != "number":
        return
    st["columns"] = {"type": "dynamic", "count": 0, "gutter": float(gutter.value) if gutter.kind == "number" else 0.0, "height": float(ch.value) if ch.kind == "number" else 0.0, "heights": [], "reversed": False}
    st["width"] = float(cw.value)


@command("mtext", aliases=("t", "mt"), group="draw", label="Multiline Text", description="Multiline text in a box with height, justify, spacing, rotation, style, width, columns.", menu="Draw > Text > Multiline Text...")
def mtext(ctx):
    rec = tc.style_record(ctx)
    st = {"height": rec["height"] or tc.default_height(ctx), "attach": 1, "rot": 0.0, "style": rec["name"], "width": None, "spacing": 1.0, "exact": False, "columns": {}}
    ctx.say('Current text style: "%s"  Text height: %s  Annotative: %s' % (rec["name"], ctx.fd(st["height"]), "Yes" if rec.get("annotative") else "No"))
    p1 = yield ctx.point("Specify first corner")
    if p1.kind != "point":
        return
    a = p1.value
    box = {}

    def show(p):
        pos, w, corners = box_from_corners(a, p, st["rot"], st["attach"])
        return [jig.poly([[c[0], c[1], 0.0] for c in corners], True)]

    while True:
        r = yield ctx.point("Specify opposite corner", ["Height", "Justify", "Line spacing", "Rotation", "Style", "Width", "Columns"], base=a, rect=True, jig=show)
        if r.kind == "point":
            pos, w, _c = box_from_corners(a, r.value, st["rot"], st["attach"])
            box["pos"] = pos
            box["width"] = st["width"] if st["width"] is not None else (w if w > ctx.d.tolerances["absolute"] else 0.0)
            break
        if r.kind != "keyword":
            return
        k = r.value
        if k == "Height":
            h = yield ctx.distance("Specify height", base=a, default=st["height"], positive=True, jig=lambda p: jig.rubber(a, p))
            v = dnum(h, a)
            if v is not None and v > 0:
                st["height"] = float(v)
                if h.kind == "number" and not h.from_default:
                    ctx.d.set_header("TEXTSIZE", float(v))
        elif k == "Justify":
            j = ctx.keyword("Enter justification", ATTACH_OPTIONS, ATTACH_OPTIONS[st["attach"] - 1])
            j.hint = "bare"
            got = yield j
            if got.kind == "keyword":
                st["attach"] = tc.ATTACH[got.value]
        elif k == "Line spacing":
            yield from _spacing(ctx, st)
        elif k == "Rotation":
            ra = yield ctx.angle("Specify rotation angle", default=st["rot"], base=a, jig=lambda p: jig.rubber(a, p))
            v = anum(ra, a)
            if v is not None:
                st["rot"] = float(v)
        elif k == "Style":
            name = yield from _ask_style(ctx)
            if name:
                st["style"] = name
        elif k == "Width":
            wv = yield ctx.distance("Specify width", base=a, nonneg=True, jig=lambda p: jig.rubber(a, p))
            v = dnum(wv, a)
            if v is not None and v >= 0:
                st["width"] = float(v)
        else:
            yield from _columns(ctx, st)
    ctx.mem["mtext_pending"] = {"position": [box["pos"][0], box["pos"][1]], "height": st["height"], "width": box["width"], "attachment": st["attach"], "rotation": st["rot"], "style": st["style"]}
    lines = []
    try:
        while True:
            t = yield ctx.text("Enter text (use \\P for new paragraphs)")
            if t.kind != "text":
                break
            lines.append(str(t.value))
    finally:
        ctx.mem.pop("mtext_pending", None)
    body = "\\P".join(lines)
    if not body.strip():
        return
    props = {"position": box["pos"], "height": st["height"], "width": box["width"], "attachment": st["attach"], "rotation": math.degrees(st["rot"]), "style": st["style"], "line_spacing": st["spacing"], "exact": st["exact"], "columns": st["columns"]}
    ctx.mem["last_mtext"] = tc.create_mtext(ctx, body, props)


@executes("mtext")
def mtext_exec(ctx, args):
    body = args.get("text", args.get("contents"))
    if not isinstance(body, str) or not body.strip():
        raise CommandError("Text is required.")
    if "point" not in args:
        raise CommandError("An insertion point is required.")
    props = {k: args[k] for k in ("height", "width", "attachment", "justify", "rotation", "style", "line_spacing", "exact", "columns") if k in args}
    props["position"] = geom.as_pt(args["point"])
    height = float(props.get("height") or tc.style_record(ctx, props.get("style"))["height"] or tc.default_height(ctx))
    contents = tc.compose_contents(body, args, height)
    h = tc.create_mtext(ctx, contents, props)
    ctx.mem["last_mtext"] = h
    return {"handle": h}
