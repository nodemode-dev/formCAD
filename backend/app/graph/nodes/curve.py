import math

from app.graph.geo import Skip, curve_or_shape, curve_spec, guid, make_shape, pt, plane_spec, plist, shapes_of, simple_node, vec
from app.graph.sdk import NodeType, NodeWarning, Port, register
from app.graph.values import Arc3, Circle3, Line3, PlaneF, Point3, Polyline3, ValueError3

CAT = "Curve"
XY = PlaneF()


def local(fn):
    def run(ctx, *args):
        try:
            return fn(*args)
        except ValueError3 as err:
            raise NodeWarning(str(err))

    return run


register(NodeType(
    id="curve.line", guid=guid("curve.line"), name="Line", nick="Ln", category=CAT, group="Primitive",
    inputs=[Port("a", "point", description="Start point"), Port("b", "point", description="End point")],
    outputs=[Port("line", "curve")],
    solve=local(lambda a, b: Line3(a, b)),
    description="Straight segment between two points.",
))

register(NodeType(
    id="curve.line_vector", guid=guid("curve.line_vector"), name="Line From Vector", nick="LnV", category=CAT, group="Primitive",
    inputs=[Port("start", "point"), Port("direction", "vector", description="Direction and length")],
    outputs=[Port("line", "curve")],
    solve=local(lambda start, direction: Line3(start, start + direction)),
    description="Segment that starts at a point and runs along a vector.",
))

register(NodeType(
    id="curve.polyline", guid=guid("curve.polyline"), name="Polyline", nick="Poly", category=CAT, group="Primitive",
    inputs=[Port("points", "point", access="list"), Port("closed", "boolean", default=False)],
    outputs=[Port("polyline", "curve")],
    solve=local(lambda points, closed: Polyline3(tuple(points), bool(closed))),
    description="Straight segments through a list of points, optionally closed.",
))

register(NodeType(
    id="curve.circle", guid=guid("curve.circle"), name="Circle", nick="Cir", category=CAT, group="Primitive",
    inputs=[Port("plane", "plane", default=XY), Port("radius", "number", default=1.0)],
    outputs=[Port("circle", "curve")],
    solve=local(lambda plane, radius: Circle3(plane, float(radius))),
    description="Circle centred on the plane origin, lying in the plane.",
))

register(NodeType(
    id="curve.arc_points", guid=guid("curve.arc_points"), name="Arc Through Points", nick="Arc3", category=CAT, group="Primitive",
    inputs=[Port("a", "point", description="Start"), Port("b", "point", description="Point on the arc"), Port("c", "point", description="End")],
    outputs=[Port("arc", "curve")],
    solve=local(lambda a, b, c: Arc3.from_3_points(a, b, c)),
    description="Arc that starts at the first point, passes the second and ends at the third.",
))

register(NodeType(
    id="curve.arc_centre", guid=guid("curve.arc_centre"), name="Arc From Angles", nick="ArcA", category=CAT, group="Primitive",
    inputs=[Port("plane", "plane", default=XY), Port("radius", "number", default=1.0), Port("start", "number", default=0.0, description="Radians"), Port("end", "number", default=math.pi / 2, description="Radians")],
    outputs=[Port("arc", "curve")],
    solve=local(lambda plane, radius, start, end: Arc3(plane, float(radius), float(start), float(end))),
    description="Arc about the plane origin between two angles in radians.",
))


def rectangle(plane, width, height, centred):
    w, h = float(width), float(height)
    if w <= 0 or h <= 0:
        raise ValueError3("a rectangle needs a positive width and height")
    x0, y0 = (-w / 2, -h / 2) if centred else (0.0, 0.0)
    corners = (plane.point_at(x0, y0), plane.point_at(x0 + w, y0), plane.point_at(x0 + w, y0 + h), plane.point_at(x0, y0 + h))
    return Polyline3(corners, True)


register(NodeType(
    id="curve.rectangle", guid=guid("curve.rectangle"), name="Rectangle", nick="Rec", category=CAT, group="Primitive",
    inputs=[Port("plane", "plane", default=XY), Port("width", "number", default=1.0), Port("height", "number", default=1.0), Port("centred", "boolean", default=False)],
    outputs=[Port("rectangle", "curve")],
    solve=local(rectangle),
    description="Closed rectangle in a plane, from its origin corner or centred on it.",
))


def pts_of(points):
    got = [p for p in points if p is not None]
    if len(got) < 2:
        raise Skip("At least two points are needed.")
    return [plist(p) for p in got]


simple_node(
    "curve.interpolate", "Interpolate Curve", "Int", "Spline",
    [Port("points", "point", access="list"), Port("degree", "integer", default=3, min=1, max=3, description="1 for a polyline, 3 for a smooth curve"), Port("closed", "boolean", default=False)],
    [Port("curve", "curve")],
    lambda points, degree, closed: {"op": "interp", "pts": pts_of(points), "degree": int(degree), "closed": bool(closed)},
    lambda args, r: make_shape(r, "curve"),
    category=CAT, description="Smooth curve that passes through every point.",
)

simple_node(
    "curve.control_points", "Curve From Control Points", "CP", "Spline",
    [Port("points", "point", access="list"), Port("degree", "integer", default=3, min=1, max=11), Port("closed", "boolean", default=False), Port("weights", "number", access="list", optional=True)],
    [Port("curve", "curve")],
    lambda points, degree, closed, weights: {"op": "nurbs", "pts": pts_of(points), "degree": int(degree), "closed": bool(closed), "weights": [float(w) for w in weights if w is not None]},
    lambda args, r: make_shape(r, "curve"),
    category=CAT, description="Curve shaped by control points of a chosen degree, with optional weights.",
)


def divided(r):
    return ([pt(q) for q in r["points"]], [vec(q) for q in r["tangents"]], [float(t) for t in r["t"]])


simple_node(
    "curve.divide_count", "Divide Curve By Count", "Div", "Division",
    [Port("curve", "curve"), Port("count", "integer", default=10, min=1)],
    [Port("points", "point"), Port("tangents", "vector"), Port("t", "number", description="Fraction of the length, 0 to 1")],
    lambda curve, count: {"op": "divide", "curve": curve_or_shape(curve), "count": int(count)},
    lambda args, r: divided(r),
    category=CAT, multi=True, description="Points at equal distances along a curve, with tangents.",
)

simple_node(
    "curve.divide_length", "Divide Curve By Length", "DivL", "Division",
    [Port("curve", "curve"), Port("length", "number", default=1.0)],
    [Port("points", "point"), Port("tangents", "vector"), Port("t", "number", description="Fraction of the length, 0 to 1")],
    lambda curve, length: {"op": "divide", "curve": curve_or_shape(curve), "length": float(length)},
    lambda args, r: divided(r),
    category=CAT, multi=True, description="Points one fixed length apart, starting at the curve start.",
)

simple_node(
    "curve.evaluate", "Evaluate Curve", "Eval", "Analysis",
    [Port("curve", "curve"), Port("t", "number", default=0.5, description="0 to 1 along the curve"), Port("by_length", "boolean", default=False, description="Measure t along the length instead of the parameter")],
    [Port("point", "point"), Port("tangent", "vector"), Port("curvature", "number")],
    lambda curve, t, by_length: {"op": "eval", "curve": curve_or_shape(curve), "t": float(t), "by_length": bool(by_length)},
    lambda args, r: (pt(r["point"]), vec(r["tangent"]), float(r["curvature"])),
    category=CAT, description="Point, unit tangent and curvature at a position along a curve.",
)

simple_node(
    "curve.length", "Curve Length", "Len", "Analysis",
    [Port("curve", "curve")],
    [Port("length", "number")],
    lambda curve: {"op": "length", "curve": curve_or_shape(curve)},
    lambda args, r: float(r["length"]),
    category=CAT, description="Total length of a curve.",
)

simple_node(
    "curve.closest_point", "Curve Closest Point", "CP", "Analysis",
    [Port("curve", "curve"), Port("point", "point")],
    [Port("point", "point"), Port("t", "number", description="Fraction of the length, 0 to 1"), Port("distance", "number")],
    lambda curve, point: {"op": "closest", "curve": curve_or_shape(curve), "point": plist(point)},
    lambda args, r: (pt(r["point"]), float(r["t"]), float(r["distance"])),
    category=CAT, description="Nearest point on a curve to a given point.",
)

simple_node(
    "curve.offset", "Offset Curve", "Off", "Modify",
    [Port("curve", "curve"), Port("distance", "number", default=1.0), Port("corner", "text", default="sharp", choices=("sharp", "round"))],
    [Port("curves", "curve")],
    lambda curve, distance, corner: {"op": "offset", "curve": curve_or_shape(curve), "distance": float(distance), "corner": str(corner)},
    lambda args, r: shapes_of(r),
    category=CAT, multi=True, description="Parallel copy of a planar curve at a distance; a negative distance goes the other way.",
)

simple_node(
    "curve.extend", "Extend Curve", "Ext", "Modify",
    [Port("curve", "curve"), Port("length", "number", default=1.0), Port("end", "text", default="both", choices=("both", "start", "end")), Port("style", "text", default="line", choices=("line", "arc", "smooth"))],
    [Port("curve", "curve")],
    lambda curve, length, end, style: {"op": "extend", "curve": curve_or_shape(curve), "length": float(length), "end": str(end), "style": str(style)},
    lambda args, r: make_shape(r, "curve"),
    category=CAT, description="Lengthen a curve at one or both ends.",
)


def join_op(curves, tol):
    specs = [curve_or_shape(c) for c in curves if c is not None]
    if not specs:
        raise Skip("No curves to join.")
    return {"op": "join", "curves": specs, "tol": float(tol)}


simple_node(
    "curve.join", "Join Curves", "Join", "Modify",
    [Port("curves", "curve", access="list"), Port("tolerance", "number", default=0.001)],
    [Port("curves", "curve")],
    join_op,
    lambda args, r: shapes_of(r),
    category=CAT, multi=True, description="Chain curves that meet end to end into longer curves.",
)

simple_node(
    "curve.explode", "Explode Curve", "Exp", "Modify",
    [Port("curve", "curve")],
    [Port("segments", "curve")],
    lambda curve: {"op": "explode", "curve": curve_or_shape(curve)},
    lambda args, r: shapes_of(r),
    category=CAT, multi=True, description="Split a curve into its segments.",
)

simple_node(
    "curve.area_centroid", "Curve Area And Centroid", "Area", "Analysis",
    [Port("curve", "curve")],
    [Port("area", "number"), Port("centroid", "point")],
    lambda curve: {"op": "area", "curve": curve_or_shape(curve)},
    lambda args, r: (float(r["area"]), pt(r["centroid"])),
    category=CAT, description="Area and centre of a closed planar curve.",
)
