import copy
import math
import os
from types import SimpleNamespace

import ezdxf
from ezdxf.document import Drawing as DxfDoc
from ezdxf.math import Vec2, Vec3

from app.interchange import dxfcommon as C
from app.interchange import dxfw_tables as TB
from app.interchange.errors import InterchangeError, Report

MAX_ARRAY_BLOCK = 20000
R2000 = 1
R2004 = 2
R2007 = 3
SNAP_KINDS = ("assoc_array", "table", "mleader", "dimension", "helix", "mline", "region", "viewport", "wipeout", "hatch", "insert", "leader")
KIND_SIG_KEYS = {
    "assoc_array": ("base",), "table": ("position",), "mleader": ("landing", "content_pos", "text"), "dimension": ("def_point", "p13", "p14", "p15", "p16", "dim_type"),
    "helix": ("center", "height"), "mline": ("vertices", "scale"), "region": (), "viewport": ("center", "width", "height"), "wipeout": ("points",),
    "hatch": ("pattern", "solid"), "insert": ("block", "position"), "leader": ("points",),
}
BASE_EXTRAS = ("annotation_scales", "reactors", "extra", "plot_style")
DIMTYPE = {"linear": 0, "aligned": 1, "angular": 2, "diameter": 3, "radius": 4, "angular3": 5, "ordinate": 6, "arc": 5, "jogged": 4, "center": 4}


def _p3(p):
    return (float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0)


def _p2(p):
    return (float(p[0]), float(p[1]))


class Writer:
    def __init__(self, drawing, version: str = "", report: Report | None = None, precision: int = 16):
        self.d = drawing
        fx = drawing.foreign.get("dxf", {}) if isinstance(drawing.foreign, dict) else {}
        self.fx = fx
        self.version = version or (C.default_version(fx.get("acadver", "")) if fx.get("acadver") else C.DEFAULT_VERSION)
        self.rank = C.version_rank(self.version)
        self.r = report or Report()
        self.precision = precision
        self.doc = None
        self.msp = None
        self.paper = {}
        self.blocks = {}
        self.counter = {"D": 0, "A": 0, "T": 0}
        self.shadow = None
        self.clip_made = {}
        self.region_parts = []

    def start(self) -> None:
        top = max([e.handle for e in self.d.ents.values()] + [self.d.next_handle, 0x100])
        doc = DxfDoc(C.VERSIONS[self.version])
        doc.entitydb.handles.reset("%X" % (top + 0x1000))
        doc._setup()
        doc._create_ezdxf_metadata()
        self.doc = doc
        self.msp = doc.modelspace()
        cp = self.fx.get("codepage")
        if cp and self.rank < R2007:
            try:
                doc.header["$DWGCODEPAGE"] = cp
            except Exception:
                pass
        for name in (C.APPID, "ACAD"):
            if name not in doc.appids:
                doc.appids.new(name)

    def appid(self, name: str) -> None:
        if name not in self.doc.appids:
            self.doc.appids.new(name)

    def write_header(self) -> None:
        h = self.doc.header
        hd = self.d.header
        for fc, dxf, kind in C.HEADER_MAP:
            if fc not in hd:
                continue
            v = hd[fc]
            try:
                if kind == "rad":
                    v = math.radians(float(v))
                elif kind == "deg":
                    v = float(v)
                elif kind == "pt2":
                    v = (float(v[0]), float(v[1]))
                elif kind == "pt3":
                    v = (float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0)
                elif kind == "int":
                    v = int(v)
                elif kind == "real":
                    v = float(v)
                elif kind == "scale":
                    continue
                else:
                    v = str(v)
                h[dxf] = v
            except Exception:
                continue
        raw = self.fx.get("header", {})
        for name, val in raw.items():
            if name in C.MAPPED_DXF or name in C.HEADER_SKIP:
                continue
            try:
                h[name] = tuple(val) if isinstance(val, list) else val
            except Exception:
                continue
        try:
            h["$LTSCALE"] = float(hd.get("LTSCALE", 1.0))
            h["$HANDSEED"] = "%X" % self.doc.entitydb.handles._handle
        except Exception:
            pass
        names = {"$CLAYER": "CLAYER", "$CELTYPE": "CELTYPE", "$TEXTSTYLE": "TEXTSTYLE", "$DIMSTYLE": "DIMSTYLE", "$CMLSTYLE": "CMLSTYLE"}
        for dxf, fc in names.items():
            if fc in hd:
                try:
                    val = str(hd[fc])
                    if dxf == "$CELTYPE":
                        val = "BYLAYER" if val.casefold() == "bylayer" else ("BYBLOCK" if val.casefold() == "byblock" else val)
                    h[dxf] = val
                except Exception:
                    pass

    def snap_table(self, entry, rec: dict) -> None:
        try:
            entry.set_xdata(C.APPID, C.pack_snapshot({"rec": rec}))
        except Exception:
            pass

    def write_tables(self) -> None:
        d = self.d
        doc = self.doc
        for rec in d.tables["linetypes"].values():
            n = rec["name"]
            if n.casefold() in ("bylayer", "byblock", "continuous"):
                continue
            pat = TB.linetype_pattern(rec)
            try:
                lt = doc.linetypes.new(n, {"description": rec.get("description", ""), "pattern": pat or [0.0]})
                self.snap_table(lt, rec)
            except Exception:
                self.r.warn('Linetype "%s" was written without its pattern.' % n)
        for rec in d.tables["textstyles"].values():
            self.write_textstyle(rec)
        for rec in d.tables["layers"].values():
            self.write_layer(rec)
        for rec in d.tables["dimstyles"].values():
            self.write_dimstyle(rec)
        for rec in d.tables["mlinestyles"].values():
            try:
                st = doc.mline_styles.new(rec["name"]) if rec["name"] not in doc.mline_styles else doc.mline_styles.get(rec["name"])
                st.elements.elements.clear()
                for el in rec.get("elements", []):
                    col = el.get("color", 256)
                    st.elements.append(float(el.get("offset", 0.0)), color=int(col) if isinstance(col, int) else 256, linetype=str(el.get("linetype", "BYLAYER")))
                st.dxf.description = rec.get("description", "")
            except Exception:
                self.r.warn('Multiline style "%s" could not be written natively.' % rec["name"])
        for rec in d.tables["mleaderstyles"].values():
            try:
                if rec["name"] not in doc.mleader_styles:
                    st = doc.mleader_styles.new(rec["name"])
                    st.set_mtext_style(rec.get("text_style", "Standard"))
                    st.dxf.char_height = float(rec.get("text_height", 2.5))
                    st.dxf.arrow_head_size = float(rec.get("arrow_size", 2.5))
                    st.dxf.landing_gap_size = float(rec.get("landing_gap", 0.0))
                    st.dxf.landing_distance = float(rec.get("dogleg", 0.0))
            except Exception:
                pass

    def write_textstyle(self, rec: dict) -> None:
        doc = self.doc
        n = rec["name"]
        font = str(rec.get("font", "txt"))
        attrs = {"height": float(rec.get("height", 0.0)), "width": float(rec.get("width_factor", 1.0)), "oblique": float(rec.get("oblique", 0.0))}
        family = ""
        if "." in font:
            attrs["font"] = font
        else:
            family = font
            attrs["font"] = font + ".ttf" if font.lower() not in ("txt", "simplex", "romans", "monotxt") else font + ".shx"
        if rec.get("big_font"):
            attrs["bigfont"] = rec["big_font"]
        gen = (2 if rec.get("backwards") else 0) | (4 if rec.get("upside_down") else 0)
        attrs["generation_flags"] = gen
        try:
            if doc.styles.has_entry(n):
                st = doc.styles.get(n)
                for k, v in attrs.items():
                    st.dxf.set(k, v)
            else:
                st = doc.styles.new(n, attrs)
            if rec.get("vertical"):
                st.dxf.flags = st.dxf.get("flags", 0) | 4
            if family and attrs["font"].endswith(".ttf"):
                st.set_extended_font_data(family)
            self.snap_table(st, rec)
        except Exception as err:
            self.r.warn('Text style "%s" was written partly: %s' % (n, err))

    def write_layer(self, rec: dict) -> None:
        doc = self.doc
        n = rec["name"]
        col = rec.get("color", 7)
        attrs = {}
        true = None
        if isinstance(col, str) and col.startswith("#"):
            true = int(col[1:], 16)
            aci = TB.nearest_aci(col)
        else:
            aci = int(col) if int(col) > 0 else 7
        flags = (1 if rec.get("frozen") else 0) | (4 if rec.get("locked") else 0) | (2 if rec.get("new_vp_freeze") else 0)
        if "|" in n:
            flags |= 16 | 32
        attrs["color"] = -aci if not rec.get("on", True) else aci
        attrs["flags"] = flags
        lt = str(rec.get("linetype", "Continuous"))
        attrs["linetype"] = lt if lt.casefold() not in ("bylayer", "byblock") else "Continuous"
        attrs["plot"] = 1 if rec.get("plot", True) else 0
        lw = int(rec.get("lineweight", -3))
        if self.rank >= R2000:
            attrs["lineweight"] = lw
        try:
            layer = doc.layers.get(n) if doc.layers.has_entry(n) else doc.layers.new(n)
            for k, v in attrs.items():
                layer.dxf.set(k, v)
            if true is not None and self.rank >= R2004:
                layer.dxf.true_color = true
            if self.rank >= R2004:
                t = int(rec.get("transparency", 0) or 0)
                if t:
                    layer.transparency = t / 100.0
            if rec.get("description"):
                layer.description = str(rec["description"])
            self.snap_table(layer, rec)
        except Exception as err:
            self.r.warn('Layer "%s" was written partly: %s' % (n, err))

    def write_dimstyle(self, rec: dict) -> None:
        doc = self.doc
        n = rec["name"]
        vars_ = rec.get("vars", {})
        try:
            st = doc.dimstyles.get(n) if doc.dimstyles.has_entry(n) else doc.dimstyles.new(n)
            for k, v in TB.dimstyle_attribs(vars_, self.rank).items():
                try:
                    if st.dxf.is_supported(k):
                        st.dxf.set(k, v)
                except Exception:
                    continue
            for name, key in (("DIMTXSTY", "dimtxsty"), ("DIMBLK", "dimblk"), ("DIMBLK1", "dimblk1"), ("DIMBLK2", "dimblk2"), ("DIMLDRBLK", "dimldrblk")):
                v = vars_.get(name)
                if v:
                    try:
                        if name != "DIMTXSTY":
                            self.arrow_block(str(v))
                        st.dxf.set(key, str(v))
                    except Exception:
                        pass
            self.snap_table(st, rec)
        except Exception as err:
            self.r.warn('Dimension style "%s" was written partly: %s' % (n, err))

    def arrow_block(self, name: str) -> None:
        if not name or name in self.doc.blocks:
            return
        try:
            from ezdxf.render.arrows import ARROWS

            ARROWS.create_block(self.doc.blocks, name)
        except Exception:
            pass

    def write_blocks(self) -> None:
        d = self.d
        for rec in d.tables["blocks"].values():
            n = rec["name"]
            xr = rec.get("xref")
            if isinstance(xr, dict) and "|" not in n:
                path = str(xr.get("path", ""))
                try:
                    from ezdxf import xref as XR

                    XR.define(self.doc, path, n, overlay=bool(xr.get("overlay")))
                    br = self.doc.block_records.get(n)
                    self.snap_table(br, rec)
                except Exception as err:
                    self.r.warn('External reference "%s" could not be recorded: %s' % (n, err))
                continue
            if "|" in n and isinstance(xr, dict):
                continue
            self.define_block(rec)

    def define_block(self, rec: dict):
        n = rec["name"]
        if n in self.blocks:
            return self.blocks[n]
        base = rec.get("base") or [0, 0, 0]
        try:
            blk = self.doc.blocks.new(n, base_point=_p3(base))
        except Exception:
            blk = self.doc.blocks.get(n)
        self.blocks[n] = blk
        br = blk.block_record
        try:
            units = int(rec.get("insunits", 0) or 0)
            if self.rank >= R2007:
                br.dxf.units = units
                br.dxf.explode = 1 if rec.get("explodable", True) else 0
                br.dxf.scale = 3
        except Exception:
            pass
        self.snap_table(br, rec)
        return blk

    def block_layout(self, name: str):
        if name in self.blocks:
            return self.blocks[name]
        rec = self.d.tables["blocks"].get(name)
        if rec is None:
            rec = {"name": name, "base": [0, 0, 0], "description": "", "explodable": True, "insunits": 0, "annotative": False, "anonymous": name.startswith("*"), "xref": None}
        return self.define_block(rec)

    def write_layouts(self) -> None:
        d = self.d
        doc = self.doc
        recs = sorted(d.tables["layouts"].values(), key=lambda r: r.get("tab_order", 0))
        if self.rank < R2000:
            if len(recs) > 1:
                self.r.drop("layouts", len(recs) - 1)
                self.r.note("R12 holds one paper space; only the first layout was saved.")
            for rec in recs[:1]:
                self.paper[rec["name"]] = doc.layout("Layout1") if "Layout1" in doc.layouts.names() else None
            return
        for i, rec in enumerate(recs):
            try:
                if i == 0:
                    if rec["name"] != "Layout1":
                        doc.layouts.rename("Layout1", rec["name"])
                    lay = doc.layouts.get(rec["name"])
                else:
                    lay = doc.layouts.new(rec["name"])
            except Exception as err:
                self.r.warn('Layout "%s" was skipped: %s' % (rec["name"], err))
                continue
            self.paper[rec["name"]] = lay
            lay.dxf.taborder = i + 1
            self.apply_page_setup(lay, rec)

    def apply_page_setup(self, lay, rec: dict) -> None:
        ps = rec.get("page_setup") or {}
        x = lay.dxf
        w, h = float(ps.get("width", 297.0)), float(ps.get("height", 210.0))
        lo, hi = min(w, h), max(w, h)
        land = bool(ps.get("landscape", True))
        try:
            x.paper_width, x.paper_height = lo, hi
            x.plot_rotation = 1 if land else 0
            m = ps.get("margins") or [0, 0, 0, 0]
            x.left_margin, x.bottom_margin, x.right_margin, x.top_margin = [float(v) for v in m]
            x.plot_paper_units = 1 if ps.get("paper_mm", True) else 0
            flags = 0
            if ps.get("display_styles"):
                flags |= 2
            if ps.get("center", True):
                flags |= 4
            if not ps.get("fit", True):
                flags |= 16
            if ps.get("plot_lineweights", True):
                flags |= 128
            if ps.get("style_table"):
                flags |= 32
            x.plot_layout_flags = flags
            area = {"display": 0, "extents": 1, "limits": 2, "view": 3, "window": 4, "layout": 5}.get(str(ps.get("plot_area", "layout")), 5)
            x.plot_type = area
            win = ps.get("window") or [0, 0, 0, 0]
            x.plot_window_x1, x.plot_window_y1, x.plot_window_x2, x.plot_window_y2 = [float(v) for v in win]
            s = float(ps.get("scale", 1.0) or 1.0)
            if s >= 1:
                x.scale_numerator, x.scale_denominator = s, 1.0
            else:
                x.scale_numerator, x.scale_denominator = 1.0, 1.0 / s
            off = ps.get("offset") or [0.0, 0.0]
            x.plot_origin_x_offset, x.plot_origin_y_offset = float(off[0]), float(off[1])
            x.current_style_sheet = str(ps.get("style_table") or "")
            if ps.get("device") and ps["device"] != "None":
                x.plot_configuration_file = str(ps["device"])
            x.paper_size = str(ps.get("paper") or "")
        except Exception as err:
            self.r.warn('Page setup of layout "%s" was written partly: %s' % (rec["name"], err))

    def write_views(self) -> None:
        d = self.d
        for rec in d.tables["views"].values():
            if str(rec["name"]).startswith("*"):
                continue
            try:
                v = self.doc.views.new(rec["name"])
                c = rec.get("center") or [0, 0]
                v.dxf.center = _p2(c)
                v.dxf.height = float(rec.get("height", 1.0))
                v.dxf.width = float(rec.get("width", rec.get("height", 1.0)))
                v.dxf.view_twist = math.degrees(float(rec.get("twist", 0.0) or 0.0))
                v.dxf.flags = 1 if str(rec.get("space", "model")) != "model" else 0
                self.snap_table(v, rec)
            except Exception as err:
                self.r.warn('View "%s" was written partly: %s' % (rec["name"], err))
        for rec in d.tables["ucs"].values():
            try:
                u = self.doc.ucs.new(rec["name"])
                u.dxf.origin = _p3(rec.get("origin", [0, 0, 0]))
                u.dxf.xaxis = _p3(rec.get("x_axis", rec.get("xaxis", [1, 0, 0])))
                u.dxf.yaxis = _p3(rec.get("y_axis", rec.get("yaxis", [0, 1, 0])))
                self.snap_table(u, rec)
            except Exception as err:
                self.r.warn('UCS "%s" was written partly: %s' % (rec["name"], err))
        for rec in d.tables["vports"].values():
            tiles = rec.get("tiles", [])
            for t in tiles:
                try:
                    vp = self.doc.viewports.new(rec["name"])
                    ll, ur = t.get("lower_left", [0, 0]), t.get("upper_right", [1, 1])
                    vp.dxf.lower_left = _p2(ll)
                    vp.dxf.upper_right = _p2(ur)
                    vp.dxf.center = _p2(t.get("center", [0, 0]))
                    vp.dxf.height = float(t.get("height", 1.0))
                    vp.dxf.aspect_ratio = float(t.get("aspect", 1.0)) or 1.0
                except Exception:
                    continue
            if tiles:
                try:
                    first = self.doc.viewports.get(rec["name"])
                    first = first[0] if isinstance(first, list) else first
                    self.snap_table(first, rec)
                except Exception:
                    pass

    def props(self, e) -> dict:
        a = {"layer": e.layer or "0"}
        col = e.color
        if isinstance(col, str) and col.startswith("#"):
            if self.rank >= R2004:
                a["true_color"] = int(col[1:], 16)
            else:
                a["color"] = TB.nearest_aci(col)
        elif isinstance(col, (int, float)) and int(col) != 256:
            a["color"] = int(col)
        lt = str(e.linetype or "ByLayer")
        if lt.casefold() == "byblock":
            a["linetype"] = "BYBLOCK"
        elif lt.casefold() != "bylayer":
            a["linetype"] = lt
        if self.rank >= R2000 and int(e.lineweight) != -1:
            a["lineweight"] = int(e.lineweight)
        if abs(float(e.ltscale) - 1.0) > 1e-12:
            a["ltscale"] = float(e.ltscale)
        if self.rank >= R2004:
            t = e.transparency
            if t == "ByBlock":
                a["transparency"] = 0x01000000
            elif isinstance(t, (int, float)) and not isinstance(t, bool):
                alpha = round(255 * (100 - float(t)) / 100.0)
                a["transparency"] = 0x02000000 | max(0, min(255, alpha))
        if not e.visible:
            a["invisible"] = 1
        if abs(float(e.thickness)) > 0:
            a["thickness"] = float(e.thickness)
        n = e.normal
        if n and (abs(n[0]) > 1e-12 or abs(n[1]) > 1e-12 or abs(n[2] - 1.0) > 1e-12):
            a["extrusion"] = _p3(n)
        return a

    def space_layout(self, space: str):
        if space == "model":
            return self.msp
        if space.startswith("layout:"):
            return self.paper.get(space[7:])
        if space.startswith("block:"):
            return self.block_layout(space[6:])
        return None

    def write_entities(self) -> None:
        d = self.d
        order = ["model"] + [s for s in d.spaces if s.startswith("layout:")] + [s for s in d.spaces if s.startswith("block:")]
        for space in order:
            handles = d.spaces.get(space, [])
            lay = self.space_layout(space)
            if lay is None:
                if handles:
                    self.r.drop("objects in missing layouts", len(handles))
                continue
            if space.startswith("layout:"):
                self.sheet_viewport(lay, space[7:])
            for h in handles:
                e = d.ents.get(h)
                if e is None:
                    continue
                try:
                    self.write_entity(e, lay)
                except Exception as err:
                    self.r.drop(e.kind)
                    self.r.warn("A %s (handle %X) was not saved: %s" % (e.kind, e.handle, err))

    def fix_handle(self, ent, handle: int) -> None:
        if not handle or ent is None:
            return
        hx = "%X" % handle
        if ent.dxf.handle == hx:
            return
        if not self.doc.entitydb.reset_handle(ent, hx):
            self.r.warn("Handle %X was already taken in the output." % handle)

    def put_xdata(self, ent, e) -> None:
        if e.xdata:
            for app, items in e.xdata.items():
                try:
                    self.appid(app)
                    ent.set_xdata(app, [(int(c), v) for c, v in items])
                except Exception:
                    continue

    def put_snapshot(self, ent, e) -> None:
        kind = e.kind
        payload = None
        sig = ""
        if kind in C.FULL_KINDS:
            payload = {"kind": kind, "ent": e.to_dict()}
            sig = C.sig_of(C.sig_values(e))
        else:
            extras = {k: copy.deepcopy(getattr(e, k)) for k in C.BASE_EXTRAS if getattr(e, k, None) not in (None, [], {}, "ByLayer")}
            native = C.NATIVE_FIELDS.get(kind)
            kf = {}
            if native is not None:
                skip = set(C.COMMON_FIELDS) | set(native) | {"kind"}
                kf = {k: v for k, v in e.to_dict().items() if k not in skip}
            if extras or kf:
                payload = {"kind": kind, "extras": extras, "kfields": kf}
        if payload is not None:
            try:
                ent.set_xdata(C.APPID, C.pack_snapshot(payload, sig))
            except Exception:
                pass

    def write_entity(self, e, lay) -> None:
        fn = getattr(self, "w_" + e.kind, None)
        if fn is None:
            if e.kind == "unknown":
                return self.w_unknown(e, lay)
            self.r.drop(e.kind)
            return
        if self.rank < R2000 and e.kind in ("mtext", "spline", "ellipse", "hatch", "leader", "mleader", "mline", "wipeout", "ray", "xline", "table", "assoc_array", "helix", "region", "lwpolyline"):
            fn = self.r12_fallback(e)
            if fn is None:
                self.r.drop(e.kind)
                return
            self.r.convert(e.kind + " to simple geometry")
            for sub in fn:
                self.write_entity(sub, lay)
            return
        main = fn(e, lay)
        if main is None:
            return
        ents = main if isinstance(main, list) else [main]
        first = ents[0]
        for extra in ents[1:]:
            try:
                self.appid(C.APPID)
                extra.set_xdata(C.APPID, [(1000, "FCPART"), (1000, "%X" % e.handle)])
            except Exception:
                pass
        self.fix_handle(first, e.handle)
        self.put_xdata(first, e)
        self.put_snapshot(first, e)
        self.r.count(e.kind)

    def r12_fallback(self, e):
        from app.doc import geom
        from app.doc.entities import Line, LwPolyline, Text, Polyline3d

        def pl(points, closed=False):
            x = Polyline3d(points=[[p[0], p[1], 0.0] for p in points], closed=closed)
            self.copy_common(e, x)
            return x

        if e.kind == "lwpolyline":
            x = Polyline3d(points=[[v["p"][0], v["p"][1], e.elevation] for v in e.vertices], closed=e.closed)
            self.copy_common(e, x)
            return [x]
        if e.kind in ("ellipse", "spline", "helix"):
            if e.kind == "ellipse":
                pts = e.sample(96)
            elif e.kind == "helix":
                pts = e.control_points
            else:
                from app.doc import curves2d

                res = curves2d.spline_points(e)
                pts = res[0] if res else (e.fit_points or e.control_points)
            return [pl(pts, False)] if len(pts) > 1 else None
        if e.kind == "mtext":
            lines = e.contents.replace("\\P", "\n").split("\n")
            out = []
            for i, ln in enumerate(lines):
                t = Text(position=[e.position[0], e.position[1] - i * e.height * 1.5, 0.0], height=e.height, text=ln, rotation=e.rotation, style=e.style)
                self.copy_common(e, t)
                out.append(t)
            return out
        if e.kind in ("ray", "xline"):
            return None
        return None

    def copy_common(self, src, dst) -> None:
        for k in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "thickness", "normal", "owner"):
            setattr(dst, k, copy.deepcopy(getattr(src, k)))
        dst.handle = src.handle

    def new(self, lay, dxftype: str, attribs: dict, e):
        attribs = {**self.props(e), **attribs}
        return lay.new_entity(dxftype, attribs)

    def w_line(self, e, lay):
        return self.new(lay, "LINE", {"start": _p3(e.start), "end": _p3(e.end)}, e)

    def w_point(self, e, lay):
        return self.new(lay, "POINT", {"location": _p3(e.position), "angle": math.degrees(e.angle)}, e)

    def w_circle(self, e, lay):
        return self.new(lay, "CIRCLE", {"center": _p3(e.center), "radius": float(e.radius)}, e)

    def w_arc(self, e, lay):
        return self.new(lay, "ARC", {"center": _p3(e.center), "radius": float(e.radius), "start_angle": math.degrees(e.start_angle), "end_angle": math.degrees(e.end_angle)}, e)

    def w_ellipse(self, e, lay):
        return self.new(lay, "ELLIPSE", {"center": _p3(e.center), "major_axis": _p3(e.major), "ratio": float(e.ratio), "start_param": float(e.start_param), "end_param": float(e.end_param)}, e)

    def w_ray(self, e, lay):
        return self.new(lay, "RAY", {"start": _p3(e.base), "unit_vector": _p3(e.direction)}, e)

    def w_xline(self, e, lay):
        return self.new(lay, "XLINE", {"start": _p3(e.base), "unit_vector": _p3(e.direction)}, e)

    def w_solid(self, e, lay):
        c = (list(e.corners) + [e.corners[-1]] * 4)[:4]
        a = {"vtx0": _p3(c[0]), "vtx1": _p3(c[1]), "vtx2": _p3(c[2]), "vtx3": _p3(c[3])}
        return self.new(lay, "SOLID", a, e)

    def w_lwpolyline(self, e, lay):
        flags = (1 if e.closed else 0) | (128 if e.linetype_gen else 0)
        a = {"flags": flags, "elevation": float(e.elevation)}
        if e.const_width:
            a["const_width"] = float(e.const_width)
        ent = self.new(lay, "LWPOLYLINE", a, e)
        ent.set_points([(float(v["p"][0]), float(v["p"][1]), float(v.get("sw", 0.0)), float(v.get("ew", 0.0)), float(v.get("bulge", 0.0))) for v in e.vertices], format="xyseb")
        return ent

    def w_polyline3d(self, e, lay):
        ent = self.new(lay, "POLYLINE", {"flags": 8 | (1 if e.closed else 0)}, e)
        for p in e.points:
            ent.append_vertex(_p3(p), dxfattribs={"flags": 32, "layer": e.layer or "0"})
        return ent

    def w_spline(self, e, lay):
        flags = (1 if e.closed else 0) | (4 if e.weights else 0)
        a = {"degree": int(e.degree), "flags": flags}
        if e.fit_tolerance:
            a["fit_tolerance"] = float(e.fit_tolerance)
        if e.start_tangent is not None:
            a["start_tangent"] = _p3(e.start_tangent)
        if e.end_tangent is not None:
            a["end_tangent"] = _p3(e.end_tangent)
        ent = self.new(lay, "SPLINE", a, e)
        ent.control_points = [_p3(p) for p in e.control_points]
        ent.knots = [float(k) for k in e.knots]
        if e.weights:
            ent.weights = [float(w) for w in e.weights]
        ent.fit_points = [_p3(p) for p in e.fit_points]
        return ent

    def w_helix(self, e, lay):
        ent = self.new(lay, "SPLINE", {"degree": int(e.degree), "flags": 8}, e)
        ent.control_points = [_p3(p) for p in e.control_points]
        ent.knots = [float(k) for k in e.knots]
        return ent

    def w_text(self, e, lay):
        a = {"insert": _p3(e.position), "height": float(e.height), "text": C.esc_line(e.text), "rotation": math.degrees(e.rotation), "style": e.style or "Standard"}
        if abs(e.width_factor - 1.0) > 1e-12:
            a["width"] = float(e.width_factor)
        if e.oblique:
            a["oblique"] = math.degrees(e.oblique)
        if e.halign:
            a["halign"] = int(e.halign)
        if e.valign:
            a["valign"] = int(e.valign)
        if e.align_point is not None and (e.halign or e.valign):
            a["align_point"] = _p3(e.align_point)
        return self.new(lay, "TEXT", a, e)

    def w_mtext(self, e, lay):
        a = {"insert": _p3(e.position), "char_height": float(e.height), "attachment_point": int(e.attachment), "rotation": math.degrees(e.rotation), "style": e.style or "Standard"}
        if e.width:
            a["width"] = float(e.width)
        if abs(e.line_spacing - 1.0) > 1e-12:
            a["line_spacing_factor"] = float(e.line_spacing)
        a["line_spacing_style"] = int(e.line_spacing_style)
        ent = self.new(lay, "MTEXT", a, e)
        ent.text = C.esc_multi(e.contents).replace("\n", "\\P")
        return ent

    def w_attdef(self, e, lay):
        m = e.modes or {}
        flags = (1 if m.get("invisible") else 0) | (2 if m.get("constant") else 0) | (4 if m.get("verify") else 0) | (8 if m.get("preset") else 0)
        a = {"insert": _p3(e.position), "tag": e.tag.replace(" ", "_"), "prompt": C.esc_line(e.prompt), "text": C.esc_line(e.default), "height": float(e.height), "rotation": math.degrees(e.rotation), "style": e.style or "Standard", "flags": flags}
        if abs(e.width_factor - 1.0) > 1e-12:
            a["width"] = float(e.width_factor)
        if e.oblique:
            a["oblique"] = math.degrees(e.oblique)
        if e.halign:
            a["halign"] = int(e.halign)
        if e.valign:
            a["valign"] = int(e.valign)
        if e.align_point is not None and (e.halign or e.valign):
            a["align_point"] = _p3(e.align_point)
        ent = self.new(lay, "ATTDEF", a, e)
        if m.get("lock_position") and self.rank >= R2007:
            ent.dxf.lock_position = 1
        return ent

    def w_insert(self, e, lay):
        from app.doc import attribs as AT
        from app.doc import blockdefs
        from app.doc import blockxf

        sx = float(e.scale[0]) if e.scale else 1.0
        sy = float(e.scale[1]) if e.scale and len(e.scale) > 1 else sx
        sz = float(e.scale[2]) if e.scale and len(e.scale) > 2 else sx
        a = {"name": e.block, "insert": _p3(e.position), "xscale": sx, "yscale": sy, "zscale": sz, "rotation": math.degrees(e.rotation)}
        arr = e.array or {}
        rows = int(arr.get("rows", 1) or 1)
        cols = int(arr.get("cols", arr.get("columns", 1)) or 1)
        if rows > 1 or cols > 1:
            a["row_count"], a["column_count"] = rows, cols
            a["row_spacing"] = float(arr.get("row_spacing", 0.0) or 0.0)
            a["column_spacing"] = float(arr.get("col_spacing", arr.get("column_spacing", 0.0)) or 0.0)
        ent = self.new(lay, "INSERT", a, e)
        if e.attributes:
            rec = blockdefs.lookup(self.d, e.block)
            defs = {x.tag.casefold(): x for x in AT.definitions(self.d, e.block)} if rec else {}
            m = blockxf.insert_matrices(e, rec)[0] if rec else None
            for att in e.attributes:
                tag = str(att.get("tag", ""))
                adef = defs.get(tag.casefold())
                if adef is not None and m is not None:
                    t = AT.reference_text(adef, att.get("value", ""), m, att)
                    pos = _p3(t.position)
                    height, rot, style = t.height, t.rotation, t.style
                    attrs = {"tag": tag, "text": C.esc_line(att.get("value", "")), "insert": pos, "height": height, "rotation": math.degrees(rot), "style": style}
                    if t.halign:
                        attrs["halign"] = int(t.halign)
                    if t.valign:
                        attrs["valign"] = int(t.valign)
                    if t.align_point is not None and (t.halign or t.valign):
                        attrs["align_point"] = _p3(t.align_point)
                    if abs(t.width_factor - 1.0) > 1e-12:
                        attrs["width"] = t.width_factor
                    if adef.oblique:
                        attrs["oblique"] = math.degrees(adef.oblique)
                    fl = (1 if (att.get("vis") is False) else 0) | (4 if AT.mode_of(adef, "verify") else 0) | (8 if AT.mode_of(adef, "preset") else 0)
                    attrs["flags"] = fl
                    attrs["layer"] = att.get("layer") or adef.layer or e.layer or "0"
                    col = att.get("color")
                    if isinstance(col, int) and col != 256:
                        attrs["color"] = col
                    elif adef.color not in (256, None) and isinstance(adef.color, int):
                        attrs["color"] = adef.color
                    if att.get("linetype") and str(att["linetype"]).casefold() not in ("bylayer",):
                        attrs["linetype"] = att["linetype"]
                else:
                    attrs = {"tag": tag, "text": C.esc_line(att.get("value", "")), "insert": _p3(e.position), "height": 2.5, "layer": e.layer or "0"}
                att_ent = ent.add_attrib(tag, attrs["text"], insert=attrs["insert"], dxfattribs={k: v for k, v in attrs.items() if k not in ("tag", "text", "insert")})
                if att.get("lock_position") and self.rank >= R2007:
                    att_ent.dxf.lock_position = 1
        return ent

    def w_hatch(self, e, lay):
        from app.doc import patterns

        ent = self.new(lay, "HATCH", {"elevation": (0.0, 0.0, float(e.elevation)), "hatch_style": int(e.style)}, e)
        if e.gradient and self.rank >= R2004:
            g = e.gradient
            c1 = g.get("color1", 5)
            c2 = g.get("color2", 7)
            gname = str(g.get("name", "LINEAR")).upper()
            if gname == "INVLINEAR":
                gname = "LINEAR"
            ent.set_gradient(TB.aci_to_rgb(c1) if isinstance(c1, int) else _hex_rgb(c1), TB.aci_to_rgb(c2) if isinstance(c2, int) else _hex_rgb(c2), rotation=math.degrees(float(g.get("angle", 0.0))) if abs(float(g.get("angle", 0.0))) <= 6.4 else float(g.get("angle", 0.0)), centered=1.0 if g.get("centered", True) else 0.0, one_color=1 if g.get("one") else 0, tint=float(g.get("tint", 0.0)), name=gname)
        elif e.solid or patterns.is_solid(e.pattern):
            ent.set_solid_fill()
        else:
            fams = patterns.families_of(e)
            cs, sn = math.cos(e.pattern_angle), math.sin(e.pattern_angle)
            lines = []
            for f in fams:
                ang = math.degrees(float(f.get("angle", 0.0)) + e.pattern_angle) if True else 0.0
                ox, oy = f.get("origin", [0.0, 0.0])[:2]
                dx, dy = f.get("offset", [0.0, 0.0])[:2]
                s = float(e.pattern_scale or 1.0)
                base = ((cs * ox - sn * oy) * s + e.origin[0], (sn * ox + cs * oy) * s + e.origin[1])
                off = ((cs * dx - sn * dy) * s, (sn * dx + cs * dy) * s)
                lines.append((ang, base, off, [float(v) * s for v in f.get("dashes", [])]))
            ent.set_pattern_fill(e.pattern or "USER", color=7, angle=math.degrees(e.pattern_angle), scale=float(e.pattern_scale or 1.0), definition=lines)
        base_color = self.props(e).get("color")
        if base_color is None:
            ent.dxf.discard("color")
        else:
            ent.dxf.color = base_color
        if e.associative:
            ent.dxf.associative = 1
        for loop in e.loops:
            verts = loop.get("vertices", [])
            flags = (1 if loop.get("outer", True) else 0) | 2
            pts = [(float(v["p"][0]), float(v["p"][1]), float(v.get("bulge", 0.0))) for v in verts]
            if len(pts) < 2:
                continue
            path = ent.paths.add_polyline_path(pts, is_closed=True, flags=flags)
            if e.associative and loop.get("sources"):
                path.source_boundary_objects = ["%X" % h for h in loop["sources"] if h in self.d.ents]
        return ent

    def w_dimension(self, e, lay):
        rec = self.d.tables["blocks"].get(e.block) if e.block else None
        bname = e.block if rec is not None else ""
        if not bname:
            bname = self.make_dim_block(e)
        t = DIMTYPE.get(e.dim_type, 0)
        a = {"dimtype": t | 32 | (128 if e.text_moved else 0) | (64 if (e.dim_type == "ordinate" and e.marks.get("ordinate") == "x") else 0), "defpoint": _p3(e.def_point), "text_midpoint": _p3(e.text_point), "dimstyle": e.style or "Standard", "actual_measurement": float(e.measurement)}
        if bname:
            a["geometry"] = bname
        if e.text_override:
            a["text"] = e.text_override
        for k, name in (("p13", "defpoint2"), ("p14", "defpoint3"), ("p15", "defpoint4"), ("p16", "defpoint5")):
            v = getattr(e, k)
            if v is not None:
                a[name] = _p3(v)
        if e.dim_type in ("linear", "aligned"):
            a["angle"] = math.degrees(e.rotation) if e.dim_type == "linear" else 0.0
        ent = self.new(lay, "DIMENSION", a, e)
        if e.overrides:
            xd = TB.dstyle_xdata(e.overrides)
            if xd:
                try:
                    ent.set_xdata("ACAD", xd)
                except Exception:
                    pass
        return ent

    def make_dim_block(self, e) -> str:
        try:
            from app.dim import explode
            from app.doc.document import Document

            if self.shadow is None:
                self.shadow = Document(self.d, "export", "", "drawing", self.d.metric)
            parts = explode.parts(self.shadow, e)
        except Exception as err:
            self.r.warn("A dimension has no drawn geometry: %s" % err)
            return ""
        self.counter["D"] += 1
        name = "*D%d" % self.counter["D"]
        while self.d.tables["blocks"].has(name) or name in self.blocks:
            self.counter["D"] += 1
            name = "*D%d" % self.counter["D"]
        blk = self.doc.blocks.new(name)
        self.blocks[name] = blk
        for p in parts:
            p.handle = 0
            try:
                fn = getattr(self, "w_" + p.kind)
                fn(p, blk)
            except Exception:
                continue
        return name

    def w_leader(self, e, lay):
        ent = self.new(lay, "LEADER", {"dimstyle": e.style or "Standard", "has_arrowhead": 1 if e.arrowhead else 0, "path_type": 1 if e.spline else 0, "annotation_type": 3}, e)
        ent.set_vertices([_p3(p) for p in e.points])
        return ent

    def w_mleader(self, e, lay):
        if self.rank >= R2007:
            try:
                from ezdxf.render.mleader import ConnectionSide

                style = e.style if e.style in self.doc.mleader_styles else "Standard"
                ml = lay.add_multileader_mtext(style) if e.content_type != "block" else None
                if ml is not None:
                    ml.set_content(e.text or " ", style=e.text_style or "Standard", char_height=float(e.text_height or 2.5))
                    side = ConnectionSide.right if e.dogleg_dir >= 0 else ConnectionSide.left
                    for ld in e.leaders:
                        pts = [Vec2(p[0], p[1]) for p in ld["pts"]]
                        ml.add_leader_line(side, pts)
                    ml.build(insert=Vec2(e.content_pos[0], e.content_pos[1]))
                    ent = ml.multileader
                    ent.dxf.layer = e.layer or "0"
                    return ent
            except Exception as err:
                self.r.note("A multileader was written as plain leaders and text: %s" % err)
        from app.doc.entities import MText

        out = []
        for ld in e.leaders:
            ent = lay.new_entity("LEADER", {**self.props(e), "has_arrowhead": 1, "path_type": 0, "annotation_type": 3})
            ent.set_vertices([_p3(p) + () for p in ld["pts"]])
            out.append(ent)
        if e.content_type != "block" and e.text:
            mt = lay.new_entity("MTEXT", {**self.props(e), "insert": _p3(e.content_pos), "char_height": float(e.text_height or 2.5), "text": e.text})
            out.append(mt)
        elif e.block:
            out.append(lay.new_entity("INSERT", {**self.props(e), "name": e.block, "insert": _p3(e.content_pos)}))
        if not out:
            return None
        self.r.convert("multileader to leaders")
        return out

    def w_mline(self, e, lay):
        if e.style not in self.doc.mline_styles:
            self.write_mline_style(e)
        ent = self.new(lay, "MLINE", {"style_name": e.style, "scale_factor": float(e.scale), "justification": int(e.justification), "flags": (2 if e.closed else 0) | (4 if e.no_start_cap else 0) | (8 if e.no_end_cap else 0)}, e)
        try:
            ent.extend([Vec3(v["p"][0], v["p"][1], 0) for v in e.vertices])
        except Exception as err:
            self.r.warn("A multiline lost its vertices: %s" % err)
        return ent

    def write_mline_style(self, e) -> None:
        st = self.doc.mline_styles.new(e.style)
        st.elements.elements.clear()
        for el in (e.style_def or {}).get("elements", []):
            col = el.get("color", 256)
            st.elements.append(float(el.get("offset", 0.0)), color=int(col) if isinstance(col, int) else 256, linetype=str(el.get("linetype", "BYLAYER")))

    def w_wipeout(self, e, lay):
        ent = lay.add_wipeout([(float(p[0]), float(p[1])) for p in e.points], dxfattribs=self.props(e))
        return ent

    def w_region(self, e, lay):
        first = None
        out = []
        for i, loop in enumerate(e.loops):
            verts = loop.get("vertices", [])
            ent = lay.new_entity("LWPOLYLINE", {**self.props(e), "flags": 1})
            ent.set_points([(float(v["p"][0]), float(v["p"][1]), 0.0, 0.0, float(v.get("bulge", 0.0))) for v in verts], format="xyseb")
            out.append(ent)
        return out or None

    def w_viewport(self, e, lay):
        if not hasattr(lay, "add_viewport"):
            return None
        vid = self.next_vp_id(lay)
        a = {"center": _p3(e.center), "width": float(e.width), "height": float(e.height), "view_center_point": _p2(e.view_center), "view_height": float(e.height) * float(e.scale), "id": vid, "status": vid if e.on else 0, "layer": e.layer or "0"}
        flags = 32768 | (16384 if e.locked else 0) | (131072 if not e.on else 0)
        if e.clip:
            flags |= 65536
        a["flags"] = flags
        ent = lay.new_entity("VIEWPORT", a)
        try:
            names = [n for n in e.frozen]
            if names:
                ent.frozen_layers = names
        except Exception as err:
            self.r.warn("Viewport %d: frozen layers were not written: %s" % (vid, err))
        if e.clip:
            try:
                poly = lay.new_entity("LWPOLYLINE", {"layer": e.layer or "0", "flags": 1})
                poly.set_points([(float(v["p"][0]), float(v["p"][1]), 0.0, 0.0, float(v.get("bulge", 0.0))) for v in e.clip], format="xyseb")
                self.appid(C.APPID)
                poly.set_xdata(C.APPID, [(1000, "FCVPCLIP")])
                ent.dxf.clipping_boundary_handle = poly.dxf.handle
            except Exception as err:
                self.r.warn("Viewport %d: the clip boundary was not written: %s" % (vid, err))
        return ent

    def next_vp_id(self, lay) -> int:
        key = lay.layout_key if hasattr(lay, "layout_key") else id(lay)
        n = self.clip_made.get(key, 1) + 1
        self.clip_made[key] = n
        return n

    def sheet_viewport(self, lay, name: str) -> None:
        if not hasattr(lay, "add_viewport") or self.rank < R2000:
            return
        rec = self.d.tables["layouts"].get(name) or {}
        ps = rec.get("page_setup") or {}
        w, h = float(ps.get("width", 297.0)), float(ps.get("height", 210.0))
        try:
            vp = lay.new_entity("VIEWPORT", {"center": (w / 2.0, h / 2.0, 0.0), "width": w, "height": h, "id": 1, "status": 1, "flags": 32768 | 32, "view_center_point": (w / 2.0, h / 2.0), "view_height": h})
            self.appid(C.APPID)
            vp.set_xdata(C.APPID, [(1000, "FCSHEETVP")])
        except Exception as err:
            self.r.warn("The sheet viewport of layout %s was not written: %s" % (name, err))

    def w_table(self, e, lay):
        self.counter["T"] += 1
        name = "*T%d" % self.counter["T"]
        blk = self.doc.blocks.new(name)
        self.blocks[name] = blk
        from app.doc.entities import Line, Text

        x, y = float(e.position[0]), float(e.position[1])
        widths, heights = [float(v) for v in e.col_widths], [float(v) for v in e.row_heights]
        tw, th = sum(widths), sum(heights)
        props = {"layer": e.layer or "0"}
        yy = y
        edges_y = [y]
        for h in heights:
            yy -= h
            edges_y.append(yy)
        xx = x
        edges_x = [x]
        for w in widths:
            xx += w
            edges_x.append(xx)
        for ey in edges_y:
            blk.new_entity("LINE", {**props, "start": (x, ey, 0), "end": (x + tw, ey, 0)})
        for ex in edges_x:
            blk.new_entity("LINE", {**props, "start": (ex, y, 0), "end": (ex, y - th, 0)})
        for ri, row in enumerate(e.cells):
            for ci, cell in enumerate(row):
                txt = str(cell.get("text", "") or "")
                if not txt:
                    continue
                hh = float(cell.get("height") or e.text_height or 2.5)
                blk.new_entity("TEXT", {**props, "insert": (edges_x[ci] + 1.0, edges_y[ri] - heights[ri] / 2.0 - hh / 2.0, 0), "height": hh, "text": C.esc_line(txt)})
        ent = self.new(lay, "INSERT", {"name": name, "insert": (0.0, 0.0, 0.0)}, e)
        return ent

    def w_assoc_array(self, e, lay):
        self.counter["A"] += 1
        name = "*A%d" % self.counter["A"]
        blk = self.doc.blocks.new(name)
        self.blocks[name] = blk
        try:
            items = e.explode_entities(MAX_ARRAY_BLOCK)
        except Exception as err:
            self.r.warn("An array could not be expanded: %s" % err)
            items = []
        for it in items:
            it.handle = 0
            fn = getattr(self, "w_" + it.kind, None)
            if fn is None:
                continue
            try:
                fn(it, blk)
            except Exception:
                continue
        return self.new(lay, "INSERT", {"name": name, "insert": (0.0, 0.0, 0.0)}, e)

    def w_unknown(self, e, lay):
        tags = e.raw.get("dxf_tags")
        if e.type_name == "IMAGE":
            self.r.drop("IMAGE")
            self.r.note("Raster image references are not carried into DXF output.")
            return
        if not tags:
            self.r.drop(e.type_name or "unknown")
            return
        try:
            from ezdxf.entities import factory
            from ezdxf.lldxf.extendedtags import ExtendedTags
            from ezdxf.lldxf.tagger import ascii_tags_loader, tag_compiler
            import io

            from ezdxf.lldxf.tags import Tags

            groups = []
            for c, v in tags:
                if int(c) == 0:
                    groups.append([])
                groups[-1].append((c, v))

            def load(g):
                text = "".join("%d\n%s\n" % (int(c), str(v).replace("\n", " ")) for c, v in g)
                return factory.load(ExtendedTags(Tags(tag_compiler(ascii_tags_loader(io.StringIO(text))))), self.doc)

            ent = load(groups[0])
            for g in groups[1:]:
                kind = str(g[0][1])
                sub = load(g)
                if kind == "VERTEX" and hasattr(ent, "vertices"):
                    sub.dxf.discard("handle")
                    sub.dxf.discard("owner")
                    ent.vertices.append(sub)
                elif kind == "SEQEND" and hasattr(ent, "new_seqend"):
                    ent.new_seqend()
            ent.dxf.discard("handle")
            ent.dxf.discard("owner")
            self.doc.entitydb.add(ent)
            lay.add_entity(ent)
            self.fix_handle(ent, e.handle)
            self.r.count("unknown " + (e.type_name or ""))
        except Exception as err:
            self.r.drop(e.type_name or "unknown")
            self.r.warn("An unknown %s object was not kept: %s" % (e.type_name, err))

    def write_private(self) -> None:
        doc = self.doc
        try:
            root = doc.rootdict
            fc = doc.objects.add_dictionary(owner=root.dxf.handle)
            root.add("FORMCAD_DATA", fc)
        except Exception:
            return
        names = list(self.d.tables.keys())
        for tname in names:
            if tname in ("linetypes", "textstyles", "layers", "dimstyles", "blocks", "views", "ucs"):
                continue
            items = self.d.tables[tname].to_list()
            if not items:
                continue
            self.xrec(fc, tname, items)
        rest = {"relations": self.d.relations, "foreign": {k: v for k, v in self.d.foreign.items() if k != "dxf"}, "tolerances": self.d.tolerances, "metric": self.d.metric}
        self.xrec(fc, "_drawing", rest)
        hdr = {k: v for k, v in self.d.header.items()}
        self.xrec(fc, "_header", hdr)
        self.xrec(fc, "_handles", {"next": self.d.next_handle})
        self.xrec(fc, "_layers_extra", [{k: v for k, v in r.items()} for r in self.d.tables["layers"].values()])

    def xrec(self, fc, name: str, payload) -> None:
        try:
            tags = C.pack_snapshot(payload)
            rec = self.doc.objects.add_xrecord(owner=fc.dxf.handle)
            rec.reset([(1, t[1]) for t in tags])
            fc.add(name, rec)
        except Exception as err:
            self.r.warn("Private data %s was not written: %s" % (name, err))

    def finish_foreign(self) -> None:
        pass

    def run(self):
        self.start()
        self.write_header()
        self.write_tables()
        self.write_blocks()
        self.write_layouts()
        self.write_views()
        self.write_entities()
        self.write_private()
        try:
            self.doc.header["$HANDSEED"] = "%X" % self.doc.entitydb.handles._handle
        except Exception:
            pass
        return self.doc


def _hex_rgb(v):
    s = str(v).lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def build(drawing, version: str = "", report: Report | None = None, precision: int = 16):
    w = Writer(drawing, version, report, precision)
    doc = w.run()
    return doc, w


def write_file(drawing, path: str, version: str = "", report: Report | None = None, precision: int = 16, binary: bool = False) -> Report:
    report = report or Report()
    doc, w = build(drawing, version, report, precision)
    dest = os.path.realpath(os.path.expanduser(path))
    folder = os.path.dirname(dest) or "."
    os.makedirs(folder, exist_ok=True)
    import tempfile

    fd, tmp = tempfile.mkstemp(prefix=".fcad-", suffix=".tmp", dir=folder)
    os.close(fd)
    try:
        if binary:
            from ezdxf.document import Drawing as _D

            doc.saveas(tmp, fmt="bin")
        else:
            doc.saveas(tmp)
        os.replace(tmp, dest)
    except Exception as err:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise InterchangeError("Could not write the DXF file: %s" % err, "io")
    report.note("DXF %s written." % w.version)
    return report
