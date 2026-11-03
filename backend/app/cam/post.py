import datetime
import json
import math
import os
import re

from app.cam import limits
from app.cam import toolpath as T
from app.cam.limits import CamError
from app.core import config

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
VARS = {"program", "date", "units", "units_code", "tool", "name", "h", "d", "rpm", "code", "f", "x", "y", "z", "a", "b", "c", "i", "j", "k", "r", "q", "p", "seconds", "text", "pos", "line", "slot", "n", "setup", "op"}
TEMPLATE_KEYS = ("header", "footer", "tool_change", "spindle_cw", "spindle_ccw", "spindle_off", "coolant_flood", "coolant_mist", "coolant_off", "rapid", "feed", "arc_cw", "arc_ccw", "dwell", "cycle_start", "cycle_drill", "cycle_dwell", "cycle_peck", "cycle_chip", "cycle_cancel", "wcs", "comp_left", "comp_right", "comp_off", "comment", "stop_optional", "stop_hard", "plane_xy", "plane_zx", "plane_yz", "setup_start", "op_start")
LIST_KEYS = ("header", "footer", "tool_change", "setup_start", "op_start")
CAP_KEYS = {"arcs": bool, "helix": bool, "cycles": list, "cutter_comp": bool, "tool_length": bool, "tool_change": bool, "wcs": list, "rotary": bool, "planes": bool, "line_numbers": bool, "feed_modal": bool, "laser": bool}
TOKEN = re.compile(r"\{([a-z_]+)\}")
EXPANDERS: dict = {}
EXTRA_VARS: set = set()


class PostError(CamError):
    pass


def shipped_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cam", "posts")


def user_dir() -> str:
    folder = config.data_dir() / "cam" / "posts"
    folder.mkdir(parents=True, exist_ok=True)
    return str(folder)


def register_expander(name: str, fn) -> None:
    EXPANDERS[name] = fn


def register_variable(name: str) -> None:
    EXTRA_VARS.add(name)


def check_template(key: str, text) -> None:
    if not isinstance(text, str):
        raise PostError("Template %s must be text." % key)
    depth = 0
    for ch in text:
        if ch == "[":
            depth += 1
            if depth > 1:
                raise PostError("Template %s nests optional parts; use one level." % key)
        elif ch == "]":
            depth -= 1
            if depth < 0:
                raise PostError("Template %s has a closing bracket with no opening." % key)
    if depth != 0:
        raise PostError("Template %s has an unclosed optional part." % key)
    for name in TOKEN.findall(text):
        if name not in VARS and name not in EXTRA_VARS:
            raise PostError("Template %s uses an unknown variable {%s}." % (key, name))
    stripped = TOKEN.sub("", text).replace("[", "").replace("]", "")
    if "{" in stripped or "}" in stripped:
        raise PostError("Template %s has an unmatched brace." % key)


def validate(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise PostError("A post is an object.")
    pid = spec.get("id")
    if not isinstance(pid, str) or not ID_RE.match(pid):
        raise PostError("A post id is 1 to 40 lowercase letters, digits, dashes or underscores.")
    out = {"id": pid, "name": str(spec.get("name") or pid)[:80], "version": 1, "extension": str(spec.get("extension") or ".nc"), "description": str(spec.get("description") or "")[:300]}
    if not re.match(r"^\.[a-z0-9]{1,5}$", out["extension"]):
        raise PostError("The file extension must look like .nc.")
    caps = spec.get("caps") or {}
    outc = {}
    for k, typ in CAP_KEYS.items():
        v = caps.get(k, False if typ is bool else [])
        if not isinstance(v, typ):
            raise PostError("Capability %s has the wrong type." % k)
        outc[k] = v
    outc["cycles"] = [c for c in outc["cycles"] if c in ("drill", "dwell", "peck", "chip")]
    outc["wcs"] = [int(s) for s in outc["wcs"] if isinstance(s, int) and 1 <= s <= 9]
    out["caps"] = outc
    num = spec.get("number") or {}
    dec = num.get("decimals", 3)
    adec = num.get("arc_decimals", 4)
    if not (isinstance(dec, int) and isinstance(adec, int) and 0 <= dec <= 6 and 0 <= adec <= 6):
        raise PostError("Decimals must be whole numbers from 0 to 6.")
    out["number"] = {"decimals": dec, "arc_decimals": adec, "trim": bool(num.get("trim", True))}
    axes = {"x": "X", "y": "Y", "z": "Z", "a": "A", "b": "B", "c": "C"}
    axes.update(spec.get("axes") or {})
    for k, v in axes.items():
        if not isinstance(v, str) or not re.match(r"^[A-Za-z]$", v):
            raise PostError("Axis letters are single letters.")
    out["axes"] = axes
    codes = spec.get("wcs_codes") or ["G54", "G55", "G56", "G57", "G58", "G59", "G59.1", "G59.2", "G59.3"]
    if not isinstance(codes, list) or not all(isinstance(c, str) and len(c) < 12 for c in codes):
        raise PostError("WCS codes are a list of short strings.")
    out["wcs_codes"] = codes
    uc = spec.get("units_codes") or {"mm": "G21", "in": "G20"}
    out["units_codes"] = {"mm": str(uc.get("mm", "G21")), "in": str(uc.get("in", "G20"))}
    tpl = spec.get("templates")
    if not isinstance(tpl, dict):
        raise PostError("A post needs templates.")
    ot = {}
    for k, v in tpl.items():
        if k not in TEMPLATE_KEYS:
            raise PostError("%s is not a template name." % k)
        if k in LIST_KEYS:
            if isinstance(v, str):
                v = [v]
            if not isinstance(v, list):
                raise PostError("Template %s must be a list of lines." % k)
            for line in v:
                check_template(k, line)
            if len(v) > 200:
                raise PostError("Template %s has too many lines." % k)
        else:
            check_template(k, v)
        ot[k] = v
    for need in ("rapid", "feed"):
        if need not in ot:
            raise PostError("A post needs a %s template." % need)
    if outc["arcs"] and not (("arc_cw" in ot) and ("arc_ccw" in ot)):
        raise PostError("A post with arcs needs arc_cw and arc_ccw templates.")
    for kind in outc["cycles"]:
        if "cycle_" + kind not in ot:
            raise PostError("The cycle %s needs a cycle_%s template." % (kind, kind))
    out["templates"] = ot
    for extra in ("laser_power",):
        if extra in spec:
            out[extra] = spec[extra]
    return out


def _read(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return validate(json.load(fh))
    except (OSError, ValueError) as err:
        raise PostError("The post file %s cannot be read: %s" % (os.path.basename(path), err))


def list_posts() -> list:
    out = {}
    for folder, source in ((shipped_dir(), "shipped"), (user_dir(), "user")):
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not name.endswith(".json"):
                continue
            try:
                spec = _read(os.path.join(folder, name))
            except PostError:
                continue
            if spec["id"] in out and source == "user":
                continue
            out[spec["id"]] = {"id": spec["id"], "name": spec["name"], "extension": spec["extension"], "description": spec["description"], "source": source, "caps": spec["caps"]}
    return list(out.values())


def load(pid: str) -> dict:
    if not ID_RE.match(str(pid)):
        raise PostError("There is no post called %s." % pid)
    for folder in (shipped_dir(), user_dir()):
        path = os.path.join(folder, pid + ".json")
        if os.path.isfile(path):
            return _read(path)
    raise PostError("There is no post called %s." % pid)


def load_raw(pid: str) -> dict:
    spec = load(pid)
    spec["source"] = "shipped" if os.path.isfile(os.path.join(shipped_dir(), pid + ".json")) else "user"
    return spec


def save_user(spec: dict) -> dict:
    clean = validate(spec)
    if os.path.isfile(os.path.join(shipped_dir(), clean["id"] + ".json")):
        raise PostError("%s is a shipped post and cannot be replaced; give your copy another id." % clean["id"])
    path = os.path.join(user_dir(), clean["id"] + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=1)
    os.replace(tmp, path)
    return clean


def delete_user(pid: str) -> None:
    if os.path.isfile(os.path.join(shipped_dir(), pid + ".json")):
        raise PostError("A shipped post cannot be removed.")
    path = os.path.join(user_dir(), pid + ".json") if ID_RE.match(pid) else ""
    if not path or not os.path.isfile(path):
        raise PostError("There is no user post called %s." % pid)
    os.remove(path)


def render(key: str, text: str, vars_: dict) -> str:
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "[":
            j = text.index("]", i)
            seg = text[i + 1 : j]
            drop = False

            def sub(m):
                nonlocal drop
                v = vars_.get(m.group(1))
                if v is None or v == "":
                    drop = True
                    return ""
                return str(v)

            r = TOKEN.sub(sub, seg)
            if not drop:
                out.append(r)
            i = j + 1
        else:
            j = i
            while j < n and text[j] != "[":
                j += 1
            out.append(TOKEN.sub(lambda m: "" if vars_.get(m.group(1)) is None else str(vars_.get(m.group(1))), text[i:j]))
            i = j
    return re.sub(r"\s+$", "", "".join(out))


class Writer:
    def __init__(self, spec: dict, options: dict):
        self.spec = spec
        self.caps = spec["caps"]
        self.tpl = spec["templates"]
        self.opt = options
        self.units = options.get("units", "mm")
        self.scale = 1.0 if self.units == "mm" else 1.0 / 25.4
        self.lines: list = []
        self.warnings: list = []
        self.last: dict = {}
        self.last_f = None
        self.plane = "xy"
        self.in_cycle = False
        self.n = 0
        self.nstep = int(options.get("line_step", 10))
        self.numbers = bool(options.get("line_numbers", self.caps["line_numbers"]))
        self.base = {"program": str(options.get("program") or "FORMCAD")[:60], "date": str(options.get("date") or ""), "units": self.units, "units_code": spec["units_codes"][self.units]}

    def fmt(self, v: float, arc: bool = False) -> str:
        dec = self.spec["number"]["arc_decimals"] if arc else self.spec["number"]["decimals"]
        if self.units == "in":
            dec = min(dec + 1, 6)
        s = "%.*f" % (dec, v * self.scale)
        if s.startswith("-") and float(s) == 0.0:
            s = s[1:]
        if self.spec["number"]["trim"] and "." in s:
            s = s.rstrip("0").rstrip(".")
            if s in ("", "-"):
                s = "0"
        return s

    def put(self, key: str, vars_=None, extra=None) -> None:
        text = self.tpl.get(key)
        if text is None:
            return
        v = dict(self.base)
        v.update(vars_ or {})
        for t in text if isinstance(text, list) else [text]:
            line = render(key, t, v)
            if line == "":
                continue
            self.emit(line)

    def emit(self, line: str) -> None:
        if self.numbers and not line.startswith(("%", "(", ";")):
            self.n += self.nstep
            line = "N%d %s" % (self.n, line)
        self.lines.append(line)

    def pos_words(self, target: dict) -> str:
        words = []
        ax = self.spec["axes"]
        for k in ("x", "y", "z", "a", "b", "c"):
            if k not in target:
                continue
            s = self.fmt(target[k]) if k in "xyz" else ("%.*f" % (self.spec["number"]["decimals"], target[k])).rstrip("0").rstrip(".")
            if self.last.get(k) != s:
                words.append(ax[k] + s)
                self.last[k] = s
        return " ".join(words)

    def reset_modal(self) -> None:
        self.last = {}
        self.last_f = None


def clean_text(text: str) -> str:
    t = re.sub(r"[()\r\n;%]", " ", str(text))
    t = "".join(c if 32 <= ord(c) < 127 else "?" for c in t)
    return re.sub(r"\s+", " ", t).strip()[:80]


def expand_arcs(moves: list, tol: float) -> list:
    out = []
    pos = None
    for m in moves:
        if m[0] == "arc" and pos is not None:
            opts = T.opts_of(m)
            for p in T.arc_points(pos, m, tol):
                n = ["feed", p[0], p[1], p[2], m[8]]
                if opts:
                    n.append(opts)
                out.append(n)
            pos = tuple(m[2:5])
            continue
        out.append(m)
        if m[0] in ("rapid", "feed"):
            pos = tuple(m[1:4])
        elif m[0] == "arc":
            pos = tuple(m[2:5])
        elif m[0] == "cycle":
            pos = (m[2], m[3], m[5])
    return out


def expand_cycles(moves: list, allowed: list) -> list:
    out = []
    pos = None
    for m in moves:
        if m[0] == "cycle" and m[1] not in allowed:
            _, kind, x, y, zb, r, q, p, f = m[:9]
            z0 = pos[2] if pos is not None else r
            top = max(z0, r)
            out.append(["rapid", x, y, top])
            if top > r + 1e-9:
                out.append(["rapid", x, y, r])
            if kind in ("drill", "dwell"):
                out.append(["feed", x, y, zb, f, {"k": "plunge"}])
                if kind == "dwell" and p:
                    out.append(["dwell", p])
            else:
                z = r
                step = q if q and q > 0 else (r - zb)
                while z > zb + 1e-9:
                    nz = max(z - step, zb)
                    if z < r - 1e-9:
                        out.append(["rapid", x, y, z + 0.254] if kind == "peck" else ["rapid", x, y, z])
                    out.append(["feed", x, y, nz, f, {"k": "plunge"}])
                    if kind == "chip" and nz > zb + 1e-9:
                        out.append(["rapid", x, y, nz + 0.5])
                        out.append(["rapid", x, y, nz])
                    elif kind == "peck" and nz > zb + 1e-9:
                        out.append(["rapid", x, y, r])
                    z = nz
            out.append(["rapid", x, y, r])
            pos = (x, y, r)
            continue
        out.append(m)
        if m[0] in ("rapid", "feed"):
            pos = tuple(m[1:4])
        elif m[0] == "arc":
            pos = tuple(m[2:5])
        elif m[0] == "cycle":
            pos = (m[2], m[3], m[5])
    return out


def generate(items: list, post_id: str, options=None) -> dict:
    spec = load(post_id)
    opt = dict(options or {})
    if opt.get("units", "mm") not in ("mm", "in"):
        raise PostError("Units must be mm or in.")
    w = Writer(spec, opt)
    caps = spec["caps"]
    arc_tol = float(opt.get("arc_tolerance", 0.005))
    w.put("header")
    cur_setup = None
    last_tool = None
    comments = opt.get("comments", True)
    total_moves = 0
    for item in items:
        setup = item["setup"]
        op = item["op"]
        moves = [list(m) for m in item["toolpath"].moves]
        total_moves += len(moves)
        limits.need(total_moves, "moves", "Post input")
        if not caps["arcs"]:
            moves = expand_arcs(moves, arc_tol)
        moves = expand_cycles(moves, caps["cycles"])
        for name, fn in EXPANDERS.items():
            moves = fn(moves, spec, opt) or moves
        if cur_setup != setup["id"]:
            slot = int(setup["wcs"].get("slot", 1))
            if caps["wcs"] and slot not in caps["wcs"]:
                raise PostError("%s cannot select work coordinate slot %d (it has %d to %d)." % (spec["name"], slot, min(caps["wcs"]), max(caps["wcs"])))
            if not caps["wcs"] and slot != 1:
                raise PostError("%s has no work coordinate selection." % spec["name"])
            if comments:
                w.put("comment", {"text": clean_text("Setup %s %s" % (setup["id"], setup.get("label") or ""))})
            w.put("setup_start", {"setup": setup["id"], "slot": slot})
            if caps["wcs"]:
                w.put("wcs", {"code": spec["wcs_codes"][slot - 1], "slot": slot})
            w.reset_modal()
            cur_setup = setup["id"]
        w.put("op_start", {"op": op["id"]})
        pos = None
        for m in moves:
            kind = m[0]
            if kind in ("rapid", "feed"):
                if w.in_cycle:
                    w.put("cycle_cancel")
                    w.in_cycle = False
                tgt = {"x": m[1], "y": m[2], "z": m[3]}
                opts = T.opts_of(m)
                if opts.get("abc") and caps["rotary"]:
                    tgt.update({"a": opts["abc"][0], "b": opts["abc"][1], "c": opts["abc"][2]})
                elif opts.get("abc") or opts.get("ax") and any(abs(v) > 1e-9 for v in (opts.get("ax") or [0, 0, 1])[:2]):
                    raise PostError("%s has no rotary axes; this toolpath uses a tilted tool." % spec["name"])
                words = w.pos_words(tgt)
                if kind == "rapid":
                    if words:
                        w.put("rapid", {"pos": words})
                else:
                    if not words:
                        pos = tuple(m[1:4])
                        continue
                    fs = w.fmt(m[4]) if (not caps["feed_modal"] or w.last_f != m[4]) else ""
                    w.last_f = m[4]
                    w.put("feed", {"pos": words, "f": fs})
                pos = tuple(m[1:4])
            elif kind == "arc":
                if w.in_cycle:
                    w.put("cycle_cancel")
                    w.in_cycle = False
                plane = m[9]
                if plane != "xy" and not caps["planes"]:
                    raise PostError("%s cannot arc outside the XY plane." % spec["name"])
                if plane != w.plane:
                    w.put("plane_" + plane)
                    w.plane = plane
                if pos is None:
                    raise PostError("An arc cannot be the first move.")
                if abs(m[4] - pos[2]) > 1e-9 and plane == "xy" and not caps["helix"]:
                    raise PostError("%s cannot cut helical arcs." % spec["name"])
                words = w.pos_words({"x": m[2], "y": m[3], "z": m[4]})
                ia, ib = {"xy": (0, 1), "zx": (2, 0), "yz": (1, 2)}[plane]
                offs = [m[5 + q] - pos[q] for q in range(3)]
                vars_ = {"pos": words, "i": "", "j": "", "k": ""}
                for q, letter in enumerate("ijk"):
                    if q in (ia, ib):
                        vars_[letter] = w.fmt(offs[q], True)
                fs = w.fmt(m[8]) if (not caps["feed_modal"] or w.last_f != m[8]) else ""
                w.last_f = m[8]
                vars_["f"] = fs
                w.put("arc_cw" if m[1] == "cw" else "arc_ccw", vars_)
                pos = tuple(m[2:5])
            elif kind == "cycle":
                _, ck, x, y, zb, r, q, p, f = m[:9]
                if not w.in_cycle:
                    w.put("cycle_start")
                w.in_cycle = True
                fs = w.fmt(f) if (not caps["feed_modal"] or w.last_f != f) else ""
                w.last_f = f
                w.put("cycle_" + ck, {"x": w.fmt(x), "y": w.fmt(y), "z": w.fmt(zb), "r": w.fmt(r), "q": w.fmt(q) if q else "", "p": ("%g" % p) if p else "", "seconds": ("%g" % p) if p else "", "f": fs})
                w.last["x"] = w.fmt(x)
                w.last["y"] = w.fmt(y)
                w.last["z"] = w.fmt(r)
                pos = (x, y, r)
            elif kind == "dwell":
                w.put("dwell", {"seconds": "%g" % m[1]})
            elif kind == "tool":
                if w.in_cycle:
                    w.put("cycle_cancel")
                    w.in_cycle = False
                tool_rec = item.get("tool") or {}
                if comments:
                    w.put("comment", {"text": clean_text("T%d %s" % (m[1], m[3]))})
                if caps["tool_change"] or "tool_change" in w.tpl:
                    w.put("tool_change", {"tool": m[1], "name": clean_text(m[3]), "h": tool_rec.get("length_offset", m[1]), "d": tool_rec.get("diameter_offset", m[1]), "rpm": "%g" % m[2]})
                last_tool = m[1]
                w.reset_modal()
            elif kind == "spindle":
                if m[2] == "off":
                    w.put("spindle_off")
                else:
                    w.put("spindle_cw" if m[2] == "cw" else "spindle_ccw", {"rpm": "%g" % m[1]})
            elif kind == "coolant":
                w.put({"flood": "coolant_flood", "mist": "coolant_mist", "off": "coolant_off"}[m[1]])
            elif kind == "wcs":
                w.put("wcs", {"code": spec["wcs_codes"][int(m[1]) - 1], "slot": int(m[1])})
                w.reset_modal()
            elif kind == "comp":
                if not caps["cutter_comp"]:
                    raise PostError("%s cannot do cutter compensation; use computer compensation on the operation." % spec["name"])
                w.put("comp_off" if m[1] == "off" else "comp_left" if m[1] == "left" else "comp_right", {"d": m[2]})
            elif kind == "comment":
                if comments:
                    w.put("comment", {"text": clean_text(m[1])})
            elif kind == "stop":
                w.put("stop_optional" if m[1] == "optional" else "stop_hard")
            elif kind == "raw":
                if w.in_cycle:
                    w.put("cycle_cancel")
                    w.in_cycle = False
                w.emit(str(m[1]))
                w.reset_modal()
            else:
                raise PostError("The post does not know the move type %s." % kind)
    if w.in_cycle:
        w.put("cycle_cancel")
    w.put("footer")
    limits.need(len(w.lines), "export_lines", "Program")
    text = "\n".join(w.lines) + "\n"
    return {"text": text, "lines": len(w.lines), "warnings": w.warnings, "extension": spec["extension"], "post": spec["id"], "units": w.units}
