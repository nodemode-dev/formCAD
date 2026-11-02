import copy
import math

from app.cmd import jig
from app.cmd.annot_grips import move_landing
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.registry import command, executes
from app.dim import arrows
from app.doc import annotation as A
from app.doc import geom
from app.doc import tables as T
from app.doc.kinds.mleader import CONTENT_TYPES, LEADER_TYPES, MAX_POINTS, MLeader, nearest_leader

STYLE_DEFAULTS = {"arrowhead": "closed filled", "leader_type": "straight", "landing": True, "content_type": "mtext", "max_points": 2}
BAD_NAME_CHARS = '<>/\\":;?*|,=`'
NUMERIC_FIELDS = ("arrow_size", "text_height", "landing_gap", "dogleg")
ORDERS = ("arrow", "landing", "content")


def style_of(ctx, name=None):
    d = ctx.d
    rec = d.table_get("mleaderstyles", str(name if name else ctx.var("CMLEADERSTYLE")))
    if rec is None:
        vals = d.tables["mleaderstyles"].values()
        rec = d.table_get("mleaderstyles", "Standard") or (vals[0] if vals else None)
    if rec is None:
        raise CommandError("No multileader style is defined.")
    return rec


def style_value(rec, key):
    return rec.get(key, STYLE_DEFAULTS[key])


def creation_factor(ctx, style) -> float:
    if style.get("annotative") and ctx.doc.current_space == "model":
        return A.factor(ctx.d, A.current_name(ctx.d))
    return 1.0


def options_from_style(style) -> dict:
    return {"order": "arrow", "leader_type": style_value(style, "leader_type"), "landing": bool(style_value(style, "landing")), "content": style_value(style, "content_type"), "maxpoints": int(style_value(style, "max_points")), "angle1": 0.0, "angle2": 0.0, "block": "", "attach": "extents"}


def get_options(ctx, style) -> dict:
    mem = ctx.mem.get("mleader")
    if mem is None:
        mem = options_from_style(style)
        ctx.mem["mleader"] = mem
    return mem


def constrain(prev, p, inc_deg: float):
    if not inc_deg or inc_deg <= 0:
        return [p[0], p[1]]
    step = math.radians(inc_deg)
    ang = round(math.atan2(p[1] - prev[1], p[0] - prev[0]) / step) * step
    d = geom.dist(prev, p)
    return [prev[0] + d * math.cos(ang), prev[1] + d * math.sin(ang)]


def build_mleader(ctx, style, opts, pts=None, content_pt=None, text="", block="", factor=None) -> MLeader:
    f = creation_factor(ctx, style) if factor is None else factor
    ltype = opts["leader_type"]
    ctype = opts["content"]
    if ctype == "mtext" and not str(text).strip():
        ctype = "none"
    if ctype == "block" and not block:
        ctype = "none"
    dog = float(style["dogleg"]) * f
    gap = float(style["landing_gap"]) * f
    has = bool(opts["landing"])
    leaders = []
    if pts and len(pts) >= 2 and ltype != "none":
        landing = [pts[-1][0], pts[-1][1], 0.0]
        direction = 1.0 if landing[0] - pts[-2][0] >= 0 else -1.0
        end = landing[0] + direction * (dog if has else 0.0)
        content_pos = [end + direction * gap, landing[1], 0.0]
        leaders = [{"id": 1, "pts": [[p[0], p[1]] for p in pts]}]
    else:
        pt = content_pt if content_pt is not None else (pts[0] if pts else None)
        if pt is None:
            raise CommandError("A multileader needs a leader line or content; nothing was drawn.")
        landing = [pt[0], pt[1], 0.0]
        direction = 1.0
        content_pos = [pt[0], pt[1], 0.0]
        ltype = "none"
    if not leaders and ctype == "none":
        raise CommandError("A multileader needs a leader line or content; nothing was drawn.")
    return MLeader(style=style["name"], leaders=leaders, landing=landing, dogleg_dir=direction, has_landing=has, leader_type=ltype if leaders else "none", content_type=ctype, text=str(text) if ctype == "mtext" else "", content_pos=content_pos, block=block if ctype == "block" else "", block_attach=opts.get("attach", "extents"))


def content_first_points(ctx, style, opts, content_pt, tip, mids, factor=None):
    f = creation_factor(ctx, style) if factor is None else factor
    dog = float(style["dogleg"]) * f if opts["landing"] else 0.0
    gap = float(style["landing_gap"]) * f
    direction = 1.0 if tip[0] <= content_pt[0] else -1.0
    landing = [content_pt[0] - direction * (gap + dog), content_pt[1]]
    return [[tip[0], tip[1]]] + [[m[0], m[1]] for m in mids] + [landing]


def preview_shapes(ctx, style, opts, pts, q):
    f = creation_factor(ctx, style)
    path = [[p[0], p[1], 0.0] for p in pts] + [[q[0], q[1], 0.0]]
    out = [jig.poly(path)]
    if opts["landing"] and len(path) >= 2:
        direction = 1.0 if path[-1][0] - path[-2][0] >= 0 else -1.0
        out.append(jig.line(path[-1], [path[-1][0] + direction * float(style["dogleg"]) * f, path[-1][1]]))
    return out


def ask_block_name(ctx):
    while True:
        r = yield ctx.word("Enter block name", ["?"])
        if r.kind == "keyword" or (r.kind == "text" and str(r.value).strip() == "?"):
            ctx.say("Blocks: " + (", ".join(x["name"] for x in ctx.d.tables["blocks"].values() if not x.get("anonymous") and not x["name"].startswith("*")) or "none"))
            continue
        if r.kind != "text":
            return None
        rec = ctx.d.table_get("blocks", str(r.value).strip())
        if rec is None or rec.get("anonymous") or rec["name"].startswith("*"):
            ctx.say("Requires the name of a block defined in the drawing.")
            continue
        return rec["name"]


def bare(prompt):
    prompt.hint = "bare"
    return prompt


def ask_mleader_options(ctx, opts):
    names = ["Leader type", "lAnding", "Content type", "Maxpoints", "First angle", "Second angle", "eXit options"]
    while True:
        r = yield bare(ctx.keyword("Enter an option", names, "eXit options"))
        if r.kind != "keyword" or r.value == "eXit options":
            return
        if r.value == "Leader type":
            t = yield ctx.keyword("Choose leader type", ["Straight", "sPline", "None"], {"straight": "Straight", "spline": "sPline", "none": "None"}[opts["leader_type"]])
            if t.kind == "keyword":
                opts["leader_type"] = {"Straight": "straight", "sPline": "spline", "None": "none"}[t.value]
        elif r.value == "lAnding":
            t = yield ctx.yesno("Use landing?", "Yes" if opts["landing"] else "No")
            if t.kind == "keyword":
                opts["landing"] = t.value == "Yes"
        elif r.value == "Content type":
            t = yield ctx.keyword("Select content type", ["Block", "Mtext", "None"], {"block": "Block", "mtext": "Mtext", "none": "None"}[opts["content"]])
            if t.kind != "keyword":
                continue
            if t.value == "Block":
                name = yield from ask_block_name(ctx)
                if name is None:
                    continue
                at = yield ctx.keyword("Select attachment", ["Center extents", "Insertion point"], "Center extents")
                opts["block"] = name
                opts["attach"] = "insertion" if at.kind == "keyword" and at.value == "Insertion point" else "extents"
                opts["content"] = "block"
            else:
                opts["content"] = t.value.lower()
        elif r.value == "Maxpoints":
            while True:
                n = yield ctx.number("Enter maximum number of points for leader line", default=opts["maxpoints"])
                if n.kind != "number":
                    break
                if n.value != int(n.value) or not 2 <= n.value <= MAX_POINTS:
                    ctx.say("Requires an integer between 2 and %d." % MAX_POINTS)
                    continue
                opts["maxpoints"] = int(n.value)
                break
        else:
            key = "angle1" if r.value == "First angle" else "angle2"
            n = yield ctx.number("Enter %s segment angle constraint (degrees, 0 for none)" % ("first" if key == "angle1" else "second"), default=opts[key])
            if n.kind == "number":
                if n.value < 0 or n.value >= 180:
                    ctx.say("Requires a number from 0 to 180.")
                else:
                    opts[key] = float(n.value)


def first_prompt(ctx, opts):
    order = opts["order"]
    if order == "arrow":
        return ctx.point("Specify leader arrowhead location", ["leader Landing", "Content", "Options"], default_text="Options")
    if order == "landing":
        return ctx.point("Specify leader landing location", ["leader Arrowhead", "Content", "Options"], default_text="Options")
    return ctx.point("Specify location of the text", ["leader Arrowhead", "leader Landing", "Options"], default_text="Options")


def ask_text(ctx, opts):
    if opts["content"] != "mtext":
        return ""
    t = yield ctx.text("Enter leader text")
    return str(t.value) if t.kind == "text" else ""


def ask_points(ctx, style, opts, pts, label="Specify next point", total=None):
    limit = total or opts["maxpoints"]
    while len(pts) < limit:
        i = len(pts) - 1
        q = yield ctx.point(label, base=pts[-1], jig=lambda c: preview_shapes(ctx, style, opts, pts, c))
        if q.kind != "point":
            break
        inc = opts["angle1"] if i == 0 else (opts["angle2"] if i == 1 else 0.0)
        pts.append(constrain(pts[-1], q.value, inc))
    return pts


@command("mleader", aliases=("mld",), group="annotation", label="Multileader", description="Multileader with leader line(s), landing and text or block content.", menu="Dimension > Multileader")
def mleader_cmd(ctx):
    style = style_of(ctx)
    opts = get_options(ctx, style)
    while True:
        r = yield first_prompt(ctx, opts)
        if r.kind == "keyword":
            if r.value == "Options":
                yield from ask_mleader_options(ctx, opts)
            elif r.value == "leader Landing":
                opts["order"] = "landing"
            elif r.value == "leader Arrowhead":
                opts["order"] = "arrow"
            else:
                opts["order"] = "content"
            continue
        if r.kind == "enter":
            yield from ask_mleader_options(ctx, opts)
            continue
        if r.kind != "point":
            return
        break
    first = [r.value[0], r.value[1]]
    block = opts["block"]
    if opts["content"] == "block" and (not block or ctx.d.table_get("blocks", block) is None):
        raise CommandError("Requires the name of a block defined in the drawing.")
    if opts["leader_type"] == "none":
        text = yield from ask_text(ctx, opts)
        ent = build_mleader(ctx, style, opts, content_pt=first, text=text, block=block)
        ctx.add(ent)
        return
    order = opts["order"]
    if order == "arrow":
        pts = yield from ask_points(ctx, style, opts, [first])
        if len(pts) < 2:
            text = yield from ask_text(ctx, opts)
            ctx.add(build_mleader(ctx, style, opts, content_pt=first, text=text, block=block))
            return
        text = yield from ask_text(ctx, opts)
        ctx.add(build_mleader(ctx, style, opts, pts=pts, text=text, block=block))
        return
    if order == "landing":
        a = yield ctx.point("Specify leader arrowhead location", base=first, jig=lambda c: preview_shapes(ctx, style, opts, [c], first))
        if a.kind != "point":
            return
        mids = []
        if opts["maxpoints"] > 2:
            tmp = [[a.value[0], a.value[1]]]
            tmp = yield from ask_points(ctx, style, opts, tmp, "Specify next point", opts["maxpoints"] - 1)
            mids = tmp[1:]
        pts = [[a.value[0], a.value[1]]] + mids + [first]
        text = yield from ask_text(ctx, opts)
        ctx.add(build_mleader(ctx, style, opts, pts=pts, text=text, block=block))
        return
    text = yield from ask_text(ctx, opts)
    a = yield ctx.point("Specify leader arrowhead location", base=first, jig=lambda c: [jig.line(first, c)])
    if a.kind != "point":
        ctx.add(build_mleader(ctx, style, opts, content_pt=first, text=text, block=block))
        return
    mids = []
    if opts["maxpoints"] > 2:
        tmp = [[a.value[0], a.value[1]]]
        tmp = yield from ask_points(ctx, style, opts, tmp, "Specify next point", opts["maxpoints"] - 1)
        mids = tmp[1:]
    pts = content_first_points(ctx, style, opts, first, a.value, mids)
    ctx.add(build_mleader(ctx, style, opts, pts=pts, text=text, block=block))


@executes("mleader")
def mleader_exec(ctx, args):
    style = style_of(ctx, args.get("style"))
    opts = options_from_style(style)
    for key, name in (("leader_type", "leader_type"), ("landing", "landing"), ("content", "content_type")):
        if name in args:
            opts[key] = args[name]
    if opts["leader_type"] not in LEADER_TYPES:
        raise CommandError("The leader type must be straight, spline or none.")
    if opts["content"] not in CONTENT_TYPES:
        raise CommandError("The content type must be mtext, block or none.")
    block = str(args.get("block", ""))
    if opts["content"] == "block" or block:
        rec = ctx.d.table_get("blocks", block)
        if rec is None or rec.get("anonymous") or rec["name"].startswith("*"):
            raise CommandError("Requires the name of a block defined in the drawing.")
        block = rec["name"]
        opts["content"] = "block"
        opts["attach"] = "insertion" if str(args.get("attach", "")).lower().startswith("ins") else "extents"
    text = str(args.get("text", ""))
    pts = [geom.as_pt(p) for p in args.get("points", [])]
    pts = [[p[0], p[1]] for p in pts]
    maxp = int(args.get("maxpoints", 0) or 0)
    if maxp and not 2 <= maxp <= MAX_POINTS:
        raise CommandError("Requires an integer between 2 and %d." % MAX_POINTS)
    if maxp and len(pts) > maxp:
        raise CommandError("The leader has more than %d points." % maxp)
    for key, i in (("angle1", 0), ("angle2", 1)):
        inc = float(args.get(key, 0.0) or 0.0)
        if inc and len(pts) > i + 1:
            pts[i + 1] = constrain(pts[i], pts[i + 1], inc)
    cp = args.get("content_point")
    if args.get("content_first") and cp is not None and pts:
        mids = pts[1:]
        pts = content_first_points(ctx, style, opts, geom.as_pt(cp), pts[0], mids)
        cp = None
    ent = build_mleader(ctx, style, opts, pts=pts or None, content_pt=geom.as_pt(cp) if cp is not None else None, text=text, block=block)
    h = ctx.add(ent)
    return {"handle": h, "leaders": len(ent.leaders), "landing": ent.landing[:2], "content_pos": ent.content_pos[:2], "dogleg_dir": ent.dogleg_dir}


def mleaders_in(ctx, handles) -> list:
    out = []
    for h in handles:
        e = ctx.d.get(int(h))
        if e is not None and e.kind == "mleader":
            out.append(e)
    return out


def pick_radius(ctx) -> float:
    return max(float(ctx.doc.view.get("height", 100.0)) * 0.02, 1e-6)


def edit_leaders(ctx, handle, add=(), remove=(), say=True) -> dict:
    ent0 = ctx.d.get(int(handle))
    if ent0 is None or ent0.kind != "mleader":
        raise CommandError("The object is not a multileader.")
    if ctx.locked(ent0):
        raise CommandError("The multileader is on a locked layer.")
    ent = ctx.d.modify(ent0.handle)
    style = style_of(ctx, ent.style)
    f = A.factor(ctx.d, A.display_scale(ctx.d, ent)) if (ent.annotation_scales and A.display_scale(ctx.d, ent)) else 1.0
    added = removed = 0
    for p in add:
        tip = [float(p[0]), float(p[1])]
        if not ent.leaders:
            dog = ent.size_of("dogleg_length", style, f) if ent.has_landing else 0.0
            gap = ent.size_of("landing_gap", style, f)
            direction = 1.0 if tip[0] <= ent.content_pos[0] else -1.0
            ent.dogleg_dir = direction
            ent.landing = [ent.content_pos[0] - direction * (gap + dog), ent.content_pos[1], 0.0]
            ent.leader_type = "straight"
        ent.leaders.append({"id": ent.next_leader_id(), "pts": [tip, [ent.landing[0], ent.landing[1]]]})
        added += 1
    for p in remove:
        ld, idx, dist = nearest_leader(ent, p)
        if ld is None or dist > pick_radius(ctx):
            ctx.say("No leader to remove.")
            continue
        if len(ent.leaders) == 1 and ent.content_type == "none":
            raise CommandError("A multileader needs a leader line or content.")
        ent.leaders.pop(idx)
        removed += 1
        if not ent.leaders:
            ent.leader_type = "none"
            ent.content_pos = [ent.content_pos[0], ent.content_pos[1], 0.0]
    if say and added:
        ctx.say("%d leader(s) added." % added)
    if say and removed:
        ctx.say("%d leader(s) removed." % removed)
    return {"added": added, "removed": removed, "leaders": len(ent.leaders)}


@command("mleaderedit", aliases=("mledit",), group="annotation", label="Add/Remove Leader", description="Add leaders to or remove leaders from a multileader.", menu="Modify > Object > Multileader > Add Leader")
def mleaderedit(ctx):
    s = yield ctx.select("Select a multileader", pick_one=True)
    if s.kind != "selection":
        return
    found = mleaders_in(ctx, s.value)
    if not found:
        ctx.say("The object is not a multileader.")
        return
    ent = found[0]
    if ctx.locked(ent):
        raise CommandError("The multileader is on a locked layer.")
    mode = "add"
    added = removed = 0
    while True:
        if mode == "add":
            r = yield ctx.point("Specify leader arrowhead location", ["Remove leaders"], jig=lambda c, h=ent.handle: [jig.line(ctx.d.get(h).landing, c)])
        else:
            r = yield ctx.point("Specify leaders to remove", ["Add leaders"])
        if r.kind == "keyword":
            mode = "remove" if mode == "add" else "add"
            continue
        if r.kind != "point":
            break
        try:
            if mode == "add":
                added += edit_leaders(ctx, ent.handle, add=[r.value], say=False)["added"]
            else:
                removed += edit_leaders(ctx, ent.handle, remove=[r.value], say=False)["removed"]
        except CommandError as err:
            ctx.say(str(err))
    if added:
        ctx.say("%d leader(s) added." % added)
    if removed:
        ctx.say("%d leader(s) removed." % removed)


@executes("mleaderedit")
def mleaderedit_exec(ctx, args):
    h = args.get("handle", ctx.doc.selection[0] if ctx.doc.selection else None)
    if h is None:
        raise CommandError("Give the handle of a multileader.")
    return edit_leaders(ctx, h, args.get("add", []), args.get("remove", []))


def last_dir(ent):
    pts = ent.leaders[0]["pts"]
    a, b = pts[-2], pts[-1]
    n = geom.dist(a, b)
    return ((b[0] - a[0]) / n, (b[1] - a[1]) / n) if n > 1e-12 else (1.0, 0.0)


def align_mleaders(ctx, ents, ref, p1, p2, spacing=None, parallel=False) -> int:
    u = (p2[0] - p1[0], p2[1] - p1[1])
    n = math.hypot(*u)
    if n < 1e-12:
        raise CommandError("The direction needs two different points.")
    u = (u[0] / n, u[1] / n)
    origin = [ref.landing[0], ref.landing[1]] if ref is not None else [p1[0], p1[1]]
    items = [e for e in ents if (ref is None or e.handle != ref.handle) and not ctx.locked(e)]

    def param(e):
        return (e.landing[0] - origin[0]) * u[0] + (e.landing[1] - origin[1]) * u[1]

    targets = {}
    if spacing is not None:
        pos = sorted([e for e in items if param(e) >= 0], key=param)
        neg = sorted([e for e in items if param(e) < 0], key=lambda e: -param(e))
        for k, e in enumerate(pos):
            targets[e.handle] = (k + 1) * spacing
        for k, e in enumerate(neg):
            targets[e.handle] = -(k + 1) * spacing
    else:
        for e in items:
            targets[e.handle] = param(e)
    n_done = 0
    rd = last_dir(ref) if (parallel and ref is not None and ref.leaders) else None
    for e in items:
        t = targets[e.handle]
        goal = [origin[0] + u[0] * t, origin[1] + u[1] * t]
        if rd is not None and e.leaders:
            pp = e.leaders[0]["pts"][-2]
            den = rd[0] * u[1] - rd[1] * u[0]
            if abs(den) > 1e-9:
                s = ((origin[0] - pp[0]) * u[1] - (origin[1] - pp[1]) * u[0]) / den
                goal = [pp[0] + rd[0] * s, pp[1] + rd[1] * s]
        ent = ctx.d.modify(e.handle)
        move_landing(ent, goal[0] - e.landing[0], goal[1] - e.landing[1])
        n_done += 1
    ctx.say("%d multileader(s) aligned." % n_done)
    return n_done


def distribute_mleaders(ctx, ents, p1, p2) -> int:
    items = [e for e in ents if not ctx.locked(e)]
    if len(items) < 2:
        raise CommandError("Distribute needs at least two multileaders.")
    u = (p2[0] - p1[0], p2[1] - p1[1])
    n2 = u[0] * u[0] + u[1] * u[1]
    if n2 < 1e-18:
        raise CommandError("The distribution needs two different points.")
    items.sort(key=lambda e: (e.landing[0] - p1[0]) * u[0] + (e.landing[1] - p1[1]) * u[1])
    for i, e in enumerate(items):
        k = i / (len(items) - 1)
        goal = [p1[0] + u[0] * k, p1[1] + u[1] * k]
        ent = ctx.d.modify(e.handle)
        move_landing(ent, goal[0] - e.landing[0], goal[1] - e.landing[1])
    ctx.say("%d multileader(s) aligned." % len(items))
    return len(items)


@command("mleaderalign", aliases=("mleadera",), group="annotation", label="Align Multileaders", description="Align, distribute or make parallel the landings of multileaders.", menu="Modify > Object > Multileader > Align")
def mleaderalign(ctx):
    s = yield ctx.select("Select multileaders")
    if s.kind != "selection":
        return
    ents = mleaders_in(ctx, s.value)
    if not ents:
        ctx.say("No multileaders selected.")
        return
    spacing = None
    parallel = False
    ref = None
    while True:
        r = yield ctx.entity("Select multileader to align to", ["Options"])
        if r.kind == "keyword" and r.value == "Options":
            o = yield ctx.keyword("Enter an option", ["Distribute", "make segments Parallel", "Specify spacing", "Use current spacing"], "Use current spacing")
            if o.kind != "keyword":
                continue
            if o.value == "Distribute":
                a = yield ctx.point("Specify first point")
                if a.kind != "point":
                    return
                b = yield ctx.point("Specify second point", base=a.value)
                if b.kind != "point":
                    return
                distribute_mleaders(ctx, ents, a.value, b.value)
                return
            if o.value == "make segments Parallel":
                parallel = True
            elif o.value == "Specify spacing":
                v = yield ctx.number("Specify spacing", minimum=0, default=0.0)
                if v.kind == "number":
                    spacing = float(v.value)
            else:
                spacing = None
            continue
        if r.kind != "entity":
            return
        cand = pick_entity(ctx, r.value)
        if cand is None or cand.kind != "mleader":
            ctx.say("The object is not a multileader.")
            continue
        ref = cand
        break
    a = yield ctx.point("Specify direction (first point)")
    if a.kind != "point":
        return
    b = yield ctx.point("Specify direction (second point)", base=a.value)
    if b.kind != "point":
        return
    align_mleaders(ctx, ents, ref, a.value, b.value, spacing, parallel)


@executes("mleaderalign")
def mleaderalign_exec(ctx, args):
    ents = mleaders_in(ctx, args.get("handles", ctx.doc.selection))
    if args.get("distribute"):
        pts = args["distribute"]
        return {"aligned": distribute_mleaders(ctx, ents, geom.as_pt(pts[0]), geom.as_pt(pts[1]))}
    ref = ctx.d.get(int(args["reference"])) if args.get("reference") is not None else None
    if ref is None or ref.kind != "mleader":
        raise CommandError("The object is not a multileader.")
    d = args.get("direction")
    if not d or len(d) != 2:
        raise CommandError("Give a direction as two points.")
    sp = args.get("spacing")
    if sp is not None and float(sp) < 0:
        raise CommandError("Requires a positive number.")
    return {"aligned": align_mleaders(ctx, ents, ref, geom.as_pt(d[0]), geom.as_pt(d[1]), None if sp is None else float(sp), bool(args.get("parallel")))}


def block_size(ctx, name: str, scale: float):
    box = None
    for e in ctx.d.entities("block:" + name):
        box = geom.union_bounds(box, e.bounds())
    if box is None:
        return scale, scale
    return (box[2] - box[0]) * scale, (box[3] - box[1]) * scale


def collect_mleaders(ctx, ents, loc, mode: str, width=None) -> int:
    blocks = [e for e in ents if e.content_type == "block" and e.block and not ctx.locked(e)]
    if len(blocks) < 2:
        raise CommandError("Select at least two multileaders with block content.")
    if mode == "wrap" and not (width and width > 0):
        raise CommandError("Requires a positive width.")
    main = blocks[0]
    style = style_of(ctx, main.style)
    f = A.factor(ctx.d, A.current_name(ctx.d)) if style.get("annotative") else 1.0
    gap = float(style["landing_gap"]) * f
    x, y = float(loc[0]), float(loc[1])
    left, row_h = x, 0.0
    placed = []
    for e in blocks:
        w, h = block_size(ctx, e.block, e.block_scale * f)
        if mode == "wrap" and placed and (x - left) + w > width + 1e-9:
            x = left
            y -= row_h + gap
            row_h = 0.0
        placed.append((e, [x, y], w, h))
        if mode == "vertical":
            y -= h + gap
        else:
            x += w + gap
            row_h = max(row_h, h)
    ent = ctx.d.modify(main.handle)
    first_w, first_h = placed[0][2], placed[0][3]
    dog = float(style["dogleg"]) * f if ent.has_landing else 0.0
    land = [left - gap - dog, placed[0][1][1] - first_h / 2.0]
    ent.dogleg_dir = 1.0
    ent.content_pos = [placed[0][1][0], placed[0][1][1], 0.0]
    ent.more_blocks = [{"block": e.block, "scale": e.block_scale, "rotation": e.block_rotation, "pos": [p[0], p[1]]} for e, p, _w, _h in placed[1:]]
    merged = list(ent.leaders)
    for e in blocks[1:]:
        merged.extend(copy.deepcopy(e.leaders))
        ctx.d.erase_entity(e.handle)
    ent.leaders = []
    for ld in merged:
        pts = [[p[0], p[1]] for p in ld["pts"]]
        pts[-1] = [land[0], land[1]]
        ent.leaders.append({"id": ent.next_leader_id(), "pts": pts})
    ent.landing = [land[0], land[1], 0.0]
    if ent.leaders:
        ent.leader_type = "straight"
    ctx.say("%d multileader(s) collected." % len(blocks))
    return len(blocks)


@command("mleadercollect", aliases=("mleaderc",), group="annotation", label="Collect Multileaders", description="Gather block-content multileaders into a row, column or wrapped group.", menu="Modify > Object > Multileader > Collect")
def mleadercollect(ctx):
    s = yield ctx.select("Select multileaders")
    if s.kind != "selection":
        return
    ents = [e for e in mleaders_in(ctx, s.value) if e.content_type == "block"]
    if len(ents) < 2:
        ctx.say("Select at least two multileaders with block content.")
        return
    mode, width = "horizontal", None
    while True:
        r = yield ctx.point("Specify collected multileader location", ["Vertical", "Horizontal", "Wrap"], default_text="Horizontal")
        if r.kind == "keyword":
            if r.value == "Wrap":
                w = yield ctx.number("Specify width", positive=True)
                if w.kind == "number":
                    mode, width = "wrap", float(w.value)
            else:
                mode = r.value.lower()
            continue
        if r.kind != "point":
            return
        break
    collect_mleaders(ctx, ents, r.value, mode, width)


@executes("mleadercollect")
def mleadercollect_exec(ctx, args):
    ents = mleaders_in(ctx, args.get("handles", ctx.doc.selection))
    mode = str(args.get("mode", "horizontal")).lower()
    if mode not in ("horizontal", "vertical", "wrap"):
        raise CommandError("The mode must be horizontal, vertical or wrap.")
    return {"collected": collect_mleaders(ctx, ents, geom.as_pt(args["point"]), mode, float(args["width"]) if args.get("width") is not None else None)}


def valid_style_name(name: str) -> bool:
    n = str(name).strip()
    return 0 < len(n) <= 255 and not any(c in BAD_NAME_CHARS for c in n)


def styles_in_use(ctx) -> set:
    return {e.style.casefold() for e in ctx.d.ents.values() if e.kind == "mleader"}


def clean_style(ctx, rec: dict) -> dict:
    out = dict(rec)
    for k in NUMERIC_FIELDS:
        v = out.get(k)
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0:
            raise CommandError("%s must be zero or more." % k.replace("_", " ").capitalize())
        out[k] = float(v)
    if ctx.d.table_get("textstyles", str(out.get("text_style", ""))) is None:
        raise CommandError("Text style %s does not exist." % out.get("text_style"))
    out["annotative"] = bool(out.get("annotative", False))
    raw = str(out.get("arrowhead", STYLE_DEFAULTS["arrowhead"]))
    head = arrows.canonical(raw)
    if head == "closed filled" and raw.strip().lstrip("_").replace("_", "").replace(" ", "").lower() not in ("closedfilled", ""):
        raise CommandError("Unknown arrowhead: %s." % raw)
    out["arrowhead"] = head
    if out.get("leader_type", "straight") not in LEADER_TYPES:
        raise CommandError("The leader type must be straight, spline or none.")
    if out.get("content_type", "mtext") not in CONTENT_TYPES:
        raise CommandError("The content type must be mtext, block or none.")
    mp = out.get("max_points", 2)
    if not isinstance(mp, int) or not 2 <= mp <= MAX_POINTS:
        raise CommandError("Requires an integer between 2 and %d." % MAX_POINTS)
    out["landing"] = bool(out.get("landing", True))
    return out


def style_action(ctx, action: str, a: dict) -> dict:
    d = ctx.d
    if action == "list":
        return {"styles": [r["name"] for r in d.tables["mleaderstyles"].values()], "current": str(ctx.var("CMLEADERSTYLE"))}
    name = str(a.get("name", "")).strip()
    fields = {k: a[k] for k in ("arrow_size", "text_height", "landing_gap", "dogleg", "text_style", "annotative", "arrowhead", "leader_type", "landing", "content_type", "max_points") if k in a}
    if action in ("create", "new"):
        if not valid_style_name(name):
            raise CommandError("Invalid style name: up to 255 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if d.table_get("mleaderstyles", name) is not None:
            raise CommandError("Style %s already exists." % name)
        base = T.new_mleaderstyle(d.metric, name)
        base.update(fields)
        rec = clean_style(ctx, base)
        d.table_set("mleaderstyles", rec)
        if a.get("current", True):
            ctx.setvar("CMLEADERSTYLE", rec["name"])
        return {"style": rec}
    rec0 = d.table_get("mleaderstyles", name)
    if rec0 is None:
        raise CommandError("Style %s does not exist." % name)
    if action == "current":
        ctx.setvar("CMLEADERSTYLE", rec0["name"])
        return {"style": rec0}
    if action == "modify":
        new = copy.deepcopy(rec0)
        new.update(fields)
        rec = clean_style(ctx, new)
        d.table_set("mleaderstyles", rec)
        return {"style": rec}
    to = str(a.get("to", "")).strip()
    if action == "copy":
        if not valid_style_name(to):
            raise CommandError("Invalid style name: up to 255 characters, none of %s." % " ".join(BAD_NAME_CHARS))
        if d.table_get("mleaderstyles", to) is not None:
            raise CommandError("Style %s already exists." % to)
        rec = copy.deepcopy(rec0)
        rec["name"] = to
        d.table_set("mleaderstyles", rec)
        return {"style": rec}
    if action == "rename":
        if rec0["name"].casefold() == "standard":
            raise CommandError("The Standard style cannot be renamed.")
        if not valid_style_name(to) or d.table_get("mleaderstyles", to) is not None:
            raise CommandError("Invalid or duplicate style name.")
        rec = copy.deepcopy(rec0)
        rec["name"] = to
        d.table_remove("mleaderstyles", rec0["name"])
        d.table_set("mleaderstyles", rec)
        for e in list(d.ents.values()):
            if e.kind == "mleader" and e.style.casefold() == rec0["name"].casefold():
                d.modify(e.handle).style = to
        if str(ctx.var("CMLEADERSTYLE")).casefold() == rec0["name"].casefold():
            ctx.setvar("CMLEADERSTYLE", to)
        return {"style": rec}
    if action == "delete":
        if rec0["name"].casefold() == "standard":
            raise CommandError("The Standard style cannot be deleted.")
        if rec0["name"].casefold() == str(ctx.var("CMLEADERSTYLE")).casefold():
            raise CommandError("The current style cannot be deleted.")
        if rec0["name"].casefold() in styles_in_use(ctx):
            raise CommandError("Style %s is used by existing multileaders and cannot be deleted." % rec0["name"])
        d.table_remove("mleaderstyles", rec0["name"])
        return {"deleted": rec0["name"]}
    raise CommandError("Unknown MLEADERSTYLE action: %s." % action)


FIELD_WORDS = ["Arrow size", "Height", "Gap", "Dogleg", "Style", "ANnotative", "Head", "eXit"]
FIELD_KEYS = {"Arrow size": "arrow_size", "Height": "text_height", "Gap": "landing_gap", "Dogleg": "dogleg"}


def ask_style_fields(ctx, rec):
    out = {}
    while True:
        r = yield ctx.keyword("Enter an option", FIELD_WORDS, "eXit")
        if r.kind != "keyword" or r.value == "eXit":
            return out
        if r.value in FIELD_KEYS:
            key = FIELD_KEYS[r.value]
            v = yield ctx.number("Specify %s" % r.value.lower(), default=out.get(key, rec.get(key)), minimum=0)
            if v.kind == "number":
                out[key] = float(v.value)
        elif r.value == "Style":
            v = yield ctx.word("Enter text style name", default=out.get("text_style", rec.get("text_style")))
            if v.kind == "text":
                out["text_style"] = str(v.value).strip()
        elif r.value == "ANnotative":
            v = yield ctx.yesno("Annotative?", "Yes" if out.get("annotative", rec.get("annotative")) else "No")
            if v.kind == "keyword":
                out["annotative"] = v.value == "Yes"
        else:
            v = yield ctx.word("Enter arrowhead name", default=out.get("arrowhead", rec.get("arrowhead", STYLE_DEFAULTS["arrowhead"])))
            if v.kind == "text":
                out["arrowhead"] = str(v.value).strip()


@command("mleaderstyle", aliases=("mls",), group="format", label="Multileader Style...", description="Create or modify multileader styles.", menu="Format > Multileader Style...")
def mleaderstyle(ctx):
    r = yield ctx.keyword("Enter an option", ["?", "Current", "New", "Modify", "Copy", "Rename", "Delete"], "?")
    if r.kind == "enter":
        r.value = "?"
    elif r.kind != "keyword":
        return
    act = r.value
    if act == "?":
        cur = str(ctx.var("CMLEADERSTYLE"))
        for rec in ctx.d.tables["mleaderstyles"].values():
            ctx.say("%s - arrow %s, text %s, gap %s, dogleg %s%s%s" % (rec["name"], ctx.fd(rec["arrow_size"]), ctx.fd(rec["text_height"]), ctx.fd(rec["landing_gap"]), ctx.fd(rec["dogleg"]), ", annotative" if rec.get("annotative") else "", "  (current)" if rec["name"].casefold() == cur.casefold() else ""))
        return
    n = yield ctx.word("Enter style name" if act != "New" else "Enter name for new style", default=str(ctx.var("CMLEADERSTYLE")) if act != "New" else None)
    if n.kind != "text":
        return
    name = str(n.value).strip()
    if act in ("Current", "Delete"):
        style_action(ctx, act.lower(), {"name": name})
        return
    if act in ("Copy", "Rename"):
        t = yield ctx.word("Enter new style name")
        if t.kind == "text":
            style_action(ctx, act.lower(), {"name": name, "to": str(t.value).strip()})
        return
    rec = T.new_mleaderstyle(ctx.d.metric, name) if act == "New" else ctx.d.table_get("mleaderstyles", name)
    if rec is None:
        raise CommandError("Style %s does not exist." % name)
    fields = yield from ask_style_fields(ctx, rec)
    style_action(ctx, "create" if act == "New" else "modify", {"name": name, **fields})
    ctx.say("Multileader style %s %s." % (name, "created and made current" if act == "New" else "modified"))


@executes("mleaderstyle")
def mleaderstyle_exec(ctx, args):
    return style_action(ctx, str(args.get("action", "list")).lower(), args)
