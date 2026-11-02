import threading

from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Builder
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader
from OCP.Interface import Interface_Static
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDF import TDF_Label
from OCP.TDataStd import TDataStd_Name
from OCP.TDocStd import TDocStd_Document
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_SOLID
from OCP.TopoDS import TopoDS_Compound, TopoDS_Iterator
from OCP.XCAFApp import XCAFApp_Application
from OCP.XCAFDoc import XCAFDoc_ColorType, XCAFDoc_DocumentTool, XCAFDoc_ShapeTool
from OCP.collections import Sequence_TDF_Label as LabelSeq

import kernel_store as store

IO_LOCK = threading.Lock()
MAX_BODIES = 5000
SCHEMAS = {"ap203": "AP203", "ap214": "AP214IS", "ap242": "AP242DIS"}


def new_document():
    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("BinXCAF"))
    app.NewDocument(TCollection_ExtendedString("BinXCAF"), doc)
    return doc


def label_name(label) -> str:
    attr = TDataStd_Name()
    if label.FindAttribute(TDataStd_Name.GetID_s(), attr):
        return attr.Get().ToExtString()
    return ""


def label_color(color_tool, shape):
    col = Quantity_Color()
    for kind in (XCAFDoc_ColorType.XCAFDoc_ColorSurf, XCAFDoc_ColorType.XCAFDoc_ColorGen, XCAFDoc_ColorType.XCAFDoc_ColorCurv):
        if color_tool.GetColor(shape, kind, col):
            return [round(col.Red(), 4), round(col.Green(), 4), round(col.Blue(), 4)]
    return None


def walk(label, shape_tool, color_tool, parent_loc, out, depth=0):
    if len(out) >= MAX_BODIES or depth > 64:
        return
    if XCAFDoc_ShapeTool.IsAssembly_s(label):
        comps = LabelSeq()
        XCAFDoc_ShapeTool.GetComponents_s(label, comps)
        for i in range(1, comps.Length() + 1):
            comp = comps.Value(i)
            loc = parent_loc.Multiplied(XCAFDoc_ShapeTool.GetLocation_s(comp))
            ref = TDF_Label()
            if XCAFDoc_ShapeTool.GetReferredShape_s(comp, ref):
                walk(ref, shape_tool, color_tool, loc, out, depth + 1)
        return
    shape = XCAFDoc_ShapeTool.GetShape_s(label)
    if shape.IsNull():
        return
    placed = shape.Located(parent_loc.Multiplied(shape.Location()))
    out.append((label_name(label), placed, label_color(color_tool, shape)))


def split_compound(name, shape, color):
    if shape.ShapeType() != TopAbs_COMPOUND:
        return [(name, shape, color)]
    kids = []
    it = TopoDS_Iterator(shape)
    while it.More():
        kids.append(it.Value())
        it.Next()
    if len(kids) > 1 and all(k.ShapeType() == TopAbs_SOLID for k in kids):
        return [("%s %d" % (name, i + 1) if name else "", k, color) for i, k in enumerate(kids)]
    return [(name, shape, color)]


def open_step(p):
    path = store.absolute_path(p.get("path"), (".step", ".stp"), True)
    with IO_LOCK:
        doc = new_document()
        reader = STEPCAFControl_Reader()
        reader.SetColorMode(True)
        reader.SetNameMode(True)
        reader.SetLayerMode(True)
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise RuntimeError("The STEP file could not be read.")
        if not reader.Transfer(doc):
            raise RuntimeError("The STEP file holds nothing the kernel could translate.")
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
        roots = LabelSeq()
        shape_tool.GetFreeShapes(roots)
        found = []
        from OCP.TopLoc import TopLoc_Location

        for i in range(1, roots.Length() + 1):
            walk(roots.Value(i), shape_tool, color_tool, TopLoc_Location(), found)
    bodies = []
    for name, shape, color in found:
        for n2, s2, c2 in split_compound(name, shape, color):
            ident = store.put(s2)
            bodies.append({"id": ident, "name": n2, "rgb": c2, "summary": store.summarize(s2)})
            if len(bodies) >= MAX_BODIES:
                break
    if not bodies:
        raise RuntimeError("The STEP file holds no solids or surfaces.")
    return {"bodies": bodies, "unit": "mm"}


def save_step(p):
    path = store.absolute_path(p.get("path"), (".step", ".stp"))
    items = p.get("bodies") or []
    if not items:
        raise RuntimeError("There are no bodies to write.")
    schema = SCHEMAS.get(str(p.get("schema", "ap214")).lower())
    if schema is None:
        raise RuntimeError("The schema is ap203, ap214 or ap242.")
    with IO_LOCK:
        Interface_Static.SetCVal_s("write.step.unit", "MM")
        Interface_Static.SetCVal_s("write.step.schema", schema)
        doc = new_document()
        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        color_tool = XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
        for item in items:
            shape = store.shape_of(item.get("id"))
            label = shape_tool.AddShape(shape, False)
            name = str(item.get("name") or "")
            if name:
                TDataStd_Name.Set_s(label, TCollection_ExtendedString(name))
            rgb = item.get("rgb")
            if rgb:
                color_tool.SetColor(label, Quantity_Color(float(rgb[0]), float(rgb[1]), float(rgb[2]), Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
        writer = STEPCAFControl_Writer()
        writer.SetColorMode(True)
        writer.SetNameMode(True)
        writer.SetLayerMode(True)
        if not writer.Transfer(doc, STEPControl_AsIs):
            raise RuntimeError("The bodies could not be translated to STEP.")
        if writer.Write(path) != IFSelect_RetDone:
            raise RuntimeError("The STEP file could not be written.")
    return {"path": path, "bodies": len(items), "schema": schema}


def open_iges(p):
    path = store.absolute_path(p.get("path"), (".iges", ".igs"), True)
    with IO_LOCK:
        reader = IGESControl_Reader()
        if reader.ReadFile(path) != IFSelect_RetDone:
            raise RuntimeError("The IGES file could not be read.")
        reader.TransferRoots()
        count = reader.NbShapes()
        if count == 0:
            raise RuntimeError("The IGES file holds no 3D geometry the kernel could translate.")
        shapes = [reader.Shape(i) for i in range(1, min(count, MAX_BODIES) + 1)]
    bodies = []
    for i, shape in enumerate(shapes):
        if shape.IsNull():
            continue
        ident = store.put(shape)
        bodies.append({"id": ident, "name": "IGES %d" % (i + 1), "rgb": None, "summary": store.summarize(shape)})
    if not bodies:
        raise RuntimeError("The IGES file holds no 3D geometry the kernel could translate.")
    return {"bodies": bodies, "unit": "mm"}


def shape_save(p):
    path = store.absolute_path(p.get("path"), (".brep",))
    shape = store.shape_of(p.get("id"))
    if not BRepTools.Write_s(shape, path):
        raise RuntimeError("The shape could not be written.")
    return {"path": path}


def shape_load(p):
    path = store.absolute_path(p.get("path"), (".brep",), True)
    from OCP.TopoDS import TopoDS_Shape

    shape = TopoDS_Shape()
    if not BRepTools.Read_s(shape, path, BRep_Builder()) or shape.IsNull():
        raise RuntimeError("The stored shape could not be read.")
    ident = store.put(shape)
    return {"id": ident, "summary": store.summarize(shape)}


METHODS = {"open_step": open_step, "save_step": save_step, "open_iges": open_iges, "shape_save": shape_save, "shape_load": shape_load}
