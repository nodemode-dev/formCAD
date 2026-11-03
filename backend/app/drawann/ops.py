import math

from app.doc import geom
from app.drawann import glyphs, settings, viewsrc
from app.doc.kinds.drawann import Balloon, CenterMark, DatumSymbol, FinishMark, GdtFrame


class AnnError(Exception):
    pass


def pt(v, what="point"):
    try:
        p = geom.as_pt(v)
    except Exception:
        raise AnnError("The %s is two numbers." % what)
    if not all(math.isfinite(x) for x in p):
        raise AnnError("The %s must be finite." % what)
    return [float(p[0]), float(p[1]), 0.0]


def num(v, what, lo=None, hi=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise AnnError("%s is a number." % what)
    if not math.isfinite(f) or (lo is not None and f < lo) or (hi is not None and f > hi):
        raise AnnError("%s is out of range." % what)
    return f


def link_arg(d, args, key="tip_link"):
    link = args.get(key)
    if link is None:
        return None
    if not isinstance(link, dict) or "h" not in link or "e" not in link:
        raise AnnError("A link is {h: view, e: edge, t: start|end|mid|center|ang}.")
    link = {"h": int(link["h"]), "e": str(link["e"]), "t": str(link.get("t", "end")), **({"a": float(link["a"])} if "a" in link else {})}
    if viewsrc.point(d, link) is None:
        raise AnnError("The link does not name a point of a drawing view.")
    return link


def tip_of(d, args, key="tip", link_key="tip_link", tol=None):
    link = link_arg(d, args, link_key)
    if link is not None:
        p = viewsrc.point(d, link)
        return [p[0], p[1], 0.0], link
    if args.get(key) is None:
        return None, {}
    p = pt(args[key], key)
    view = args.get("view")
    if view not in (None, "", 0):
        v = viewsrc.need(d, view)
        tol = tol if tol is not None else d.tolerances["absolute"] * 10.0
        link = viewsrc.link_for_point(d, v, (p[0], p[1]), tol)
        if link:
            q = viewsrc.point(d, link)
            return [q[0], q[1], 0.0], link
    return p, {}


def datums_of(raw):
    out = []
    for item in raw or []:
        if isinstance(item, str):
            ref, mod = item, ""
        elif isinstance(item, dict):
            ref, mod = item.get("ref", ""), item.get("mod", "")
        else:
            raise AnnError("A datum reference is a letter or {ref, mod}.")
        if str(ref).strip() == "":
            continue
        try:
            out.append({"ref": glyphs.datum_letter(ref), "mod": glyphs.modifier_of(mod)})
        except glyphs.GlyphError as err:
            raise AnnError(str(err))
    if len(out) > 3:
        raise AnnError("A frame holds at most three datum references.")
    return out


def apply_frame(d, e, args):
    try:
        if "char" in args or "characteristic" in args:
            e.char = glyphs.key_of(args.get("char", args.get("characteristic")))
        if "tolerance" in args:
            t = str(args["tolerance"]).strip()
            if len(t) > 24:
                raise AnnError("The tolerance value holds at most 24 characters.")
            if t.startswith("-"):
                raise AnnError("A tolerance value cannot be negative.")
            e.tolerance = t
        if "zone" in args:
            e.zone = glyphs.zone_of(args["zone"])
        if "modifier" in args:
            e.modifier = glyphs.modifier_of(args["modifier"])
        if "projected" in args:
            e.projected = bool(args["projected"])
        if "datums" in args:
            e.datums = datums_of(args["datums"])
        if "order" in args:
            e.order = settings.check_order(args["order"]) if args["order"] else []
    except (glyphs.GlyphError, settings.SettingsError) as err:
        raise AnnError(str(err))
    if "height" in args:
        e.text_height = num(args["height"], "The text height", 0.0, 1000.0)
    if "rotation" in args:
        e.rotation = math.radians(num(args["rotation"], "The rotation", -3600.0, 3600.0))
    for k in ("note_above", "note_below"):
        if k in args:
            setattr(e, k, str(args[k])[:60])
    if "arrow" in args:
        e.arrow = bool(args["arrow"])
    if "leader_side" in args:
        s = str(args["leader_side"] or "").lower()
        if s not in ("", "left", "right"):
            raise AnnError("The leader side is left or right.")
        e.leader_side = s
    if "leader" in args and args["leader"] is not None:
        pts = [pt(p, "leader point") for p in args["leader"]]
        e.leader = pts
        e.leader_link = {}
    tip, link = tip_of(d, args, "tip", "leader_link")
    if tip is not None:
        e.leader = [tip] + [list(p) for p in e.leader[1:]]
        e.leader_link = link
    if "leader_clear" in args and args["leader_clear"]:
        e.leader, e.leader_link = [], {}


def new_frame(d, args):
    e = GdtFrame(position=pt(args.get("point", args.get("position", [0.0, 0.0]))))
    apply_frame(d, e, args)
    return e


def new_datum(d, args):
    e = DatumSymbol(position=pt(args.get("point", args.get("position", [0.0, 0.0]))))
    try:
        e.letter = glyphs.datum_letter(args.get("letter", "A"))
    except glyphs.GlyphError as err:
        raise AnnError(str(err))
    if "height" in args:
        e.text_height = num(args["height"], "The text height", 0.0, 1000.0)
    if "filled" in args:
        e.filled = bool(args["filled"])
    tip, link = tip_of(d, args)
    e.tip, e.tip_link = tip, link
    return e


def new_balloon(d, args):
    e = Balloon(position=pt(args.get("point", args.get("position", [0.0, 0.0]))))
    text = args.get("text", args.get("item"))
    if text in (None, ""):
        raise AnnError("Give the balloon text or the BOM item.")
    e.text = str(text)[:12]
    e.item = str(args.get("item", e.text))
    e.part_key = str(args.get("part_key", ""))
    if args.get("diameter") is not None:
        e.diameter = num(args["diameter"], "The diameter", 0.5, 200.0)
    if args.get("end") is not None:
        end = str(args["end"]).lower()
        if end not in ("arrow", "dot"):
            raise AnnError("The balloon end is arrow or dot.")
        e.end = end
    tip, link = tip_of(d, args)
    e.tip, e.tip_link = tip, link
    return e


def new_finish(d, args):
    e = FinishMark(position=pt(args.get("point", args.get("position", [0.0, 0.0]))))
    v = str(args.get("value", "Ra 3.2")).strip()
    if not v or len(v) > 24:
        raise AnnError("The surface finish value holds 1 to 24 characters.")
    e.value = v
    if args.get("height") is not None:
        e.height = num(args["height"], "The text height", 0.0, 1000.0)
    if args.get("rotation") is not None:
        e.rotation = math.radians(num(args["rotation"], "The rotation", -3600.0, 3600.0))
    tip, link = tip_of(d, args, "point", "tip_link")
    if link:
        e.position, e.tip_link = tip, link
    return e


def new_centermark(d, args):
    mode = str(args.get("mode", "circle")).lower()
    if mode not in ("circle", "axis"):
        raise AnnError("The mode is circle or axis.")
    e = CenterMark(mode=mode)
    link = link_arg(d, args, "link")
    if mode == "circle":
        if link:
            view = viewsrc.need(d, link["h"])
            ed = viewsrc.edge(d, view, link["e"])
            if ed is None or ed["type"] not in ("circle", "arc"):
                raise AnnError("The edge is not a circle or an arc.")
            e.center, e.radius = [float(ed["c"][0]), float(ed["c"][1]), 0.0], float(ed["r"])
            e.link = {"h": link["h"], "e": link["e"], "t": "center"}
            e.view, e.edge = int(link["h"]), link["e"]
        else:
            e.center = pt(args.get("center"), "center")
            e.radius = num(args.get("radius"), "The radius", 1e-6, 1e9)
    else:
        a_link, b_link = link_arg(d, args, "a_link"), link_arg(d, args, "b_link")
        e.a = pt(viewsrc.point(d, a_link), "a") if a_link else pt(args.get("a"), "a")
        e.b = pt(viewsrc.point(d, b_link), "b") if b_link else pt(args.get("b"), "b")
        e.a_link, e.b_link = a_link or {}, b_link or {}
        e.center = [(e.a[0] + e.b[0]) / 2.0, (e.a[1] + e.b[1]) / 2.0, 0.0]
    return e
