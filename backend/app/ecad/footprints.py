import re

from app.ecad.store import EcadError

SMD_LAYERS = ["F.Cu", "F.Paste", "F.Mask"]
TH_LAYERS = ["*.Cu", "*.Mask"]
METRIC_OF = {"0201": "0603", "0402": "1005", "0603": "1608", "0805": "2012", "1206": "3216", "1210": "3225", "1812": "4532", "2010": "5025", "2512": "6332"}
DEFAULTS = {
    "chip": {"code": "0603", "toe": 0.25, "heel": 0.05, "side": 0.0, "tol": 0.1, "courtyard": 0.25},
    "dual": {"pins": 8, "pitch": 1.27, "body_l": 4.9, "body_w": 3.9, "span": 6.0, "lead_w": 0.4, "lead_l": 0.8, "height": 1.75, "toe": 0.35, "heel": 0.1, "side": 0.03, "tol": 0.1, "min_gap": 0.2, "courtyard": 0.25, "ep": None},
    "quad": {"pins": 32, "pitch": 0.8, "body_l": 7.0, "body_w": 7.0, "span": 9.0, "lead_w": 0.35, "lead_l": 0.8, "height": 1.4, "toe": 0.35, "heel": 0.1, "side": 0.03, "tol": 0.1, "min_gap": 0.2, "courtyard": 0.25, "ep": None},
    "sot": {"pins": 3, "pitch": 0.95, "body_l": 2.9, "body_w": 1.3, "span": 2.4, "lead_w": 0.4, "lead_l": 0.45, "height": 1.1, "toe": 0.3, "heel": 0.1, "side": 0.05, "tol": 0.1, "courtyard": 0.25},
    "header": {"rows": 1, "cols": 2, "pitch": 2.54, "drill": 1.0, "pad": 1.7, "numbering": "across", "height": 8.5, "courtyard": 0.25},
    "dip": {"pins": 8, "pitch": 2.54, "row_span": 7.62, "drill": 0.8, "pad": 1.6, "body_w": 6.35, "height": 4.0, "courtyard": 0.25},
    "terminal": {"pins": 2, "pitch": 5.0, "drill": 1.3, "pad": 2.4, "height": 10.0, "courtyard": 0.25},
    "radial": {"pitch": 2.5, "body_d": 5.0, "drill": 0.8, "pad": 1.6, "height": 7.0, "courtyard": 0.25},
}
LIMITS = {"pins": (2, 400), "pitch": (0.2, 20.0), "cols": (1, 100), "rows": (1, 4)}
PRESETS = {
    "CHIP-0402": ("chip", {"code": "0402"}), "CHIP-0603": ("chip", {"code": "0603"}), "CHIP-0805": ("chip", {"code": "0805"}), "CHIP-1206": ("chip", {"code": "1206"}),
    "SOIC-8": ("dual", {"pins": 8}), "SOIC-14": ("dual", {"pins": 14, "body_l": 8.65}), "SOIC-16": ("dual", {"pins": 16, "body_l": 9.9}),
    "TSSOP-14": ("dual", {"pins": 14, "pitch": 0.65, "body_l": 5.0, "body_w": 4.4, "span": 6.4, "lead_w": 0.25, "lead_l": 0.6, "height": 1.1}),
    "QFP-32": ("quad", {"pins": 32}), "QFN-16": ("quad", {"pins": 16, "pitch": 0.65, "body_l": 3.0, "body_w": 3.0, "span": 3.0, "lead_w": 0.3, "lead_l": 0.4, "height": 0.8, "ep": [1.7, 1.7]}),
    "SOT23-3": ("sot", {"pins": 3}), "SOT23-5": ("sot", {"pins": 5}), "SOT23-6": ("sot", {"pins": 6}),
    "HDR-1x02": ("header", {"rows": 1, "cols": 2}), "HDR-1x03": ("header", {"rows": 1, "cols": 3}), "HDR-1x04": ("header", {"rows": 1, "cols": 4}), "HDR-2x05": ("header", {"rows": 2, "cols": 5}),
    "DIP-8": ("dip", {"pins": 8}), "DIP-14": ("dip", {"pins": 14}), "TERM-2_P5.00": ("terminal", {"pins": 2}), "TERM-3_P5.00": ("terminal", {"pins": 3}),
    "RADIAL-D5_P2.5": ("radial", {}), "RADIAL-D8_P3.5": ("radial", {"pitch": 3.5, "body_d": 8.0, "height": 11.0}),
}


def _num(params: dict, key: str, lo=None, hi=None) -> float:
    try:
        v = float(params[key])
    except (TypeError, ValueError, KeyError):
        raise EcadError("Parameter %s must be a number." % key)
    if v != v or abs(v) > 1e4:
        raise EcadError("Parameter %s is out of range." % key)
    if lo is not None and v < lo:
        raise EcadError("Parameter %s must be at least %g." % (key, lo))
    if hi is not None and v > hi:
        raise EcadError("Parameter %s must be at most %g." % (key, hi))
    return v


def _int(params: dict, key: str) -> int:
    lo, hi = LIMITS.get(key, (1, 400))
    v = _num(params, key, lo, hi)
    if v != int(v):
        raise EcadError("Parameter %s must be a whole number." % key)
    return int(v)


def _r(v: float) -> float:
    return round(v + 0.0, 4)


def _pad(number, pos, size, shape="rect", layers=None, drill=None, rot=0, ratio=0.25) -> dict:
    return {
        "number": str(number), "shape": shape, "pos": [_r(pos[0]), _r(pos[1])], "size": [_r(size[0]), _r(size[1])], "rot": rot,
        "layers": list(layers or (TH_LAYERS if drill else SMD_LAYERS)), "drill": drill, "plated": True, "mask_margin": None, "paste_margin": None,
        "roundrect_ratio": ratio if shape == "roundrect" else None, "poly": None, "thermal": None,
    }


def _rect_pts(x0, y0, x1, y1):
    return [[_r(x0), _r(y0)], [_r(x1), _r(y0)], [_r(x1), _r(y1)], [_r(x0), _r(y1)], [_r(x0), _r(y0)]]


def _courtyard(pads, body, margin):
    xs, ys = [], []
    for p in pads:
        w, h = p["size"]
        xs += [p["pos"][0] - w / 2, p["pos"][0] + w / 2]
        ys += [p["pos"][1] - h / 2, p["pos"][1] + h / 2]
    xs += [-body[0] / 2, body[0] / 2]
    ys += [-body[1] / 2, body[1] / 2]
    x0, x1, y0, y1 = min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin
    grid = 0.05
    x0, y0 = grid * (x0 // grid), grid * (y0 // grid)
    x1, y1 = -grid * (-x1 // grid), -grid * (-y1 // grid)
    return [[_r(x0), _r(y0)], [_r(x1), _r(y0)], [_r(x1), _r(y1)], [_r(x0), _r(y1)]]


def _line(pts, w=0.12):
    return {"t": "line", "pts": [[_r(a), _r(b)] for a, b in pts], "w": w}


def _finish(fid, family, params, pads, body_xy, height, attrs, silk, fab=None, margin=0.25, desc="", body_pos=(0, 0), shape="box", size=None):
    return {
        "id": fid, "name": fid, "description": desc, "family": family, "attrs": attrs, "source": "generated", "params": {"family": family, **params}, "pads": pads,
        "courtyard": _courtyard(pads, body_xy, margin), "silk": silk + [{"t": "text", "text": "%R", "pos": [0, 0], "h": 1.0}], "fab": fab or [_line(_rect_pts(-body_xy[0] / 2, -body_xy[1] / 2, body_xy[0] / 2, body_xy[1] / 2))],
        "body": {"shape": shape, "size": size or [_r(body_xy[0]), _r(body_xy[1]), _r(height)], "pos": [body_pos[0], body_pos[1]], "z0": 0.0},
    }


def _tolerances(p):
    t = p.get("tol", 0.1) / 2
    return p["toe"] + t, p["heel"] + t, p["side"] + t


def chip(params: dict) -> dict:
    p = {**DEFAULTS["chip"], **params}
    code = str(p["code"])
    if p.get("body_l") and p.get("body_w"):
        L, W = _num(p, "body_l", 0.2, 30), _num(p, "body_w", 0.1, 30)
        label = "%gx%g" % (L, W)
    else:
        metric = METRIC_OF.get(code, code)
        if not re.fullmatch(r"\d{4}", metric):
            raise EcadError("Give a size code such as 0603, or body_l and body_w.")
        L, W = int(metric[:2]) / 10, int(metric[2:]) / 10
        label = code
    term = _num(p, "term_l", 0.05, L / 2) if p.get("term_l") else min(0.6, 0.2 * L + 0.0)
    toe, heel, side = _tolerances(p)
    inner = L / 2 - term - heel
    if inner <= 0:
        raise EcadError("The terminals leave no gap between the pads.")
    outer = L / 2 + toe
    length, width = outer - inner, W + 2 * side
    cx = (inner + outer) / 2
    pads = [_pad("1", (-cx, 0), (length, width), "roundrect"), _pad("2", (cx, 0), (length, width), "roundrect")]
    gap = inner - 0.12 / 2 - 0.1
    silk = [_line([(-gap, W / 2 + 0.2), (gap, W / 2 + 0.2)]), _line([(-gap, -W / 2 - 0.2), (gap, -W / 2 - 0.2)])] if gap > 0.1 else []
    fid = "CHIP-" + label
    return _finish(fid, "chip", {k: p[k] for k in ("code", "toe", "heel", "side", "tol", "courtyard")}, pads, (L, W), W * 0.6, ["smd"], silk, margin=p["courtyard"], desc="Two-terminal chip, pad rule from terminal length plus toe, heel, side and tolerance.", size=[_r(L), _r(W), _r(W * 0.6)])


def dual(params: dict) -> dict:
    p = {**DEFAULTS["dual"], **params}
    n, pitch = _int(p, "pins"), _num(p, "pitch", 0.2, 20)
    if n % 2:
        raise EcadError("A dual-row package has an even pin count.")
    span, lead_w, lead_l = _num(p, "span", 0.5, 100), _num(p, "lead_w", 0.05, 5), _num(p, "lead_l", 0.1, 10)
    body_l, body_w = _num(p, "body_l", 0.5, 100), _num(p, "body_w", 0.5, 100)
    toe, heel, side = _tolerances(p)
    z_out, z_in = span / 2 + toe, span / 2 - lead_l - heel
    if z_in <= 0:
        raise EcadError("The leads leave no gap between the pad rows.")
    length = z_out - z_in
    width = min(lead_w + 2 * side, pitch - _num(p, "min_gap", 0.05, 5))
    if width <= 0:
        raise EcadError("The pitch is too small for the minimum pad gap.")
    half = n // 2
    pads = []
    for i in range(half):
        y = (half - 1) / 2 * pitch - i * pitch
        pads.append(_pad(i + 1, (-(z_in + z_out) / 2, y), (length, width), "roundrect"))
    for i in range(half):
        y = -(half - 1) / 2 * pitch + i * pitch
        pads.append(_pad(half + i + 1, ((z_in + z_out) / 2, y), (length, width), "roundrect"))
    ep = p.get("ep")
    if ep:
        pads.append(_pad(n + 1, (0, 0), (float(ep[0]), float(ep[1])), "rect"))
    sx = body_w / 2 + 0.1
    sy = max(body_l / 2, 0.0) + 0.0
    silk = [_line([(-sx, sy), (sx, sy)]), _line([(-sx, -sy), (sx, -sy)]), {"t": "circle", "c": [_r(-(z_in + z_out) / 2 - length / 2 - 0.3), _r((half - 1) / 2 * pitch)], "r": 0.15, "w": 0.12}]
    fid = "DUAL-%d_P%g_S%g" % (n, pitch, span)
    return _finish(fid, "dual", {k: p[k] for k in ("pins", "pitch", "body_l", "body_w", "span", "lead_w", "lead_l", "height", "toe", "heel", "side", "tol", "min_gap", "courtyard", "ep")}, pads, (body_w, body_l), p["height"], ["smd"], silk, margin=p["courtyard"], desc="Dual-row gull-wing package, pin 1 top left, counter-clockwise.")


def quad(params: dict) -> dict:
    p = {**DEFAULTS["quad"], **params}
    n, pitch = _int(p, "pins"), _num(p, "pitch", 0.2, 20)
    if n % 4:
        raise EcadError("A quad package has a pin count divisible by 4.")
    span, lead_w, lead_l = _num(p, "span", 0.5, 100), _num(p, "lead_w", 0.05, 5), _num(p, "lead_l", 0.1, 10)
    body_l, body_w = _num(p, "body_l", 0.5, 100), _num(p, "body_w", 0.5, 100)
    toe, heel, side = _tolerances(p)
    z_out, z_in = span / 2 + toe, span / 2 - lead_l - heel
    if z_in <= 0:
        raise EcadError("The leads leave no gap between the pad rows.")
    length = z_out - z_in
    width = min(lead_w + 2 * side, pitch - _num(p, "min_gap", 0.05, 5))
    if width <= 0:
        raise EcadError("The pitch is too small for the minimum pad gap.")
    q = n // 4
    zc = (z_in + z_out) / 2
    pads = []
    for i in range(q):
        pads.append(_pad(i + 1, (-zc, (q - 1) / 2 * pitch - i * pitch), (length, width), "roundrect"))
    for i in range(q):
        pads.append(_pad(q + i + 1, (-(q - 1) / 2 * pitch + i * pitch, -zc), (width, length), "roundrect"))
    for i in range(q):
        pads.append(_pad(2 * q + i + 1, (zc, -(q - 1) / 2 * pitch + i * pitch), (length, width), "roundrect"))
    for i in range(q):
        pads.append(_pad(3 * q + i + 1, ((q - 1) / 2 * pitch - i * pitch, zc), (width, length), "roundrect"))
    ep = p.get("ep")
    if ep:
        pads.append(_pad(n + 1, (0, 0), (float(ep[0]), float(ep[1])), "rect"))
    hx, hy = body_l / 2 + 0.1, body_w / 2 + 0.1
    silk = [_line([(-hx, hy), (hx, hy), (hx, -hy), (-hx, -hy), (-hx, hy)]), {"t": "circle", "c": [_r(-zc - length / 2 - 0.3), _r((q - 1) / 2 * pitch)], "r": 0.15, "w": 0.12}]
    fid = "QUAD-%d_P%g_B%g" % (n, pitch, body_l)
    return _finish(fid, "quad", {k: p[k] for k in ("pins", "pitch", "body_l", "body_w", "span", "lead_w", "lead_l", "height", "toe", "heel", "side", "tol", "min_gap", "courtyard", "ep")}, pads, (body_l, body_w), p["height"], ["smd"], silk, margin=p["courtyard"], desc="Four-side package, pin 1 top of the left side, counter-clockwise.")


def sot(params: dict) -> dict:
    p = {**DEFAULTS["sot"], **params}
    n = _int(p, "pins")
    if n not in (3, 5, 6):
        raise EcadError("A small-outline transistor package has 3, 5 or 6 pins.")
    pitch, span, lead_w, lead_l = _num(p, "pitch", 0.3, 3), _num(p, "span", 0.5, 20), _num(p, "lead_w", 0.05, 2), _num(p, "lead_l", 0.1, 3)
    toe, heel, side = _tolerances(p)
    z_out, z_in = span / 2 + toe, span / 2 - lead_l - heel
    if z_in <= 0:
        raise EcadError("The leads leave no gap between the pad rows.")
    length, width, zc = z_out - z_in, lead_w + 2 * side, (z_in + z_out) / 2
    pads = []
    if n == 3:
        pads = [_pad(1, (-zc, pitch), (length, width), "roundrect"), _pad(2, (-zc, -pitch), (length, width), "roundrect"), _pad(3, (zc, 0), (length, width), "roundrect")]
    else:
        right = 3 if n == 6 else 2
        for i in range(3):
            pads.append(_pad(i + 1, (-zc, pitch - i * pitch), (length, width), "roundrect"))
        ys = [pitch, -pitch] if right == 2 else [pitch, 0, -pitch]
        order = list(range(3 + right, 3, -1))
        for num, y in zip(order, ys):
            pads.append(_pad(num, (zc, y), (length, width), "roundrect"))
        pads.sort(key=lambda q: int(q["number"]))
    bl, bw = p["body_l"], p["body_w"]
    silk = [_line([(-0.6, bw / 2 + 0.1), (0.6, bw / 2 + 0.1)]), _line([(-0.6, -bw / 2 - 0.1), (0.6, -bw / 2 - 0.1)])]
    fid = "SOT23-%d_P%g" % (n, pitch)
    return _finish(fid, "sot", {k: p[k] for k in ("pins", "pitch", "body_l", "body_w", "span", "lead_w", "lead_l", "height", "toe", "heel", "side", "tol", "courtyard")}, pads, (bw, bl), p["height"], ["smd"], silk, margin=p["courtyard"], desc="Small-outline transistor, pins 1 to 3 down the left, remaining pins up the right.")


def _th_row(num_start, n, pitch, drill, pad, first_rect=True, x=0.0, y0=0.0, step=(0.0, -1.0)):
    out = []
    for i in range(n):
        shape = "rect" if (i == 0 and first_rect and num_start == 1) else "circle"
        out.append(_pad(num_start + i, (x + step[0] * pitch * i, y0 + step[1] * pitch * i), (pad, pad), shape, drill={"d": drill}))
    return out


def header(params: dict) -> dict:
    p = {**DEFAULTS["header"], **params}
    rows, cols, pitch = _int(p, "rows"), _int(p, "cols"), _num(p, "pitch", 0.5, 10)
    drill, pad = _num(p, "drill", 0.2, 6), _num(p, "pad", 0.4, 10)
    if pad - drill < 0.4:
        raise EcadError("The pad leaves less than 0.2 mm of copper ring around the drill.")
    pads = []
    for c in range(cols):
        for r in range(rows):
            num = c * rows + r + 1 if p["numbering"] == "across" else (r * cols + c + 1)
            shape = "rect" if num == 1 else "circle"
            pads.append(_pad(num, (r * pitch, -c * pitch), (pad, pad), shape, drill={"d": drill}))
    pads.sort(key=lambda q: int(q["number"]))
    w, h = rows * pitch, cols * pitch
    cx, cy = (rows - 1) * pitch / 2, -(cols - 1) * pitch / 2
    silk = [_line(_rect_pts(-pitch / 2, pitch / 2, (rows - 0.5) * pitch, -(cols - 0.5) * pitch))]
    fid = "HDR-%dx%02d_P%g" % (rows, cols, pitch) if pitch != 2.54 else "HDR-%dx%02d" % (rows, cols)
    fp = _finish(fid, "header", {k: p[k] for k in ("rows", "cols", "pitch", "drill", "pad", "numbering", "height", "courtyard")}, pads, (w, h), p["height"], ["through_hole"], silk, margin=p["courtyard"], desc="Pin header, pin 1 square.", body_pos=(cx, cy))
    fp["fab"] = [_line(_rect_pts(-pitch / 2, pitch / 2, (rows - 0.5) * pitch, -(cols - 0.5) * pitch))]
    fp["courtyard"] = [[_r(-pitch / 2 - p["courtyard"]), _r(pitch / 2 + p["courtyard"])], [_r((rows - 0.5) * pitch + p["courtyard"]), _r(pitch / 2 + p["courtyard"])], [_r((rows - 0.5) * pitch + p["courtyard"]), _r(-(cols - 0.5) * pitch - p["courtyard"])], [_r(-pitch / 2 - p["courtyard"]), _r(-(cols - 0.5) * pitch - p["courtyard"])]]
    return fp


def dip(params: dict) -> dict:
    p = {**DEFAULTS["dip"], **params}
    n, pitch, rs = _int(p, "pins"), _num(p, "pitch", 1.0, 10), _num(p, "row_span", 2, 30)
    if n % 2:
        raise EcadError("A dual-in-line package has an even pin count.")
    drill, pad = _num(p, "drill", 0.2, 4), _num(p, "pad", 0.4, 8)
    half = n // 2
    pads = []
    for i in range(half):
        pads.append(_pad(i + 1, (0, -i * pitch), (pad, pad), "rect" if i == 0 else "oval", drill={"d": drill}))
    for i in range(half):
        pads.append(_pad(half + i + 1, (rs, -(half - 1 - i) * pitch), (pad, pad), "oval", drill={"d": drill}))
    bw, bl = p["body_w"], half * pitch
    cx, cy = rs / 2, -(half - 1) * pitch / 2
    fp = _finish("DIP-%d_P%g_W%g" % (n, pitch, rs), "dip", {k: p[k] for k in ("pins", "pitch", "row_span", "drill", "pad", "body_w", "height", "courtyard")}, pads, (rs + pad, (half - 1) * pitch + pad), p["height"], ["through_hole"], [_line(_rect_pts(cx - bw / 2, cy + bl / 2, cx + bw / 2, cy - bl / 2))], margin=p["courtyard"], desc="Dual-in-line package, pin 1 square.", body_pos=(cx, cy), size=[_r(bw), _r(bl), _r(p["height"])])
    fp["courtyard"] = _courtyard(pads, (0, 0), p["courtyard"])
    return fp


def terminal(params: dict) -> dict:
    p = {**DEFAULTS["terminal"], **params}
    n, pitch = _int(p, "pins"), _num(p, "pitch", 1.0, 20)
    drill, pad = _num(p, "drill", 0.3, 6), _num(p, "pad", 0.6, 10)
    pads = [_pad(i + 1, (i * pitch, 0), (pad, pad), "rect" if i == 0 else "oval", drill={"d": drill}) for i in range(n)]
    w, h = n * pitch, 7.0
    cx = (n - 1) * pitch / 2
    fp = _finish("TERM-%d_P%.2f" % (n, pitch), "terminal", {k: p[k] for k in ("pins", "pitch", "drill", "pad", "height", "courtyard")}, pads, (w, h), p["height"], ["through_hole"], [_line(_rect_pts(cx - w / 2, h / 2, cx + w / 2, -h / 2))], margin=p["courtyard"], desc="Screw terminal row.", body_pos=(cx, 0))
    return fp


def radial(params: dict) -> dict:
    p = {**DEFAULTS["radial"], **params}
    pitch, d = _num(p, "pitch", 1.0, 30), _num(p, "body_d", 2, 60)
    drill, pad = _num(p, "drill", 0.3, 4), _num(p, "pad", 0.6, 8)
    pads = [_pad(1, (-pitch / 2, 0), (pad, pad), "rect", drill={"d": drill}), _pad(2, (pitch / 2, 0), (pad, pad), "circle", drill={"d": drill})]
    silk = [{"t": "circle", "c": [0, 0], "r": _r(d / 2 + 0.1), "w": 0.12}]
    fp = _finish("RADIAL-D%g_P%g" % (d, pitch), "radial", {k: p[k] for k in ("pitch", "body_d", "drill", "pad", "height", "courtyard")}, pads, (d, d), p["height"], ["through_hole"], silk, fab=[{"t": "circle", "c": [0, 0], "r": _r(d / 2), "w": 0.12}], margin=p["courtyard"], desc="Radial leaded capacitor, pin 1 square (positive).", shape="cyl", size=[_r(d), _r(p["height"])])
    return fp


FAMILIES = {"chip": chip, "dual": dual, "quad": quad, "sot": sot, "header": header, "dip": dip, "terminal": terminal, "radial": radial}


def generate(family: str, params: dict | None = None) -> dict:
    fn = FAMILIES.get(str(family))
    if fn is None:
        raise EcadError("Unknown footprint family %s. Use one of: %s." % (family, ", ".join(FAMILIES)))
    params = dict(params or {})
    unknown = [k for k in params if k not in DEFAULTS[family] and k not in ("term_l", "body_l", "body_w")]
    if unknown:
        raise EcadError("Unknown parameter %s for family %s." % (", ".join(sorted(unknown)), family))
    fp = fn(params)
    if len(fp["pads"]) > 1000:
        raise EcadError("That footprint has too many pads.")
    return fp


def preset(fid: str):
    spec = PRESETS.get(fid)
    if spec is None:
        return None
    fp = generate(spec[0], spec[1])
    fp["id"] = fp["name"] = fid
    return fp


def preset_ids() -> list:
    return list(PRESETS)
