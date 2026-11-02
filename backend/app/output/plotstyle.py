import copy
import json
import os

from app.core import config
from app.output.sheet import PT_PER_MM

FORMAT = "formcad-plot-style"
VERSION = 1
MAX_FILE = 4 * 1024 * 1024
MAX_NAMED = 1024
MAX_NAME = 255
MAX_LW = 2.11
EXT = {"color": ".fcpsc", "named": ".fcpsn"}
CAPS = ("object", "butt", "square", "round", "diamond")
JOINS = ("object", "miter", "bevel", "round", "diamond")
FILLS = ("object", "solid", "checkerboard", "crosshatch", "diamonds", "horizontal", "slant_left", "slant_right", "dots", "vertical")
NONE_NAMES = ("", "none")


class StyleError(Exception):
    pass


def blank_style(name, description=""):
    return {"name": name, "description": description, "color": None, "grayscale": False, "screening": 100, "linetype": None, "lineweight": None, "cap": "object", "join": "object", "fill": "object"}


def clean_style(raw, fallback_name=""):
    if not isinstance(raw, dict):
        raise StyleError("A plot style must be an object.")
    name = str(raw.get("name", fallback_name)).strip()
    if not name or len(name) > MAX_NAME or any(ord(c) < 32 for c in name):
        raise StyleError("A plot style name is 1 to 255 characters.")
    out = blank_style(name, str(raw.get("description", ""))[:MAX_NAME])
    col = raw.get("color")
    if col is not None:
        if not (isinstance(col, (list, tuple)) and len(col) == 3):
            raise StyleError("A style colour is three numbers or null.")
        out["color"] = [max(0, min(255, int(c))) for c in col]
    out["grayscale"] = bool(raw.get("grayscale", False))
    try:
        out["screening"] = max(0, min(100, int(round(float(raw.get("screening", 100))))))
    except (TypeError, ValueError):
        raise StyleError("Screening is a number from 0 to 100.")
    lt = raw.get("linetype")
    out["linetype"] = None if lt is None or str(lt).strip().casefold() in ("", "object", "use object linetype") else str(lt).strip()[:MAX_NAME]
    lw = raw.get("lineweight")
    if lw is not None:
        try:
            lw = float(lw)
        except (TypeError, ValueError):
            raise StyleError("A style lineweight is a number of millimetres or null.")
        if lw != lw:
            raise StyleError("A style lineweight is a number of millimetres or null.")
        out["lineweight"] = max(0.0, min(MAX_LW, lw))
    for key, allowed in (("cap", CAPS), ("join", JOINS), ("fill", FILLS)):
        v = str(raw.get(key, "object")).strip().casefold().replace(" ", "_")
        out[key] = v if v in allowed else "object"
    return out


def color_names():
    return ["Color_%d" % i for i in range(1, 256)]


def new_table(kind, name, description=""):
    if kind not in ("color", "named"):
        raise StyleError("A plot style table is colour-dependent or named.")
    t = {"name": str(name), "kind": kind, "description": description, "order": [], "styles": {}}
    if kind == "color":
        for nm in color_names():
            t["order"].append(nm)
            t["styles"][nm.casefold()] = blank_style(nm)
    else:
        t["order"].append("Normal")
        t["styles"]["normal"] = blank_style("Normal", "Uses the object's own properties.")
    return t


def clean_table(raw):
    if not isinstance(raw, dict):
        raise StyleError("A plot style table must be an object.")
    kind = raw.get("kind")
    name = str(raw.get("name", "")).strip()
    if kind not in ("color", "named"):
        raise StyleError("A plot style table is colour-dependent or named.")
    if not name or len(name) > MAX_NAME:
        raise StyleError("A plot style table name is 1 to 255 characters.")
    t = new_table(kind, name, str(raw.get("description", ""))[:1024])
    items = raw.get("styles", [])
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        raise StyleError("The styles must be a list.")
    if kind == "color":
        valid = {n.casefold() for n in color_names()}
        for it in items:
            st = clean_style(it)
            if st["name"].casefold() in valid:
                st["name"] = "Color_" + st["name"].split("_", 1)[1]
                t["styles"][st["name"].casefold()] = st
    else:
        seen = set()
        order = []
        styles = {}
        for it in items:
            st = clean_style(it)
            k = st["name"].casefold()
            if k in seen:
                continue
            seen.add(k)
            order.append(st["name"])
            styles[k] = st
        if "normal" not in styles:
            order.insert(0, "Normal")
            styles["normal"] = blank_style("Normal", "Uses the object's own properties.")
        if len(order) > MAX_NAMED:
            raise StyleError("A named table holds at most 1024 styles.")
        t["order"], t["styles"] = order, styles
    return t


def to_file(table):
    return {"format": FORMAT, "version": VERSION, "kind": table["kind"], "name": table["name"], "description": table.get("description", ""), "styles": [table["styles"][n.casefold()] for n in table["order"] if table["kind"] == "named" or table["styles"][n.casefold()] != blank_style(n)]}


def parse_file(text):
    if len(text) > MAX_FILE:
        raise StyleError("The plot style file is larger than 4 MiB.")
    try:
        raw = json.loads(text)
    except ValueError:
        raise StyleError("The file is not a plot style table.")
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise StyleError("The file is not a plot style table.")
    try:
        ver = int(raw.get("version", 0))
    except (TypeError, ValueError):
        raise StyleError("The plot style file has no version.")
    if ver > VERSION:
        raise StyleError("The plot style file was written by a newer version.")
    return clean_table(raw)


def mono(name, kind, black):
    t = new_table(kind, name)
    for st in t["styles"].values():
        if black:
            st["color"] = [0, 0, 0]
        else:
            st["grayscale"] = True
    return t


def builtins():
    d = new_table("color", "default", "Object colours, linetypes and lineweights.")
    m = mono("monochrome", "color", True)
    m["description"] = "Every colour prints black."
    g = mono("grayscale", "color", False)
    g["description"] = "Every colour prints as the grey of its luminance."
    n = new_table("named", "default (named)", "Normal, Black, Screened 50% and Thick.")
    for nm, fields, desc in (("Black", {"color": [0, 0, 0]}, "Prints black."), ("Screened 50%", {"screening": 50}, "Half intensity."), ("Thick", {"lineweight": 0.5}, "Half a millimetre.")):
        st = blank_style(nm, desc)
        st.update(fields)
        n["order"].append(nm)
        n["styles"][nm.casefold()] = st
    nm = new_table("named", "monochrome (named)", "Normal prints black.")
    nm["styles"]["normal"]["color"] = [0, 0, 0]
    out = {}
    for t in (d, m, g, n, nm):
        t["builtin"] = True
        out[t["name"].casefold()] = t
    return out


BUILTIN = builtins()


def folder():
    path = os.path.join(config.data_dir(), "plot-styles")
    return path


def file_tables():
    out = {}
    base = folder()
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(tuple(EXT.values())):
            continue
        full = os.path.join(base, fn)
        try:
            if os.path.getsize(full) > MAX_FILE:
                continue
            with open(full, "r", encoding="utf-8") as fh:
                t = parse_file(fh.read())
        except (OSError, StyleError, UnicodeDecodeError):
            continue
        t["file"] = full
        out.setdefault(t["name"].casefold(), t)
    return out


def drawing_tables(d):
    out = {}
    for rec in d.tables["plotstyles"].values():
        try:
            t = clean_table(rec)
        except StyleError:
            continue
        t["stored"] = True
        out[t["name"].casefold()] = t
    return out


def all_tables(d):
    out = dict(BUILTIN)
    out.update(file_tables())
    if d is not None:
        out.update(drawing_tables(d))
    return out


def find(d, name):
    key = str(name or "").strip().casefold()
    if key in NONE_NAMES:
        return None
    return all_tables(d).get(key)


def summary(t):
    return {"name": t["name"], "kind": t["kind"], "description": t.get("description", ""), "builtin": bool(t.get("builtin")), "stored": bool(t.get("stored")), "file": t.get("file", ""), "count": len(t["order"])}


def listing(d):
    return [summary(t) for t in all_tables(d).values()]


def describe(t):
    return {**summary(t), "styles": [t["styles"][n.casefold()] for n in t["order"]]}


def store(doc, table):
    d = doc.drawing
    rec = {k: copy.deepcopy(v) for k, v in table.items() if k in ("name", "kind", "description", "order", "styles")}
    d.table_set("plotstyles", rec)
    return rec


def editable_copy(doc, name):
    d = doc.drawing
    t = find(d, name)
    if t is None:
        raise StyleError('Plot style table "%s" not found.' % name)
    if t.get("stored"):
        return d.tables["plotstyles"].get(t["name"])
    return store(doc, t)


def luminance(rgb):
    return 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]


def printed_color(style, obj_rgb, obj_c7):
    if style is not None and style["color"] is not None:
        rgb = tuple(style["color"])
    elif obj_c7:
        rgb = (0, 0, 0)
    else:
        rgb = tuple(obj_rgb)
    if style is not None and style["grayscale"]:
        g = int(round(luminance(rgb)))
        rgb = (g, g, g)
    if style is not None and style["screening"] < 100:
        s = style["screening"] / 100.0
        rgb = tuple(int(round(255 - (255 - c) * s)) for c in rgb)
    return rgb


def lookup(table, aci, style_name):
    if table is None:
        return None
    if table["kind"] == "color":
        return table["styles"].get(("color_%d" % aci).casefold())
    key = str(style_name or "normal").casefold()
    return table["styles"].get(key) or table["styles"].get("normal")


def cap_code(name, default=1):
    return {"butt": 0, "round": 1, "square": 2, "diamond": 1}.get(name, default)


def join_code(name, default=1):
    return {"miter": 0, "round": 1, "bevel": 2, "diamond": 0}.get(name, default)


def edit_style(table, name, fields):
    key = str(name).casefold()
    st = table["styles"].get(key)
    if st is None:
        raise StyleError('Plot style "%s" not found.' % name)
    merged = {**st}
    for k, v in fields.items():
        if k == "name":
            continue
        if k not in st:
            raise StyleError("Unknown plot style field %s." % k)
        merged[k] = v
    table["styles"][key] = clean_style(merged, st["name"])
    return table["styles"][key]


def add_style(table, name, fields=None):
    if table["kind"] != "named":
        raise StyleError("Styles are added only to named tables.")
    nm = str(name).strip()
    if not nm:
        raise StyleError("A plot style needs a name.")
    if nm.casefold() in table["styles"]:
        raise StyleError('A plot style named "%s" already exists.' % nm)
    if len(table["order"]) >= MAX_NAMED:
        raise StyleError("A named table holds at most 1024 styles.")
    st = clean_style({**blank_style(nm), **(fields or {}), "name": nm})
    table["order"].append(nm)
    table["styles"][nm.casefold()] = st
    return st


def remove_style(table, name):
    if table["kind"] != "named":
        raise StyleError("Styles are removed only from named tables.")
    key = str(name).casefold()
    if key == "normal":
        raise StyleError("The Normal style cannot be removed.")
    if key not in table["styles"]:
        raise StyleError('Plot style "%s" not found.' % name)
    del table["styles"][key]
    table["order"] = [n for n in table["order"] if n.casefold() != key]


def save_to_folder(table, path=None):
    target = path or os.path.join(folder(), "".join(c if c.isalnum() or c in "-_ ()" else "_" for c in table["name"]) + EXT[table["kind"]])
    target = os.path.abspath(os.path.expanduser(str(target)))
    root, ext = os.path.splitext(target)
    if ext.lower() != EXT[table["kind"]]:
        target = root + EXT[table["kind"]]
    os.makedirs(os.path.dirname(target), exist_ok=True)
    from app.core import outputs

    try:
        target = outputs.checked(target, (EXT[table["kind"]],))
    except outputs.OutputRefused as err:
        raise StyleError(str(err))
    with open(target, "w", encoding="utf-8") as fh:
        json.dump(to_file(table), fh, indent=1, ensure_ascii=False)
    return target


def width_pt(mm):
    return mm * PT_PER_MM
