import copy
import math
import os

import ezdxf
from ezdxf import recover as ezrecover
from ezdxf.lldxf import const as ZC

from app.interchange import dxfcommon as C
from app.interchange import dxfw_tables as TB
from app.interchange.errors import InterchangeError, Report

MAX_FILE = 512 * 1024 * 1024
HANDLED = {"LINE", "POINT", "CIRCLE", "ARC", "ELLIPSE", "RAY", "XLINE", "SOLID", "TRACE", "LWPOLYLINE", "POLYLINE", "SPLINE", "TEXT", "MTEXT", "ATTDEF", "INSERT", "HATCH", "DIMENSION", "LEADER", "MULTILEADER", "MLINE", "WIPEOUT", "VIEWPORT", "ACAD_TABLE"}


def _v3(p):
    return [float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 else 0.0]


def _h(handle) -> int:
    try:
        return int(str(handle), 16)
    except (TypeError, ValueError):
        return 0


class Reader:
    def __init__(self, doc, report: Report, auditor=None):
        self.doc = doc
        self.r = report
        self.auditor = auditor
        self.d = None
        self.shift_jobs = []
        self.space_of_record = {}
        self.parts = {}
        self.restored = {}
        self.drop_blocks = set()
        self.skip_handles = set()
        self.block_names = {}
        self.next_aux = 0

    def run(self):
        from app.doc.model import Drawing

        doc = self.doc
        hd = doc.header
        metric = int(hd.get("$MEASUREMENT", 0) or 0) == 1
        d = Drawing(metric)
        self.d = d
        for name in ("layers", "linetypes", "dimstyles", "textstyles", "mlinestyles", "mleaderstyles", "layouts", "blocks", "views", "ucs", "vports", "tablestyles"):
            d.tables[name].load_list([])
        d.spaces = {"model": []}
        d.header = dict(d.header)
        fc = self.private()
        self.read_header(fc)
        self.read_tables(fc)
        self.read_blocks(fc)
        self.read_layouts(fc)
        self.read_views()
        self.read_entities()
        self.finish(fc)
        return d

    def private(self) -> dict:
        out = {}
        try:
            fc = self.doc.rootdict.get("FORMCAD_DATA")
        except Exception:
            fc = None
        if fc is None:
            return out
        try:
            for key in fc.keys():
                rec = fc.get(key)
                tags = [(t.code, t.value) for t in rec.tags] if rec is not None else []
                payload, _s = C.unpack_snapshot(tags)
                if payload is not None:
                    out[key] = payload
        except Exception as err:
            self.r.warn("Private data could not be read: %s" % err)
        return out

    def read_header(self, fc: dict) -> None:
        d = self.d
        hd = self.doc.header
        if isinstance(fc.get("_header"), dict):
            d.header.update(fc["_header"])
        for name, dxf, kind in C.HEADER_MAP:
            if dxf not in hd:
                continue
            try:
                v = hd[dxf]
                if kind == "rad":
                    v = math.degrees(float(v))
                elif kind == "pt2":
                    v = [float(v[0]), float(v[1])]
                elif kind == "pt3":
                    v = [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0] if name != "INSBASE" else [float(v[0]), float(v[1])]
                elif kind == "int":
                    v = int(v)
                elif kind in ("real", "deg"):
                    v = float(v)
                elif kind == "scale":
                    continue
                else:
                    v = str(v)
                if name == "CELTYPE":
                    v = {"BYLAYER": "ByLayer", "BYBLOCK": "ByBlock"}.get(str(v).upper(), v)
                d.header[name] = v
            except Exception:
                continue
        raw = {}
        for name in hd.varnames():
            if name in C.MAPPED_DXF or name in C.HEADER_SKIP:
                continue
            try:
                v = hd[name]
                if isinstance(v, (int, float, str)):
                    raw[name] = v
                elif isinstance(v, (tuple, list)) or hasattr(v, "__iter__"):
                    raw[name] = [float(x) for x in v]
            except Exception:
                continue
        acad = str(hd.get("$ACADVER", ""))
        info = {"acadver": acad, "header": raw, "source": "dxf"}
        if self.doc.dxfversion < "AC1021" or "$DWGCODEPAGE" in hd:
            info["codepage"] = str(hd.get("$DWGCODEPAGE", "ANSI_1252"))
        d.foreign["dxf"] = info
        d.header["ACADVER"] = acad or d.header.get("ACADVER")
        if self.doc.dxfversion:
            self.r.note("Read DXF %s." % C.CODE_TO_NAME.get(self.doc.dxfversion, self.doc.dxfversion))

    def snap_rec(self, entry):
        try:
            tags = entry.get_xdata(C.APPID)
        except Exception:
            return None
        payload, _s = C.unpack_snapshot(tags)
        if payload and isinstance(payload.get("rec"), dict):
            return copy.deepcopy(payload["rec"])
        return None

    def read_tables(self, fc: dict) -> None:
        from app.doc import tables as T

        d = self.d
        doc = self.doc
        for lt in doc.linetypes:
            n = lt.dxf.name
            rec = self.snap_rec(lt)
            if n.upper() in ("BYLAYER", "BYBLOCK", "CONTINUOUS"):
                d.tables["linetypes"].put({"name": {"BYLAYER": "ByLayer", "BYBLOCK": "ByBlock", "CONTINUOUS": "Continuous"}[n.upper()], "description": lt.dxf.get("description", "") or "", "elements": [], "pattern_length": 0.0})
                continue
            if rec is None:
                els = []
                try:
                    pat = list(lt.pattern_tags.tags) if False else []
                    p = lt.pattern_tags
                    vals = [t.value for t in p.tags if t.code == 49]
                    els = [{"length": float(v)} for v in vals]
                except Exception:
                    els = []
                rec = {"name": n, "description": lt.dxf.get("description", "") or "", "elements": els, "pattern_length": float(sum(abs(e["length"]) for e in els))}
            d.tables["linetypes"].put(rec)
        for st in doc.styles:
            n = st.dxf.name
            if not n or n.startswith("*") and False:
                continue
            rec = self.snap_rec(st) or T.new_textstyle(n)
            font = str(st.dxf.get("font", "") or "")
            fam = ""
            try:
                fam = st.get_extended_font_data()[0]
            except Exception:
                fam = ""
            rec["name"] = n
            keep = str(rec.get("font", "")).lower()
            if fam:
                rec["font"] = fam
            elif font and font.lower() not in (keep, keep + ".shx", keep + ".ttf"):
                rec["font"] = font
            rec["big_font"] = str(st.dxf.get("bigfont", "") or "")
            rec["height"] = float(st.dxf.get("height", 0.0) or 0.0)
            rec["width_factor"] = float(st.dxf.get("width", 1.0) or 1.0)
            rec["oblique"] = float(st.dxf.get("oblique", 0.0) or 0.0)
            gf = int(st.dxf.get("generation_flags", 0) or 0)
            rec["backwards"] = bool(gf & 2)
            rec["upside_down"] = bool(gf & 4)
            rec["vertical"] = bool(int(st.dxf.get("flags", 0) or 0) & 4)
            d.tables["textstyles"].put(rec)
        for ly in doc.layers:
            n = ly.dxf.name
            rec = self.snap_rec(ly) or T.new_layer(n)
            rec["name"] = n
            col = int(ly.dxf.get("color", 7) or 7)
            rec["on"] = col >= 0
            aci = abs(col) or 7
            if ly.dxf.hasattr("true_color") and int(ly.dxf.true_color) > 0 and not (isinstance(rec.get("color"), int) and TB.nearest_aci("#%06X" % int(ly.dxf.true_color)) == rec.get("color") and False):
                rec["color"] = "#%06X" % (int(ly.dxf.true_color) & 0xFFFFFF)
            else:
                rec["color"] = aci
            flags = int(ly.dxf.get("flags", 0) or 0)
            rec["frozen"] = bool(flags & 1)
            rec["locked"] = bool(flags & 4)
            rec["new_vp_freeze"] = bool(flags & 2)
            lt = str(ly.dxf.get("linetype", "Continuous") or "Continuous")
            rec["linetype"] = "Continuous" if lt.upper() == "CONTINUOUS" else lt
            rec["lineweight"] = int(ly.dxf.get("lineweight", -3)) if ly.dxf.hasattr("lineweight") else rec.get("lineweight", -3)
            rec["plot"] = bool(ly.dxf.get("plot", 1))
            try:
                t = ly.transparency
                rec["transparency"] = int(round(float(t) * 100)) if t else 0
            except Exception:
                pass
            try:
                if ly.description:
                    rec["description"] = ly.description
            except Exception:
                pass
            d.tables["layers"].put(rec)
        for ds in doc.dimstyles:
            n = ds.dxf.name
            rec = self.snap_rec(ds)
            if rec is None:
                rec = T.new_dimstyle(n)
            vars_ = rec.setdefault("vars", {})
            for name, (code, kind) in TB.DIM_CODES.items():
                key = name.lower()
                try:
                    if ds.dxf.hasattr(key):
                        v = ds.dxf.get(key)
                        if kind == "c":
                            v = chr(int(v)) if v else "."
                        elif kind == "i":
                            v = int(v)
                        elif kind == "r":
                            v = float(v)
                        vars_[name] = v
                except Exception:
                    continue
            for name, key in (("DIMTXSTY", "dimtxsty"), ("DIMBLK", "dimblk"), ("DIMBLK1", "dimblk1"), ("DIMBLK2", "dimblk2"), ("DIMLDRBLK", "dimldrblk")):
                try:
                    v = ds.dxf.get(key)
                    if v is not None:
                        vars_[name] = str(v)
                except Exception:
                    pass
            rec["name"] = n
            d.tables["dimstyles"].put(rec)
        for name, st in list(self.doc.mline_styles.items()) if hasattr(self.doc.mline_styles, "items") else []:
            pass
        snap = fc.get("mlinestyles")
        try:
            for st in self.doc.mline_styles:
                els = []
                for el in st.elements.elements:
                    els.append({"offset": float(el.offset), "color": int(el.color), "linetype": str(el.linetype)})
                d.tables["mlinestyles"].put({"name": st.dxf.name, "description": st.dxf.get("description", "") or "", "elements": els, "start_cap": {"line": False, "outer_arc": False, "inner_arcs": False, "angle": 90.0}, "end_cap": {"line": False, "outer_arc": False, "inner_arcs": False, "angle": 90.0}, "joints": False, "fill": None})
        except Exception:
            pass
        try:
            for st in self.doc.mleader_styles:
                d.tables["mleaderstyles"].put({"name": st.dxf.name, "arrow_size": float(st.dxf.get("arrow_head_size", 2.5)), "text_height": float(st.dxf.get("char_height", 2.5)), "landing_gap": float(st.dxf.get("landing_gap_size", 0.0)), "dogleg": float(st.dxf.get("landing_distance", 0.0)), "text_style": "Standard", "annotative": False})
        except Exception:
            pass
        for tname, payload in fc.items():
            if tname.startswith("_") or not isinstance(payload, list):
                continue
            if tname in d.tables:
                d.tables[tname].load_list(payload)

    def read_blocks(self, fc: dict) -> None:
        d = self.d
        for blk in self.doc.blocks:
            if blk.is_any_layout:
                continue
            name = blk.name
            br = blk.block_record
            rec = self.snap_rec(br) if br is not None else None
            if rec is None:
                rec = {"name": name, "base": [0.0, 0.0, 0.0], "description": "", "explodable": True, "insunits": 0, "annotative": False, "anonymous": name.startswith("*"), "xref": None}
            rec["name"] = name
            try:
                rec["base"] = _v3(blk.block.dxf.get("base_point", (0, 0, 0)))
                rec["anonymous"] = name.startswith("*")
                if br is not None:
                    rec["insunits"] = int(br.dxf.get("units", rec.get("insunits", 0)) or 0)
                    rec["explodable"] = bool(br.dxf.get("explode", 1))
            except Exception:
                pass
            bf = int(blk.block.dxf.get("flags", 0) or 0)
            if bf & 4:
                path = str(blk.block.dxf.get("xref_path", "") or "")
                overlay = bool(bf & 8)
                try:
                    from app.doc import xref as XR

                    info = XR.new_info(path, overlay)
                except Exception:
                    info = {"path": path, "overlay": overlay, "status": "notloaded", "reason": "", "resolved": "", "objects": 0, "unloaded": False, "typed": False}
                rec["xref"] = info
            d.tables["blocks"].put(rec)
            d.spaces.setdefault("block:" + name, [])

    def read_layouts(self, fc: dict) -> None:
        d = self.d
        base = {r["name"].casefold(): r for r in (fc.get("layouts") or [])} if isinstance(fc.get("layouts"), list) else {}
        for lay in self.doc.layouts:
            if lay.is_modelspace:
                self.space_of_record[lay.layout_key] = "model"
                continue
            name = lay.name
            rec = copy.deepcopy(base.get(name.casefold())) or {}
            from app.doc import tables as T

            dflt = T.new_layout(name, int(lay.dxf.get("taborder", 1) or 1), d.metric)
            rec = {**dflt, **rec}
            rec["name"] = name
            rec["tab_order"] = int(lay.dxf.get("taborder", rec.get("tab_order", 1)) or 1)
            rec["page_setup"] = self.read_page_setup(lay, dict(rec.get("page_setup") or dflt["page_setup"]))
            d.tables["layouts"].put(rec)
            d.spaces.setdefault("layout:" + name, [])
            self.space_of_record[lay.layout_key] = "layout:" + name

    def read_page_setup(self, lay, ps: dict) -> dict:
        x = lay.dxf
        try:
            w, h = float(x.get("paper_width", 0) or 0), float(x.get("paper_height", 0) or 0)
            rot = int(x.get("plot_rotation", 0) or 0)
            if w > 0 and h > 0:
                sw, sh = (h, w) if rot % 2 == 1 else (w, h)
                ps["width"], ps["height"] = max(sw, sh), min(sw, sh) if sw >= sh else (sw if True else sh)
                ps["landscape"] = sw >= sh
                if not ps["landscape"]:
                    ps["width"], ps["height"] = sw, sh
            ps["margins"] = [float(x.get("left_margin", 0) or 0), float(x.get("bottom_margin", 0) or 0), float(x.get("right_margin", 0) or 0), float(x.get("top_margin", 0) or 0)]
            ps["paper_mm"] = int(x.get("plot_paper_units", 1) or 0) != 0
            fl = int(x.get("plot_layout_flags", 0) or 0)
            ps["display_styles"] = bool(fl & 2)
            ps["center"] = bool(fl & 4)
            ps["fit"] = not bool(fl & 16)
            ps["plot_lineweights"] = bool(fl & 128)
            area = {0: "display", 1: "extents", 2: "limits", 3: "view", 4: "window", 5: "layout"}.get(int(x.get("plot_type", 5) or 0), "layout")
            ps["plot_area"] = area
            ps["window"] = [float(x.get("plot_window_x1", 0) or 0), float(x.get("plot_window_y1", 0) or 0), float(x.get("plot_window_x2", 0) or 0), float(x.get("plot_window_y2", 0) or 0)]
            num, den = float(x.get("scale_numerator", 1) or 1), float(x.get("scale_denominator", 1) or 1)
            ps["scale"] = num / den if den else 1.0
            ps["offset"] = [float(x.get("plot_origin_x_offset", 0) or 0), float(x.get("plot_origin_y_offset", 0) or 0)]
            ps["style_table"] = str(x.get("current_style_sheet", "") or "")
            cfg = str(x.get("plot_configuration_file", "") or "")
            ps["device"] = cfg or "None"
            ps["paper"] = str(x.get("paper_size", "") or "")
        except Exception as err:
            self.r.warn("Page setup of layout %s was read partly: %s" % (lay.name, err))
        return ps

    def read_views(self) -> None:
        d = self.d
        for v in self.doc.views:
            try:
                rec = self.snap_rec(v) or {"name": v.dxf.name, "space": "model", "center": [0.0, 0.0], "height": 1.0, "width": 1.0, "twist": 0.0, "layer_state": ""}
                rec["name"] = v.dxf.name
                rec["center"] = [float(v.dxf.center[0]), float(v.dxf.center[1])]
                rec["height"] = float(v.dxf.get("height", 1.0))
                rec["width"] = float(v.dxf.get("width", 1.0))
                rec["twist"] = float(v.dxf.get("view_twist", 0.0) or 0.0)
                if not (int(v.dxf.get("flags", 0) or 0) & 1):
                    rec["space"] = "model"
                d.tables["views"].put(rec)
            except Exception:
                continue
        for u in self.doc.ucs:
            try:
                rec = self.snap_rec(u) or {"name": u.dxf.name}
                rec["name"] = u.dxf.name
                rec["origin"] = _v3(u.dxf.get("origin", (0, 0, 0)))
                rec["x_axis"] = _v3(u.dxf.get("xaxis", (1, 0, 0)))
                rec["y_axis"] = _v3(u.dxf.get("yaxis", (0, 1, 0)))
                d.tables["ucs"].put(rec)
            except Exception:
                continue
        try:
            groups = {}
            for ent in self.doc.viewports:
                n = ent.dxf.name
                groups.setdefault(n, []).append(ent)
            for n, items in groups.items():
                rec = self.snap_rec(items[0]) if items else None
                tiles = []
                for ent in items:
                    tiles.append({"lower_left": [float(ent.dxf.lower_left[0]), float(ent.dxf.lower_left[1])], "upper_right": [float(ent.dxf.upper_right[0]), float(ent.dxf.upper_right[1])], "center": [float(ent.dxf.center[0]), float(ent.dxf.center[1])], "height": float(ent.dxf.get("height", 1.0)), "aspect": float(ent.dxf.get("aspect_ratio", 1.0) or 1.0)})
                out = rec or {"name": n}
                out["name"] = n
                out["tiles"] = tiles
                d.tables["vports"].put(out)
        except Exception:
            pass

    def common(self, e, dst) -> None:
        x = e.dxf
        dst.layer = str(x.get("layer", "0") or "0")
        if x.hasattr("true_color") and int(x.true_color) >= 0:
            dst.color = "#%06X" % (int(x.true_color) & 0xFFFFFF)
        else:
            dst.color = int(x.get("color", 256))
        lt = str(x.get("linetype", "BYLAYER") or "BYLAYER")
        dst.linetype = {"BYLAYER": "ByLayer", "BYBLOCK": "ByBlock"}.get(lt.upper(), lt)
        dst.lineweight = int(x.get("lineweight", -1)) if x.hasattr("lineweight") else -1
        dst.ltscale = float(x.get("ltscale", 1.0) or 1.0) if x.is_supported("ltscale") else 1.0
        t = x.get("transparency") if x.hasattr("transparency") else None
        if t is None:
            dst.transparency = "ByLayer"
        elif int(t) & 0x01000000:
            dst.transparency = "ByBlock"
        elif int(t) & 0x02000000:
            dst.transparency = int(round(100 - (int(t) & 0xFF) * 100.0 / 255.0))
        else:
            dst.transparency = "ByLayer"
        dst.visible = not bool(x.get("invisible", 0))
        dst.thickness = float(x.get("thickness", 0.0) or 0.0) if x.is_supported("thickness") else 0.0
        if x.is_supported("extrusion") and x.hasattr("extrusion"):
            ex = x.extrusion
            dst.normal = [float(ex[0]), float(ex[1]), float(ex[2])]
        dst.handle = _h(x.get("handle"))
        try:
            xd = {}
            for app in e.xdata.data.keys() if e.xdata is not None else []:
                if app in (C.APPID, "ACAD"):
                    continue
                xd[app] = [[t.code, t.value if not hasattr(t.value, "x") else [t.value.x, t.value.y, t.value.z]] for t in e.get_xdata(app)]
            dst.xdata = xd
        except Exception:
            pass

    def read_entities(self) -> None:
        d = self.d
        for lay in self.doc.layouts:
            space = self.space_of_record.get(lay.layout_key, "model")
            self.read_space(lay, space)
        for blk in self.doc.blocks:
            if blk.is_any_layout:
                continue
            self.read_space(blk, "block:" + blk.name)

    def read_space(self, lay, space: str) -> None:
        d = self.d
        for e in lay:
            try:
                self.skip_handles.discard(0)
                if self.is_marker(e):
                    continue
                ents = self.convert(e, space)
            except Exception as err:
                self.r.drop(e.dxftype())
                self.r.warn("A %s was not read: %s" % (e.dxftype(), err))
                continue
            for ent in ents:
                if ent is None:
                    continue
                ent.owner = space
                if not ent.handle or ent.handle in d.ents:
                    ent.handle = 0
                    self.next_aux += 1
                    ent.handle = -self.next_aux
                d.ents[ent.handle] = ent
                d.spaces.setdefault(space, []).append(ent.handle)
                self.r.count(ent.kind)

    def is_marker(self, e) -> bool:
        try:
            if not e.has_xdata(C.APPID):
                return False
            tags = e.get_xdata(C.APPID)
        except Exception:
            return False
        first = str(tags[0].value) if len(tags) else ""
        if first in ("FCSHEETVP", "FCVPCLIP"):
            return True
        if first == "FCPART":
            self.parts.setdefault(int(str(tags[1].value), 16), []).append(_h(e.dxf.handle))
        return False

    def snapshot(self, e):
        try:
            if not e.has_xdata(C.APPID):
                return None, ""
            tags = e.get_xdata(C.APPID)
        except Exception:
            return None, ""
        if len(tags) and str(tags[0].value).startswith(C.SNAP_MAGIC):
            return C.unpack_snapshot(tags)
        return None, ""

    def convert(self, e, space: str) -> list:
        t = e.dxftype()
        fn = getattr(self, "r_" + t.lower(), None)
        if fn is None:
            return [self.unknown(e)]
        out = fn(e)
        if out is None:
            return []
        ents = out if isinstance(out, list) else [out]
        if not ents:
            return []
        first = ents[0]
        if first.kind != "unknown":
            self.common(e, first)
            first = self.apply_snapshot(e, first)
            ents[0] = first
        return ents

    def apply_snapshot(self, e, ent):
        payload, sig = self.snapshot(e)
        if not payload:
            return ent
        from app.doc.entities import entity_from_dict

        kind = payload.get("kind")
        if "ent" in payload and kind in C.FULL_KINDS:
            try:
                snap = entity_from_dict(copy.deepcopy(payload["ent"]))
            except Exception:
                return ent
            if sig and C.sig_of(C.sig_values(ent)) != sig and ent.kind == kind:
                self.r.note("A %s was edited by another program; its extra FormCAD data was ignored." % kind)
                return ent
            if ent.kind not in (kind, "insert", "lwpolyline", "spline", "leader", "mleader", "mline", "dimension", "hatch"):
                return ent
            for k in ("layer", "color", "linetype", "lineweight", "ltscale", "transparency", "visible", "thickness", "normal", "handle"):
                setattr(snap, k, copy.deepcopy(getattr(ent, k)))
            snap.xdata = ent.xdata
            self.restored[snap.handle] = snap
            if ent.kind == "insert" and kind in ("table", "assoc_array", "gdtframe", "datumsym", "balloon", "finishmark", "centermark"):
                self.drop_blocks.add(getattr(ent, "block", ""))
            if kind == "dimension" and getattr(ent, "block", ""):
                self.drop_blocks.add(ent.block)
            if kind == "dimension":
                snap.block = ""
            return snap
        extras = payload.get("extras") or {}
        for k, v in extras.items():
            try:
                setattr(ent, k, copy.deepcopy(v))
            except Exception:
                pass
        for k, v in (payload.get("kfields") or {}).items():
            if hasattr(ent, k):
                setattr(ent, k, copy.deepcopy(v))
        return ent

    def r_line(self, e):
        from app.doc.entities import Line

        return Line(start=_v3(e.dxf.start), end=_v3(e.dxf.end))

    def r_point(self, e):
        from app.doc.entities import Point

        return Point(position=_v3(e.dxf.location), angle=math.radians(float(e.dxf.get("angle", 0.0) or 0.0)))

    def r_circle(self, e):
        from app.doc.entities import Circle

        return Circle(center=_v3(e.dxf.center), radius=float(e.dxf.radius))

    def r_arc(self, e):
        from app.doc.entities import Arc

        return Arc(center=_v3(e.dxf.center), radius=float(e.dxf.radius), start_angle=math.radians(float(e.dxf.start_angle)), end_angle=math.radians(float(e.dxf.end_angle)))

    def r_ellipse(self, e):
        from app.doc.entities import Ellipse

        return Ellipse(center=_v3(e.dxf.center), major=_v3(e.dxf.major_axis), ratio=float(e.dxf.ratio), start_param=float(e.dxf.get("start_param", 0.0)), end_param=float(e.dxf.get("end_param", math.tau)))

    def r_ray(self, e):
        from app.doc.entities import Ray

        return Ray(base=_v3(e.dxf.start), direction=_v3(e.dxf.unit_vector))

    def r_xline(self, e):
        from app.doc.entities import XLine

        return XLine(base=_v3(e.dxf.start), direction=_v3(e.dxf.unit_vector))

    def r_solid(self, e):
        from app.doc.entities import Solid

        c = [_v3(e.dxf.get("vtx%d" % i, e.dxf.vtx0)) for i in range(4)]
        if c[3] == c[2]:
            c = c[:3]
        return Solid(corners=c)

    r_trace = r_solid

    def r_lwpolyline(self, e):
        from app.doc.entities import LwPolyline

        verts = [{"p": [float(p[0]), float(p[1])], "bulge": float(p[4]), "sw": float(p[2]), "ew": float(p[3])} for p in e.get_points("xyseb")]
        return LwPolyline(vertices=verts, closed=bool(e.closed), const_width=float(e.dxf.get("const_width", 0.0) or 0.0), elevation=float(e.dxf.get("elevation", 0.0) or 0.0), linetype_gen=bool(int(e.dxf.get("flags", 0) or 0) & 128))

    def r_polyline(self, e):
        from app.doc.entities import LwPolyline, Polyline3d

        if e.is_3d_polyline:
            return Polyline3d(points=[_v3(v.dxf.location) for v in e.vertices], closed=bool(e.is_closed))
        if e.is_2d_polyline:
            verts = []
            for v in e.vertices:
                loc = v.dxf.location
                verts.append({"p": [float(loc[0]), float(loc[1])], "bulge": float(v.dxf.get("bulge", 0.0) or 0.0), "sw": float(v.dxf.get("start_width", 0.0) or 0.0), "ew": float(v.dxf.get("end_width", 0.0) or 0.0)})
            return LwPolyline(vertices=verts, closed=bool(e.is_closed), elevation=float(e.dxf.get("elevation", (0, 0, 0))[2]) if e.dxf.hasattr("elevation") else 0.0)
        return self.unknown(e)

    def r_spline(self, e):
        from app.doc.entities import Spline

        flags = int(e.dxf.get("flags", 0) or 0)
        st = e.dxf.get("start_tangent")
        en = e.dxf.get("end_tangent")
        return Spline(degree=int(e.dxf.get("degree", 3)), knots=[float(k) for k in e.knots], control_points=[_v3(p) for p in e.control_points], weights=[float(w) for w in e.weights], fit_points=[_v3(p) for p in e.fit_points], closed=bool(flags & 1), start_tangent=_v3(st) if st is not None else None, end_tangent=_v3(en) if en is not None else None, fit_tolerance=float(e.dxf.get("fit_tolerance", 0.0) or 0.0))

    def r_text(self, e):
        from app.doc.entities import Text

        x = e.dxf
        ap = x.get("align_point")
        return Text(position=_v3(x.insert), align_point=_v3(ap) if ap is not None and (int(x.get("halign", 0) or 0) or int(x.get("valign", 0) or 0)) else None, height=float(x.get("height", 2.5)), text=C.unesc_line(x.get("text", "")), rotation=math.radians(float(x.get("rotation", 0.0) or 0.0)), width_factor=float(x.get("width", 1.0) or 1.0), oblique=math.radians(float(x.get("oblique", 0.0) or 0.0)), style=str(x.get("style", "Standard")), halign=int(x.get("halign", 0) or 0), valign=int(x.get("valign", 0) or 0))

    def r_mtext(self, e):
        from app.doc.entities import MText

        x = e.dxf
        rot = float(x.get("rotation", 0.0) or 0.0)
        if not x.hasattr("rotation") and x.hasattr("text_direction"):
            td = x.text_direction
            rot = math.degrees(math.atan2(td[1], td[0]))
        return MText(position=_v3(x.insert), height=float(x.get("char_height", 2.5)), width=float(x.get("width", 0.0) or 0.0), attachment=int(x.get("attachment_point", 1)), rotation=math.radians(rot), style=str(x.get("style", "Standard")), contents=C.unesc_multi(e.text), line_spacing=float(x.get("line_spacing_factor", 1.0) or 1.0), line_spacing_style=int(x.get("line_spacing_style", 1) or 1))

    def r_attdef(self, e):
        from app.doc.entities import AttDef

        x = e.dxf
        f = int(x.get("flags", 0) or 0)
        ap = x.get("align_point")
        modes = {"invisible": bool(f & 1), "constant": bool(f & 2), "verify": bool(f & 4), "preset": bool(f & 8), "lock_position": bool(x.get("lock_position", 0))}
        return AttDef(position=_v3(x.insert), tag=str(x.get("tag", "")), prompt=C.unesc_line(x.get("prompt", "")), default=C.unesc_line(x.get("text", "")), height=float(x.get("height", 2.5)), rotation=math.radians(float(x.get("rotation", 0.0) or 0.0)), style=str(x.get("style", "Standard")), modes=modes, align_point=_v3(ap) if ap is not None and (int(x.get("halign", 0) or 0) or int(x.get("valign", 0) or 0)) else None, halign=int(x.get("halign", 0) or 0), valign=int(x.get("valign", 0) or 0), width_factor=float(x.get("width", 1.0) or 1.0), oblique=math.radians(float(x.get("oblique", 0.0) or 0.0)))

    def r_insert(self, e):
        from app.doc.entities import Insert

        x = e.dxf
        ins = Insert(block=str(x.name), position=_v3(x.insert), scale=[float(x.get("xscale", 1.0)), float(x.get("yscale", 1.0)), float(x.get("zscale", 1.0))], rotation=math.radians(float(x.get("rotation", 0.0) or 0.0)))
        rows, cols = int(x.get("row_count", 1) or 1), int(x.get("column_count", 1) or 1)
        if rows > 1 or cols > 1:
            ins.array = {"rows": rows, "cols": cols, "row_spacing": float(x.get("row_spacing", 0.0) or 0.0), "col_spacing": float(x.get("column_spacing", 0.0) or 0.0)}
        blk = None
        try:
            blk = self.doc.blocks.get(ins.block)
        except Exception:
            blk = None
        defs = {}
        if blk is not None:
            for a in blk.query("ATTDEF"):
                defs[str(a.dxf.tag).casefold()] = a
        atts = []
        for a in e.attribs:
            tag = str(a.dxf.get("tag", ""))
            adef = defs.get(tag.casefold())
            lay = str(a.dxf.get("layer", "0"))
            col = int(a.dxf.get("color", 256)) if not a.dxf.hasattr("true_color") else "#%06X" % (int(a.dxf.true_color) & 0xFFFFFF)
            lt = str(a.dxf.get("linetype", "BYLAYER"))
            rec = {"tag": tag, "value": C.unesc_line(a.dxf.get("text", "")), "lock_position": bool(a.dxf.get("lock_position", 0)), "layer": None, "color": None, "linetype": None, "lineweight": None, "shift": None, "at": None, "vis": not bool(int(a.dxf.get("flags", 0) or 0) & 1)}
            if adef is not None:
                if lay.casefold() != str(adef.dxf.get("layer", "0")).casefold() and lay != "0":
                    rec["layer"] = lay
                if col != adef.dxf.get("color", 256) and col != 256:
                    rec["color"] = col
                if lt.upper() not in ("BYLAYER",) and lt.upper() != str(adef.dxf.get("linetype", "BYLAYER")).upper():
                    rec["linetype"] = lt
            atts.append(rec)
        ins.attributes = atts
        self.shift_jobs.append((ins, [(float(a.dxf.insert[0]), float(a.dxf.insert[1])) for a in e.attribs]))
        if e.dxftype() == "ACAD_TABLE":
            self.r.convert("table to block reference")
        return ins

    r_acad_table = r_insert

    def attrib_shifts(self, ins, pts) -> None:
        try:
            from app.doc import attribs as AT
            from app.doc import blockdefs, blockxf

            rec = blockdefs.lookup(self.d, ins.block)
            if rec is None or not ins.attributes:
                return
            defs = {x.tag.casefold(): x for x in AT.definitions(self.d, ins.block)}
            m = blockxf.insert_matrices(ins, rec)[0]
            det = m[0] * m[3] - m[1] * m[2]
            if abs(det) < 1e-18:
                return
            for row, got in zip(ins.attributes, pts):
                adef = defs.get(str(row["tag"]).casefold())
                if adef is None:
                    continue
                want = blockdefs.insert_point(m, [adef.position[0], adef.position[1]])
                dx, dy = float(got[0]) - want[0], float(got[1]) - want[1]
                sx = (m[3] * dx - m[2] * dy) / det
                sy = (-m[1] * dx + m[0] * dy) / det
                if abs(sx) > 1e-6 or abs(sy) > 1e-6:
                    row["shift"] = [sx, sy]
        except Exception:
            return

    def r_hatch(self, e):
        from app.doc.entities import Hatch

        h = Hatch()
        x = e.dxf
        h.solid = bool(x.get("solid_fill", 0))
        h.pattern = "SOLID" if h.solid else str(x.get("pattern_name", "ANSI31") or "ANSI31")
        h.pattern_angle = math.radians(float(x.get("pattern_angle", 0.0) or 0.0))
        h.pattern_scale = float(x.get("pattern_scale", 1.0) or 1.0)
        h.associative = bool(x.get("associative", 0))
        h.style = int(x.get("hatch_style", 0) or 0)
        el = x.get("elevation", (0, 0, 0))
        h.elevation = float(el[2]) if el is not None else 0.0
        g = getattr(e, "gradient", None)
        if g is not None:
            h.solid = False
            h.pattern = "SOLID"
            h.gradient = {"name": str(g.name), "color1": TB.rgb_hex(g.color1), "color2": TB.rgb_hex(g.color2), "tint": float(g.tint), "one": bool(g.one_color), "angle": float(g.rotation), "centered": bool(g.centered)}
        loops = []
        for i, path in enumerate(e.paths):
            verts = self.path_vertices(path)
            if len(verts) < 2:
                continue
            flags = int(getattr(path, "path_type_flags", 0) or 0)
            src = [_h(s) for s in getattr(path, "source_boundary_objects", [])]
            loops.append({"vertices": verts, "sources": [s for s in src if s], "outer": bool(flags & 1) or i == 0, "depth": 0 if (flags & 1 or i == 0) else 1})
        h.loops = loops
        if not patterns_known(h.pattern) and not h.solid and h.gradient is None:
            h.pattern_lines = self.pattern_lines(e, h)
        return h

    def pattern_lines(self, e, h) -> list:
        out = []
        try:
            cs, sn = math.cos(-h.pattern_angle), math.sin(-h.pattern_angle)
            s = h.pattern_scale or 1.0
            for ln in e.pattern.lines:
                ang = math.degrees(math.radians(ln.angle) - h.pattern_angle)
                bx, by = ln.base_point[0], ln.base_point[1]
                ox, oy = ln.offset[0], ln.offset[1]
                out.append({"angle": ang, "origin": [(cs * bx - sn * by) / s, (sn * bx + cs * by) / s], "offset": [(cs * ox - sn * oy) / s, (sn * ox + cs * oy) / s], "dashes": [float(v) / s for v in ln.dash_length_items]})
        except Exception:
            return []
        return out

    def path_vertices(self, path) -> list:
        try:
            if hasattr(path, "vertices"):
                out = []
                for v in path.vertices:
                    out.append({"p": [float(v[0]), float(v[1])], "bulge": float(v[2]) if len(v) > 2 else 0.0})
                return out
            if hasattr(path, "edges"):
                return self.edge_chain(path.edges)
        except Exception:
            return []
        return []

    def edge_chain(self, edges) -> list:
        pts = []
        for ed in edges:
            t = ed.type
            if t == "LineEdge":
                a, b = (float(ed.start[0]), float(ed.start[1])), (float(ed.end[0]), float(ed.end[1]))
                pts.append({"p": [a[0], a[1]], "bulge": 0.0})
                last = [b[0], b[1]]
            elif t == "ArcEdge":
                c, r = ed.center, float(ed.radius)
                a0, a1 = math.radians(float(ed.start_angle)), math.radians(float(ed.end_angle))
                ccw = bool(ed.ccw)
                if ccw:
                    sweep = (a1 - a0) % math.tau or math.tau
                else:
                    sweep = -((a0 - a1) % math.tau or math.tau)
                s = [c[0] + r * math.cos(a0), c[1] + r * math.sin(a0)]
                en = [c[0] + r * math.cos(a1), c[1] + r * math.sin(a1)]
                pts.append({"p": s, "bulge": math.tan(sweep / 4.0) if abs(sweep) < math.tau - 1e-9 else 1.0})
                last = en
            else:
                try:
                    vs = [(float(v[0]), float(v[1])) for v in ed.flattening(0.01)] if hasattr(ed, "flattening") else []
                except Exception:
                    vs = []
                if hasattr(ed, "construction_tool"):
                    try:
                        vs = [(float(v[0]), float(v[1])) for v in ed.construction_tool().flattening(0.01)]
                    except Exception:
                        vs = []
                if not vs:
                    continue
                for v in vs[:-1]:
                    pts.append({"p": [v[0], v[1]], "bulge": 0.0})
                last = [vs[-1][0], vs[-1][1]]
                self.r.convert("hatch edges to polyline")
        if pts and len(edges):
            if math.hypot(last[0] - pts[0]["p"][0], last[1] - pts[0]["p"][1]) > 1e-9:
                pts.append({"p": last, "bulge": 0.0})
        return pts

    def r_dimension(self, e):
        from app.doc.entities import Dimension

        x = e.dxf
        dt = int(x.get("dimtype", 0) or 0)
        base = dt & 7
        kinds = {0: "linear", 1: "aligned", 2: "angular", 3: "diameter", 4: "radius", 5: "angular3", 6: "ordinate", 7: "angular3"}
        dim = Dimension(dim_type=kinds.get(base, "linear"))
        dim.def_point = _v3(x.get("defpoint", (0, 0, 0)))
        dim.text_point = _v3(x.get("text_midpoint", (0, 0, 0)))
        for k, name in (("p13", "defpoint2"), ("p14", "defpoint3"), ("p15", "defpoint4"), ("p16", "defpoint5")):
            v = x.get(name)
            setattr(dim, k, _v3(v) if v is not None and x.hasattr(name) else None)
        dim.text_override = str(x.get("text", "") or "")
        if dim.text_override == "<>":
            dim.text_override = ""
        dim.style = str(x.get("dimstyle", "Standard") or "Standard")
        dim.measurement = float(x.get("actual_measurement", 0.0) or 0.0)
        dim.rotation = math.radians(float(x.get("angle", 0.0) or 0.0)) if base == 0 else 0.0
        dim.text_moved = bool(dt & 128)
        dim.block = str(x.get("geometry", "") or "")
        if base == 6:
            dim.marks = {"ordinate": "x" if dt & 64 else "y"}
        try:
            if e.has_xdata("ACAD"):
                dim.overrides = TB.parse_dstyle(e.get_xdata("ACAD"))
        except Exception:
            pass
        return dim

    def r_leader(self, e):
        from app.doc.entities import KINDS

        Leader = KINDS["leader"]

        return Leader(points=[_v3(p) for p in e.vertices], arrowhead=bool(e.dxf.get("has_arrowhead", 1)), spline=bool(e.dxf.get("path_type", 0)), style=str(e.dxf.get("dimstyle", "Standard") or "Standard"))

    def r_multileader(self, e):
        from app.doc.entities import KINDS

        MLeader = KINDS["mleader"]

        ctx = e.context
        ml = MLeader()
        ml.style = "Standard"
        try:
            st = self.doc.entitydb.get(e.dxf.get("style_handle"))
            if st is not None:
                ml.style = str(st.dxf.name)
        except Exception:
            pass
        leaders = []
        for i, ld in enumerate(ctx.leaders):
            for j, ln in enumerate(ld.lines):
                pts = [[float(v[0]), float(v[1])] for v in ln.vertices]
                if len(pts) >= 2:
                    leaders.append({"id": len(leaders) + 1, "pts": pts})
        ml.leaders = leaders
        mt = ctx.mtext
        if mt is not None:
            ml.text = str(mt.default_content or "")
            ml.content_pos = _v3(mt.insert)
            ml.content_type = "mtext"
            ml.text_height = float(ctx.char_height) if getattr(ctx, "char_height", None) else None
        else:
            ml.content_type = "none"
        if leaders:
            ml.landing = [leaders[0]["pts"][-1][0], leaders[0]["pts"][-1][1], 0.0]
        return ml

    def r_mline(self, e):
        from app.doc.entities import KINDS

        MLine = KINDS["mline"]

        m = MLine()
        m.style = str(e.dxf.get("style_name", "STANDARD") or "STANDARD")
        m.scale = float(e.dxf.get("scale_factor", 1.0))
        m.justification = int(e.dxf.get("justification", 0) or 0)
        fl = int(e.dxf.get("flags", 0) or 0)
        m.closed = bool(fl & 2)
        m.no_start_cap = bool(fl & 4)
        m.no_end_cap = bool(fl & 8)
        m.vertices = [{"p": [float(v.location[0]), float(v.location[1])], "cuts": []} for v in e.vertices]
        rec = self.d.tables["mlinestyles"].get(m.style)
        if rec is not None:
            m.style_def = copy.deepcopy(rec)
        return m

    def r_wipeout(self, e):
        from app.doc.entities import KINDS

        Wipeout = KINDS["wipeout"]

        try:
            pts = [[float(v[0]), float(v[1]), 0.0] for v in e.boundary_path_wcs()]
        except Exception:
            pts = [[float(v[0]), float(v[1]), 0.0] for v in e.get_boundary_path()]
        if len(pts) > 1 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-12:
            pts = pts[:-1]
        return Wipeout(points=pts)

    def r_viewport(self, e):
        from app.doc.entities import KINDS

        x = e.dxf
        cls = KINDS.get("viewport")
        vp = cls()
        vp.center = _v3(x.center)
        vp.width = float(x.width)
        vp.height = float(x.height)
        vc = x.get("view_center_point", (0, 0))
        vp.view_center = [float(vc[0]), float(vc[1]), 0.0]
        vh = float(x.get("view_height", vp.height) or vp.height)
        vp.scale = vh / vp.height if vp.height else 1.0
        fl = int(x.get("flags", 0) or 0)
        vp.on = int(x.get("status", 1) or 0) > 0 and not (fl & 131072)
        vp.locked = bool(fl & 16384)
        vp.vp_id = int(x.get("id", 0) or 0)
        try:
            vp.frozen = [str(n) for n in e.frozen_layers]
        except Exception:
            vp.frozen = []
        h = x.get("clipping_boundary_handle")
        if h and (fl & 65536 or True):
            poly = self.doc.entitydb.get(h)
            if poly is not None and poly.dxftype() == "LWPOLYLINE":
                vp.clip = [{"p": [float(p[0]), float(p[1])], "bulge": float(p[4])} for p in poly.get_points("xyseb")]
        return vp

    def unknown(self, e):
        from app.doc.entities import Unknown

        u = Unknown()
        u.type_name = e.dxftype()
        u.handle = _h(e.dxf.get("handle"))
        try:
            u.layer = str(e.dxf.get("layer", "0") or "0")
        except Exception:
            pass
        try:
            from ezdxf.lldxf.tagwriter import TagCollector

            tc = TagCollector(dxfversion=self.doc.dxfversion)
            e.export_dxf(tc)
            flat = []
            for t in tc.tags:
                v = t.value
                if hasattr(v, "x"):
                    comps = [v.x, v.y, v.z]
                    flat.extend([[t.code + 10 * i, repr(float(c))] for i, c in enumerate(comps)])
                elif isinstance(v, (tuple, list)):
                    flat.extend([[t.code + 10 * i, repr(float(c))] for i, c in enumerate(v)])
                elif isinstance(v, bool):
                    flat.append([t.code, "1" if v else "0"])
                else:
                    flat.append([t.code, str(v)])
            u.raw = {"dxf_tags": flat}
            self.r.note("Entity type %s is kept but not shown." % u.type_name)
        except Exception as err:
            self.r.drop(u.type_name)
            self.r.warn("An unknown %s could not be kept: %s" % (u.type_name, err))
        return u

    def finish(self, fc: dict) -> None:
        d = self.d
        for ins, pts in self.shift_jobs:
            self.attrib_shifts(ins, pts)
        for h in list(self.restored.keys()):
            for ph in self.parts.get(h, []):
                if ph in d.ents:
                    ent = d.ents.pop(ph)
                    lst = d.spaces.get(ent.owner)
                    if lst is not None and ph in lst:
                        lst.remove(ph)
        for name in self.drop_blocks:
            if name and name.startswith("*"):
                self.remove_block(name)
        used = {h for h in d.ents if h > 0}
        top = max(used | {0x100})
        remap = {}
        for h in list(d.ents.keys()):
            if h <= 0:
                top += 1
                ent = d.ents.pop(h)
                ent.handle = top
                remap[h] = top
                d.ents[top] = ent
        if remap:
            for sp, lst in d.spaces.items():
                d.spaces[sp] = [remap.get(h, h) for h in lst]
        hs = fc.get("_handles")
        d.next_handle = max(top + 1, int(hs["next"]) if isinstance(hs, dict) and isinstance(hs.get("next"), int) else 0, d.next_handle)
        rest = fc.get("_drawing")
        if isinstance(rest, dict):
            d.relations = copy.deepcopy(rest.get("relations", {}))
            for k, v in (rest.get("foreign") or {}).items():
                d.foreign[k] = v
            d.tolerances = {**d.tolerances, **(rest.get("tolerances") or {})}
        from app.doc import container

        container.repair(d)
        if not d.tables["layouts"]:
            d.tables["layouts"].put(__import__("app.doc.tables", fromlist=["new_layout"]).new_layout("Layout1", 1, d.metric))
            d.spaces.setdefault("layout:Layout1", [])
        for h, ent in d.ents.items():
            if ent.kind == "hatch" and ent.associative:
                pass
        if self.auditor is not None:
            try:
                for m in list(self.auditor.fixes)[:20]:
                    self.r.warn("Repaired: " + str(m.message))
                for m in list(self.auditor.errors)[:20]:
                    self.r.warn("Problem: " + str(m.message))
            except Exception:
                pass

    def remove_block(self, name: str) -> None:
        d = self.d
        d.tables["blocks"].drop(name)
        sp = "block:" + name
        for h in d.spaces.pop(sp, []):
            d.ents.pop(h, None)


def patterns_known(name: str) -> bool:
    try:
        from app.doc import patterns

        return patterns.known(name)
    except Exception:
        return False


def load_ezdxf(path: str, recover: bool, report: Report):
    auditor = None
    if recover:
        doc, auditor = ezrecover.readfile(path)
        report.note("The file was repaired while reading.")
        return doc, auditor
    try:
        return ezdxf.readfile(path), None
    except (ZC.DXFStructureError, ZC.DXFError, UnicodeDecodeError, ValueError, KeyError, IndexError) as err:
        report.note("The file has structure errors (%s); reading again in repair mode." % err)
        try:
            doc, auditor = ezrecover.readfile(path)
        except Exception as err2:
            raise InterchangeError("The DXF file could not be read, even in repair mode: %s" % err2, "corrupt")
        return doc, auditor
    except IOError as err:
        raise InterchangeError("Cannot open the file: %s" % err, "io")


def read_file(path: str, recover: bool = False, report: Report | None = None):
    report = report or Report()
    src = os.path.realpath(os.path.expanduser(path))
    try:
        size = os.path.getsize(src)
    except OSError as err:
        raise InterchangeError("Cannot open the file: %s" % err, "io")
    if size > MAX_FILE:
        raise InterchangeError("The file is larger than the 512 MB limit.", "toolarge")
    doc, auditor = load_ezdxf(src, recover, report)
    rd = Reader(doc, report, auditor)
    try:
        d = rd.run()
    except InterchangeError:
        raise
    except Exception as err:
        raise InterchangeError("The DXF content could not be turned into a drawing: %s" % err, "baddoc")
    return d, report
