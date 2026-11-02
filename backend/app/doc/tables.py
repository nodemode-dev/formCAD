import copy

LINEWEIGHTS = (0, 5, 9, 13, 15, 18, 20, 25, 30, 35, 40, 50, 53, 60, 70, 80, 90, 100, 106, 120, 140, 158, 200, 211)
LW_BYLAYER = -1
LW_BYBLOCK = -2
LW_DEFAULT = -3

TABLE_NAMES = ("layers", "linetypes", "textstyles", "dimstyles", "mleaderstyles", "tablestyles", "mlinestyles", "blocks", "layouts", "views", "ucs", "vports", "groups", "layerstates", "layerfilters", "scales", "plotstyles")

ARROWHEADS = ("closed filled", "closed blank", "closed", "dot", "small dot", "blank dot", "oblique", "architectural tick", "open", "right-angle", "30-degree open", "origin indicator", "origin indicator 2", "small", "filled box", "blank box", "filled datum triangle", "blank datum triangle", "integral", "none")

METRIC_SCALES = ("1:1", "1:2", "1:4", "1:5", "1:8", "1:10", "1:16", "1:20", "1:30", "1:40", "1:50", "1:100", "2:1", "4:1", "8:1", "10:1", "100:1")
IMPERIAL_EXTRA = (("1/128\" = 1'-0\"", 1, 1536), ("1/64\" = 1'-0\"", 1, 768), ("1/32\" = 1'-0\"", 1, 384), ("1/16\" = 1'-0\"", 1, 192), ("3/32\" = 1'-0\"", 3, 384), ("1/8\" = 1'-0\"", 1, 96), ("3/16\" = 1'-0\"", 3, 192), ("1/4\" = 1'-0\"", 1, 48), ("3/8\" = 1'-0\"", 3, 96), ("1/2\" = 1'-0\"", 1, 24), ("3/4\" = 1'-0\"", 3, 48), ("1\" = 1'-0\"", 1, 12), ("1 1/2\" = 1'-0\"", 3, 24), ("3\" = 1'-0\"", 3, 12), ("6\" = 1'-0\"", 1, 2), ("1' = 1'-0\"", 1, 1))


class Table:
    def __init__(self, name: str):
        self.name = name
        self._items: dict = {}

    @staticmethod
    def key(name: str) -> str:
        return str(name).casefold()

    def get(self, name: str):
        return self._items.get(self.key(name))

    def has(self, name: str) -> bool:
        return self.key(name) in self._items

    def put(self, record: dict) -> None:
        self._items[self.key(record["name"])] = record

    def drop(self, name: str) -> None:
        self._items.pop(self.key(name), None)

    def names(self) -> list:
        return [r["name"] for r in self._items.values()]

    def values(self) -> list:
        return list(self._items.values())

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, name) -> bool:
        return self.has(name)

    def to_list(self) -> list:
        return copy.deepcopy(list(self._items.values()))

    def load_list(self, items: list) -> None:
        self._items = {}
        for rec in items:
            self.put(copy.deepcopy(rec))


def new_layer(name: str, **kw) -> dict:
    rec = {"name": name, "color": 7, "linetype": "Continuous", "lineweight": LW_DEFAULT, "on": True, "frozen": False, "locked": False, "plot": True, "transparency": 0, "description": "", "plot_style": "Color_7", "new_vp_freeze": False, "xdata": {}}
    rec.update(kw)
    return rec


def _lt(name: str, description: str, elements: list, metric: bool) -> dict:
    k = 25.4 if metric else 1.0
    els = []
    for e in elements:
        if isinstance(e, dict):
            t = dict(e)
            for key in ("scale", "x", "y"):
                if key in t:
                    t[key] = t[key] * k
            els.append(t)
        else:
            els.append({"length": e * k})
    total = sum(abs(e.get("length", 0.0)) for e in els)
    return {"name": name, "description": description, "elements": els, "pattern_length": total}


def standard_linetypes(metric: bool) -> list:
    o = {"length": 0.0, "text": "o", "style": "Standard", "scale": 0.1, "rotation": 0.0, "absolute": False, "x": -0.1, "y": -0.05}
    defs = [
        ("BORDER", "Border ____ ____ . ____ ____ .", [0.5, -0.25, 0.5, -0.25, 0.0, -0.25]),
        ("CENTER", "Center ____ _ ____ _ ____ _", [1.25, -0.25, 0.25, -0.25]),
        ("CENTER2", "Center (.5x) ___ _ ___ _", [0.75, -0.125, 0.125, -0.125]),
        ("CENTERX2", "Center (2x) ________ __ ________", [2.5, -0.5, 0.5, -0.5]),
        ("DASHDOT", "Dash dot __ . __ . __ .", [0.5, -0.25, 0.0, -0.25]),
        ("DASHDOT2", "Dash dot (.5x) _._._._", [0.25, -0.125, 0.0, -0.125]),
        ("DASHED", "Dashed __ __ __ __ __", [0.5, -0.25]),
        ("DASHED2", "Dashed (.5x) _ _ _ _ _", [0.25, -0.125]),
        ("DASHEDX2", "Dashed (2x) ____  ____  ____", [1.0, -0.5]),
        ("DIVIDE", "Divide ____ . . ____ . .", [0.5, -0.25, 0.0, -0.25, 0.0, -0.25]),
        ("DOT", "Dot . . . . . .", [0.0, -0.25]),
        ("DOT2", "Dot (.5x) ......", [0.0, -0.125]),
        ("HIDDEN", "Hidden __ __ __ __ __", [0.25, -0.125]),
        ("HIDDEN2", "Hidden (.5x) _ _ _ _ _", [0.125, -0.0625]),
        ("HIDDENX2", "Hidden (2x) ____ ____ ____", [0.5, -0.25]),
        ("PHANTOM", "Phantom ______ __ __ ______", [1.25, -0.25, 0.25, -0.25, 0.25, -0.25]),
        ("PHANTOM2", "Phantom (.5x) ___ _ _ ___", [0.625, -0.125, 0.125, -0.125, 0.125, -0.125]),
        ("FENCELINE1", "Fenceline circle ----0----0----", [0.25, -0.1, o, -0.1, 1.0]),
        ("ZIGZAG", "Zig zag /\\/\\/\\/\\/\\", [0.0001, -0.2, {"length": 0.0, "shape": "ZIG", "style": "", "scale": 0.2, "rotation": 0.0, "absolute": False, "x": 0.0, "y": 0.0}, -0.2]),
    ]
    out = [
        {"name": "ByBlock", "description": "", "elements": [], "pattern_length": 0.0},
        {"name": "ByLayer", "description": "", "elements": [], "pattern_length": 0.0},
        {"name": "Continuous", "description": "Solid line", "elements": [], "pattern_length": 0.0},
    ]
    for name, desc, els in defs:
        out.append(_lt(name, desc, els, metric))
    return out


def new_textstyle(name: str = "Standard", **kw) -> dict:
    rec = {"name": name, "font": "txt", "big_font": "", "height": 0.0, "width_factor": 1.0, "oblique": 0.0, "backwards": False, "upside_down": False, "vertical": False, "annotative": False}
    rec.update(kw)
    return rec


DIM_DEFAULTS = {
    "DIMSCALE": 1.0, "DIMASZ": 0.18, "DIMEXO": 0.0625, "DIMEXE": 0.18, "DIMTXT": 0.18, "DIMGAP": 0.09, "DIMDEC": 4, "DIMADEC": 0,
    "DIMLFAC": 1.0, "DIMTAD": 0, "DIMTIH": 1, "DIMTOH": 1, "DIMBLK": "", "DIMBLK1": "", "DIMBLK2": "", "DIMTSZ": 0.0,
    "DIMCLRD": 0, "DIMCLRE": 0, "DIMCLRT": 0, "DIMTFILL": 0, "DIMTFILLCLR": 0, "DIMTXSTY": "Standard", "DIMPOST": "", "DIMCEN": 0.09,
    "DIMZIN": 0, "DIMLUNIT": 2, "DIMTOL": 0, "DIMTP": 0.0, "DIMTM": 0.0, "DIMDLI": 0.38, "DIMDLE": 0.0, "DIMJUST": 0,
    "DIMRND": 0.0, "DIMDSEP": ".", "DIMFRAC": 0, "DIMLIM": 0, "DIMTDEC": 4, "DIMTFAC": 1.0, "DIMTZIN": 0, "DIMALT": 0,
    "DIMALTF": 25.4, "DIMALTD": 2, "DIMAPOST": "", "DIMALTRND": 0.0, "DIMALTU": 2, "DIMALTZ": 0, "DIMAUNIT": 0,
    "DIMSE1": 0, "DIMSE2": 0, "DIMSD1": 0, "DIMSD2": 0, "DIMATFIT": 3, "DIMTIX": 0, "DIMSOXD": 0, "DIMTOFL": 0,
    "DIMTMOVE": 0, "DIMTVP": 0.0, "DIMTOLJ": 1, "DIMAZIN": 0, "DIMARCSYM": 0, "DIMLDRBLK": "", "DIMLTYPE": "", "DIMLTEX1": "",
    "DIMLTEX2": "", "DIMLWD": -2, "DIMLWE": -2, "DIMFXLON": 0, "DIMFXL": 1.0, "DIMJOGANG": 45.0,
}

ISO25_OVERRIDES = {
    "DIMASZ": 2.5, "DIMEXO": 0.625, "DIMEXE": 1.25, "DIMTXT": 2.5, "DIMGAP": 0.625, "DIMDEC": 2, "DIMCEN": 2.5, "DIMDLI": 3.75,
    "DIMTAD": 1, "DIMTIH": 0, "DIMTOH": 0, "DIMDSEP": ",", "DIMALTF": 0.0394, "DIMFXL": 1.0, "DIMZIN": 8, "DIMTDEC": 2,
}


def new_dimstyle(name: str = "Standard", preset: dict | None = None) -> dict:
    vars_ = dict(DIM_DEFAULTS)
    if preset:
        vars_.update(preset)
    return {"name": name, "vars": vars_, "annotative": False, "description": ""}


def new_mleaderstyle(metric: bool, name: str = "Standard") -> dict:
    if metric:
        return {"name": name, "arrow_size": 2.5, "text_height": 2.5, "landing_gap": 0.625, "dogleg": 5.0, "text_style": "Standard", "annotative": False}
    return {"name": name, "arrow_size": 0.18, "text_height": 0.18, "landing_gap": 0.09, "dogleg": 0.36, "text_style": "Standard", "annotative": False}


def new_tablestyle(metric: bool, name: str = "Standard") -> dict:
    text = 2.5 if metric else 0.18
    margin = 1.0 if metric else 0.06
    cell = lambda nm, mult, align: {"name": nm, "text_style": "Standard", "text_height": text * mult, "text_color": 0, "fill": None, "alignment": align, "margin_h": margin, "margin_v": margin, "borders": {k: {"visible": True, "color": 0, "lineweight": -2} for k in ("top", "inside_h", "bottom", "left", "inside_v", "right")}, "format": "general", "precision": 0, "merge_across": nm == "Title"}
    return {"name": name, "text_height": text, "margin": margin, "title_row": True, "header_row": True, "cell_styles": [cell("Title", 1.4, 5), cell("Header", 1.0, 5), cell("Data", 1.0, 4)]}


def new_mlinestyle(name: str = "STANDARD") -> dict:
    return {"name": name, "description": "", "elements": [{"offset": 0.5, "color": 256, "linetype": "BYLAYER"}, {"offset": -0.5, "color": 256, "linetype": "BYLAYER"}], "start_cap": {"line": False, "outer_arc": False, "inner_arcs": False, "angle": 90.0}, "end_cap": {"line": False, "outer_arc": False, "inner_arcs": False, "angle": 90.0}, "joints": False, "fill": None}


def new_layout(name: str, order: int, metric: bool) -> dict:
    paper = (420.0, 297.0) if metric else (279.4, 215.9)
    return {"name": name, "tab_order": order, "page_setup": {"device": "None", "paper": "", "width": paper[0], "height": paper[1], "margins": [0.0, 0.0, 0.0, 0.0], "landscape": True, "plot_area": "layout", "window": [0.0, 0.0, 0.0, 0.0], "fit": True, "scale": 1.0, "style_table": "", "center": True, "plot_lineweights": True, "display_styles": False, "transparency": False, "paper_mm": True}, "view": None}


def scale_records(metric: bool) -> list:
    out = []
    for nm in METRIC_SCALES:
        a, b = nm.split(":")
        out.append({"name": nm, "paper": float(a), "drawing": float(b)})
    if not metric:
        for nm, p, d in IMPERIAL_EXTRA:
            out.append({"name": nm, "paper": float(p), "drawing": float(d)})
    return out
