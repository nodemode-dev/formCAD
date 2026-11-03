import functools

from app.graph.nodes.common import NodeWarning, P, add
from app.graph.values import Colour, PlaneF, Point3, Transform, ValueError3, Vector3

CAT = "Vector"
NUM = "number"
ORIGIN = Point3(0.0, 0.0, 0.0)
UNIT_Z = Vector3(0.0, 0.0, 1.0)


def safe(fn):
    @functools.wraps(fn)
    def wrapped(ctx, *args):
        try:
            return fn(ctx, *args)
        except ValueError3 as err:
            raise NodeWarning(str(err), "DEGENERATE")

    return wrapped


def xyz():
    return [P(n, NUM, "item", 0.0, n.upper(), "%s coordinate." % n.upper()) for n in ("x", "y", "z")]


add("vector.point", "e2383cad-bddc-4d1d-92f1-8186e7e7700b", "Construct Point", "Pt", CAT, "Point", xyz(), [P("point", "point", "item", None, "P", "The point.")], solve=lambda ctx, x, y, z: Point3(x, y, z), description="A point from its three coordinates.")
add("vector.point_parts", "04d57c1e-6d10-4c73-8151-67732790b2e3", "Deconstruct Point", "DPt", CAT, "Point", [P("point", "point", "item", None, "P", "The point.")], [P(n, NUM, "item", None, n.upper(), "%s coordinate." % n.upper()) for n in ("x", "y", "z")], solve=lambda ctx, p: (p.x, p.y, p.z), description="The three coordinates of a point.")
add("vector.vector", "568e85df-ea25-47b9-99ea-bb323504f2d4", "Construct Vector", "Vec", CAT, "Vector", xyz(), [P("vector", "vector", "item", None, "V", "The vector.")], solve=lambda ctx, x, y, z: Vector3(x, y, z), description="A vector from its three components.")
add("vector.vector_parts", "d259323c-998b-45a0-b77e-aadc2fa038fe", "Deconstruct Vector", "DVec", CAT, "Vector", [P("vector", "vector", "item", None, "V", "The vector.")], [P("x", NUM, "item", None, "X", "X component."), P("y", NUM, "item", None, "Y", "Y component."), P("z", NUM, "item", None, "Z", "Z component."), P("length", NUM, "item", None, "L", "Length.")], solve=lambda ctx, v: (v.x, v.y, v.z, v.length), description="The components and the length of a vector.")
add("vector.between", "69887c54-4bb1-4815-b02e-34de62414116", "Vector Between", "Vec2Pt", CAT, "Vector", [P("from", "point", "item", None, "A", "Start point."), P("to", "point", "item", None, "B", "End point.")], [P("vector", "vector", "item", None, "V", "From the start to the end."), P("length", NUM, "item", None, "L", "Its length.")], solve=lambda ctx, a, b: ((b - a), (b - a).length), description="The vector from one point to another.")
add("vector.add", "f18edc0e-ad92-4663-9b30-71d8179bc9fa", "Add Vectors", "V+V", CAT, "Vector", [P("a", "vector", "item", None, "A", "First vector."), P("b", "vector", "item", None, "B", "Second vector.")], [P("vector", "vector", "item", None, "V", "The sum.")], solve=lambda ctx, a, b: a + b, description="Sum of two vectors.")
add("vector.subtract", "5b155790-3ba7-4691-8a9b-b35611e98ec5", "Subtract Vectors", "V-V", CAT, "Vector", [P("a", "vector", "item", None, "A", "First vector."), P("b", "vector", "item", None, "B", "Second vector.")], [P("vector", "vector", "item", None, "V", "A minus B.")], solve=lambda ctx, a, b: a - b, description="Difference of two vectors.")
add("vector.multiply", "55152364-a247-46b5-b50b-eafa9ef57acb", "Scale Vector", "V*k", CAT, "Vector", [P("vector", "vector", "item", None, "V", "The vector."), P("factor", NUM, "item", 1.0, "K", "The factor.")], [P("vector", "vector", "item", None, "R", "The scaled vector.")], solve=lambda ctx, v, k: v * k, description="Multiplies a vector by a number.")


@safe
def amplitude(ctx, v, length):
    return v.unit() * length


add("vector.amplitude", "89d03b2a-55c2-4198-b957-069552f14276", "Set Length", "Amp", CAT, "Vector", [P("vector", "vector", "item", None, "V", "The vector."), P("length", NUM, "item", 1.0, "L", "The new length.")], [P("vector", "vector", "item", None, "R", "Same direction, new length.")], solve=amplitude, description="Gives a vector a chosen length, keeping its direction.")
add("vector.negate", "ad66383f-1776-4dc5-a479-03083ee46205", "Reverse Vector", "Rev", CAT, "Vector", [P("vector", "vector", "item", None, "V", "The vector.")], [P("vector", "vector", "item", None, "R", "Pointing the other way.")], solve=lambda ctx, v: -v, description="Flips a vector.")
add("vector.unit", "ec6fc5bf-dbe4-43ae-9966-75e97da24fca", "Unit Vector", "Unit", CAT, "Vector", [P("vector", "vector", "item", None, "V", "The vector.")], [P("vector", "vector", "item", None, "R", "Length one, same direction.")], solve=safe(lambda ctx, v: v.unit()), description="Scales a vector to length one; a zero vector gives a warning.")
add("vector.length", "a2aa554c-c906-48ed-9c2b-d55dd859b7a1", "Vector Length", "Len", CAT, "Vector", [P("vector", "vector", "item", None, "V", "The vector.")], [P("length", NUM, "item", None, "L", "Its length.")], solve=lambda ctx, v: v.length, description="The length of a vector.")
add("vector.dot", "91ad3ced-9c7f-44cc-a819-11fad7c31acd", "Dot Product", "Dot", CAT, "Vector", [P("a", "vector", "item", None, "A", "First vector."), P("b", "vector", "item", None, "B", "Second vector.")], [P("dot", NUM, "item", None, "D", "The dot product.")], solve=lambda ctx, a, b: a.dot(b), description="Dot product of two vectors.")
add("vector.cross", "c5658135-b7f5-458e-a649-d1f57ab0d2b3", "Cross Product", "Cross", CAT, "Vector", [P("a", "vector", "item", None, "A", "First vector."), P("b", "vector", "item", None, "B", "Second vector.")], [P("vector", "vector", "item", None, "V", "Perpendicular to both, by the right hand rule."), P("length", NUM, "item", None, "L", "Its length.")], solve=lambda ctx, a, b: (a.cross(b), a.cross(b).length), description="Cross product of two vectors.")
add("vector.angle", "c036ee48-09e5-479f-9da2-440d3a62c552", "Vector Angle", "Angle", CAT, "Vector", [P("a", "vector", "item", None, "A", "First vector."), P("b", "vector", "item", None, "B", "Second vector.")], [P("angle", NUM, "item", None, "R", "The angle between them in radians, 0 to pi.")], solve=safe(lambda ctx, a, b: a.angle(b)), description="The smaller angle between two vectors; a zero vector gives a warning.")
add("vector.distance", "0e075120-c862-445a-afd7-854229a32ac7", "Distance", "Dist", CAT, "Point", [P("a", "point", "item", None, "A", "First point."), P("b", "point", "item", None, "B", "Second point.")], [P("distance", NUM, "item", None, "D", "The distance.")], solve=lambda ctx, a, b: a.distance(b), description="Distance between two points.")
add("vector.lerp", "75ee3443-55a5-4d13-b799-cd5e6569aa32", "Point Between", "Lerp", CAT, "Point", [P("a", "point", "item", None, "A", "Point at t = 0."), P("b", "point", "item", None, "B", "Point at t = 1."), P("t", NUM, "item", 0.5, "T", "Blend factor.")], [P("point", "point", "item", None, "P", "The point on the line through A and B.")], solve=lambda ctx, a, b, t: a + (b - a) * t, description="A point on the line through two points; 0.5 is the midpoint.")
add("vector.offset_point", "fc1173b4-824b-4f6e-8cb0-e9e52bde8cca", "Offset Point", "Off", CAT, "Point", [P("point", "point", "item", None, "P", "The point."), P("vector", "vector", "item", None, "V", "The offset.")], [P("point", "point", "item", None, "R", "The point moved by the vector.")], solve=lambda ctx, p, v: p + v, description="Moves a point by a vector.")


@safe
def plane_axes(ctx, o, x, y):
    return PlaneF.from_origin_axes(o or ORIGIN, x or Vector3(1.0, 0.0, 0.0), y or Vector3(0.0, 1.0, 0.0))


add("vector.plane", "0f0c0ea6-0d5f-4f80-8abf-c821447e5327", "Plane From Axes", "Pln", CAT, "Plane", [P("origin", "point", "item", None, "O", "Origin (the world origin when empty).", True), P("x", "vector", "item", None, "X", "Direction of the plane X axis (world X when empty).", True), P("y", "vector", "item", None, "Y", "A direction in the plane, made perpendicular to X (world Y when empty).", True)], [P("plane", "plane", "item", None, "P", "The plane.")], solve=plane_axes, description="A plane from an origin and two axis directions.")


@safe
def plane_normal(ctx, o, n, xh):
    return PlaneF.from_origin_normal(o or ORIGIN, n or UNIT_Z, xh)


add("vector.plane_normal", "cf15b646-fe8b-4fe2-9522-861ee3527255", "Plane From Normal", "PlnN", CAT, "Plane", [P("origin", "point", "item", None, "O", "Origin (the world origin when empty).", True), P("normal", "vector", "item", None, "N", "Direction of the plane Z axis (world Z when empty).", True), P("x", "vector", "item", None, "X", "A hint for the X axis, optional.", True)], [P("plane", "plane", "item", None, "P", "The plane.")], solve=plane_normal, description="A plane from an origin and a normal direction.")
add("vector.plane_xy", "4a5a27ee-69f4-449b-b843-cef7170047fb", "Plane XY", "XY", CAT, "Plane", [P("origin", "point", "item", None, "O", "Origin (the world origin when empty).", True)], [P("plane", "plane", "item", None, "P", "A plane parallel to the world XY plane.")], solve=lambda ctx, o: PlaneF.world_xy(o), description="The world XY plane moved to an origin.")
add("vector.plane_xz", "3bd4bc70-bb16-4eba-bcfa-628f8fa2ed7a", "Plane XZ", "XZ", CAT, "Plane", [P("origin", "point", "item", None, "O", "Origin (the world origin when empty).", True)], [P("plane", "plane", "item", None, "P", "A plane parallel to the world XZ plane, X to the right and Z up.")], solve=lambda ctx, o: PlaneF.world_xz(o), description="The world XZ plane moved to an origin.")
add("vector.plane_yz", "909582d5-cd41-4ad9-ae32-da7fe5adb1d8", "Plane YZ", "YZ", CAT, "Plane", [P("origin", "point", "item", None, "O", "Origin (the world origin when empty).", True)], [P("plane", "plane", "item", None, "P", "A plane parallel to the world YZ plane, Y to the right and Z up.")], solve=lambda ctx, o: PlaneF.world_yz(o), description="The world YZ plane moved to an origin.")
add("vector.plane_3pt", "79f5024a-7b90-4356-ac09-dcd2e4608996", "Plane From Points", "Pln3", CAT, "Plane", [P("origin", "point", "item", None, "O", "Origin."), P("x", "point", "item", None, "X", "A point on the X axis."), P("y", "point", "item", None, "Y", "A point on the side of Y.")], [P("plane", "plane", "item", None, "P", "The plane through the three points.")], solve=safe(lambda ctx, o, x, y: PlaneF.from_3_points(o, x, y)), description="A plane through an origin, a point on its X axis and a point on its Y side.")
add("vector.plane_parts", "7086cf73-c76b-450d-9f18-73f24ab87bbf", "Deconstruct Plane", "DPln", CAT, "Plane", [P("plane", "plane", "item", None, "P", "The plane.")], [P("origin", "point", "item", None, "O", "Origin."), P("x", "vector", "item", None, "X", "X axis."), P("y", "vector", "item", None, "Y", "Y axis."), P("z", "vector", "item", None, "Z", "Normal.")], solve=lambda ctx, p: (p.origin, p.x, p.y, p.z), description="The origin and axes of a plane.")
add("vector.plane_offset", "b448d8e5-1969-46e7-b841-7c337dbf7731", "Offset Plane", "PlnOff", CAT, "Plane", [P("plane", "plane", "item", None, "P", "The plane."), P("distance", NUM, "item", 0.0, "D", "Distance along the normal.")], [P("plane", "plane", "item", None, "R", "The moved plane.")], solve=lambda ctx, p, d: PlaneF(p.origin + p.z * d, p.x, p.y, p.z), description="Moves a plane along its own normal.")

XF = "Transform"
XG = "Values"
add("xform.translation", "650d3c33-f38b-44fa-ae3a-19f4b6b7f930", "Translation", "Move", XF, XG, [P("vector", "vector", "item", None, "V", "The movement.")], [P("transform", "transform", "item", None, "X", "The transform value.")], solve=lambda ctx, v: Transform.translation(v), description="A transform value that moves by a vector.")


@safe
def rotation(ctx, angle, axis, centre):
    return Transform.rotation(angle, axis or UNIT_Z, centre or ORIGIN)


add("xform.rotation", "5d1f6714-30fa-4976-87fe-1d4c4a1d6834", "Rotation", "Rot", XF, XG, [P("angle", NUM, "item", 0.0, "A", "Angle in radians, counter clockwise seen from the tip of the axis."), P("axis", "vector", "item", None, "V", "Axis direction (world Z when empty).", True), P("centre", "point", "item", None, "C", "A point on the axis (the world origin when empty).", True)], [P("transform", "transform", "item", None, "X", "The transform value.")], solve=rotation, description="A transform value that turns around an axis.")


def scaling(ctx, k, ky, kz, centre):
    return Transform.scaling(k, ky, kz, centre or ORIGIN)


add("xform.scale", "15892e90-c45a-4c6c-969a-d0410a504e9f", "Scale", "Scale", XF, XG, [P("factor", NUM, "item", 1.0, "K", "Factor along X, and along Y and Z when those are empty."), P("factor_y", NUM, "item", None, "Y", "Factor along Y.", True), P("factor_z", NUM, "item", None, "Z", "Factor along Z.", True), P("centre", "point", "item", None, "C", "Fixed point (the world origin when empty).", True)], [P("transform", "transform", "item", None, "X", "The transform value.")], solve=scaling, description="A transform value that scales about a point, evenly or per axis.")
add("xform.mirror", "5ed9236f-413b-4971-80fe-2d5425de2432", "Mirror", "Mirror", XF, XG, [P("plane", "plane", "item", None, "P", "The mirror plane.")], [P("transform", "transform", "item", None, "X", "The transform value.")], solve=safe(lambda ctx, p: Transform.mirror(p)), description="A transform value that reflects across a plane.")
add("xform.compound", "a5ede24a-b0a1-40c8-a661-f7dc1ee422e1", "Compound Transform", "Comp", XF, XG, [P("first", "transform", "item", None, "A", "Applied first."), P("then", "transform", "item", None, "B", "Applied second.")], [P("transform", "transform", "item", None, "X", "A then B as one transform.")], solve=lambda ctx, a, b: b.compose(a), description="Joins two transforms into one that does the first and then the second.")
add("xform.inverse", "25c840d0-fb66-448a-80d0-31f0ad8b8891", "Inverse Transform", "Inv", XF, XG, [P("transform", "transform", "item", None, "X", "The transform.")], [P("transform", "transform", "item", None, "R", "The transform that undoes it.")], solve=safe(lambda ctx, t: t.inverse()), description="The transform that undoes another; a collapsing transform gives a warning.")
add("xform.plane_to_plane", "05688cbb-2660-49f0-bca6-48b3b77fe6ca", "Plane To Plane", "Orient", XF, XG, [P("from", "plane", "item", None, "A", "The source plane."), P("to", "plane", "item", None, "B", "The target plane.")], [P("transform", "transform", "item", None, "X", "Moves the source frame onto the target frame.")], solve=safe(lambda ctx, a, b: Transform.plane_to_plane(a, b)), description="A transform value that takes one plane to another.")

add("colour.rgb", "9600c3c3-75d2-476b-965c-a56884ae7513", "Colour From RGB", "RGB", "Colour", "Construct", [P("r", "integer", "item", 0, "R", "Red, 0 to 255."), P("g", "integer", "item", 0, "G", "Green, 0 to 255."), P("b", "integer", "item", 0, "B", "Blue, 0 to 255."), P("a", "integer", "item", 255, "A", "Opacity, 0 to 255.")], [P("colour", "colour", "item", None, "C", "The colour.")], solve=lambda ctx, r, g, b, a: Colour(r, g, b, a), description="A colour from its red, green, blue and opacity values.")
add("colour.parts", "71223348-3db3-4930-afde-69b45dead545", "Deconstruct Colour", "DCol", "Colour", "Construct", [P("colour", "colour", "item", None, "C", "The colour.")], [P("r", "integer", "item", None, "R", "Red."), P("g", "integer", "item", None, "G", "Green."), P("b", "integer", "item", None, "B", "Blue."), P("a", "integer", "item", None, "A", "Opacity.")], solve=lambda ctx, c: (c.r, c.g, c.b, c.a), description="The red, green, blue and opacity values of a colour.")
