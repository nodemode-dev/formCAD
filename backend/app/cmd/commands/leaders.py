import math

from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc.entities import Insert, MText, Text
from app.doc.kinds.leader import Leader

HOOK_LIMIT = math.radians(15.0)
ANNOTATION_OPTIONS = ["Tolerance", "Copy", "Block", "None", "Mtext"]


def user_blocks(ctx) -> list:
    return [r["name"] for r in ctx.d.tables["blocks"].values() if not r.get("anonymous") and not r["name"].startswith("*")]


def dim_numbers(ctx) -> dict:
    scale = float(ctx.var("DIMSCALE")) or 1.0
    return {"arrow": float(ctx.var("DIMASZ")) * scale, "gap": float(ctx.var("DIMGAP")) * scale, "text": float(ctx.var("DIMTXT")) * scale, "tad": int(ctx.var("DIMTAD"))}


def hook_needed(pts, spline: bool) -> bool:
    if spline or len(pts) < 2:
        return False
    a, b = pts[-2], pts[-1]
    ang = abs(math.atan2(b[1] - a[1], b[0] - a[0])) % math.pi
    ang = min(ang, math.pi - ang)
    return ang > HOOK_LIMIT


def run_side(pts) -> float:
    a, b = pts[-2], pts[-1]
    return 1.0 if b[0] - a[0] >= 0 else -1.0


def leader_path(ctx, pts, spline: bool, hook: bool) -> list:
    out = [[p[0], p[1], 0.0] for p in pts]
    if hook and hook_needed(pts, spline):
        n = dim_numbers(ctx)
        side = run_side(pts)
        out.append([pts[-1][0] + side * n["arrow"], pts[-1][1], 0.0])
    return out


def leader_preview(ctx, pts, q, spline):
    path = [[p[0], p[1]] for p in pts] + [[q[0], q[1]]]
    return [jig.poly([[p[0], p[1], 0.0] for p in path])]


def make_leader(ctx, pts, spline: bool, arrow: bool, hook: bool) -> Leader:
    n = dim_numbers(ctx)
    path = leader_path(ctx, pts, spline, hook)
    return Leader(points=path, arrowhead=bool(arrow), spline=bool(spline), style=str(ctx.d.header.get("DIMSTYLE", "Standard")), arrow_size=n["arrow"])


def text_style_name(ctx) -> str:
    name = str(ctx.var("DIMTXSTY"))
    return name if ctx.d.table_get("textstyles", name) else "Standard"


def place_text(ctx, end, side: float):
    n = dim_numbers(ctx)
    if n["tad"] > 0:
        attach = 7 if side >= 0 else 9
        pos = [end[0] + side * n["gap"], end[1] + n["gap"], 0.0]
    else:
        attach = 4 if side >= 0 else 6
        pos = [end[0] + side * n["gap"], end[1], 0.0]
    return pos, attach, n["text"]


def add_annotation_text(ctx, end, side: float, contents: str, like=None):
    pos, attach, height = place_text(ctx, end, side)
    style = text_style_name(ctx)
    if like is not None and like.kind == "text":
        t = Text(position=pos, height=like.height, text=like.text, style=like.style, rotation=0.0, width_factor=like.width_factor, oblique=like.oblique, halign=0, valign=0)
        return ctx.add(t)
    if like is not None and like.kind == "mtext":
        m = MText(position=pos, height=like.height, width=like.width, attachment=attach, style=like.style, contents=like.contents, line_spacing=like.line_spacing, line_spacing_style=like.line_spacing_style)
        return ctx.add(m)
    return ctx.add(MText(position=pos, height=height, attachment=attach, style=style, contents=contents))


def add_annotation_block(ctx, end, name: str, sx: float, sy: float, rot: float, base):
    pos = [end[0] - (base[0] if base else 0.0) * sx, end[1] - (base[1] if base else 0.0) * sy, 0.0]
    ins = Insert(block=name, position=pos, scale=[sx, sy, sx], rotation=rot)
    return ctx.add(ins)


def finish_leader(ctx, pts, spline, arrow, annotation):
    kind = annotation[0] if annotation else "none"
    hook = kind in ("text", "copy")
    ent = make_leader(ctx, pts, spline, arrow, hook)
    ctx.add(ent)
    end = ent.points[-1]
    side = run_side(ent.points)
    if kind == "text" and annotation[1]:
        add_annotation_text(ctx, end, side, "\\P".join(annotation[1]))
    elif kind == "copy":
        add_annotation_text(ctx, end, side, "", annotation[1])
    elif kind == "block":
        name, sx, sy, rot, base = annotation[1]
        add_annotation_block(ctx, end, name, sx, sy, rot, base)
    return ent


def ask_format(ctx, mem):
    while True:
        r = yield ctx.keyword("Enter leader format option", ["Spline", "STraight", "Arrow", "None", "eXit"], "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return
        if r.value == "Spline":
            mem["spline"] = True
        elif r.value == "STraight":
            mem["spline"] = False
        elif r.value == "Arrow":
            mem["arrow"] = True
        else:
            mem["arrow"] = False
        return


def ask_block(ctx):
    while True:
        r = yield ctx.word("Enter block name")
        if r.kind != "text":
            return None
        name = str(r.value).strip()
        if name == "?":
            ctx.say("Blocks: " + (", ".join(user_blocks(ctx)) or "none"))
            continue
        rec = ctx.d.table_get("blocks", name)
        if rec is None or rec.get("anonymous"):
            ctx.say('Block "%s" not found.' % name)
            continue
        break
    sx = sy = 1.0
    rot = 0.0
    base = None
    while True:
        r = yield ctx.number("Enter X scale factor, specify opposite corner", ["Basepoint", "Scale", "X", "Y", "Z", "Rotate"], default=1.0)
        if r.kind == "enter" or (r.kind == "number" and r.from_default):
            break
        if r.kind == "number":
            if r.value == 0:
                ctx.say("Requires a nonzero number.")
                continue
            sx = float(r.value)
            y = yield ctx.number("Enter Y scale factor", default=sx, default_text="use X scale factor")
            sy = sx if y.kind != "number" else float(y.value)
            if sy == 0:
                ctx.say("Requires a nonzero number.")
                sy = sx
            break
        if r.kind != "keyword":
            break
        if r.value == "Basepoint":
            b = yield ctx.point("Specify base point")
            if b.kind == "point":
                base = [b.value[0], b.value[1]]
        elif r.value in ("Scale", "X", "Y"):
            v = yield ctx.number("Enter %s scale factor" % ("overall" if r.value == "Scale" else r.value), default=1.0)
            if v.kind == "number" and v.value != 0:
                if r.value == "Scale":
                    sx = sy = float(v.value)
                elif r.value == "X":
                    sx = float(v.value)
                else:
                    sy = float(v.value)
            elif v.kind == "number":
                ctx.say("Requires a nonzero number.")
        elif r.value == "Z":
            yield ctx.number("Enter Z scale factor", default=1.0)
        else:
            a = yield ctx.angle("Specify rotation angle", default=0.0)
            if a.kind == "number":
                rot = float(a.value)
        continue
    a = yield ctx.angle("Specify rotation angle", default=rot)
    if a.kind == "number":
        rot = float(a.value)
    return (rec["name"], sx, sy, rot, base)


def ask_annotation(ctx):
    lines = []
    while True:
        if not lines:
            r = yield ctx.text("Enter first line of annotation text or", default="options")
            if r.kind == "text" and r.value == "options" and r.from_default:
                o = yield ctx.keyword("Enter an annotation option", ANNOTATION_OPTIONS, "Mtext")
                val = o.value if o.kind == "keyword" else "Mtext"
                if val in ("Mtext", "Tolerance"):
                    ctx.say("The editor cannot open at the command line; type the text instead.")
                    continue
                if val == "None":
                    return ("none", None)
                if val == "Copy":
                    p = yield ctx.entity("Select an object to copy")
                    src = pick_entity(ctx, p.value) if p.kind == "entity" else None
                    if src is None or src.kind not in ("text", "mtext"):
                        ctx.say("The object is not text.")
                        continue
                    return ("copy", src)
                got = yield from ask_block(ctx)
                if got is None:
                    continue
                return ("block", got)
            if r.kind != "text":
                return ("none", None)
            lines.append(str(r.value))
        else:
            r = yield ctx.text("Enter next line of annotation text")
            if r.kind != "text":
                break
            lines.append(str(r.value))
    return ("text", lines)


@command("leader", aliases=("lead",), group="annotation", label="Leader", description="Command-line leader with annotation text, block, copy or none.", menu="Dimension > Leader")
def leader_cmd(ctx):
    mem = ctx.mem.setdefault("leader", {"spline": False, "arrow": True})
    p0 = yield ctx.point("Specify leader start point")
    if p0.kind != "point":
        return
    pts = [[p0.value[0], p0.value[1]]]
    while len(pts) < 2:
        p = yield ctx.point("Specify next point", base=pts[-1], jig=lambda q: leader_preview(ctx, pts, q, mem["spline"]))
        if p.kind != "point":
            return
        if geom.dist(p.value, pts[-1]) > ctx.d.tolerances["absolute"]:
            pts.append([p.value[0], p.value[1]])
    annotation = None
    while annotation is None:
        r = yield ctx.point("Specify next point", ["Annotation", "Format", "Undo"], base=pts[-1], default_text="Annotation", jig=lambda q: leader_preview(ctx, pts, q, mem["spline"]))
        if r.kind == "point":
            if geom.dist(r.value, pts[-1]) > ctx.d.tolerances["absolute"]:
                pts.append([r.value[0], r.value[1]])
            continue
        if r.kind == "keyword" and r.value == "Format":
            yield from ask_format(ctx, mem)
            continue
        if r.kind == "keyword" and r.value == "Undo":
            if len(pts) > 2:
                pts.pop()
            else:
                ctx.say("Nothing to undo.")
            continue
        annotation = yield from ask_annotation(ctx)
    finish_leader(ctx, pts, mem["spline"], mem["arrow"], annotation)


@executes("leader")
def leader_exec(ctx, args):
    pts = [geom.as_pt(p) for p in args.get("points", [])]
    clean = []
    for p in pts:
        if not clean or geom.dist(p, clean[-1]) > ctx.d.tolerances["absolute"]:
            clean.append([p[0], p[1]])
    if len(clean) < 2:
        raise CommandError("A leader needs at least two distinct points.")
    spline = bool(args.get("spline", False))
    arrow = bool(args.get("arrow", True))
    annotation = ("none", None)
    if args.get("block"):
        b = args["block"]
        name = b["name"] if isinstance(b, dict) else str(b)
        rec = ctx.d.table_get("blocks", name)
        if rec is None or rec.get("anonymous"):
            raise CommandError('Block "%s" not found.' % name)
        sx = float(b.get("scale", b.get("sx", 1.0))) if isinstance(b, dict) else 1.0
        sy = float(b.get("sy", sx)) if isinstance(b, dict) else sx
        if sx == 0 or sy == 0:
            raise CommandError("Requires a nonzero number.")
        annotation = ("block", (rec["name"], sx, sy, float(b.get("rotation", 0.0)) if isinstance(b, dict) else 0.0, None))
    elif args.get("copy") is not None:
        src = ctx.d.get(int(args["copy"]))
        if src is None or src.kind not in ("text", "mtext"):
            raise CommandError("The object is not text.")
        annotation = ("copy", src)
    elif args.get("lines") or args.get("text"):
        lines = [str(x) for x in args["lines"]] if args.get("lines") else [str(args["text"])]
        annotation = ("text", lines)
    ent = finish_leader(ctx, clean, spline, arrow, annotation)
    return {"points": ent.points, "arrowhead": ent.arrowhead, "spline": ent.spline}
