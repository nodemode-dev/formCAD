import math

from app.cmd import jig
from app.cmd import hatch_support as HS
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import hatchfill as H
from app.doc import loops as L
from app.doc import patterns

DRAW_ORDER_WORDS = {"none": 0, "back": 1, "front": 2, "behind": 3, "behind boundary": 3, "in front": 4, "front of boundary": 4, "in front of boundary": 4}
POINT_OPTIONS = ["Select objects", "Undo", "seTtings", "Pattern", "sCale", "Angle", "Origin", "sEparate"]
OBJECT_OPTIONS = ["picK internal point", "Undo", "seTtings", "sCale", "Angle", "Origin", "sEparate"]
GRADIENT_POINT_OPTIONS = ["Select objects", "Undo", "seTtings", "Name", "Color", "Angle", "Centered", "Origin", "sEparate"]
GRADIENT_OBJECT_OPTIONS = ["picK internal point", "Undo", "seTtings", "Name", "Color", "Angle", "Centered", "Origin", "sEparate"]
SETTINGS_OPTIONS = ["Associative", "Island detection", "Gap tolerance", "Draw order", "ANnotative", "Transparency", "Retain boundaries", "Boundary set", "Done"]
ORIGIN_OPTIONS = ["Bottom left", "bottom Right", "Top left", "top riGht", "Center", "Use current"]
ISLAND_OPTIONS = ["Normal", "Outer", "Ignore"]
RETAIN_OPTIONS = ["No", "Polyline", "Region"]
ORDER_OPTIONS = ["None", "Back", "Front", "Behind boundary", "in Front of boundary"]


def draw_order_value(value) -> int:
    if isinstance(value, int) and 0 <= value <= 4:
        return value
    key = str(value).strip().lower()
    if key in DRAW_ORDER_WORDS:
        return DRAW_ORDER_WORDS[key]
    raise CommandError("Draw order is none, back, front, behind boundary or in front of boundary.")


def retain_value(value) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int) and value in (0, 1, 2):
        return value
    key = str(value).strip().lower()
    table = {"no": 0, "none": 0, "polyline": 1, "region": 2}
    if key in table:
        return table[key]
    raise CommandError("Retained boundaries are none, polyline or region.")


def pick_jig(ctx, st):
    def show(cursor):
        try:
            found = L.detect_at(ctx.doc, cursor, st.island, st.gap, st.boundary)
        except Exception:
            return []
        return [jig.poly(lp["vertices"], True) for lp in found]

    return show


def ask_pattern(ctx, st):
    while True:
        r = yield ctx.word("Enter a pattern name", ["Solid"], st.pattern)
        if r.kind == "enter":
            return True
        if r.kind == "keyword":
            st.pattern = "SOLID"
            st.gradient = None
            return True
        if r.kind != "text":
            return False
        text = str(r.value).strip()
        if text == "?":
            ctx.say("Built-in patterns: " + ", ".join(patterns.NAMES))
            if patterns.USER:
                ctx.say("Loaded patterns: " + ", ".join(sorted(patterns.USER)))
            continue
        try:
            st.pattern = HS.resolve_pattern(text)
        except CommandError as err:
            ctx.say(str(err))
            continue
        st.gradient = None
        return True


def ask_scale_angle(ctx, st):
    if patterns.is_solid(st.pattern):
        return True
    r = yield ctx.number("Specify a scale for the hatch pattern", default=st.scale, positive=True, default_text=ctx.fd(st.scale))
    if r.kind == "number":
        st.scale = float(r.value)
    elif r.kind != "enter":
        return False
    r = yield ctx.angle("Specify an angle for the hatch pattern", default=st.angle, absolute=False)
    if r.kind == "number":
        st.angle = float(r.value)
    elif r.kind != "enter":
        return False
    return True


def ask_origin(ctx, st):
    r = yield ctx.point("Specify the pattern origin", ORIGIN_OPTIONS, default_text="Use current")
    if r.kind == "point":
        st.origin = [r.value[0], r.value[1]]
        st.origin_mode = 0
        return True
    if r.kind == "keyword":
        st.origin_mode = HS.parse_origin_mode(r.value.lower())
        return True
    if r.kind == "enter":
        st.origin_mode = 0
        return True
    return False


def ask_color(ctx, current, msg):
    while True:
        r = yield ctx.word(msg, [], str(current))
        if r.kind == "enter":
            return current
        if r.kind != "text":
            return None
        try:
            return HS.color_value(str(r.value))
        except CommandError as err:
            ctx.say(str(err))


def ask_gradient_color(ctx, st):
    g = st.gradient
    c1 = yield from ask_color(ctx, g["color1"], "Enter first gradient colour")
    if c1 is None:
        return False
    g["color1"] = c1
    while True:
        r = yield ctx.word("Enter second gradient colour", ["One colour tint"], str(g["color2"]))
        if r.kind == "enter":
            return True
        if r.kind == "keyword":
            t = yield ctx.number("Enter a tint from -1 to 1", default=g["tint"], minimum=-1.0, maximum=1.0, default_text="%g" % g["tint"])
            if t.kind == "number":
                g["tint"] = float(t.value)
            g["one"] = True
            return True
        if r.kind != "text":
            return False
        try:
            g["color2"] = HS.color_value(str(r.value))
        except CommandError as err:
            ctx.say(str(err))
            continue
        g["one"] = False
        return True


def ask_settings(ctx, st):
    while True:
        r = yield ctx.keyword("Enter a hatch setting", SETTINGS_OPTIONS, "Done")
        if r.kind != "keyword":
            return
        k = r.value
        if k == "Done":
            return
        if k == "Associative":
            y = yield ctx.yesno("Associate the hatch with its boundary?", "Yes" if st.associative else "No")
            if y.kind == "keyword":
                st.associative = y.value == "Yes"
        elif k == "Island detection":
            cur = HS.STYLE_NAMES[st.island].title()
            y = yield ctx.keyword("Enter island detection style", ISLAND_OPTIONS, cur)
            if y.kind == "keyword":
                st.island = HS.parse_style(y.value)
        elif k == "Gap tolerance":
            y = yield ctx.number("Enter a gap tolerance from 0 to 5000", default=st.gap, minimum=0.0, maximum=5000.0, default_text=ctx.fd(st.gap))
            if y.kind == "number":
                st.gap = float(y.value)
        elif k == "Draw order":
            cur = ORDER_OPTIONS[st.draw_order]
            y = yield ctx.keyword("Enter draw order", ORDER_OPTIONS, cur)
            if y.kind == "keyword":
                st.draw_order = draw_order_value(y.value.lower())
        elif k == "ANnotative":
            y = yield ctx.yesno("Make the hatch annotative?", "Yes" if st.annotative else "No")
            if y.kind == "keyword":
                st.annotative = y.value == "Yes"
        elif k == "Transparency":
            y = yield ctx.word("Enter transparency ByLayer, ByBlock or 0 to 90", [], str(st.transparency))
            if y.kind == "text":
                try:
                    st.transparency = HS.parse_transparency(y.value)
                except CommandError as err:
                    ctx.say(str(err))
        elif k == "Retain boundaries":
            cur = RETAIN_OPTIONS[st.retain]
            y = yield ctx.keyword("Retain boundary objects", RETAIN_OPTIONS, cur)
            if y.kind == "keyword":
                st.retain = retain_value(y.value)
        elif k == "Boundary set":
            y = yield ctx.select("Select objects for the boundary set (Enter uses everything visible)")
            if y.kind == "selection":
                st.boundary = list(y.value) if y.value else None
                ctx.say("%s objects form the boundary set." % (len(y.value) if y.value else "All"))


def save_state(ctx, st, gradient):
    HS.store_settings(ctx, st)
    if gradient and st.gradient:
        HS.store_gradient(ctx, st.gradient)


def run_flow(ctx, gradient, classic):
    st = HS.read_settings(ctx)
    if gradient:
        st.gradient = HS.default_gradient(ctx)
    ctx.say(HS.current_line(ctx, st, gradient))
    if classic and not gradient:
        ok = yield from ask_pattern(ctx, st)
        if not ok:
            return
        ok = yield from ask_scale_angle(ctx, st)
        if not ok:
            return
    picks = []
    objects_mode = False
    while True:
        if objects_mode:
            opts = GRADIENT_OBJECT_OPTIONS if gradient else OBJECT_OPTIONS
            r = yield ctx.entity("Select objects", opts)
        else:
            opts = GRADIENT_POINT_OPTIONS if gradient else POINT_OPTIONS
            r = yield ctx.point("Pick internal point", opts, jig=pick_jig(ctx, st))
        if r.kind == "enter":
            break
        if r.kind == "point":
            try:
                found = L.detect_at(ctx.doc, r.value, st.island, st.gap, st.boundary)
            except Exception as err:
                ctx.say(str(err))
                continue
            if not found:
                ctx.say(HS.NOT_FOUND)
                continue
            picks.append(("point", [r.value[0], r.value[1]]))
            continue
        if r.kind == "entity":
            picks.append(("object", r.value["handle"]))
            continue
        if r.kind != "keyword":
            return
        k = r.value
        if k == "Select objects":
            objects_mode = True
        elif k == "picK internal point":
            objects_mode = False
        elif k == "Undo":
            if picks:
                picks.pop()
            else:
                ctx.say("Nothing to undo.")
        elif k == "seTtings":
            yield from ask_settings(ctx, st)
        elif k == "Pattern":
            ok = yield from ask_pattern(ctx, st)
            if not ok:
                return
            ok = yield from ask_scale_angle(ctx, st)
            if not ok:
                return
        elif k == "sCale":
            q = yield ctx.number("Specify a scale for the hatch pattern", default=st.scale, positive=True, default_text=ctx.fd(st.scale))
            if q.kind == "number":
                st.scale = float(q.value)
        elif k == "Angle":
            if gradient:
                q = yield ctx.angle("Specify an angle for the gradient", default=st.gradient["angle"], absolute=False)
                if q.kind == "number":
                    st.gradient["angle"] = float(q.value)
            else:
                q = yield ctx.angle("Specify an angle for the hatch pattern", default=st.angle, absolute=False)
                if q.kind == "number":
                    st.angle = float(q.value)
        elif k == "Origin":
            yield from ask_origin(ctx, st)
        elif k == "sEparate":
            y = yield ctx.yesno("Create separate hatches?", "Yes" if st.separate else "No")
            if y.kind == "keyword":
                st.separate = y.value == "Yes"
        elif k == "Name":
            q = yield ctx.keyword("Enter a gradient name", [n.title() for n in H.GRADIENT_NAMES], st.gradient["name"].title())
            if q.kind == "keyword":
                st.gradient["name"] = q.value.upper()
        elif k == "Color":
            yield from ask_gradient_color(ctx, st)
        elif k == "Centered":
            y = yield ctx.yesno("Centre the gradient?", "Yes" if st.gradient["centered"] else "No")
            if y.kind == "keyword":
                st.gradient["centered"] = y.value == "Yes"
    if not picks:
        return
    points = [p for kind, p in picks if kind == "point"]
    handles = [p for kind, p in picks if kind == "object"]
    try:
        groups = HS.groups_for(ctx, st, points, handles)
    except Exception as err:
        raise CommandError(str(err))
    save_state(ctx, st, gradient)
    HS.create_all(ctx, st, groups)


@command("hatch", aliases=("h", "bh"), group="draw", label="Hatch...", description="Fill closed areas with a pattern or solid; boundary by pick point or objects.", menu="Draw > Hatch...")
def hatch_cmd(ctx):
    yield from run_flow(ctx, False, False)


@command("-hatch", group="draw", label="Hatch (command line)", description="Hatch with the pattern, scale and angle asked first.", menu="")
def hatch_classic(ctx):
    yield from run_flow(ctx, False, True)


@command("gradient", aliases=("gd",), group="draw", label="Gradient...", description="Fill closed areas with a gradient.", menu="Draw > Gradient...")
def gradient_cmd(ctx):
    yield from run_flow(ctx, True, False)


def boundary_inputs(ctx, args):
    points = []
    for p in args.get("points") or []:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            raise CommandError("Each internal point is [x, y].")
        points.append([float(p[0]), float(p[1])])
    handles = [int(h) for h in args.get("handles") or []]
    if args.get("picked"):
        mem = ctx.mem.get("hatchpick") or {}
        points += [list(p) for p in mem.get("points", [])]
        handles += [h for h in mem.get("objects", []) if h not in handles]
    return points, handles


def settings_from(ctx, args, gradient):
    st = HS.read_settings(ctx)
    if "pattern" in args and args["pattern"] is not None:
        st.pattern = HS.resolve_pattern(args["pattern"], args.get("pattern_name"))
    if "scale" in args and args["scale"] is not None:
        v = float(args["scale"])
        if not v > 0 or not math.isfinite(v):
            raise CommandError("Value must be positive and nonzero.")
        st.scale = v
    if "angle" in args and args["angle"] is not None:
        st.angle = math.radians(float(args["angle"]))
    if "associative" in args and args["associative"] is not None:
        st.associative = bool(args["associative"])
    if "separate" in args and args["separate"] is not None:
        st.separate = bool(args["separate"])
    if "origin" in args and args["origin"] is not None:
        o = args["origin"]
        st.origin = [float(o[0]), float(o[1])]
        st.origin_mode = 0
    if "origin_mode" in args and args["origin_mode"] is not None:
        st.origin_mode = HS.parse_origin_mode(args["origin_mode"])
    if "style" in args and args["style"] is not None:
        st.island = HS.parse_style(args["style"])
    if "gap" in args and args["gap"] is not None:
        g = float(args["gap"])
        if not 0.0 <= g <= 5000.0:
            raise CommandError("Gap tolerance is between 0 and 5000.")
        st.gap = g
    if "draw_order" in args and args["draw_order"] is not None:
        st.draw_order = draw_order_value(args["draw_order"])
    if "annotative" in args and args["annotative"] is not None:
        st.annotative = bool(args["annotative"])
    if "transparency" in args and args["transparency"] is not None:
        st.transparency = HS.parse_transparency(args["transparency"])
    if "retain" in args and args["retain"] is not None:
        st.retain = retain_value(args["retain"])
    if args.get("boundary_set") is not None:
        st.boundary = [int(h) for h in args["boundary_set"]]
    if gradient:
        st.gradient = HS.gradient_from(args, HS.default_gradient(ctx))
    return st


def run_exec(ctx, args, gradient):
    points, handles = boundary_inputs(ctx, args)
    if not points and not handles:
        raise CommandError(HS.NO_INPUT)
    if len(points) + len(handles) > HS.MAX_PICKS:
        raise CommandError("Too many internal points or objects.")
    st = settings_from(ctx, args, gradient)
    groups = HS.groups_for(ctx, st, points, handles)
    made = HS.create_all(ctx, st, groups)
    out = {"handles": made}
    out["loops"] = [len(ctx.d.get(h).loops) for h in made]
    return out


@executes("hatch")
def hatch_exec(ctx, args):
    return run_exec(ctx, args, False)


@executes("-hatch")
def hatch_classic_exec(ctx, args):
    return run_exec(ctx, args, False)


@executes("gradient")
def gradient_exec(ctx, args):
    return run_exec(ctx, args, True)


@command("hatchpick", group="draw", label="Hatch Pick", description="Collect dialog picks for hatch without changing the drawing.", menu="", undoable=False, repeatable=False)
def hatchpick(ctx):
    mem = ctx.mem.setdefault("hatchpick", {"points": [], "objects": [], "origin": None, "hatch": None})
    while True:
        r = yield ctx.keyword("Enter a pick option", ["Points", "Objects", "oRigin", "Hatch"], "Points")
        if r.kind != "keyword":
            return
        k = r.value
        if k == "Points":
            while True:
                q = yield ctx.point("Pick internal point")
                if q.kind != "point":
                    break
                mem["points"].append([q.value[0], q.value[1]])
        elif k == "Objects":
            while True:
                q = yield ctx.entity("Select objects")
                if q.kind != "entity":
                    break
                mem["objects"].append(q.value["handle"])
        elif k == "oRigin":
            q = yield ctx.point("Specify the pattern origin")
            if q.kind == "point":
                mem["origin"] = [q.value[0], q.value[1]]
        else:
            q = yield ctx.entity("Select hatch object")
            if q.kind == "entity":
                ent = ctx.d.get(q.value["handle"])
                if ent is not None and ent.kind == "hatch":
                    mem["hatch"] = ent.handle
                else:
                    ctx.say("That object is not a hatch.")
        ctx.say("Picks kept: %d points, %d objects." % (len(mem["points"]), len(mem["objects"])))
        return


@executes("hatchpick")
def hatchpick_exec(ctx, args):
    mem = ctx.mem.setdefault("hatchpick", {"points": [], "objects": [], "origin": None, "hatch": None})
    if args.get("clear"):
        mem["points"], mem["objects"], mem["origin"], mem["hatch"] = [], [], None, None
    for p in args.get("points") or []:
        mem["points"].append([float(p[0]), float(p[1])])
    for h in args.get("handles") or []:
        mem["objects"].append(int(h))
    if args.get("origin") is not None:
        o = args["origin"]
        mem["origin"] = [float(o[0]), float(o[1])]
    if args.get("hatch") is not None:
        mem["hatch"] = int(args["hatch"])
    st = HS.read_settings(ctx)
    if args.get("style") is not None:
        st.island = HS.parse_style(args["style"])
    found = 0
    for p in mem["points"]:
        found += 1 if L.detect_at(ctx.doc, p, st.island, st.gap) else 0
    return {"points": list(mem["points"]), "handles": list(mem["objects"]), "origin": mem["origin"], "hatch": mem["hatch"], "boundaries": found}


@command("hatch.patterns", group="draw", label="Hatch Patterns", description="Load or clear user hatch pattern files.", menu="", undoable=False, repeatable=False)
def hatch_patterns(ctx):
    r = yield ctx.word("Enter a pattern file path", ["Clear", "List"])
    if r.kind == "keyword":
        if r.value == "Clear":
            ctx.say("%d user pattern(s) cleared." % patterns.clear())
        else:
            info = patterns.listing()
            ctx.say("Built-in: " + ", ".join(info["standard"]))
            ctx.say("User: " + (", ".join(info["user"]) if info["user"] else "none"))
        return
    if r.kind != "text":
        return
    try:
        res = patterns.load(str(r.value))
    except patterns.PatternError as err:
        raise CommandError(str(err))
    ctx.say("Loaded: " + (", ".join(res["added"]) if res["added"] else "none"))
    for w in res["warnings"]:
        ctx.say(w)


@executes("hatch.patterns")
def hatch_patterns_exec(ctx, args):
    out = {"added": [], "warnings": []}
    if args.get("clear"):
        patterns.clear()
    src = args.get("path") or args.get("text")
    if src:
        try:
            res = patterns.load(str(src))
        except patterns.PatternError as err:
            raise CommandError(str(err))
        out["added"] = res["added"]
        out["warnings"] = res["warnings"]
    out.update(patterns.listing())
    return out
