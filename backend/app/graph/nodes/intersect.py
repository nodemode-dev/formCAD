from app.graph.geo import curve_or_shape, plane_spec, pt, shape_spec, shapes_of, simple_node
from app.graph.sdk import Port
from app.graph.values import PlaneF

CAT = "Intersect"
XY = PlaneF()

simple_node(
    "intersect.curve_curve", "Curve And Curve", "CCx", "Intersect",
    [Port("a", "curve"), Port("b", "curve"), Port("tolerance", "number", default=0.001)],
    [Port("points", "point")],
    lambda a, b, tolerance: {"op": "x_cc", "a": curve_or_shape(a), "b": curve_or_shape(b), "tol": float(tolerance)},
    lambda args, r: [pt(q) for q in r["points"]],
    category=CAT, multi=True, description="Points where two curves meet. No crossing gives an empty list.",
)

simple_node(
    "intersect.curve_plane", "Curve And Plane", "CPx", "Intersect",
    [Port("curve", "curve"), Port("plane", "plane", default=XY)],
    [Port("points", "point")],
    lambda curve, plane: {"op": "x_cp", "curve": curve_or_shape(curve), "plane": plane_spec(plane)},
    lambda args, r: [pt(q) for q in r["points"]],
    category=CAT, multi=True, description="Points where a curve crosses a plane.",
)

simple_node(
    "intersect.brep_plane", "Solid Section By Plane", "BPx", "Intersect",
    [Port("brep", "geometry"), Port("plane", "plane", default=XY)],
    [Port("curves", "curve")],
    lambda brep, plane: {"op": "x_bp", "brep": shape_spec(brep), "plane": plane_spec(plane)},
    lambda args, r: shapes_of(r),
    category=CAT, multi=True, description="Curves where a plane cuts through a solid or surface.",
)

simple_node(
    "intersect.brep_brep", "Solid And Solid", "BBx", "Intersect",
    [Port("a", "geometry"), Port("b", "geometry")],
    [Port("curves", "curve")],
    lambda a, b: {"op": "x_bb", "a": shape_spec(a), "b": shape_spec(b)},
    lambda args, r: shapes_of(r),
    category=CAT, multi=True, description="Curves along which two solids or surfaces cross.",
)
