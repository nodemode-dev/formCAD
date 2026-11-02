import os
import struct
import zlib

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.GCPnts import GCPnts_TangentialDeflection
from OCP.GeomAbs import GeomAbs_Circle
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_REVERSED
from OCP.TopExp import TopExp
from OCP.TopLoc import TopLoc_Location
from OCP.TopoDS import TopoDS
from OCP.collections import IndexedDataMap_TopoDS_Shape_List_TopoDS_Shape_TopTools_ShapeMapHasher as AncestorMap

import kernel_store as store

MAGIC = 0x4D424346
VERSION = 1
HEADER = 96
MAX_TRIANGLES = 4_000_000
MAX_EDGE_POINTS = 2_000_000
SNAP_VERTEX = 0
SNAP_EDGE_MID = 1
SNAP_CENTRE = 2


def pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


def run_mesh(shape, linear: float, angular: float) -> None:
    if not (linear > 0 and angular > 0):
        raise RuntimeError("The deflections must be positive.")
    BRepMesh_IncrementalMesh(shape, float(linear), False, float(angular), True)


def edge_polyline(edge, face_of, linear, angular):
    if BRep_Tool.Degenerated_s(edge):
        return []
    face = face_of.get(edge)
    if face is not None:
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            poly = BRep_Tool.PolygonOnTriangulation_s(edge, tri, loc)
            if poly is not None:
                trsf = loc.Transformation()
                nodes = poly.Nodes()
                pts = []
                for i in range(nodes.Lower(), nodes.Upper() + 1):
                    p = tri.Node(nodes.Value(i)).Transformed(trsf)
                    pts.append((p.X(), p.Y(), p.Z()))
                if len(pts) >= 2:
                    return pts
    curve = BRepAdaptor_Curve(edge)
    disc = GCPnts_TangentialDeflection(curve, float(angular), float(linear))
    pts = []
    for i in range(1, disc.NbPoints() + 1):
        p = disc.Value(i)
        pts.append((p.X(), p.Y(), p.Z()))
    return pts


def build(ident: str, linear: float, angular: float, out_path: str) -> dict:
    ent = store.entry(ident)
    shape = ent.shape
    run_mesh(shape, linear, angular)
    ent.meshed = (linear, angular)
    maps = store.maps_of(ident)
    faces, edges, verts = maps["faces"], maps["edges"], maps["vertices"]

    positions = []
    normals = []
    indices = []
    tri_face = []
    face_rows = []
    base = 0
    tri_total = 0
    face_of = {}
    for fi in range(1, faces.Extent() + 1):
        face = TopoDS.Face(faces.FindKey(fi))
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        try:
            kind = int(BRepAdaptor_Surface(face).GetType())
        except Exception:
            kind = 10
        first = tri_total
        if tri is None or tri.NbTriangles() == 0:
            face_rows.append((fi - 1, first, 0, kind))
            continue
        trsf = loc.Transformation()
        reversed_face = face.Orientation() == TopAbs_REVERSED
        if not tri.HasNormals():
            tri.ComputeNormals()
        has_normals = tri.HasNormals()
        n_nodes = tri.NbNodes()
        for i in range(1, n_nodes + 1):
            p = tri.Node(i).Transformed(trsf)
            positions.extend((p.X(), p.Y(), p.Z()))
            if has_normals:
                d = tri.Normal(i).Transformed(trsf)
                nx, ny, nz = d.X(), d.Y(), d.Z()
                if reversed_face:
                    nx, ny, nz = -nx, -ny, -nz
            else:
                nx = ny = nz = 0.0
            normals.extend((nx, ny, nz))
        n_tri = tri.NbTriangles()
        for i in range(1, n_tri + 1):
            a, b, c = tri.Triangle(i).Get()
            if reversed_face:
                b, c = c, b
            indices.extend((base + a - 1, base + b - 1, base + c - 1))
            tri_face.append(fi - 1)
        base += n_nodes
        tri_total += n_tri
        face_rows.append((fi - 1, first, n_tri, kind))
        if tri_total > MAX_TRIANGLES:
            raise RuntimeError("The tessellation is too fine: more than %d triangles. Raise the deflection." % MAX_TRIANGLES)

    anc = AncestorMap()
    TopExp.MapShapesAndAncestors_s(shape, TopAbs_EDGE, TopAbs_FACE, anc)
    for ei in range(1, anc.Extent() + 1):
        lst = anc.FindFromIndex(ei)
        if lst.Extent() > 0:
            face_of[anc.FindKey(ei)] = TopoDS.Face(lst.First())

    edge_pos = []
    edge_rows = []
    snaps = []
    point_total = 0
    for ei in range(1, edges.Extent() + 1):
        edge = TopoDS.Edge(edges.FindKey(ei))
        try:
            curve = BRepAdaptor_Curve(edge)
            ckind = int(curve.GetType())
        except Exception:
            curve = None
            ckind = 8
        pts = edge_polyline(edge, face_of, linear, angular)
        first = point_total
        for p in pts:
            edge_pos.extend(p)
        point_total += len(pts)
        edge_rows.append((ei - 1, first, len(pts), ckind))
        if point_total > MAX_EDGE_POINTS:
            raise RuntimeError("The edge polylines are too fine. Raise the deflection.")
        if curve is None or BRep_Tool.Degenerated_s(edge):
            continue
        try:
            mid = curve.Value(0.5 * (curve.FirstParameter() + curve.LastParameter()))
            snaps.append((mid.X(), mid.Y(), mid.Z(), SNAP_EDGE_MID, ei - 1, 0.0, 0.0, 0.0))
            if curve.GetType() == GeomAbs_Circle:
                circ = curve.Circle()
                c = circ.Location()
                n = circ.Axis().Direction()
                snaps.append((c.X(), c.Y(), c.Z(), SNAP_CENTRE, ei - 1, n.X(), n.Y(), n.Z()))
        except Exception:
            pass
    for vi in range(1, verts.Extent() + 1):
        p = BRep_Tool.Pnt_s(TopoDS.Vertex(verts.FindKey(vi)))
        snaps.append((p.X(), p.Y(), p.Z(), SNAP_VERTEX, vi - 1, 0.0, 0.0, 0.0))

    nv = len(positions) // 3
    body = bytearray()
    offsets = {}

    def section(name, data):
        pad4(body)
        offsets[name] = HEADER + len(body)
        body.extend(data)

    section("positions", struct.pack("<%df" % len(positions), *positions))
    section("normals", struct.pack("<%df" % len(normals), *normals))
    section("indices", struct.pack("<%dI" % len(indices), *indices))
    section("tri_face", struct.pack("<%dI" % len(tri_face), *tri_face))
    section("face_table", b"".join(struct.pack("<4I", *r) for r in face_rows))
    section("edge_table", b"".join(struct.pack("<4I", *r) for r in edge_rows))
    section("edge_positions", struct.pack("<%df" % len(edge_pos), *edge_pos))
    section("snaps", b"".join(struct.pack("<3f2I3f", *s) for s in snaps))
    pad4(body)

    if nv:
        xs, ys, zs = positions[0::3], positions[1::3], positions[2::3]
        box = [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    else:
        box = [0.0] * 6
    total = HEADER + len(body)
    crc = zlib.crc32(bytes(body)) & 0xFFFFFFFF
    head = struct.pack(
        "<16I6f",
        MAGIC, VERSION, nv, tri_total, len(face_rows), len(edge_rows), point_total, len(snaps),
        offsets["positions"], offsets["normals"], offsets["indices"], offsets["tri_face"],
        offsets["face_table"], offsets["edge_table"], offsets["edge_positions"], offsets["snaps"],
        *box,
    )
    head = head[:64] + struct.pack("<2I", total, crc) + head[64:]
    if len(head) != HEADER:
        raise RuntimeError("Internal header size error.")
    tmp = out_path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(head)
        fh.write(body)
    os.replace(tmp, out_path)
    return {"path": out_path, "bytes": total, "vertices": nv, "triangles": tri_total, "faces": len(face_rows), "edges": len(edge_rows), "edge_points": point_total, "snaps": len(snaps), "bbox": box, "linear": linear, "angular": angular}
