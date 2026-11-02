import base64
import json
import zlib

APPID = "FORMCAD"
SNAP_MAGIC = "FCSNAP1"
CHUNK = 200

VERSIONS = {"R12": "AC1009", "R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021", "R2010": "AC1024", "R2013": "AC1027", "R2018": "AC1032"}
VERSION_ORDER = ("R12", "R2000", "R2004", "R2007", "R2010", "R2013", "R2018")
CODE_TO_NAME = {v: k for k, v in VERSIONS.items()}
DEFAULT_VERSION = "R2018"


def parse_version(text) -> str:
    t = str(text or "").strip().upper().replace(" ", "")
    if not t:
        return ""
    if t in VERSIONS:
        return t
    if t in CODE_TO_NAME:
        return CODE_TO_NAME[t]
    if t.isdigit():
        for cand in ("R" + t, "R20" + t if len(t) == 2 else ""):
            if cand in VERSIONS:
                return cand
    return ""


def default_version(code) -> str:
    c = str(code or "").strip().upper()
    if not c.startswith("AC10") or not c[2:].isdigit():
        return DEFAULT_VERSION
    n = int(c[2:])
    if n < 1018:
        return "R2000"
    if n < 1021:
        return "R2004"
    if n < 1024:
        return "R2007"
    if n < 1027:
        return "R2010"
    if n < 1032:
        return "R2013"
    return "R2018"


def version_rank(name: str) -> int:
    return VERSION_ORDER.index(name)


def r(v, n: int = 6):
    if isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, n) + 0.0
    if isinstance(v, (list, tuple)):
        return [r(x, n) for x in v]
    if isinstance(v, dict):
        return {k: r(x, n) for k, x in v.items()}
    return v


def sig_of(values) -> str:
    raw = json.dumps(r(values), sort_keys=True, separators=(",", ":"), default=str)
    return "%08x" % (zlib.crc32(raw.encode("utf-8")) & 0xFFFFFFFF)


def pack_snapshot(payload, sig: str = "") -> list:
    raw = zlib.compress(json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8"), 6)
    text = base64.b64encode(raw).decode("ascii")
    out = [(1000, SNAP_MAGIC + " " + (sig or "-"))]
    for i in range(0, len(text), CHUNK):
        out.append((1000, text[i : i + CHUNK]))
    return out


def unpack_snapshot(tags):
    items = [t[1] if isinstance(t, tuple) else t.value for t in tags]
    items = [str(v) for v in items]
    if not items or not items[0].startswith(SNAP_MAGIC):
        return None, ""
    sig = items[0].split(" ", 1)[1] if " " in items[0] else ""
    try:
        raw = zlib.decompress(base64.b64decode("".join(items[1:]).encode("ascii")), 0, 64 * 1024 * 1024)
        return json.loads(raw.decode("utf-8")), ("" if sig == "-" else sig)
    except (ValueError, zlib.error):
        return None, ""


def _u_escapes(s: str) -> str:
    if "\\U+" not in s:
        return s
    out = []
    i = 0
    n = len(s)
    units = []
    while i < n:
        if s.startswith("\\U+", i) and i + 7 <= n and all(ch in "0123456789abcdefABCDEF" for ch in s[i + 3 : i + 7]):
            units.append(int(s[i + 3 : i + 7], 16))
            i += 7
            continue
        if units:
            out.append(_units_text(units))
            units = []
        out.append(s[i])
        i += 1
    if units:
        out.append(_units_text(units))
    return "".join(out)


def _units_text(units) -> str:
    raw = b"".join(u.to_bytes(2, "little") for u in units)
    try:
        return raw.decode("utf-16-le")
    except UnicodeDecodeError:
        return "".join("\\U+%04X" % u for u in units)


def esc_line(text: str) -> str:
    return str(text).replace("\\U+", "\\U+005C" + "U+").replace("^", "^ ").replace("\t", "^I").replace("\r", "").replace("\n", " ")


def unesc_line(text: str) -> str:
    out = []
    s = _u_escapes(str(text))
    i = 0
    while i < len(s):
        c = s[i]
        if c == "^" and i + 1 < len(s):
            n = s[i + 1]
            if n == " ":
                out.append("^")
                i += 2
                continue
            if n == "I":
                out.append("\t")
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


def esc_multi(text: str) -> str:
    return str(text).replace("^", "^ ").replace("\t", "^I").replace("\r", "")


def unesc_multi(text: str) -> str:
    return unesc_line(str(text).replace("^J", "\n"))


HEADER_MAP = (
    ("LUNITS", "$LUNITS", "int"), ("LUPREC", "$LUPREC", "int"), ("AUNITS", "$AUNITS", "int"), ("AUPREC", "$AUPREC", "int"),
    ("ANGBASE", "$ANGBASE", "rad"), ("ANGDIR", "$ANGDIR", "int"), ("INSUNITS", "$INSUNITS", "int"), ("MEASUREMENT", "$MEASUREMENT", "int"),
    ("CLAYER", "$CLAYER", "str"), ("CECOLOR", "$CECOLOR", "int"), ("CELTYPE", "$CELTYPE", "str"), ("CELWEIGHT", "$CELWEIGHT", "int"),
    ("CELTSCALE", "$CELTSCALE", "real"), ("LTSCALE", "$LTSCALE", "real"), ("PSLTSCALE", "$PSLTSCALE", "int"),
    ("TEXTSTYLE", "$TEXTSTYLE", "str"), ("TEXTSIZE", "$TEXTSIZE", "real"), ("DIMSTYLE", "$DIMSTYLE", "str"),
    ("CMLSTYLE", "$CMLSTYLE", "str"), ("CMLJUST", "$CMLJUST", "int"), ("CMLSCALE", "$CMLSCALE", "real"),
    ("PDMODE", "$PDMODE", "int"), ("PDSIZE", "$PDSIZE", "real"), ("FILLMODE", "$FILLMODE", "int"), ("MIRRTEXT", "$MIRRTEXT", "int"),
    ("ATTMODE", "$ATTMODE", "int"), ("THICKNESS", "$THICKNESS", "real"), ("ELEVATION", "$ELEVATION", "real"),
    ("INSBASE", "$INSBASE", "pt3"), ("LIMMIN", "$LIMMIN", "pt2"), ("LIMMAX", "$LIMMAX", "pt2"), ("LWDISPLAY", "$LWDISPLAY", "int"),
    ("SNAPBASE", "$SNAPBASE", "pt2"), ("SNAPANG", "$SNAPANG", "deg"), ("FILLETRAD", "$FILLETRAD", "real"),
    ("CHAMFERA", "$CHAMFERA", "real"), ("CHAMFERB", "$CHAMFERB", "real"), ("CHAMFERC", "$CHAMFERC", "real"), ("CHAMFERD", "$CHAMFERD", "real"),
    ("PLINEWID", "$PLINEWID", "real"), ("PLINEGEN", "$PLINEGEN", "int"), ("TRACEWID", "$TRACEWID", "real"), ("SPLINESEGS", "$SPLINESEGS", "int"),
    ("CANNOSCALE", "$CANNOSCALE", "scale"), ("CTABLESTYLE", "$CTABLESTYLE", "str"), ("LIMCHECK", "$LIMCHECK", "int"),
)
HEADER_SKIP = {"$ACADVER", "$HANDSEED", "$TDUPDATE", "$TDUUPDATE", "$VERSIONGUID", "$FINGERPRINTGUID", "$DWGCODEPAGE", "$ACADMAINTVER", "$TDCREATE", "$TDUCREATE", "$TDINDWG", "$TDUSRTIMER", "$CLAYER", "$DIMSTYLE", "$CELTYPE", "$TEXTSTYLE", "$CMLSTYLE", "$CTABLESTYLE", "$CANNOSCALE"}
MAPPED_DXF = {m[1] for m in HEADER_MAP}

DIM_TEXT_VARS = {"DIMPOST", "DIMAPOST", "DIMBLK", "DIMBLK1", "DIMBLK2", "DIMLDRBLK", "DIMTXSTY", "DIMLTYPE", "DIMLTEX1", "DIMLTEX2"}
DIM_NAME_VARS = {"DIMBLK", "DIMBLK1", "DIMBLK2", "DIMLDRBLK", "DIMTXSTY", "DIMLTYPE", "DIMLTEX1", "DIMLTEX2"}


COMMON_FIELDS = ("handle", "owner", "layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "thickness", "normal", "plot_style", "annotation_scales", "xdata", "reactors", "extra")
BASE_EXTRAS = ("annotation_scales", "reactors", "extra", "plot_style")
FULL_KINDS = ("assoc_array", "table", "mleader", "dimension", "helix", "mline", "region", "hatch")
NATIVE_FIELDS = {
    "viewport": ("center", "width", "height", "view_center", "scale", "on", "locked", "frozen", "clip"),
    "insert": ("block", "position", "scale", "rotation", "attributes", "array"),
    "leader": ("points", "arrowhead", "spline", "style"),
    "wipeout": ("points",),
    "spline": ("degree", "knots", "control_points", "weights", "fit_points", "closed", "start_tangent", "end_tangent", "fit_tolerance"),
    "mtext": ("position", "height", "width", "attachment", "rotation", "style", "contents", "line_spacing", "line_spacing_style"),
}
SIG_KEYS = {
    "assoc_array": ("base",), "table": ("position",), "mleader": ("content_pos",), "dimension": ("def_point",),
    "helix": ("center",), "mline": ("scale",), "region": (),
}


def sig_values(e):
    if e.kind == "hatch":
        return [[[v["p"][0], v["p"][1]] for v in loop.get("vertices", [])] for loop in e.loops]
    if e.kind == "mline":
        return [[v["p"][0], v["p"][1]] for v in e.vertices]
    if e.kind == "region":
        return [[[v["p"][0], v["p"][1]] for v in loop.get("vertices", [])] for loop in e.loops]
    return [getattr(e, k, None) for k in SIG_KEYS.get(e.kind, ())]
