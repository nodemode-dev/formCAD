import math
import re
from dataclasses import replace

from app.cmd import jig, prompts, units
from app.cmd.prompts import Input, InputError, Prompt
from app.lisp.registry import bad_type, fn, string
from app.lisp.types import EName, MISSING, from_list, mkpoint, point_of

BIT_NONULL = 1
BIT_NOZERO = 2
BIT_NONEG = 4
BIT_NOZ = 64
BIT_TEXT = 128


@fn("initget", 0, 2)
def f_initget(L, *args):
    bits = 0
    kw = ""
    if args:
        if type(args[0]) is str:
            kw = args[0]
        elif type(args[0]) is int:
            bits = args[0]
            if len(args) > 1:
                kw = string(args[1]) if args[1] is not None else ""
        elif args[0] is not None:
            raise bad_type("fixnump", args[0])
    L.init_bits = bits
    L.init_kw = kw
    return None


def parse_keywords(text: str) -> list:
    out = []
    names = []
    for tok in text.split():
        if tok.startswith("_") and len(tok) > 1:
            continue
        full, _, short = tok.partition(",")
        if full:
            out.append((full, short))
            names.append(full)
    return out


def match_kw(kws: list, text: str):
    t = text.strip()
    if t.startswith("_"):
        t = t[1:]
    if not t:
        return None
    low = t.lower()
    for full, short in kws:
        if low == full.lower() or (short and low == short.lower()):
            return full
    for full, short in kws:
        lead = ""
        for ch in full:
            if ch.isupper():
                lead += ch
            else:
                break
        if lead and len(low) >= len(lead) and low.startswith(lead.lower()) and full.lower().startswith(low):
            return full
    return None


def take_init(L):
    bits, kw = L.init_bits, L.init_kw
    L.init_bits = 0
    L.init_kw = ""
    return bits, parse_keywords(kw)


def _generic(p: Prompt, text: str, env, kws, bits):
    t = text.strip()
    if t == "":
        return ("input", Input("enter"))
    kw = match_kw(kws, t)
    if kw:
        return ("input", Input("keyword", kw, text=t))
    try:
        return prompts.resolve(replace(p, parse=None, options=[]), text, env)
    except InputError as err:
        if bits & BIT_TEXT:
            return ("input", Input("text", t, text=t))
        m = str(err)
        if m in ("Point or option keyword required.", "Invalid input.", "Invalid point."):
            raise InputError("Invalid option keyword." if kws and p.kind() == "keyword" else "Invalid point.")
        raise


def point_parser(kws, bits):
    def parse(p, text, env):
        return _generic(p, text, env, kws, bits)

    return parse


def dist_parser(kws, bits):
    def parse(p, text, env):
        try:
            return _generic(p, text, env, kws, bits)
        except InputError as err:
            if str(err) in ("Invalid point.", "Requires numeric distance or a point."):
                raise InputError("Requires numeric distance or two points.")
            raise

    return parse


def angle_parser(kws, bits):
    def parse(p, text, env):
        try:
            return _generic(p, text, env, kws, bits)
        except InputError as err:
            if str(err) in ("Invalid point.", "Requires numeric distance or a point."):
                raise InputError("Requires valid numeric angle or second point.")
            raise

    return parse


def number_parser(kind, kws, bits):
    def parse(p, text, env):
        t = text.strip()
        if t == "":
            return ("input", Input("enter"))
        kw = match_kw(kws, t)
        if kw:
            return ("input", Input("keyword", kw, text=t))
        if kind == "int":
            if re.fullmatch(r"[+-]?\d+", t):
                v = int(t)
                if v < -32768 or v > 32767:
                    raise InputError("Value must be between -32768 and 32767.")
                return ("input", Input("number", v, text=t))
            if bits & BIT_TEXT:
                return ("input", Input("text", t, text=t))
            raise InputError("Requires an integer value.")
        v = units.parse_distance(t)
        if v is None:
            if bits & BIT_TEXT:
                return ("input", Input("text", t, text=t))
            raise InputError("Requires numeric value.")
        return ("input", Input("number", v, text=t))

    return parse


def keyword_parser(kws, bits):
    def parse(p, text, env):
        t = text.strip()
        if t == "":
            return ("input", Input("enter"))
        kw = match_kw(kws, t)
        if kw:
            return ("input", Input("keyword", kw, text=t))
        if bits & BIT_TEXT:
            return ("input", Input("text", t, text=t))
        raise InputError("Invalid option keyword.")

    return parse


def _prompt(msg, accepts, kws, parse, base=None, **kw) -> Prompt:
    return Prompt(msg if isinstance(msg, str) else "", accepts, [f for f, _ in kws], None, "", base, hint="raw", parse=parse, **kw)


def _msg(p):
    if p is None:
        return ""
    if type(p) is not str:
        raise bad_type("stringp", p)
    return p


def _base(b):
    if b is None:
        return None
    p = point_of(b)
    if p is None:
        raise bad_type("2D/3D point", b)
    return p


def _checks(bits, v, L) -> bool:
    if bits & BIT_NOZERO and v == 0:
        L.ctx.say("Value must be nonzero.")
        return False
    if bits & BIT_NONEG and v < 0:
        L.ctx.say("Value must be positive.")
        return False
    return True


def _ask_point(L, prompt, bits, kws):
    while True:
        inp = L.ctx.ask(prompt)
        if inp is None:
            return MISSING
        if inp.kind == "enter":
            if bits & BIT_NONULL:
                continue
            return None
        return inp


def _gp(L, prompt: Prompt, bits, kws):
    inp = _ask_point(L, prompt, bits, kws)
    if inp is MISSING:
        return None
    if inp is None:
        return None
    if inp.kind == "point":
        return mkpoint([inp.value[0], inp.value[1], inp.value[2] if len(inp.value) > 2 else 0.0])
    if inp.kind in ("keyword", "text"):
        return inp.value
    if inp.kind == "number":
        return None
    return None


@fn("getpoint", 0, 2)
def f_getpoint(L, a=None, b=None):
    base = None
    msg = ""
    if type(a) is str or a is None:
        msg = _msg(a)
    else:
        base = _base(a)
        msg = _msg(b)
    bits, kws = take_init(L)
    p = _prompt(msg, ("point",) + (("text",) if bits & BIT_TEXT else ()), kws, point_parser(kws, bits), base)
    if base is not None:
        p.jig = lambda cur, b0=base: jig.rubber(b0, cur)
    return _gp(L, p, bits, kws)


@fn("getcorner", 1, 2)
def f_getcorner(L, base, msg=None):
    b = _base(base)
    bits, kws = take_init(L)
    p = _prompt(_msg(msg), ("point",), kws, point_parser(kws, bits), b, rect_corner=True)
    p.jig = lambda cur, b0=b: [jig.poly([[b0[0], b0[1]], [cur[0], b0[1]], [cur[0], cur[1]], [b0[0], cur[1]]], True)]
    return _gp(L, p, bits, kws)


def _second_point(L, first, bits, kws, label="Second point"):
    p = _prompt(label, ("point",), kws, point_parser(kws, bits), first)
    p.jig = lambda cur, b0=first: jig.rubber(b0, cur)
    inp = _ask_point(L, p, bits, kws)
    if inp is MISSING or inp is None:
        return None
    return inp if inp.kind == "point" else None


@fn("getdist", 0, 2)
def f_getdist(L, a=None, b=None):
    base = None
    if type(a) is str or a is None:
        msg = _msg(a)
    else:
        base = _base(a)
        msg = _msg(b)
    bits, kws = take_init(L)
    while True:
        p = _prompt(msg, ("distance", "point") + (("text",) if bits & BIT_TEXT else ()), kws, dist_parser(kws, bits), base)
        if base is not None:
            p.jig = lambda cur, b0=base: jig.rubber(b0, cur)
        inp = _ask_point(L, p, bits, kws)
        if inp is MISSING or inp is None:
            return None
        if inp.kind in ("keyword", "text"):
            return inp.value
        d = None
        if inp.kind == "number":
            d = float(inp.value)
        elif inp.kind == "point":
            first = base if base is not None else inp.value
            if base is not None:
                second = inp
            else:
                second = _second_point(L, first, bits, kws)
                if second is None:
                    return None
            a_, b_ = first, second.value
            dz = 0.0 if bits & BIT_NOZ else (b_[2] - a_[2] if len(a_) > 2 and len(b_) > 2 else 0.0)
            d = math.sqrt((b_[0] - a_[0]) ** 2 + (b_[1] - a_[1]) ** 2 + dz * dz)
        if d is None:
            return None
        if _checks(bits, d, L):
            return d
        bits_keep = bits
        bits = bits_keep


def _angle(L, a, b, absolute: bool):
    base = None
    if type(a) is str or a is None:
        msg = _msg(a)
    else:
        base = _base(a)
        msg = _msg(b)
    bits, kws = take_init(L)
    h = L.ctx.runner.doc.drawing.header
    angbase, angdir = float(h.get("ANGBASE", 0.0)), int(h.get("ANGDIR", 0))
    while True:
        p = _prompt(msg, ("angle", "point") + (("text",) if bits & BIT_TEXT else ()), kws, angle_parser(kws, bits), base)
        if base is not None:
            p.jig = lambda cur, b0=base: jig.rubber(b0, cur)
        inp = _ask_point(L, p, bits, kws)
        if inp is MISSING or inp is None:
            return None
        if inp.kind in ("keyword", "text"):
            return inp.value
        direction = None
        if inp.kind == "number":
            direction = float(inp.value)
        elif inp.kind == "point":
            first = base if base is not None else inp.value
            if base is not None:
                second = inp
            else:
                second = _second_point(L, first, bits, kws)
                if second is None:
                    return None
            direction = math.atan2(second.value[1] - first[1], second.value[0] - first[0]) % (2 * math.pi)
        if direction is None:
            return None
        val = direction if absolute else units.angle_for_display(direction, angbase, angdir)
        if _checks(bits, val, L):
            return val


@fn("getangle", 0, 2)
def f_getangle(L, a=None, b=None):
    return _angle(L, a, b, False)


@fn("getorient", 0, 2)
def f_getorient(L, a=None, b=None):
    return _angle(L, a, b, True)


def _number(L, msg, kind):
    bits, kws = take_init(L)
    while True:
        p = _prompt(_msg(msg), ("number",) + (("text",) if bits & BIT_TEXT else ()), kws, number_parser(kind, kws, bits))
        inp = _ask_point(L, p, bits, kws)
        if inp is MISSING or inp is None:
            return None
        if inp.kind in ("keyword", "text"):
            return inp.value
        v = inp.value
        if kind == "int":
            v = int(v)
        else:
            v = float(v)
        if _checks(bits, v, L):
            return v


@fn("getreal", 0, 1)
def f_getreal(L, msg=None):
    return _number(L, msg, "real")


@fn("getint", 0, 1)
def f_getint(L, msg=None):
    return _number(L, msg, "int")


@fn("getstring", 0, 2)
def f_getstring(L, a=None, b=None):
    spaces = False
    if type(a) is str or a is None and b is None:
        msg = _msg(a)
    else:
        spaces = a is not None
        msg = _msg(b)
    bits, kws = take_init(L)
    p = Prompt(msg, ("text",), [], None, "", None, free_text=True, hint="raw")
    inp = L.ctx.ask(p)
    if inp is None:
        return None
    if inp.kind == "enter":
        return ""
    s = str(inp.value if inp.kind == "text" else inp.text or inp.value)
    if not spaces:
        s = s.split(" ")[0]
    return s


@fn("getkword", 0, 1)
def f_getkword(L, msg=None):
    bits, kws = take_init(L)
    while True:
        p = _prompt(_msg(msg), ("text",) if bits & BIT_TEXT else (), kws, keyword_parser(kws, bits))
        p.free_text = False
        inp = _ask_point(L, p, bits, kws)
        if inp is MISSING or inp is None:
            return None
        if inp.kind in ("keyword", "text"):
            return inp.value
        return None


def _ent_prompt(L, msg):
    bits, kws = take_init(L)
    p = Prompt(_msg(msg) or "Select object", ("entity",), [f for f, _ in kws], None, "", None, hint="raw")
    p.parse = None
    return p, bits, kws


@fn("entsel", 0, 1)
def f_entsel(L, msg=None):
    p, bits, kws = _ent_prompt(L, msg)
    while True:
        inp = L.ctx.ask(p)
        if inp is None:
            return None
        if inp.kind == "enter":
            if bits & BIT_NONULL:
                continue
            return None
        if inp.kind == "keyword":
            return inp.value
        if inp.kind == "entity":
            v = inp.value
            pt = v.get("point") or [0.0, 0.0]
            return from_list([EName(int(v["handle"])), mkpoint([pt[0], pt[1], pt[2] if len(pt) > 2 else 0.0])])
        return None


@fn("nentsel", 0, 1)
def f_nentsel(L, msg=None):
    return f_entsel(L, msg)
