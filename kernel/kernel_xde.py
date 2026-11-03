import math
import os
import re

from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.GProp import GProp_GProps
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Plane, GeomAbs_Sphere
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESCAFControl import IGESCAFControl_Reader, IGESCAFControl_Writer
from OCP.IGESControl import IGESControl_Controller
from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Controller
from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
from OCP.TDF import TDF_Label, TDF_Tool
from OCP.TDataStd import TDataStd_Name
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS, TopoDS_Iterator
from OCP.XCAFDimTolObjects import (
    XCAFDimTolObjects_DatumObject,
    XCAFDimTolObjects_DimensionObject,
    XCAFDimTolObjects_DimensionType as DimType,
    XCAFDimTolObjects_GeomToleranceMatReqModif as MatMod,
    XCAFDimTolObjects_GeomToleranceObject,
    XCAFDimTolObjects_GeomToleranceType as TolType,
    XCAFDimTolObjects_GeomToleranceTypeValue as ZoneType,
)
from OCP.XCAFDoc import (
    XCAFDoc_Area,
    XCAFDoc_Centroid,
    XCAFDoc_ColorType,
    XCAFDoc_Datum,
    XCAFDoc_DimTolTool,
    XCAFDoc_Dimension,
    XCAFDoc_DocumentTool,
    XCAFDoc_GeomTolerance,
    XCAFDoc_Volume,
    XCAFDoc_ShapeTool,
)
from OCP.collections import Sequence_TDF_Label as LabelSeq
from OCP.gp import gp_Pnt, gp_Trsf

import kernel_store as store
from kernel_io import IO_LOCK, label_color, label_name, new_document

MAX_BODIES = 5000
MAX_PMI = 5000
MAX_NODES = 20000
SCHEMAS = {"ap203": "AP203", "ap214": "AP214IS", "ap242": "AP242DIS"}
UNIT_NAMES = {"mm": "MM", "cm": "CM", "m": "M", "inch": "INCH", "foot": "FT", "micron": "UM"}
UNIT_PER_MM = {"MM": 1.0, "CM": 0.1, "M": 0.001, "INCH": 1.0 / 25.4, "FT": 1.0 / 304.8, "UM": 1000.0}
STEP_EXT = (".step", ".stp")
IGES_EXT = (".iges", ".igs")
DIM_TYPES = {
    "distance": "Location_LinearDistance",
    "diameter": "Size_Diameter",
    "radius": "Size_Radius",
    "thickness": "Location_LinearDistance",
    "angle": "Location_Angular",
}
DIM_BACK = {
    "Location_LinearDistance": "distance",
    "Location_LinearDistance_FromCenterToInner": "distance",
    "Location_LinearDistance_FromCenterToOuter": "distance",
    "Location_LinearDistance_FromInnerToCenter": "distance",
    "Location_LinearDistance_FromInnerToInner": "distance",
    "Location_LinearDistance_FromInnerToOuter": "distance",
    "Location_LinearDistance_FromOuterToCenter": "distance",
    "Location_LinearDistance_FromOuterToInner": "distance",
    "Location_LinearDistance_FromOuterToOuter": "distance",
    "Size_Diameter": "diameter",
    "Size_Radius": "radius",
    "Size_Thickness": "thickness",
    "Location_Angular": "angle",
    "Size_Angular": "angle",
}
TOL_TYPES = {
    "straightness": "Straightness",
    "flatness": "Flatness",
    "circularity": "CircularityOrRoundness",
    "cylindricity": "Cylindricity",
    "profile_line": "ProfileOfLine",
    "profile_surface": "ProfileOfSurface",
    "parallelism": "Parallelism",
    "perpendicularity": "Perpendicularity",
    "angularity": "Angularity",
    "position": "Position",
    "concentricity": "Concentricity",
    "symmetry": "Symmetry",
    "runout": "CircularRunout",
    "total_runout": "TotalRunout",
}
TOL_BACK = {v: k for k, v in TOL_TYPES.items()}
TOL_BACK["Coaxiality"] = "concentricity"


def enum_of(cls, prefix, name):
    return getattr(cls, "%s_%s" % (prefix, name))


def enum_name(value, prefix):
    text = str(value)
    return text.split(prefix + "_", 1)[1] if (prefix + "_") in text else text


def hstr(text):
    return TCollection_HAsciiString(str(text))


def set_name(label, name):
    if name:
        TDataStd_Name.Set_s(label, TCollection_ExtendedString(str(name)))


def labels(items):
    seq = LabelSeq()
    for item in items:
        seq.Append(item)
    return seq


def seq_list(seq):
    return [seq.Value(i) for i in range(1, seq.Length() + 1)]


def entry_of(label):
    from OCP.TCollection import TCollection_AsciiString

    text = TCollection_AsciiString()
    TDF_Tool.Entry_s(label, text)
    return text.ToCString()


def to_trsf(m):
    t = gp_Trsf()
    t.SetValues(m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], m[8], m[9], m[10], m[11])
    return t


def file_schema(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(8192).decode("latin-1")
    except OSError:
        return ""
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", head)
    return m.group(1) if m else ""


def count_entities(path):
    if os.path.getsize(path) > 96 * 1024 * 1024:
        return {}
    with open(path, "rb") as fh:
        text = fh.read().decode("latin-1")
    keys = {
        "dimensional_location": r"DIMENSIONAL_LOCATION\(",
        "dimensional_size": r"DIMENSIONAL_SIZE\(",
        "plus_minus_tolerance": r"PLUS_MINUS_TOLERANCE\(",
        "datum": r"[=\s]DATUM\(",
        "datum_feature": r"DATUM_FEATURE\(",
        "datum_reference": r"DATUM_REFERENCE_COMPARTMENT\(",
        "geometric_tolerance": r"[A-Z_]+_TOLERANCE\(\)|[A-Z]+_TOLERANCE\('",
        "volume_measure": r"VOLUME_MEASURE\(",
        "presentation_layer": r"PRESENTATION_LAYER_ASSIGNMENT\(",
        "assembly_usage": r"NEXT_ASSEMBLY_USAGE_OCCURRENCE\(",
    }
    return {k: len(re.findall(v, text)) for k, v in keys.items()}


def configure_reader(reader, gdt=True):
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    reader.SetLayerMode(True)
    if hasattr(reader, "SetPropsMode"):
        reader.SetPropsMode(True)
    if gdt and hasattr(reader, "SetGDTMode"):
        reader.SetGDTMode(True)


def layers_of(layer_tool, label):
    try:
        seq = layer_tool.GetLayers(label)
    except Exception:
        return []
    if seq is None:
        return []
    out = []
    for i in range(1, seq.Length() + 1):
        out.append(seq.Value(i).ToExtString())
    return out


class Walker:
    def __init__(self, shape_tool, color_tool, layer_tool):
        self.shape_tool = shape_tool
        self.color_tool = color_tool
        self.layer_tool = layer_tool
        self.found = []
        self.defs = {}

    def run(self, label, loc, path, name_hint, depth=0):
        if len(self.found) >= MAX_BODIES or depth > 64:
            return
        if XCAFDoc_ShapeTool.IsAssembly_s(label):
            title = label_name(label) or name_hint
            comps = LabelSeq()
            XCAFDoc_ShapeTool.GetComponents_s(label, comps)
            sub = path + [title]
            for i in range(1, comps.Length() + 1):
                comp = comps.Value(i)
                cloc = loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(comp))
                ref = TDF_Label()
                if XCAFDoc_ShapeTool.GetReferredShape_s(comp, ref):
                    self.run(ref, cloc, sub, label_name(comp) or label_name(ref), depth + 1)
            return
        shape = XCAFDoc_ShapeTool.GetShape_s(label)
        if shape.IsNull():
            return
        placed = shape.Located(loc.Multiplied(shape.Location()))
        key = entry_of(label)
        first = key not in self.defs
        if first:
            self.defs[key] = (label, shape)
        self.found.append({
            "name": name_hint or label_name(label),
            "shape": placed,
            "def": key,
            "first": first,
            "rgb": label_color(self.color_tool, shape),
            "layers": layers_of(self.layer_tool, label),
            "path": [p for p in path if p],
        })


def split_compound(item):
    shape = item["shape"]
    if shape.ShapeType() != TopAbs_COMPOUND:
        return [item]
    kids = []
    it = TopoDS_Iterator(shape)
    while it.More():
        kids.append(it.Value())
        it.Next()
    if len(kids) > 1 and all(k.ShapeType() == TopAbs_SOLID for k in kids):
        out = []
        for i, k in enumerate(kids):
            c = dict(item)
            c["shape"] = k
            c["name"] = "%s %d" % (item["name"], i + 1) if item["name"] else ""
            c["first"] = item["first"] and i == 0
            c["split"] = True
            out.append(c)
        return out
    return [item]


def read_pmi(dim_tool, defs, body_of_def, report):
    maps = {}

    def map_for(key, kind):
        if (key, kind) not in maps:
            maps[(key, kind)] = store.build_maps(defs[key][1])[kind]
        return maps[(key, kind)]

    def resolve(label_list):
        out = []
        key_hit = None
        for lab in label_list:
            shape = XCAFDoc_ShapeTool.GetShape_s(lab)
            if shape.IsNull():
                continue
            st = shape.ShapeType()
            kind = "faces" if st == TopAbs_FACE else "edges" if st == TopAbs_EDGE else None
            if kind is None:
                continue
            for key in defs:
                idx = map_for(key, kind).FindIndex(shape)
                if idx > 0:
                    out.append({"kind": "face" if kind == "faces" else "edge", "index": idx - 1})
                    key_hit = key_hit or key
                    break
        return out, key_hit

    items = []
    lost = []
    dims = LabelSeq()
    dim_tool.GetDimensionLabels(dims)
    for lab in seq_list(dims):
        obj = XCAFDoc_Dimension.Set_s(lab).GetObject()
        tname = enum_name(obj.GetType(), "DimensionType")
        dtype = DIM_BACK.get(tname)
        first, second = LabelSeq(), LabelSeq()
        XCAFDoc_DimTolTool.GetRefShapeLabel_s(lab, first, second)
        refs, key = resolve(seq_list(first))
        refs2, key2 = resolve(seq_list(second))
        if dtype is None:
            lost.append({"what": "dimension", "reason": "dimension type %s has no FormCAD kind" % tname})
            continue
        if not refs or key not in body_of_def:
            lost.append({"what": "dimension", "reason": "its feature could not be matched to a body face or edge"})
            continue
        plus, minus = 0.0, 0.0
        if obj.IsDimWithPlusMinusTolerance():
            plus, minus = float(obj.GetUpperTolValue()), float(obj.GetLowerTolValue())
        items.append({"type": "dimension", "def": key, "dtype": dtype, "value": float(obj.GetValue()), "plus": plus, "minus": minus, "refs": refs, "refs2": refs2, "step_type": tname})
    tols = LabelSeq()
    dim_tool.GetGeomToleranceLabels(tols)
    seen_datums = set()
    dts = LabelSeq()
    dim_tool.GetDatumLabels(dts)
    datum_entries = {}
    for lab in seq_list(dts):
        att = XCAFDoc_Datum.Set_s(lab)
        letter = ""
        try:
            letter = att.GetObject().GetName().ToCString()
        except Exception:
            letter = ""
        letter = letter or att.GetIdentification().ToCString() or att.GetName().ToCString()
        datum_entries[entry_of(lab)] = letter
        shapes, other = LabelSeq(), LabelSeq()
        XCAFDoc_DimTolTool.GetRefShapeLabel_s(lab, shapes, other)
        refs, key = resolve(seq_list(shapes))
        if not letter or not refs or key not in body_of_def:
            lost.append({"what": "datum", "reason": "the datum has no identifier or its feature could not be matched"})
            continue
        sig = (key, letter[:1].upper(), tuple((r["kind"], r["index"]) for r in refs))
        if sig in seen_datums:
            continue
        seen_datums.add(sig)
        items.append({"type": "datum", "def": key, "letter": letter[:1].upper(), "refs": refs, "refs2": []})
    for lab in seq_list(tols):
        obj = XCAFDoc_GeomTolerance.Set_s(lab).GetObject()
        tname = enum_name(obj.GetType(), "GeomToleranceType")
        char = TOL_BACK.get(tname)
        shapes, other = LabelSeq(), LabelSeq()
        XCAFDoc_DimTolTool.GetRefShapeLabel_s(lab, shapes, other)
        refs, key = resolve(seq_list(shapes))
        if char is None:
            lost.append({"what": "tolerance", "reason": "tolerance type %s has no FormCAD kind" % tname})
            continue
        if not refs or key not in body_of_def:
            lost.append({"what": "tolerance", "reason": "its feature could not be matched to a body face or edge"})
            continue
        zone = enum_name(obj.GetTypeOfValue(), "GeomToleranceTypeValue")
        mod = enum_name(obj.GetMaterialRequirementModifier(), "GeomToleranceMatReqModif")
        dls = LabelSeq()
        XCAFDoc_DimTolTool.GetDatumOfTolerLabels_s(lab, dls)
        letters = []
        ranked = []
        for dl in seq_list(dls):
            att = XCAFDoc_Datum.Set_s(dl)
            try:
                pos = int(att.GetObject().GetPosition())
            except Exception:
                pos = 0
            letter = datum_entries.get(entry_of(dl)) or att.GetIdentification().ToCString()
            ranked.append((pos or 99, letter[:1].upper()))
        for _pos, letter in sorted(ranked):
            if letter:
                letters.append(letter)
        items.append({
            "type": "tolerance", "def": key, "char": char, "tol": float(obj.GetValue()),
            "zone": {"Diameter": "diameter", "SphericalDiameter": "sphere"}.get(zone, "none"),
            "modifier": {"M": "M", "L": "L"}.get(mod, ""), "datums": letters[:3], "refs": refs, "refs2": [], "step_type": tname,
        })
    return items, lost


def xde_read(p):
    path = store.absolute_path(p.get("path"), STEP_EXT + IGES_EXT, True)
    iges = os.path.splitext(path)[1].lower() in IGES_EXT
    unit = str(p.get("unit") or "mm").lower()
    want_pmi = bool(p.get("pmi", True))
    with IO_LOCK:
        if iges:
            IGESControl_Controller.Init_s()
        else:
            STEPControl_Controller.Init_s()
        Interface_Static.SetCVal_s("xstep.cascade.unit", UNIT_NAMES.get(unit, "MM"))
        doc = new_document()
        reader = IGESCAFControl_Reader() if iges else STEPCAFControl_Reader()
        configure_reader(reader, want_pmi)
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise RuntimeError("The %s file could not be read." % ("IGES" if iges else "STEP"))
        if not reader.Transfer(doc):
            raise RuntimeError("The file holds nothing the kernel could translate.")
        main = doc.Main()
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(main)
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(main)
        layer_tool = XCAFDoc_DocumentTool.LayerTool_s(main)
        roots = LabelSeq()
        shape_tool.GetFreeShapes(roots)
        walker = Walker(shape_tool, color_tool, layer_tool)
        for i in range(1, roots.Length() + 1):
            root = roots.Value(i)
            walker.run(root, TopLoc_Location(), [], label_name(root) or "")
        flat = []
        for item in walker.found:
            flat.extend(split_compound(item))
        flat = flat[:MAX_BODIES]
        if not flat:
            raise RuntimeError("The file holds no solids or surfaces.")
        bodies = []
        body_of_def = {}
        for item in flat:
            ident = store.put(item["shape"])
            body = {"id": ident, "name": item["name"], "rgb": item["rgb"], "layers": item["layers"], "path": item["path"], "def": item["def"], "summary": store.summarize(item["shape"])}
            if item["first"] and not item.get("split"):
                body_of_def.setdefault(item["def"], len(bodies))
            bodies.append(body)
        pmi, lost = [], []
        if want_pmi and not iges:
            dim_tool = XCAFDoc_DocumentTool.DimTolTool_s(main)
            single = {k: v for k, v in walker.defs.items() if k in body_of_def}
            pmi, lost = read_pmi(dim_tool, single, body_of_def, None)
            for item in pmi:
                item["body"] = body_of_def[item.pop("def")]
        colors = LabelSeq()
        try:
            color_tool.GetColors(colors)
            colour_count = colors.Length()
        except Exception:
            colour_count = 0
    return {
        "bodies": bodies,
        "pmi": pmi[:MAX_PMI],
        "pmi_lost": lost,
        "unit": unit,
        "schema": "" if iges else file_schema(path),
        "colours_in_file": colour_count,
        "entities": {} if iges else count_entities(path),
    }


def set_color(color_tool, label, rgb):
    if rgb and len(rgb) == 3:
        color_tool.SetColor(label, Quantity_Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)


def attach_validation(label, shape):
    vol = GProp_GProps()
    area = GProp_GProps()
    try:
        BRepGProp.SurfaceProperties_s(shape, area)
        XCAFDoc_Area.Set_s(label, area.Mass())
        if store.count_of(shape, TopAbs_SOLID):
            BRepGProp.VolumeProperties_s(shape, vol)
            XCAFDoc_Volume.Set_s(label, vol.Mass())
            c = vol.CentreOfMass()
            XCAFDoc_Centroid.Set_s(label, gp_Pnt(c.X(), c.Y(), c.Z()))
        return True
    except Exception:
        return False


def pick(maps, ref):
    kind = "faces" if ref.get("kind") == "face" else "edges"
    idx = int(ref.get("index", -1))
    m = maps[kind]
    if idx < 0 or idx >= m.Extent():
        return None
    return m.FindKey(idx + 1)


def build_pmi(dim_tool, shape_tool, def_label, maps, items, report, key):
    cache = {}

    def sub_label(ref):
        k = (ref.get("kind"), ref.get("index"))
        if k in cache:
            return cache[k]
        sh = pick(maps, ref)
        lab = None if sh is None else shape_tool.AddSubShape(def_label, sh)
        if lab is not None and lab.IsNull():
            lab = None
        cache[k] = lab
        return lab

    datum_labels = {}
    datum_positions = {}
    for it in items:
        if it["type"] == "tolerance":
            for pos, letter in enumerate(it.get("datums") or [], 1):
                datum_positions.setdefault(letter, pos)
    for it in items:
        if it["type"] != "datum":
            continue
        subs = [sub_label(r) for r in it["refs"]]
        subs = [s for s in subs if s is not None]
        if not subs:
            report["dropped"].append({"id": it["id"], "reason": "the datum feature is not on the body"})
            continue
        lab = dim_tool.AddDatum()
        obj = XCAFDimTolObjects_DatumObject()
        obj.SetName(hstr(it["letter"]))
        obj.SetPosition(datum_positions.get(it["letter"], 1))
        dim_tool.SetDatum(labels(subs), lab)
        XCAFDoc_Datum.Set_s(lab).SetObject(obj)
        datum_labels[it["letter"]] = lab
        report["written"].append(it["id"])
    for it in items:
        if it["type"] == "dimension":
            subs = [sub_label(r) for r in it["refs"]]
            subs2 = [sub_label(r) for r in it["refs2"]]
            if None in subs or None in subs2 or not subs:
                report["dropped"].append({"id": it["id"], "reason": "a feature of the dimension is not on the body"})
                continue
            two = it["dtype"] in ("distance", "angle", "thickness")
            if two and not subs2:
                if it["dtype"] == "thickness" and len(subs) >= 2:
                    subs, subs2 = subs[:1], subs[1:2]
                else:
                    report["dropped"].append({"id": it["id"], "reason": "a %s dimension needs two features and OCCT refuses one" % it["dtype"]})
                    continue
            lab = dim_tool.AddDimension()
            obj = XCAFDimTolObjects_DimensionObject()
            obj.SetType(enum_of(DimType, "XCAFDimTolObjects_DimensionType", DIM_TYPES[it["dtype"]]))
            obj.SetValue(float(it["value"]))
            if it.get("plus", 0) or it.get("minus", 0):
                obj.SetUpperTolValue(float(it.get("plus", 0)))
                obj.SetLowerTolValue(float(it.get("minus", 0)))
            if two:
                dim_tool.SetDimension(labels(subs), labels(subs2), lab)
            else:
                dim_tool.SetDimension(subs[0], lab)
            XCAFDoc_Dimension.Set_s(lab).SetObject(obj)
            report["written"].append(it["id"])
            if it["dtype"] == "thickness":
                report["notes"].append({"id": it["id"], "reason": "a thickness is written as a linear distance between its two faces; OCCT keeps only one feature of a size dimension"})
        elif it["type"] == "tolerance":
            subs = [sub_label(r) for r in it["refs"]]
            if None in subs or not subs:
                report["dropped"].append({"id": it["id"], "reason": "a toleranced feature is not on the body"})
                continue
            lab = dim_tool.AddGeomTolerance()
            obj = XCAFDimTolObjects_GeomToleranceObject()
            obj.SetType(enum_of(TolType, "XCAFDimTolObjects_GeomToleranceType", TOL_TYPES[it["char"]]))
            obj.SetValue(float(it["tol"]))
            zone = {"diameter": "Diameter", "sphere": "SphericalDiameter"}.get(it.get("zone"), "None")
            obj.SetTypeOfValue(enum_of(ZoneType, "XCAFDimTolObjects_GeomToleranceTypeValue", zone))
            if it.get("modifier") in ("M", "L"):
                obj.SetMaterialRequirementModifier(enum_of(MatMod, "XCAFDimTolObjects_GeomToleranceMatReqModif", it["modifier"]))
            dim_tool.SetGeomTolerance(subs[0], lab)
            XCAFDoc_GeomTolerance.Set_s(lab).SetObject(obj)
            missing = []
            for letter in it.get("datums") or []:
                dl = datum_labels.get(letter)
                if dl is None:
                    missing.append(letter)
                    continue
                dim_tool.SetDatumToGeomTol(dl, lab)
            report["written"].append(it["id"])
            if missing:
                report["notes"].append({"id": it["id"], "reason": "datum %s has no datum feature on this body and was left out of the frame" % ", ".join(missing)})


def xde_write(p):
    path = store.absolute_path(p.get("path"), STEP_EXT + IGES_EXT)
    iges = os.path.splitext(path)[1].lower() in IGES_EXT
    schema = SCHEMAS.get(str(p.get("schema", "ap214")).lower())
    if schema is None:
        raise RuntimeError("The schema is ap203, ap214 or ap242.")
    unit = UNIT_NAMES.get(str(p.get("unit") or "mm").lower())
    if unit is None:
        raise RuntimeError("The unit is mm, cm, m, inch, foot or micron.")
    nodes = p.get("nodes") or []
    bodies = p.get("bodies") or {}
    if not nodes or not bodies:
        raise RuntimeError("There are no bodies to write.")
    if len(nodes) > MAX_NODES or len(bodies) > MAX_BODIES:
        raise RuntimeError("The model has more than %d bodies or %d nodes." % (MAX_BODIES, MAX_NODES))
    pmi_items = [dict(i) for i in (p.get("pmi") or []) if i.get("body") in bodies][:MAX_PMI]
    scale = UNIT_PER_MM[unit]
    for i in pmi_items:
        if i["type"] == "dimension" and i.get("dtype") != "angle":
            for key in ("value", "plus", "minus"):
                i[key] = float(i.get(key) or 0.0) * scale
        elif i["type"] == "tolerance":
            i["tol"] = float(i.get("tol") or 0.0) * scale
    want_pmi = bool(pmi_items) and not iges
    use = schema
    pmi_report = {"written": [], "dropped": [], "notes": [], "requested": len(pmi_items)}
    if want_pmi and schema != "AP242DIS":
        raise RuntimeError("Semantic PMI needs the AP242 schema.")
    with IO_LOCK:
        if iges:
            IGESControl_Controller.Init_s()
            Interface_Static.SetCVal_s("write.iges.unit", unit)
            Interface_Static.SetCVal_s("write.iges.brep.mode", "1")
        else:
            STEPControl_Controller.Init_s()
            if not Interface_Static.SetCVal_s("write.step.schema", use):
                raise RuntimeError("The kernel did not accept the %s schema." % use)
            Interface_Static.SetCVal_s("write.step.unit", unit)
        doc = new_document()
        main = doc.Main()
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(main)
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(main)
        layer_tool = XCAFDoc_DocumentTool.LayerTool_s(main)
        dim_tool = XCAFDoc_DocumentTool.DimTolTool_s(main)
        def_labels = {}
        body_loc = {}
        validated = 0
        for key, b in bodies.items():
            full = store.shape_of(b["id"])
            body_loc[key] = full.Location()
            shape = full.Located(TopLoc_Location())
            lab = shape_tool.AddShape(shape, False)
            set_name(lab, b.get("name"))
            set_color(color_tool, lab, b.get("rgb"))
            for layer in b.get("layers") or []:
                layer_tool.SetLayer(lab, TCollection_ExtendedString(str(layer)), False)
            if attach_validation(lab, shape) and not iges:
                validated += 1
            def_labels[key] = lab
            mine = [i for i in pmi_items if i.get("body") == key]
            if mine and want_pmi:
                build_pmi(dim_tool, shape_tool, lab, store.build_maps(shape), mine, pmi_report, key)
        node_labels = {}

        def node_location(n):
            matrix = n.get("matrix")
            own = TopLoc_Location(to_trsf(matrix)) if matrix else TopLoc_Location()
            return own.Multiplied(body_loc[n["body"]]) if n.get("body") is not None else own

        top = []
        for idx, n in enumerate(nodes):
            parent = int(n.get("parent", -1))
            if n.get("body") is not None:
                comp_src = def_labels[n["body"]]
                is_leaf = True
            else:
                comp_src = shape_tool.NewShape()
                set_name(comp_src, n.get("name"))
                is_leaf = False
            node_labels[idx] = (comp_src, is_leaf)
            if parent < 0:
                top.append(idx)
        for idx, n in enumerate(nodes):
            parent = int(n.get("parent", -1))
            if parent < 0:
                continue
            pl, pleaf = node_labels[parent]
            cl, _ = node_labels[idx]
            comp = shape_tool.AddComponent(pl, cl, node_location(n))
            if n.get("name"):
                set_name(comp, n["name"])
        for idx in top:
            n = nodes[idx]
            lab, leaf = node_labels[idx]
            loc = node_location(n)
            if leaf and not loc.IsIdentity():
                wrapper = shape_tool.NewShape()
                set_name(wrapper, n.get("name"))
                comp = shape_tool.AddComponent(wrapper, lab, loc)
                set_name(comp, n.get("name"))
        try:
            shape_tool.UpdateAssemblies()
        except Exception:
            pass
        if iges:
            writer = IGESCAFControl_Writer()
            writer.SetColorMode(True)
            writer.SetNameMode(True)
            writer.SetLayerMode(True)
            if not writer.Transfer(doc):
                raise RuntimeError("The bodies could not be translated to IGES.")
            if not writer.Write(path):
                raise RuntimeError("The IGES file could not be written.")
        else:
            writer = STEPCAFControl_Writer()
            writer.SetColorMode(True)
            writer.SetNameMode(True)
            writer.SetLayerMode(True)
            if hasattr(writer, "SetPropsMode"):
                writer.SetPropsMode(True)
            writer.SetDimTolMode(bool(want_pmi))
            writer.Writer().Model(True)
            if not writer.Transfer(doc, STEPControl_AsIs):
                raise RuntimeError("The bodies could not be translated to STEP.")
            if writer.Write(path) != IFSelect_RetDone:
                raise RuntimeError("The STEP file could not be written; the kernel refused the model or its PMI.")
    out = {"path": path, "schema": "" if iges else file_schema(path), "schema_requested": use, "unit": unit, "bodies": len(bodies), "nodes": len(nodes), "validation": validated, "bytes": os.path.getsize(path)}
    out["entities"] = {} if iges else count_entities(path)
    out["pmi"] = pmi_report
    return out


def feature_of(wid, ref):
    sh = pick(store.maps_of(wid), ref)
    if sh is None:
        return None
    if ref.get("kind") == "face":
        face = TopoDS.Face_s(sh) if hasattr(TopoDS, "Face_s") else TopoDS.Face(sh)
        ad = BRepAdaptor_Surface(face)
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, props)
        c = props.CentreOfMass()
        centre = [c.X(), c.Y(), c.Z()]
        bf = BRepGProp_Face(face)
        u0, u1, v0, v1 = ad.FirstUParameter(), ad.LastUParameter(), ad.FirstVParameter(), ad.LastVParameter()
        info = {"shape": face, "centre": centre, "area": props.Mass(), "kind": "face", "type": "other"}
        t = ad.GetType()
        if t == GeomAbs_Plane:
            pl = ad.Plane()
            d = pl.Axis().Direction()
            n = [d.X(), d.Y(), d.Z()]
            if face.Orientation().name.endswith("REVERSED"):
                n = [-v for v in n]
            info.update(type="plane", normal=n)
        elif t == GeomAbs_Cylinder:
            cy = ad.Cylinder()
            loc, d = cy.Location(), cy.Axis().Direction()
            info.update(type="cylinder", radius=cy.Radius(), axis_point=[loc.X(), loc.Y(), loc.Z()], axis=[d.X(), d.Y(), d.Z()])
        elif t == GeomAbs_Sphere:
            sp = ad.Sphere()
            loc = sp.Location()
            info.update(type="sphere", radius=sp.Radius(), axis_point=[loc.X(), loc.Y(), loc.Z()])
        else:
            from OCP.gp import gp_Vec

            um, vm = (u0 + u1) / 2, (v0 + v1) / 2
            pnt, nrm = gp_Pnt(), gp_Vec()
            bf.Normal(um, vm, pnt, nrm)
            if nrm.Magnitude() > 1e-12:
                nrm.Normalize()
                info["normal"] = [nrm.X(), nrm.Y(), nrm.Z()]
            info["centre"] = [pnt.X(), pnt.Y(), pnt.Z()]
        return info
    edge = TopoDS.Edge_s(sh) if hasattr(TopoDS, "Edge_s") else TopoDS.Edge(sh)
    ad = BRepAdaptor_Curve(edge)
    mid = ad.Value((ad.FirstParameter() + ad.LastParameter()) / 2)
    info = {"shape": edge, "centre": [mid.X(), mid.Y(), mid.Z()], "kind": "edge", "type": "other"}
    t = ad.GetType()
    if t == GeomAbs_Line:
        d = ad.Line().Direction()
        info.update(type="line", axis=[d.X(), d.Y(), d.Z()], axis_point=info["centre"])
    elif t == GeomAbs_Circle:
        ci = ad.Circle()
        loc, d = ci.Location(), ci.Axis().Direction()
        info.update(type="circle", radius=ci.Radius(), axis_point=[loc.X(), loc.Y(), loc.Z()], axis=[d.X(), d.Y(), d.Z()])
    return info


def vsub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def vdot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def vadd(a, b, k=1.0):
    return [a[0] + k * b[0], a[1] + k * b[1], a[2] + k * b[2]]


def vlen(a):
    return math.sqrt(vdot(a, a))


def dir_of(f):
    if f["type"] == "plane":
        return f["normal"]
    if f["type"] in ("cylinder", "circle", "line"):
        return f["axis"]
    return f.get("normal")


def reduce_feature(f):
    if f["type"] == "plane":
        return ("plane", f["centre"], f["normal"])
    if f["type"] in ("cylinder", "line", "circle"):
        return ("axis", f["axis_point"], f["axis"])
    if f["type"] == "sphere":
        return ("point", f["axis_point"], None)
    return ("shape", f["centre"], f.get("normal"))


def project_plane(pt, plane_pt, n):
    k = vdot(vsub(pt, plane_pt), n)
    return k, vadd(pt, n, -k)


def measure_pair(a, b):
    ra, rb = reduce_feature(a), reduce_feature(b)
    kinds = (ra[0], rb[0])
    if kinds == ("plane", "plane"):
        if abs(abs(vdot(ra[2], rb[2])) - 1.0) < 1e-9:
            k, foot = project_plane(ra[1], rb[1], rb[2])
            return abs(k), ra[1], foot
    if kinds in (("plane", "axis"), ("plane", "point")) or kinds in (("axis", "plane"), ("point", "plane")):
        swap = ra[0] != "plane"
        pl, ot = (rb, ra) if swap else (ra, rb)
        if ot[0] == "point" or abs(vdot(ot[2], pl[2])) < 1e-9:
            k, foot = project_plane(ot[1], pl[1], pl[2])
            return abs(k), ot[1], foot
    if kinds == ("axis", "axis"):
        if abs(abs(vdot(ra[2], rb[2])) - 1.0) < 1e-9:
            w = vsub(ra[1], rb[1])
            along = vdot(w, rb[2])
            perp = vsub(w, [along * c for c in rb[2]])
            return vlen(perp), ra[1], vsub(ra[1], perp)
    if kinds == ("point", "point"):
        return vlen(vsub(ra[1], rb[1])), ra[1], rb[1]
    dist = BRepExtrema_DistShapeShape(a["shape"], b["shape"])
    if not dist.IsDone() or dist.NbSolution() < 1:
        raise RuntimeError("The distance between these features could not be measured.")
    p1, p2 = dist.PointOnShape1(1), dist.PointOnShape2(1)
    return dist.Value(), [p1.X(), p1.Y(), p1.Z()], [p2.X(), p2.Y(), p2.Z()]


def pmi_measure(p):
    wid = p.get("id")
    dtype = p.get("dtype")
    a_refs = p.get("refs") or []
    b_refs = p.get("refs2") or []
    if not a_refs:
        raise RuntimeError("Pick a feature first.")
    fa = feature_of(wid, a_refs[0])
    if fa is None:
        raise RuntimeError("The first feature is not on the body.")
    if dtype in ("diameter", "radius"):
        if fa.get("radius") is None:
            raise RuntimeError("A %s dimension needs a cylinder, sphere or circle." % dtype)
        r = fa["radius"]
        out = r * 2 if dtype == "diameter" else r
        c = fa["axis_point"]
        d = fa.get("axis") or [0, 0, 1]
        ref = [1, 0, 0] if abs(d[0]) < 0.9 else [0, 1, 0]
        u = [d[1] * ref[2] - d[2] * ref[1], d[2] * ref[0] - d[0] * ref[2], d[0] * ref[1] - d[1] * ref[0]]
        ln = vlen(u) or 1.0
        u = [x / ln for x in u]
        if fa["type"] == "cylinder":
            c = vadd(fa["centre"], d, -vdot(vsub(fa["centre"], fa["axis_point"]), d))
        return {"value": out, "from": vadd(c, u, -r), "to": vadd(c, u, r), "normal": d, "centre": c, "radius": r}
    if not b_refs:
        if dtype == "thickness" and len(a_refs) >= 2:
            b_refs = a_refs[1:2]
        else:
            raise RuntimeError("A %s dimension needs two features." % dtype)
    fb = feature_of(wid, b_refs[0])
    if fb is None:
        raise RuntimeError("The second feature is not on the body.")
    if dtype == "angle":
        da, db = dir_of(fa), dir_of(fb)
        if da is None or db is None:
            raise RuntimeError("An angle needs planes, cylinders, circles or lines.")
        cosv = max(-1.0, min(1.0, vdot(da, db)))
        ang = math.degrees(math.acos(cosv))
        if fa["type"] == "plane" and fb["type"] == "plane":
            ang = 180.0 - ang
        elif ang > 90.0:
            ang = 180.0 - ang
        flip = (fa["type"] == "plane" and fb["type"] == "plane") or cosv < 0
        return {"value": ang, "from": fa["centre"], "to": fb["centre"], "normal": da, "normal2": [-c for c in db] if flip else db, "centre": fa["centre"]}
    value, p1, p2 = measure_pair(fa, fb)
    d = vsub(p2, p1)
    ln = vlen(d)
    return {"value": value, "from": p1, "to": p2, "normal": [x / ln for x in d] if ln > 1e-12 else (dir_of(fa) or [0, 0, 1]), "centre": [(p1[i] + p2[i]) / 2 for i in range(3)]}


def pmi_anchors(p):
    wid = p.get("id")
    out = []
    for ref in p.get("refs") or []:
        f = feature_of(wid, ref)
        if f is None:
            out.append(None)
            continue
        out.append({"kind": f["kind"], "type": f["type"], "centre": f["centre"], "normal": dir_of(f), "radius": f.get("radius"), "axis_point": f.get("axis_point")})
    return {"features": out}


def pmi_features(p):
    wid = p.get("id")
    maps = store.maps_of(wid)
    limit = int(p.get("limit", 2000))
    out = {"faces": [], "edges": []}
    for kind, name in (("face", "faces"), ("edge", "edges")):
        n = min(maps[name].Extent(), limit)
        for i in range(n):
            f = feature_of(wid, {"kind": kind, "index": i})
            if f is None:
                continue
            row = {"index": i, "type": f["type"], "centre": f["centre"], "normal": dir_of(f), "radius": f.get("radius")}
            if kind == "face":
                row["area"] = f["area"]
            out[name].append(row)
    return out


METHODS = {"xde_read": xde_read, "xde_write": xde_write, "pmi_measure": pmi_measure, "pmi_anchors": pmi_anchors, "pmi_features": pmi_features}
