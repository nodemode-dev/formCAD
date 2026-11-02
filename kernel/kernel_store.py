import itertools
import os
import threading

from OCP.BRep import BRep_Tool
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SHELL, TopAbs_SOLID, TopAbs_VERTEX
from OCP.TopExp import TopExp
from OCP.collections import IndexedMap_TopoDS_Shape_TopTools_ShapeMapHasher as ShapeMap

MAX_SHAPES = 4096
MAX_FILE = 512 * 1024 * 1024

SHAPES: dict = {}
_ids = itertools.count(1)
LOCK = threading.RLock()


class Entry:
    __slots__ = ("shape", "maps", "meshed")

    def __init__(self, shape):
        self.shape = shape
        self.maps = None
        self.meshed = None


def put(shape) -> str:
    with LOCK:
        if len(SHAPES) >= MAX_SHAPES:
            raise RuntimeError("The worker holds too many shapes; free some first.")
        ident = "s%d" % next(_ids)
        SHAPES[ident] = Entry(shape)
        return ident


def entry(ident) -> Entry:
    got = SHAPES.get(str(ident))
    if got is None:
        raise RuntimeError("No shape %s in the worker." % ident)
    return got


def shape_of(ident):
    return entry(ident).shape


def free(ids) -> int:
    count = 0
    with LOCK:
        for ident in ids:
            if SHAPES.pop(str(ident), None) is not None:
                count += 1
    return count


def build_maps(shape) -> dict:
    out = {}
    for name, kind in (("faces", TopAbs_FACE), ("edges", TopAbs_EDGE), ("vertices", TopAbs_VERTEX)):
        m = ShapeMap()
        TopExp.MapShapes_s(shape, kind, m)
        out[name] = m
    return out


def maps_of(ident) -> dict:
    e = entry(ident)
    if e.maps is None:
        e.maps = build_maps(e.shape)
    return e.maps


def count_of(shape, kind) -> int:
    m = ShapeMap()
    TopExp.MapShapes_s(shape, kind, m)
    return m.Extent()


def bbox_of(shape, use_triangulation=False):
    from OCP.BRepBndLib import BRepBndLib as B

    box = Bnd_Box()
    B.AddOptimal_s(shape, box, use_triangulation, False)
    if box.IsVoid():
        return None
    return [box.GetXMin(), box.GetYMin(), box.GetZMin(), box.GetXMax(), box.GetYMax(), box.GetZMax()]


def summarize(shape) -> dict:
    solids = count_of(shape, TopAbs_SOLID)
    shells = count_of(shape, TopAbs_SHELL)
    faces = count_of(shape, TopAbs_FACE)
    edges = count_of(shape, TopAbs_EDGE)
    verts = count_of(shape, TopAbs_VERTEX)
    try:
        valid = bool(BRepCheck_Analyzer(shape).IsValid())
    except Exception:
        valid = False
    closed = False
    try:
        from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds

        free = ShapeAnalysis_FreeBounds(shape, 1e-6, False, False)
        closed = solids > 0 and count_of(free.GetClosedWires(), TopAbs_EDGE) == 0 and count_of(free.GetOpenWires(), TopAbs_EDGE) == 0
    except Exception:
        closed = False
    return {"solids": solids, "shells": shells, "faces": faces, "edges": edges, "vertices": verts, "valid": valid, "closed": closed, "bbox": bbox_of(shape)}


def absolute_path(raw, suffixes=None, exists=False) -> str:
    path = str(raw or "")
    if not path or not os.path.isabs(path):
        raise RuntimeError("The worker needs an absolute file path.")
    if suffixes and os.path.splitext(path)[1].lower() not in suffixes:
        raise RuntimeError("The file name must end in %s." % ", ".join(suffixes))
    if exists:
        if not os.path.isfile(path):
            raise RuntimeError("The file does not exist.")
        if os.path.getsize(path) > MAX_FILE:
            raise RuntimeError("The file is larger than the 512 MB limit.")
    return path
