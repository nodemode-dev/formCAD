import math

from app.cam import post
from app.cam.post import PostError
from app.probing import expr as E

PROBE_CODES = {"g38.2": "G38.2", "g38.3": "G38.3", "g38.4": "G38.4", "g38.5": "G38.5"}
MILL_AXES = {"x": "X", "y": "Y", "z": "Z"}


def is_lathe(spec) -> bool:
    pid = spec["id"]
    return pid.startswith("lathe") or pid.endswith("_lathe")


def allows_lathe(spec) -> bool:
    return is_lathe(spec) or spec["id"].startswith("millturn")


def is_grbl(spec) -> bool:
    return "grbl" in spec["id"]


def fmt_for(spec):
    dec = spec["number"]["decimals"]
    trim = spec["number"]["trim"]

    def fmt(v):
        s = "%.*f" % (dec, v)
        if s.startswith("-") and float(s) == 0.0:
            s = s[1:]
        if trim and "." in s:
            s = s.rstrip("0").rstrip(".")
            if s in ("", "-"):
                s = "0"
        return s

    return fmt


def opts_of(m):
    return m[-1] if isinstance(m[-1], dict) else {}


def lathe_lines(moves, spec, opt):
    fmt = fmt_for(spec)
    dia = bool(opt.get("diameter_mode", True))
    out = []
    started = False
    last = {}
    for m in moves:
        k = m[0]
        o = opts_of(m)
        if k in ("rapid", "feed"):
            if not started:
                out.append(["raw", "G7" if dia else "G8"])
                out.append(["raw", "G95"])
                started = True
            x = m[1] * (2.0 if dia else 1.0)
            z = m[3]
            words = []
            for letter, val in (("X", x), ("Z", z)):
                s = fmt(val)
                if last.get(letter) != s:
                    words.append(letter + s)
                    last[letter] = s
            if k == "rapid":
                if words:
                    out.append(["raw", "G0 " + " ".join(words)])
                continue
            if "fpr" not in o:
                raise PostError("%s is a lathe post; this move has no feed per revolution. Use turning operations with it." % spec["name"])
            if "sync" in o:
                out.append(["raw", "G33 %s K%s" % (" ".join(words) if words else "X%s Z%s" % (fmt(x), fmt(z)), fmt(o["sync"]))])
                last["F"] = None
                continue
            fs = fmt(o["fpr"])
            if not words and last.get("F") == fs:
                continue
            line = "G1 " + " ".join(words)
            if last.get("F") != fs:
                line += " F" + fs
                last["F"] = fs
            out.append(["raw", line.strip()])
        elif k == "spindle" and m[2] != "off":
            css = o.get("css")
            mcode = "M3" if m[2] == "cw" else "M4"
            if css:
                out.append(["raw", "G96 D%s S%s %s" % (fmt(css["max_rpm"]), fmt(css["vc"]), mcode)])
            else:
                out.append(["raw", "G97 S%s %s" % (fmt(m[1]), mcode)])
            last["F"] = None
        elif k == "arc":
            raise PostError("%s writes straight moves only; arcs are not used by the turning operations." % spec["name"])
        else:
            if k == "tool":
                started = False
                last = {}
            out.append(m)
    return out


def live_lines(moves, spec, opt):
    fmt = fmt_for(spec)
    dia = bool(opt.get("diameter_mode", True))
    out = [["raw", "G7" if dia else "G8"], ["raw", "G94"]]
    for m in moves:
        o = opts_of(m)
        live = o.get("live")
        if m[0] in ("rapid", "feed") and live:
            a = math.radians(live["c"])
            r = m[1] * math.cos(a) + m[2] * math.sin(a)
            x = r * (2.0 if dia else 1.0)
            words = "X%s Z%s C%s" % (fmt(x), fmt(m[3]), fmt(live["c"]))
            if m[0] == "rapid":
                out.append(["raw", "G0 " + words])
            else:
                out.append(["raw", "G1 %s F%s" % (words, fmt(m[4]))])
        elif m[0] == "arc" and live:
            raise PostError("Live tool operations write straight moves only.")
        else:
            out.append(m)
    return out


def expr_word(letter, ex, val, fmt):
    if ex is not None:
        return letter + E.to_ngc(ex)
    return letter + fmt(val)


def probe_lines(moves, spec, opt):
    fmt = fmt_for(spec)
    grbl = is_grbl(spec)
    out = []
    for m in moves:
        k = m[0]
        o = opts_of(m)
        if k in ("rapid", "feed") and (o.get("probe") or o.get("expr")):
            ex = o.get("expr") or {}
            words = " ".join(expr_word(a.upper(), ex.get(a), m[1 + i], fmt) for i, a in enumerate("xyz"))
            if o.get("probe"):
                out.append(["raw", "%s %s F%s" % (PROBE_CODES[o["probe"]], words, fmt(m[4]))])
                name = o.get("store")
                if name and not grbl:
                    for ax, num in zip("xyz", (5061, 5062, 5063)):
                        out.append(["raw", "#<_%s_%s> = #%d" % (name, ax, num)])
            elif k == "rapid":
                out.append(["raw", "G0 " + words])
            else:
                out.append(["raw", "G1 %s F%s" % (words, fmt(m[4]))])
        elif k == "param":
            if grbl:
                out.append(["raw", "(%s = %s, computed by the sender from the probe report)" % (m[1], E.to_ngc(m[2]))])
            else:
                out.append(["raw", "#<_%s> = %s" % (m[1], E.to_ngc(m[2]))])
        elif k == "wcs_set":
            if grbl:
                out.append(["raw", "(set work offset P%d: %s)" % (m[1], ", ".join("%s=%s" % (a.upper(), E.to_ngc(v)) for a, v in m[2].items()))])
            else:
                words = " ".join("%s%s" % (a.upper(), E.to_ngc(v)) for a, v in m[2].items())
                out.append(["raw", "G10 L2 P%d %s" % (m[1], words)])
        else:
            out.append(m)
    return out


def expand(moves, spec, opt):
    uses_probe = any(m[0] in ("param", "wcs_set") or opts_of(m).get("probe") or opts_of(m).get("expr") for m in moves)
    uses_lathe = any(opts_of(m).get("fpr") is not None for m in moves)
    uses_live = any(opts_of(m).get("live") for m in moves)
    if not uses_probe and not uses_lathe and not uses_live and not is_lathe(spec):
        return None
    if opt.get("units", "mm") != "mm":
        raise PostError("Turning and probing programs are written in millimetres only.")
    cur = moves
    if uses_live:
        if not allows_lathe(spec):
            raise PostError("%s cannot index the part with a C axis; pick a post whose id starts with millturn." % spec["name"])
        cur = live_lines(cur, spec, opt)
    if uses_lathe:
        if not allows_lathe(spec):
            raise PostError("%s is not a lathe post; pick a post whose id starts with lathe or millturn." % spec["name"])
        cur = lathe_lines(cur, spec, opt)
    elif is_lathe(spec) and not uses_probe:
        if any(m[0] in ("rapid", "feed") for m in cur):
            raise PostError("%s is a lathe post; this operation has no feed per revolution." % spec["name"])
    if uses_probe:
        cur = probe_lines(cur, spec, opt)
    return cur


post.register_expander("turning_probing", expand)
