from app.display import palette

DEFAULT_LW = 0.25
LW_BYLAYER = -1
LW_BYBLOCK = -2
LW_DEFAULT = -3


class Props:
    __slots__ = ("layer", "rgb", "c7", "lw", "lt", "tr", "plot", "ltmul", "head")

    def __init__(self, layer, rgb, c7, lw, lt, tr, plot, ltmul):
        self.head = None
        self.layer = layer
        self.rgb = rgb
        self.c7 = c7
        self.lw = lw
        self.lt = lt
        self.tr = tr
        self.plot = plot
        self.ltmul = ltmul


def _num(v, default):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if f == f else default


def pattern_of(rec):
    if rec is None:
        return None
    out = []
    for el in rec.get("elements", ()):
        if "text" in el or "shape" in el:
            continue
        v = _num(el.get("length"), 0.0)
        if out and v != 0.0 and out[-1] != 0.0 and (v > 0) == (out[-1] > 0):
            out[-1] += v
        else:
            out.append(v)
    if not out or all(v < 0 for v in out):
        return None
    if len(out) == 1 and out[0] > 0:
        return None
    return out


class Context:
    def __init__(self, doc, session=None):
        self.doc = doc
        d = doc.drawing
        self.d = d
        h = d.header
        self.metric = d.metric
        self.ltscale = max(_num(h.get("LTSCALE", 1.0), 1.0), 1e-9)
        raw = h.get("LWDEFAULT", 25)
        lw = _num(raw, 25) / 100.0
        self.lw_default = lw if 0.0 <= lw <= 2.11 else DEFAULT_LW
        self.pdmode = int(_num(h.get("PDMODE", 0), 0))
        self.pdsize = _num(h.get("PDSIZE", 0.0), 0.0)
        self.fillmode = int(_num(h.get("FILLMODE", 1), 1))
        self.lwdisplay = int(_num(h.get("LWDISPLAY", 0), 0))
        self.session = session or {}
        self.textfill = int(self.session.get("TEXTFILL", 1))
        self.layers = d.tables["layers"]
        self.lt_cache = {}
        self.layer_cache = {}
        self.style_cache = {}
        self.shape_cache = {}
        self.props_cache = {}
        self.deps = set()

    def layer(self, name):
        return self.layers.get(name)

    def lt_pattern(self, name):
        key = str(name).casefold()
        hit = self.lt_cache.get(key, 0)
        if hit != 0:
            return hit
        rec = self.d.table_get("linetypes", name)
        val = (rec["name"], pattern_of(rec)) if rec is not None else (str(name), None)
        self.lt_cache[key] = val
        return val

    def layer_props(self, name):
        key = str(name).casefold()
        hit = self.layer_cache.get(key)
        if hit is not None:
            return hit
        rec = self.layers.get(name)
        if rec is None:
            val = ((255, 255, 255), True, self.lw_default, "Continuous", 0.0, True)
        else:
            rgb, c7 = palette.resolve(rec.get("color", 7), 7, None)
            lw = rec.get("lineweight", LW_DEFAULT)
            lwv = self.lw_default if lw is None or lw < 0 else lw / 100.0
            tr = min(90.0, max(0.0, _num(rec.get("transparency", 0), 0.0))) / 100.0
            val = (rgb, c7, lwv, rec.get("linetype") or "Continuous", tr, bool(rec.get("plot", True)))
        self.layer_cache[key] = val
        return val

    def layer_summary(self):
        out = {}
        for rec in self.layers.values():
            rgb, c7, lwv, lt, _tr, plot = self.layer_props(rec["name"])
            out[rec["name"]] = {"color": list(rgb), "color7": c7, "on": bool(rec.get("on", True)), "frozen": bool(rec.get("frozen", False)), "locked": bool(rec.get("locked", False)), "lw": lwv, "lt": lt, "plot": plot}
        return out

    def props(self, ent, parent=None):
        if parent is not None:
            return self.props_of(ent, parent)
        try:
            key = (ent.layer, ent.color, ent.lineweight, ent.linetype, ent.ltscale, ent.transparency)
            hit = self.props_cache.get(key)
        except TypeError:
            return self.props_of(ent, None)
        if hit is None:
            hit = self.props_of(ent, None)
            self.props_cache[key] = hit
        return hit

    def props_of(self, ent, parent):
        lname = ent.layer or "0"
        if parent is not None and lname == "0":
            lname = parent.layer
        l_rgb, l_c7, l_lw, l_lt, l_tr, l_plot = self.layer_props(lname)
        col = ent.color
        if isinstance(col, bool):
            col = 256
        if isinstance(col, (int, float)) and int(col) == 256:
            rgb, c7 = l_rgb, l_c7
        elif isinstance(col, (int, float)) and int(col) == 0:
            rgb, c7 = (parent.rgb, parent.c7) if parent is not None else (palette.WHITE, True)
        else:
            rgb, c7 = palette.resolve(col, 7, None)
        lw = ent.lineweight
        if lw is None or lw == LW_BYLAYER:
            lwv = l_lw
        elif lw == LW_BYBLOCK:
            lwv = parent.lw if parent is not None else self.lw_default
        elif lw == LW_DEFAULT:
            lwv = self.lw_default
        else:
            lwv = max(0.0, _num(lw, 25.0) / 100.0)
        ltn = ent.linetype or "ByLayer"
        low = str(ltn).casefold()
        mul = _num(ent.ltscale, 1.0)
        if parent is not None:
            mul *= parent.ltmul
        if low == "bylayer":
            name, pat = self.lt_pattern(l_lt)
        elif low == "byblock":
            if parent is not None and parent.lt is not None:
                name, pat = parent.lt["name"], parent.lt["pattern"]
            else:
                name, pat = "Continuous", None
        else:
            name, pat = self.lt_pattern(ltn)
        lt = None
        if pat is not None:
            lt = {"name": name, "pattern": pat, "scale": self.ltscale * (mul if mul > 0 else 1.0)}
        tr = ent.transparency
        if isinstance(tr, (int, float)) and not isinstance(tr, bool):
            trv = min(90.0, max(0.0, float(tr))) / 100.0
        elif str(tr).casefold() == "byblock":
            trv = parent.tr if parent is not None else 0.0
        else:
            trv = l_tr
        return Props(lname, rgb, c7, lwv, lt, trv, l_plot, mul if mul > 0 else 1.0)

    def visible(self, ent, parent=None):
        if not ent.visible:
            return False
        lname = ent.layer or "0"
        if parent is not None and lname == "0":
            lname = parent.layer
        rec = self.layers.get(lname)
        return rec is None or (rec["on"] and not rec["frozen"])

    def textstyle(self, name):
        key = str(name).casefold()
        rec = self.style_cache.get(key)
        if rec is None:
            rec = self.d.table_get("textstyles", name) or self.d.table_get("textstyles", "Standard") or {}
            self.style_cache[key] = rec
        return rec
