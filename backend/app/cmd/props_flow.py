from app.cmd.context import CommandError
from app.cmd.prompts import Prompt
from app.doc import props as P

CH_OPTS = ["Color", "LAyer", "LType", "ltScale", "LWeight", "Thickness", "TRansparency"]


def shared_text(ctx, ents, name):
    vals = P.snapshot_values(ctx.d, ents, [name])
    v = vals.get(name)
    if v == "varies":
        return "varies"
    return "" if v is None else str(v)


def editable_split(ctx, handles):
    live = []
    locked = 0
    for h in handles:
        e = ctx.d.get(int(h))
        if e is None:
            continue
        if ctx.locked(e):
            locked += 1
        else:
            live.append(e)
    return live, locked


def say_locked(ctx, n) -> None:
    if n == 1:
        ctx.say("1 was on a locked layer.")
    elif n > 1:
        ctx.say("%d were on a locked layer." % n)


def _apply(ctx, ents, name, value) -> bool:
    try:
        P.apply_changes(ctx.d, ents, {name: value})
    except P.PropError as err:
        ctx.say(str(err))
        return False
    return True


def _ask(ctx, msg, ents, name, options=()):
    return Prompt(msg, ("text",), list(options), None, shared_text(ctx, ents, name))


def ask_triple(ctx):
    while True:
        t = yield Prompt("Enter red,green,blue color", ("text",))
        if t.kind != "text":
            return None
        try:
            return P.parse_triple(t.value)
        except P.PropError as err:
            ctx.say(str(err))


def ask_color(ctx, ents):
    while True:
        r = yield _ask(ctx, "Enter new color", ents, "color", ["Truecolor"])
        if r.kind == "keyword":
            v = yield from ask_triple(ctx)
            if v is None:
                return
        elif r.kind == "text":
            try:
                v = P.parse_typed_color(r.value)
            except P.PropError as err:
                ctx.say(str(err))
                continue
        else:
            return
        if _apply(ctx, ents, "color", v):
            return


def ask_layer(ctx, ents):
    while True:
        r = yield _ask(ctx, "Enter new layer name", ents, "layer")
        if r.kind != "text":
            return
        if _apply(ctx, ents, "layer", r.value.strip()):
            return


def ask_linetype(ctx, ents):
    while True:
        r = yield _ask(ctx, "Enter new linetype name", ents, "linetype")
        if r.kind != "text":
            return
        if _apply(ctx, ents, "linetype", r.value.strip()):
            return


def ask_ltscale(ctx, ents):
    while True:
        r = yield Prompt("Specify new linetype scale", ("number",), [], None, shared_text(ctx, ents, "ltscale"))
        if r.kind != "number":
            return
        if r.value <= 0:
            ctx.say("Value must be positive and nonzero.")
            continue
        if _apply(ctx, ents, "ltscale", r.value):
            return


def ask_lineweight(ctx, ents):
    while True:
        r = yield _ask(ctx, "Enter new lineweight", ents, "lineweight", ["ByLayer", "ByBlock", "Default"])
        if r.kind == "keyword":
            v = r.value
        elif r.kind == "text":
            v = r.value.strip()
        else:
            return
        try:
            w, rounded = P.parse_lineweight(v)
        except P.PropError as err:
            ctx.say(str(err))
            continue
        if rounded:
            ctx.say("Lineweight rounded to nearest valid value of %s mm" % P.lw_text(w))
        if _apply(ctx, ents, "lineweight", w if w < 0 else w / 100.0):
            return


def ask_thickness(ctx, ents):
    r = yield Prompt("Specify new thickness", ("number",), [], None, shared_text(ctx, ents, "thickness"))
    if r.kind == "number":
        _apply(ctx, ents, "thickness", r.value)


def ask_transparency(ctx, ents):
    while True:
        r = yield _ask(ctx, "Enter new transparency value", ents, "transparency", ["ByLayer", "ByBlock"])
        if r.kind == "keyword":
            v = r.value
        elif r.kind in ("text", "number"):
            v = r.value.strip() if r.kind == "text" else r.value
        else:
            return
        if _apply(ctx, ents, "transparency", v):
            return


FLOWS = {"Color": ask_color, "LAyer": ask_layer, "LType": ask_linetype, "ltScale": ask_ltscale, "LWeight": ask_lineweight, "Thickness": ask_thickness, "TRansparency": ask_transparency}


def chprop_loop(ctx, ents, extra=(), extra_flows=None):
    while True:
        r = yield ctx.word("Enter property to change", CH_OPTS + list(extra))
        if r.kind == "text":
            if r.value.strip().lower() in ("l", "lt", "t"):
                ctx.say("Ambiguous response, please clarify...")
            else:
                ctx.say("Invalid option keyword.")
            continue
        if r.kind != "keyword":
            return
        if extra_flows and r.value in extra_flows:
            yield from extra_flows[r.value](ctx, ents)
        else:
            yield from FLOWS[r.value](ctx, ents)


def check_args(args):
    props = args.get("properties")
    if props is None:
        props = {k: v for k, v in args.items() if k not in ("handles", "kind", "skip_locked", "properties")}
    if not isinstance(props, dict) or not props:
        raise CommandError("no properties given")
    return props
