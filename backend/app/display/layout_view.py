import json
import math

from app.display import insert, palette
from app.display.resolve import Context
from app.display.state import make_entry, session_values, state_for
from app.doc import layouts, viewports
from app.doc.model import layout_space

MAX_ITEMS = 250000
_encode = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode


def _matrix(vp) -> tuple:
    k = 1.0 / vp.scale
    return (k, 0.0, 0.0, k, vp.center[0] - vp.view_center[0] * k, vp.center[1] - vp.view_center[1] * k)


def _inverse(m) -> tuple:
    k = 1.0 / m[0]
    return (k, 0.0, 0.0, k, -m[4] * k, -m[5] * k)


def _window(vp) -> list:
    box = vp.bounds()
    lo = vp.to_model([box[0], box[1]])
    hi = vp.to_model([box[2], box[3]])
    return [lo[0], lo[1], hi[0], hi[1]]


def _hit(b, w) -> bool:
    return b is not None and b[2] >= w[0] and b[0] <= w[2] and b[3] >= w[1] and b[1] <= w[3]


def _override_values(ctx, ov: dict) -> dict:
    out = {}
    if "color" in ov:
        rgb, c7 = palette.resolve(ov["color"], 7, None)
        out["color"] = list(rgb)
        out["color7"] = c7
    if "lineweight" in ov:
        v = ov["lineweight"]
        out["lw"] = ctx.lw_default if v is None or v < 0 else v / 100.0
    if "linetype" in ov:
        name, pat = ctx.lt_pattern(ov["linetype"])
        out["lt"] = {"name": name, "pattern": pat, "scale": ctx.ltscale} if pat is not None else None
    if "transparency" in ov:
        out["tr"] = min(90.0, max(0.0, float(ov["transparency"]))) / 100.0
    return out


def _apply_override(item: dict, vals: dict) -> None:
    orig = {k: item.get(k) for k in vals}
    for k, v in vals.items():
        item[k] = v
    g = item.get("geom")
    if g and g.get("type") == "compound":
        for part in g["parts"]:
            for k, v in vals.items():
                if k in part and part.get(k) == orig.get(k):
                    part[k] = v


def _psl(item: dict, scale: float) -> None:
    lt = item.get("lt")
    if lt:
        item["lt"] = dict(lt, scale=lt["scale"] / scale)
    g = item.get("geom")
    if g and g.get("type") == "compound":
        for part in g["parts"]:
            lt = part.get("lt")
            if lt:
                part["lt"] = dict(lt, scale=lt["scale"] / scale)


def _convert(item: dict, m, vp, vals, psl) -> dict:
    item["geom"] = insert.xf_geom(item["geom"], m)
    if item.get("prims"):
        item["prims"] = insert.xf_prims(item["prims"], m, None)
    item["bounds"] = insert.xf_bounds(item.get("bounds"), m)
    item["grips"] = []
    item["space"] = "model"
    item["vp"] = vp.handle
    if vals:
        _apply_override(item, vals)
    if not psl:
        _psl(item, vp.scale)
    return item


def _annotative_items(doc, ms, scale_name: str):
    d = doc.drawing
    ents = d.ents
    saved = d.header.get("CANNOSCALE")
    d.header["CANNOSCALE"] = scale_name
    out = {}
    try:
        ctx = Context(doc, session_values())
        for h in ms.current_seq(doc):
            e = ents.get(h)
            if e is None or not e.annotation_scales:
                continue
            made = make_entry(e, ctx, ms.okey.get(h, 0), doc.rev)
            if made is not None:
                out[h] = made
    finally:
        if saved is None:
            d.header.pop("CANNOSCALE", None)
        else:
            d.header["CANNOSCALE"] = saved
    return out


def viewport_items(doc, vp, ms=None, ctx=None) -> list:
    d = doc.drawing
    lrec = d.layer(vp.layer)
    if not vp.on or (lrec is not None and lrec["frozen"]):
        return []
    if ms is None:
        ms = state_for(doc, "model")
        ms.update(doc)
    ctx = ctx or Context(doc, session_values())
    win = _window(vp)
    m = _matrix(vp)
    frozen = {str(n).casefold() for n in vp.frozen}
    entries = ms.entries or {}
    swap = {}
    cur = str(d.header.get("CANNOSCALE", "1:1"))
    want = vp.anno_scale or cur
    if want != cur and d.tables["scales"].has(want):
        swap = _annotative_items(doc, ms, want)
    overrides = {}
    for key, ov in vp.overrides.items():
        vals = _override_values(ctx, ov)
        if vals:
            overrides[key] = vals
    psl = int(d.header.get("PSLTSCALE", 1)) != 0
    ordered = []
    for h, en in entries.items():
        if swap and h in d.ents and d.ents[h].annotation_scales:
            continue
        ordered.append(en)
    ordered.extend(swap.values())
    ordered.sort(key=lambda en: en.order)
    out = []
    for en in ordered:
        if en.layer in frozen or not _hit(en.bounds, win):
            continue
        item = json.loads(en.js)
        vals = overrides.get(en.layer)
        out.append(_convert(item, m, vp, vals, psl))
        if len(out) >= MAX_ITEMS:
            break
    return out


def _vp_dict(doc, vp, content: bool, ms, ctx) -> dict:
    d = doc.drawing
    info = viewports.info(d, vp)
    rec = d.tables["layers"].get(vp.layer)
    info["frame"] = bool(rec is None or (rec.get("on", True) and not rec.get("frozen", False)))
    info["contentVisible"] = bool(vp.on and (rec is None or not rec.get("frozen", False)))
    info["clip"] = [{"p": list(v["p"]), "bulge": v["bulge"]} for v in vp.outline()] if vp.clip else None
    info["outline"] = vp.outline_points()
    info["bounds"] = list(vp.bounds())
    info["matrix"] = list(_matrix(vp))
    info["inverse"] = list(_inverse(_matrix(vp)))
    info["modelWindow"] = _window(vp)
    info["active"] = bool(doc.active_vp == vp.handle)
    info["items"] = viewport_items(doc, vp, ms, ctx) if content and info["contentVisible"] else []
    return info


def layout_dict(doc, name: str, content: bool = True) -> dict:
    d = doc.drawing
    rec = layouts.find(d, name)
    if rec is None:
        raise layouts.LayoutError('Layout "%s" not found.' % name)
    ps = layouts.normalize(d, rec.get("page_setup"))
    w, h = layouts.sheet_units(d, ps)
    k = layouts.unit_mm(d, ps)
    space = layout_space(rec["name"])
    ms = state_for(doc, "model")
    ms.update(doc)
    ctx = Context(doc, session_values())
    vps = [_vp_dict(doc, vp, content, ms, ctx) for vp in viewports.of_space(d, space) if vp.visible]
    out = {
        "name": rec["name"],
        "order": rec.get("tab_order", 0),
        "unit": "mm" if k == 1.0 else "in",
        "unitMm": k,
        "paper": {"name": ps["paper"], "width": w, "height": h, "landscape": ps["landscape"], "widthMm": layouts.sheet_size(ps)[0], "heightMm": layouts.sheet_size(ps)[1]},
        "margins": [m / k for m in ps["margins"]],
        "printable": layouts.printable_units(d, ps),
        "pageSetup": ps,
        "viewports": vps,
        "active": doc.active_vp if doc.tab == space else 0,
        "maximized": doc.vp_max if doc.tab == space else 0,
        "current": doc.tab == space,
    }
    return out


def build_json(doc, key: str) -> str:
    name = key.split(":", 1)[1]
    return _encode(layout_dict(doc, name, True))


def layout_display(doc, name: str, since=None) -> dict:
    from app import display

    lay = layouts.find(doc.drawing, name)
    if lay is None:
        raise layouts.LayoutError('Layout "%s" not found.' % name)
    return display.build_items(doc, since, lay["name"])
