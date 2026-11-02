import math

from app.interchange import dxfcommon as C

DIM_CODES = {
    "DIMPOST": (3, "s"), "DIMAPOST": (4, "s"), "DIMSCALE": (40, "r"), "DIMASZ": (41, "r"), "DIMEXO": (42, "r"), "DIMDLI": (43, "r"),
    "DIMEXE": (44, "r"), "DIMRND": (45, "r"), "DIMDLE": (46, "r"), "DIMTP": (47, "r"), "DIMTM": (48, "r"), "DIMFXL": (49, "r"),
    "DIMJOGANG": (50, "r"), "DIMTFILL": (69, "i"), "DIMTFILLCLR": (70, "i"), "DIMTOL": (71, "i"), "DIMLIM": (72, "i"), "DIMTIH": (73, "i"),
    "DIMTOH": (74, "i"), "DIMSE1": (75, "i"), "DIMSE2": (76, "i"), "DIMTAD": (77, "i"), "DIMZIN": (78, "i"), "DIMAZIN": (79, "i"),
    "DIMTXT": (140, "r"), "DIMCEN": (141, "r"), "DIMTSZ": (142, "r"), "DIMALTF": (143, "r"), "DIMLFAC": (144, "r"), "DIMTVP": (145, "r"),
    "DIMTFAC": (146, "r"), "DIMGAP": (147, "r"), "DIMALTRND": (148, "r"), "DIMALT": (170, "i"), "DIMALTD": (171, "i"), "DIMTOFL": (172, "i"),
    "DIMTIX": (174, "i"), "DIMSOXD": (175, "i"), "DIMCLRD": (176, "i"), "DIMCLRE": (177, "i"), "DIMCLRT": (178, "i"), "DIMADEC": (179, "i"),
    "DIMDEC": (271, "i"), "DIMTDEC": (272, "i"), "DIMALTU": (273, "i"), "DIMAUNIT": (275, "i"), "DIMFRAC": (276, "i"), "DIMLUNIT": (277, "i"),
    "DIMDSEP": (278, "c"), "DIMTMOVE": (279, "i"), "DIMJUST": (280, "i"), "DIMSD1": (281, "i"), "DIMSD2": (282, "i"), "DIMTOLJ": (283, "i"),
    "DIMTZIN": (284, "i"), "DIMALTZ": (285, "i"), "DIMATFIT": (289, "i"), "DIMFXLON": (290, "i"), "DIMLWD": (371, "i"), "DIMLWE": (372, "i"),
}
CODE_TO_VAR = {v[0]: k for k, v in DIM_CODES.items()}
NAME_VARS = {"DIMBLK": 342, "DIMBLK1": 343, "DIMBLK2": 344, "DIMLDRBLK": 341, "DIMTXSTY": 340, "DIMLTYPE": 345, "DIMLTEX1": 346, "DIMLTEX2": 347}
LOWER_ATTR = {"DIMATFIT": "dimatfit", "DIMFXLON": "dimfxlon"}


def dimstyle_attribs(vars_: dict, version_rank: int) -> dict:
    out = {}
    for name, val in vars_.items():
        if name in NAME_VARS or name not in DIM_CODES:
            continue
        kind = DIM_CODES[name][1]
        key = name.lower()
        if kind == "s":
            out[key] = str(val)
        elif kind == "r":
            out[key] = float(val)
        elif kind == "c":
            out[key] = ord(str(val)[0]) if val else ord(".")
        else:
            out[key] = int(val)
    return out


def dstyle_xdata(overrides: dict) -> list:
    pairs = []
    for name, val in overrides.items():
        spec = DIM_CODES.get(name)
        if spec is None:
            continue
        code, kind = spec
        pairs.append((1070, code))
        if kind == "s":
            pairs.append((1000, str(val)))
        elif kind == "r":
            pairs.append((1040, float(val)))
        elif kind == "c":
            pairs.append((1070, ord(str(val)[0]) if val else 46))
        else:
            pairs.append((1070, int(val)))
    if not pairs:
        return []
    return [(1000, "DSTYLE"), (1002, "{")] + pairs + [(1002, "}")]


def parse_dstyle(tags) -> dict:
    out = {}
    items = [(t.code, t.value) for t in tags]
    i = 0
    while i < len(items) and items[i][1] != "{":
        i += 1
    i += 1
    while i + 1 < len(items):
        code, val = items[i]
        if code == 1002:
            break
        if code == 1070 and val in CODE_TO_VAR:
            name = CODE_TO_VAR[val]
            kind = DIM_CODES[name][1]
            v = items[i + 1][1]
            if kind == "c":
                v = chr(int(v)) if v else "."
            elif kind == "i":
                v = int(v)
            elif kind == "r":
                v = float(v)
            out[name] = v
            i += 2
        else:
            i += 2
    return out


def linetype_pattern(rec: dict) -> list:
    els = []
    for e in rec.get("elements", []):
        els.append(float(e.get("length", 0.0)))
    total = sum(abs(x) for x in els)
    if not els:
        return []
    return [total] + els


def aci_to_rgb(aci):
    from ezdxf.colors import aci2rgb

    return tuple(aci2rgb(int(aci)))


def nearest_aci(hexcolor: str) -> int:
    from ezdxf.colors import DXF_DEFAULT_COLORS, int2rgb

    s = hexcolor.lstrip("#")
    r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    best, bd = 7, 1e18
    for i in range(1, 256):
        cr, cg, cb = int2rgb(DXF_DEFAULT_COLORS[i])
        d = (cr - r) ** 2 + (cg - g) ** 2 + (cb - b) ** 2
        if d < bd:
            best, bd = i, d
    return best


def rgb_hex(rgb) -> str:
    return "#%02X%02X%02X" % (int(rgb[0]), int(rgb[1]), int(rgb[2]))


def deg(v) -> float:
    return math.degrees(float(v))


def rad(v) -> float:
    return math.radians(float(v))
