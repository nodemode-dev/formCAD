from app.graph.geo import Skip, curve_or_shape, guid, make_shape, plist, pt, shape_spec, shapes_of, simple_node, vec
from app.graph.sdk import Port
from app.graph.values import Point3, Vector3

CAT = "Surface"
UP = Vector3(0.0, 0.0, 1.0)


def specs_of(curves):
    got = [curve_or_shape(c) for c in curves if c is not None]
    if not got:
        raise Skip("No curves were given.")
    return got


simple_node(
    "surface.extrude", "Extrude Curve", "Ext", "Freeform",
    [Port("curve", "curve"), Port("direction", "vector", default=UP, description="Direction and distance"), Port("cap", "boolean", default=False, description="Close a planar curve into a solid")],
    [Port("geometry", "geometry")],
    lambda curve, direction, cap: {"op": "extrude", "curve": curve_or_shape(curve), "vector": vec_list(direction), "cap": bool(cap)},
    lambda args, r: make_shape(r),
    category=CAT, description="Sweep a curve along a vector into a surface, or a solid when capped.",
)


def vec_list(v):
    return [v.x, v.y, v.z]


def loft_op(curves, ruled, solid):
    specs = specs_of(curves)
    if len(specs) < 2:
        raise Skip("A loft needs at least two curves.")
    return {"op": "loft", "curves": specs, "ruled": bool(ruled), "solid": bool(solid)}


simple_node(
    "surface.loft", "Loft", "Loft", "Freeform",
    [Port("curves", "curve", access="list"), Port("ruled", "boolean", default=False, description="Straight sections between curves"), Port("solid", "boolean", default=False, description="Cap the ends into a solid")],
    [Port("geometry", "geometry")],
    loft_op,
    lambda args, r: make_shape(r),
    category=CAT, description="Surface through a list of section curves in order.",
)


def sweep_op(rail, profiles, solid):
    return {"op": "sweep", "rail": curve_or_shape(rail), "profiles": specs_of(profiles), "solid": bool(solid)}


simple_node(
    "surface.sweep", "Sweep One Rail", "Sweep", "Freeform",
    [Port("rail", "curve"), Port("profiles", "curve", access="list"), Port("solid", "boolean", default=False)],
    [Port("geometry", "geometry")],
    sweep_op,
    lambda args, r: make_shape(r),
    category=CAT, description="Carry one or more profile curves along a rail curve.",
)

simple_node(
    "surface.revolve", "Revolve Curve", "Rev", "Freeform",
    [Port("curve", "curve"), Port("origin", "point", default=Point3()), Port("axis", "vector", default=UP), Port("degrees", "number", default=360.0)],
    [Port("geometry", "geometry")],
    lambda curve, origin, axis, degrees: {"op": "revolve", "curve": curve_or_shape(curve), "origin": plist(origin), "axis": vec_list(axis), "degrees": float(degrees)},
    lambda args, r: make_shape(r),
    category=CAT, description="Spin a curve about an axis through a point.",
)

simple_node(
    "surface.planar", "Planar Surface", "Plan", "Freeform",
    [Port("curves", "curve", access="list", description="An outer boundary and optional holes, all closed and flat")],
    [Port("surface", "surface")],
    lambda curves: {"op": "planar", "curves": specs_of(curves)},
    lambda args, r: make_shape(r, "surface"),
    category=CAT, description="Flat surface bounded by closed curves; the largest is the outer edge.",
)

simple_node(
    "surface.divide", "Divide Surface", "DivS", "Analysis",
    [Port("surface", "surface"), Port("u", "integer", default=10, min=1), Port("v", "integer", default=10, min=1)],
    [Port("points", "point"), Port("normals", "vector")],
    lambda surface, u, v: {"op": "srf_divide", "surface": shape_spec(surface), "u": int(u), "v": int(v)},
    lambda args, r: ([[pt(q) for q in row] for row in r["points"]], [[vec(q) for q in row] for row in r["normals"]]),
    category=CAT, multi=True, rows=("points", "normals"), description="Grid of points and normals; one branch per row along u.",
)

simple_node(
    "surface.evaluate", "Evaluate Surface", "EvalS", "Analysis",
    [Port("surface", "surface"), Port("u", "number", default=0.5, description="0 to 1"), Port("v", "number", default=0.5, description="0 to 1")],
    [Port("point", "point"), Port("normal", "vector")],
    lambda surface, u, v: {"op": "srf_eval", "surface": shape_spec(surface), "u": float(u), "v": float(v)},
    lambda args, r: (pt(r["point"]), vec(r["normal"])),
    category=CAT, description="Point and unit normal at a position on a surface.",
)

simple_node(
    "surface.closest_point", "Surface Closest Point", "CPS", "Analysis",
    [Port("surface", "surface"), Port("point", "point")],
    [Port("point", "point"), Port("u", "number"), Port("v", "number"), Port("distance", "number")],
    lambda surface, point: {"op": "srf_closest", "surface": shape_spec(surface), "point": plist(point)},
    lambda args, r: (pt(r["point"]), float(r["u"]), float(r["v"]), float(r["distance"])),
    category=CAT, description="Nearest point on a surface, with its u and v position from 0 to 1.",
)

simple_node(
    "surface.boundary", "Surface Boundary", "Bnd", "Analysis",
    [Port("surface", "surface")],
    [Port("curves", "curve"), Port("outer", "boolean")],
    lambda surface: {"op": "srf_boundary", "surface": shape_spec(surface)},
    lambda args, r: (shapes_of(r), [bool(d.get("outer")) for d in r.get("shapes") or []]),
    category=CAT, multi=True, description="Edge loops of a surface, the outer one flagged.",
)
