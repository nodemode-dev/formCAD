import array
import os

from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepLib import BRepLib
from OCP.Geom import Geom_BezierSurface
from OCP.GProp import GProp_GProps
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.collections import Array2_gp_Pnt
from OCP.gp import gp_Pnt

import kernel_store as store

MAX_PATCHES = 60000


def surface_of(coords, at):
    grid = Array2_gp_Pnt(1, 4, 1, 4)
    k = at
    for i in range(1, 5):
        for j in range(1, 5):
            grid.SetValue(i, j, gp_Pnt(coords[k], coords[k + 1], coords[k + 2]))
            k += 3
    return Geom_BezierSurface(grid)


def read_patches(path, count):
    count = int(count)
    if count < 1 or count > MAX_PATCHES:
        raise RuntimeError("The patch count must be 1 to %d." % MAX_PATCHES)
    path = store.absolute_path(path, (".bez",), True)
    if os.path.getsize(path) != count * 48 * 8:
        raise RuntimeError("The patch file has the wrong size.")
    data = array.array("d")
    with open(path, "rb") as fh:
        data.fromfile(fh, count * 48)
    return data


def fast_summary(shape, bbox, valid, closed):
    if bbox and len(bbox) == 6:
        box = [float(x) for x in bbox]
    else:
        b = Bnd_Box()
        BRepBndLib.Add_s(shape, b, False)
        box = [b.GetXMin(), b.GetYMin(), b.GetZMin(), b.GetXMax(), b.GetYMax(), b.GetZMax()]
    return {
        "solids": store.count_of(shape, TopAbs_SOLID), "shells": store.count_of(shape, TopAbs_SHELL), "faces": store.count_of(shape, TopAbs_FACE),
        "edges": store.count_of(shape, TopAbs_EDGE), "vertices": store.count_of(shape, TopAbs_VERTEX), "valid": valid, "closed": closed, "bbox": box,
    }


def subd_brep(p):
    count = int(p.get("count", 0))
    tol = float(p.get("tolerance", 1e-6))
    if not 1e-9 <= tol <= 1.0:
        raise RuntimeError("The sewing tolerance must be 1e-9 to 1.")
    coords = read_patches(p.get("path"), count)
    sew = BRepBuilderAPI_Sewing(tol, True, True, False, False)
    for n in range(count):
        mk = BRepBuilderAPI_MakeFace(surface_of(coords, n * 48), 1e-7)
        if not mk.IsDone():
            raise RuntimeError("Patch %d could not be made into a face." % n)
        sew.Add(mk.Face())
    sew.Perform()
    shape = sew.SewedShape()
    free_edges = int(sew.NbFreeEdges())
    multiple = int(sew.NbMultipleEdges())
    shells = []
    exp = TopExp_Explorer(shape, TopAbs_SHELL)
    while exp.More():
        shells.append(TopoDS.Shell(exp.Current()))
        exp.Next()
    closed = False
    volume = None
    result = shape
    if free_edges == 0 and multiple == 0 and len(shells) == 1:
        maker = BRepBuilderAPI_MakeSolid(shells[0])
        if maker.IsDone():
            solid = maker.Solid()
            BRepLib.OrientClosedSolid_s(solid)
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(solid, props)
            if props.Mass() < 0:
                solid.Reverse()
                props = GProp_GProps()
                BRepGProp.VolumeProperties_s(solid, props)
            result = solid
            closed = True
            volume = props.Mass()
    free_bound = free_edges
    try:
        fb = ShapeAnalysis_FreeBounds(result, 1e-6, False, False)
        free_bound = store.count_of(fb.GetClosedWires(), TopAbs_EDGE) + store.count_of(fb.GetOpenWires(), TopAbs_EDGE)
    except Exception:
        pass
    valid = bool(BRepCheck_Analyzer(result).IsValid())
    ident = store.put(result)
    return {
        "id": ident, "summary": fast_summary(result, p.get("bbox"), valid, closed and free_bound == 0), "closed": closed and free_bound == 0, "volume": volume, "faces_made": count,
        "free_edges": free_edges, "multiple_edges": multiple, "free_bound_edges": free_bound, "shells": len(shells), "valid": valid,
    }


METHODS = {"subd_brep": subd_brep}
