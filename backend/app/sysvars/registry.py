import json
import math
import os
import re
import sys
import threading

from app.doc import events
from app.sysvars.defs import BY_NAME, LW_SET, VARS, VarDef

FROZEN = {"ACADVER"}
COLOR_NAMES = {"red": 1, "yellow": 2, "green": 3, "cyan": 4, "blue": 5, "magenta": 6, "white": 7}
_NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")

_lock = threading.RLock()
_session: dict = {}
_loaded = False


class SysvarError(ValueError):
    pass


def _profile_path():
    try:
        from app.core import config

        return config.data_dir() / "sysvars.json"
    except Exception:
        return None


def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    with _lock:
        if _loaded:
            return
        for v in VARS:
            if v.scope == "session":
                _session[v.name] = v.default
        path = _profile_path()
        if path is not None and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                for name, val in data.items():
                    vd = BY_NAME.get(name)
                    if vd is not None and vd.profile:
                        try:
                            _session[name] = _coerce(vd, val)
                        except SysvarError:
                            pass
            except (OSError, ValueError):
                pass
        _loaded = True


def _save_profile() -> None:
    path = _profile_path()
    if path is None:
        return
    data = {v.name: _session[v.name] for v in VARS if v.profile and v.name in _session}
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def session_value(name: str):
    _ensure_loaded()
    return _session.get(name, BY_NAME[name].default)


def _num(s: str):
    s = s.strip()
    if _NUM.match(s):
        return float(s)
    return None


def parse_color(value):
    if isinstance(value, bool):
        raise SysvarError("bad colour")
    if isinstance(value, int):
        if 0 <= value <= 256:
            return value
        raise SysvarError("bad colour")
    if isinstance(value, float) and value == int(value):
        return parse_color(int(value))
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return "#%02X%02X%02X" % tuple(max(0, min(255, int(c))) for c in value)
    s = str(value).strip().lower()
    if s in ("bylayer", "by layer"):
        return 256
    if s in ("byblock", "by block"):
        return 0
    if s in COLOR_NAMES:
        return COLOR_NAMES[s]
    if re.fullmatch(r"\d{1,3}", s):
        return parse_color(int(s))
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if m:
        return "#" + m.group(1).upper()
    m = re.fullmatch(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})", s)
    if m:
        return parse_color([int(m.group(i)) for i in (1, 2, 3)])
    raise SysvarError("bad colour")


def color_text(c) -> str:
    if c == 256:
        return "ByLayer"
    if c == 0:
        return "ByBlock"
    return str(c)


def parse_point(value):
    if isinstance(value, str):
        parts = [p for p in re.split(r"[,\s]+", value.strip()) if p]
        nums = [_num(p) for p in parts]
    elif isinstance(value, (list, tuple)):
        nums = [float(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else None for p in value]
    else:
        nums = [None]
    if len(nums) not in (2, 3) or any(n is None or not math.isfinite(n) for n in nums):
        raise SysvarError("bad point")
    return [nums[0], nums[1]]


def _coerce(vd: VarDef, value):
    t = vd.type
    if t == "int":
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, str):
            s = value.strip().lower()
            if s in ("true", "on", "yes"):
                return 1
            if s in ("false", "off", "no"):
                return 0
            n = _num(s)
            if n is None:
                raise SysvarError("not a number")
            value = n
        if isinstance(value, (int, float)):
            if not math.isfinite(value) or value != int(value):
                raise SysvarError("not a whole number")
            return int(value)
        raise SysvarError("not a number")
    if t == "real":
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            n = _num(value)
            if n is None:
                raise SysvarError("not a number")
            value = n
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
        raise SysvarError("not a number")
    if t == "string":
        if isinstance(value, (list, dict)):
            raise SysvarError("not text")
        return str(value)
    if t == "point":
        return parse_point(value)
    if t == "color":
        return parse_color(value)
    return value


def _rule_text(rule) -> str:
    kind = rule[0]
    if kind == "range":
        return "(%s to %s)" % (_fmt(rule[1]), _fmt(rule[2]))
    if kind == "set":
        vals = [str(v) for v in rule[1]]
        return "(" + (" or ".join(vals) if len(vals) == 2 else ", ".join(vals)) + ")"
    if kind == "min":
        return "(a number of at least %s)" % _fmt(rule[1])
    if kind == "gt":
        return "(a number above %s)" % _fmt(rule[1])
    if kind == "point":
        return "(both greater than 0)" if rule[1] == "pos" else ("(no negatives)" if rule[1] == "nonneg" else "(x,y)")
    if kind == "name":
        return "(an existing entry)"
    if kind == "lw":
        return "(a standard lineweight)"
    if kind == "color":
        return "(ByLayer, ByBlock, a name, 0 to 256 or r,g,b)"
    return ""


def _fmt(v) -> str:
    return str(int(v)) if float(v) == int(v) else repr(v)


def rule_text(vd: VarDef) -> str:
    return _rule_text(vd.rule)


def _check(vd: VarDef, v, doc):
    rule = vd.rule
    kind = rule[0]
    ok = True
    if kind == "range":
        ok = rule[1] <= v <= rule[2]
    elif kind == "set":
        ok = v in rule[1]
    elif kind == "min":
        ok = v >= rule[1]
    elif kind == "gt":
        ok = v > rule[1]
    elif kind == "point":
        if rule[1] == "pos":
            ok = v[0] > 0 and v[1] > 0
        elif rule[1] == "nonneg":
            ok = v[0] >= 0 and v[1] >= 0
    elif kind == "lw":
        ok = v in LW_SET or (rule[1] and v in (-1, -2, -3))
    elif kind == "list":
        parts = [p for p in str(v).split(";") if p.strip()]
        ok = len(parts) <= 10 and all(_num(p) is not None for p in parts)
    elif kind == "text":
        ok = len(str(v)) <= 1024
    if not ok:
        raise SysvarError("invalid value for %s %s" % (vd.name, _rule_text(rule)))
    if kind == "name":
        if doc is None:
            raise SysvarError("no drawing open")
        rec = doc.drawing.table_get(rule[1], str(v))
        if rec is None:
            raise SysvarError("invalid value for %s (an existing %s)" % (vd.name, rule[1].rstrip("s")))
        return rec["name"]
    return v


def _bad(vd: VarDef, err: SysvarError):
    msg = str(err)
    if msg.startswith("invalid value") or msg == "no drawing open":
        return err
    return SysvarError("invalid value for %s %s" % (vd.name, _rule_text(vd.rule)) if vd.rule[0] != "any" else "invalid value for %s" % vd.name)


def is_readonly(vd: VarDef) -> bool:
    return vd.readonly or vd.name in FROZEN


def readonly_value(doc, name: str):
    import platform as plat

    if name == "LASTPOINT":
        return list(doc.lastpoint) if doc else [0.0, 0.0, 0.0]
    if name == "PLATFORM":
        return {"linux": "Linux", "darwin": "macOS", "win32": "Windows"}.get(sys.platform, plat.system())
    if doc is None:
        return BY_NAME[name].default
    d = doc.drawing
    if name == "VIEWCTR":
        return [doc.view["center"][0], doc.view["center"][1], 0.0]
    if name == "VIEWSIZE":
        return doc.view["height"]
    if name in ("EXTMIN", "EXTMAX"):
        box = d.extents(doc.current_space if doc.current_space in d.spaces else "model")
        if not box:
            return [0.0, 0.0, 0.0]
        return [box[0], box[1], 0.0] if name == "EXTMIN" else [box[2], box[3], 0.0]
    if name == "TILEMODE":
        return 1 if doc.current_space == "model" else 0
    if name == "CTAB":
        return "Model" if doc.current_space == "model" else doc.current_space.split(":", 1)[-1]
    if name == "CMDNAMES":
        return doc.get_runner().command_name().upper()
    if name == "CMDACTIVE":
        return 1 if doc.get_runner().command_name() else 0
    if name == "DWGNAME":
        return doc.name
    if name == "DWGPREFIX":
        return (os.path.dirname(doc.path) + os.sep) if doc.path else ""
    if name == "DWGTITLED":
        return 1 if doc.path else 0
    if name == "DBMOD":
        return 1 if doc.dirty else 0
    if name == "BLOCKEDITOR":
        return 0
    if name == "UNDOCTL":
        return doc.undo.bits()
    if name == "UNDOMARKS":
        return doc.undo.reachable_marks()
    if name == "CPLOTSTYLE":
        return "ByLayer"
    if name == "CANNOSCALEVALUE":
        v = d.scale_value(d.header.get("CANNOSCALE", "1:1"))
        return 1.0 / v if v else 1.0
    if name == "ACADVER":
        return d.header.get("ACADVER", "AC1032")
    return BY_NAME[name].default


def _current_dimstyle(doc):
    d = doc.drawing
    return d.table_get("dimstyles", d.header.get("DIMSTYLE", "Standard"))


def get_var(doc, name: str, radians: bool = False):
    _ensure_loaded()
    key = name.upper()
    vd = BY_NAME.get(key)
    if vd is None:
        if doc is not None and key in doc.drawing.header:
            return doc.drawing.header[key]
        raise SysvarError("Unknown variable %s. Type SETVAR ? to list variables." % key)
    if vd.name in FROZEN:
        return readonly_value(doc, key)
    if vd.scope == "readonly":
        return readonly_value(doc, key)
    if vd.scope == "session":
        return _session.get(key, vd.default)
    if doc is None:
        raise SysvarError("no drawing open")
    if vd.dim:
        style = _current_dimstyle(doc)
        val = style["vars"].get(key, vd.default) if style else vd.default
        if vd.angle and radians:
            return math.radians(val)
        return val
    val = doc.drawing.header.get(key, vd.default_for(doc.drawing.metric))
    if vd.angle and not radians:
        return math.degrees(val)
    return list(val) if isinstance(val, list) else val


def set_var(doc, name: str, value, radians: bool = False, create: bool = True):
    _ensure_loaded()
    key = name.upper()
    vd = BY_NAME.get(key)
    if vd is None:
        if doc is None:
            raise SysvarError("Unknown variable %s. Type SETVAR ? to list variables." % key)
        d = doc.drawing
        if key in d.header:
            cur = d.header[key]
            vd = VarDef(key, "real" if isinstance(cur, float) else "int" if isinstance(cur, int) and not isinstance(cur, bool) else "point" if isinstance(cur, list) else "string", cur, "drawing", ("any",), "Header variable", hidden=True)
        elif create:
            vd = VarDef(key, "string" if isinstance(value, str) else "real" if isinstance(value, float) else "int", value, "drawing", ("any",), "Header variable", hidden=True)
        else:
            raise SysvarError("Unknown variable %s. Type SETVAR ? to list variables." % key)
    if is_readonly(vd):
        raise SysvarError("%s is read-only" % key)
    try:
        v = _coerce(vd, value)
        if vd.angle and radians:
            v = math.degrees(v)
        v = _check(vd, v, doc)
    except SysvarError as err:
        raise _bad(vd, err)
    if vd.scope == "session":
        with _lock:
            _session[key] = v
            if vd.profile:
                _save_profile()
        events.publish({"type": "sysvar", "name": key, "value": v, "doc": None})
        return v
    if doc is None:
        raise SysvarError("no drawing open")
    stored = _apply_drawing(doc, vd, key, v)
    events.publish({"type": "sysvar", "name": key, "value": stored, "doc": doc.id})
    return stored


def _apply_drawing(doc, vd: VarDef, key: str, v):
    d = doc.drawing
    stored = v
    if vd.angle:
        stored = math.radians(v)
        if key == "ANGBASE":
            stored = stored % (2 * math.pi)
    if key == "LWDISPLAY":
        stored = int(v)

    def write():
        if vd.dim:
            style = d.modify_record("dimstyles", d.header.get("DIMSTYLE", "Standard"))
            cur = style["vars"].get(key, vd.default)
            style["vars"][key] = float(stored) if isinstance(cur, float) and not isinstance(stored, str) else stored
        else:
            d.set_header(key, list(stored) if isinstance(stored, list) else stored)

    if doc.in_tx():
        write()
    else:
        with doc.transaction("SETVAR"):
            write()
    if vd.dim:
        return get_var(doc, key)
    if vd.angle:
        return v
    return stored


def listing(doc) -> list:
    _ensure_loaded()
    out = []
    seen = set()
    for vd in VARS:
        if vd.hidden:
            continue
        seen.add(vd.name)
        try:
            val = get_var(doc, vd.name)
        except SysvarError:
            val = vd.default_for(True)
        out.append(entry(vd, val))
    if doc is not None:
        for name, val in sorted(doc.drawing.header.items()):
            if name in seen or name in BY_NAME:
                continue
            out.append({"name": name, "value": val, "type": "real" if isinstance(val, float) else "int" if isinstance(val, int) else "point" if isinstance(val, list) else "string", "scope": "drawing", "readonly": False, "description": "Header variable"})
    return out


def entry(vd: VarDef, val) -> dict:
    return {"name": vd.name, "value": val, "type": vd.type, "scope": "readonly" if is_readonly(vd) else vd.scope, "readonly": is_readonly(vd), "description": vd.desc, "default": vd.default_for(True) if not isinstance(vd.default, list) else list(vd.default), "range": rule_text(vd), "profile": vd.profile}


def format_value(val) -> str:
    if isinstance(val, list):
        return ",".join(format_value(v) for v in val)
    if isinstance(val, float):
        s = ("%.6f" % val).rstrip("0").rstrip(".")
        return "0" if s in ("", "-0") else s
    if val is None:
        return ""
    return str(val)


def count() -> int:
    return len(VARS)


def known(name: str) -> bool:
    return name.upper() in BY_NAME
