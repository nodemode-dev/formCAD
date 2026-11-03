from app.graph.geo import Skip, make_shape, plane_spec, pt, shape_spec, shapes_of, simple_node
from app.graph.sdk import Port
from app.graph.values import PlaneF

CAT = "Solid"
XY = PlaneF()


def positive(value, what):
    v = float(value)
    if not v > 0:
        raise Skip("%s must be positive." % what)
    return v


simple_node(
    "brep.box", "Box", "Box", "Primitive",
    [Port("plane", "plane", default=XY), Port("x", "number", default=1.0), Port("y", "number", default=1.0), Port("z", "number", default=1.0), Port("centred", "boolean", default=False)],
    [Port("box", "brep")],
    lambda plane, x, y, z, centred: {"op": "prim", "kind": "box", "plane": plane_spec(plane), "dx": positive(x, "The x size"), "dy": positive(y, "The y size"), "dz": positive(z, "The z size"), "centered": bool(centred)},
    lambda args, r: make_shape(r, "brep"),
    category=CAT, description="Solid box with its corner at the plane origin, or centred on it.",
)

simple_node(
    "brep.sphere", "Sphere", "Sph", "Primitive",
    [Port("plane", "plane", default=XY, description="Origin is the centre"), Port("radius", "number", default=1.0)],
    [Port("sphere", "brep")],
    lambda plane, radius: {"op": "prim", "kind": "sphere", "plane": plane_spec(plane), "radius": positive(radius, "The radius")},
    lambda args, r: make_shape(r, "brep"),
    category=CAT, description="Solid sphere.",
)

simple_node(
    "brep.cylinder", "Cylinder", "Cyl", "Primitive",
    [Port("plane", "plane", default=XY, description="Origin is the base centre; the cylinder rises along the plane normal"), Port("radius", "number", default=1.0), Port("height", "number", default=1.0)],
    [Port("cylinder", "brep")],
    lambda plane, radius, height: {"op": "prim", "kind": "cylinder", "plane": plane_spec(plane), "radius": positive(radius, "The radius"), "height": positive(height, "The height")},
    lambda args, r: make_shape(r, "brep"),
    category=CAT, description="Solid cylinder standing on a base circle.",
)


def specs(items):
    return [shape_spec(i) for i in items if i is not None]


def boolean_op(mode):
    def build(a, b):
        first, second = specs(a), specs(b)
        if not first:
            raise Skip("The first list is empty.")
        if not second and mode != "union":
            raise Skip("The second list is empty.")
        return {"op": "bool", "mode": mode, "a": first, "b": second}

    return build


for _mode, _name, _nick, _text in (
    ("union", "Boolean Union", "Uni", "Merge solids into one; with only the first list, unite its members."),
    ("difference", "Boolean Difference", "Dif", "Cut every solid of the second list out of the first."),
    ("intersection", "Boolean Intersection", "Int", "Keep only the volume shared by both lists."),
):
    simple_node(
        "brep." + _mode, _name, _nick, "Boolean",
        [Port("a", "brep", access="list"), Port("b", "brep", access="list", optional=True)],
        [Port("result", "brep")],
        boolean_op(_mode),
        lambda args, r: shapes_of(r),
        category=CAT, multi=True, description=_text,
    )


def fillet_op(brep, radius, edges):
    chosen = [int(e) for e in edges if e is not None]
    return {"op": "fillet", "brep": shape_spec(brep), "radius": positive(radius, "The radius"), "edges": chosen if chosen else "all"}


simple_node(
    "brep.fillet", "Fillet Edges", "Fil", "Modify",
    [Port("brep", "brep"), Port("radius", "number", default=1.0), Port("edges", "integer", access="list", optional=True, description="Edge indices; all edges when empty")],
    [Port("brep", "brep")],
    fillet_op,
    lambda args, r: make_shape(r, "brep"),
    category=CAT, description="Round edges of a solid with a constant radius.",
)

simple_node(
    "brep.mass", "Volume And Mass", "Mass", "Analysis",
    [Port("brep", "geometry"), Port("density", "number", default=1.0, description="Mass per cubic millimetre")],
    [Port("volume", "number"), Port("area", "number"), Port("centroid", "point"), Port("mass", "number")],
    lambda brep, density: {"op": "props", "brep": shape_spec(brep), "density": float(density)},
    lambda args, r: (r.get("volume"), r.get("area"), pt(r["centroid"]) if r.get("centroid") else None, r.get("mass")),
    category=CAT, description="Volume, surface area, centre of mass and mass; volume is empty for an open shape.",
)

simple_node(
    "brep.deconstruct", "Deconstruct Solid", "Dec", "Analysis",
    [Port("brep", "geometry")],
    [Port("faces", "surface"), Port("edges", "curve"), Port("vertices", "point")],
    lambda brep: {"op": "decon", "brep": shape_spec(brep)},
    lambda args, r: (shapes_of(r, "faces"), shapes_of(r, "edges"), [pt(q) for q in r["vertices"]]),
    category=CAT, multi=True, description="Faces, edges and corner points of a solid or surface.",
)
