from app.bodies import refgeo
from app.part import registry
from app.part.registry import PartError


def refgeo_plane(step, spec):
    name = spec.get("name") or spec.get("ref") or spec.get("plane")
    if not name:
        raise PartError("Name the reference plane.")
    try:
        rec = refgeo.Resolver(step.d).record(str(name))
    except refgeo.RefError as err:
        raise PartError(str(err))
    if rec["kind"] not in ("plane", "cs"):
        raise PartError("%s is not a plane." % rec["name"])
    g = rec["geometry"]
    s = step.mm
    return {"origin": [c * s for c in g["origin"]], "x": list(g["x"]), "y": list(g["y"]), "z": list(g["z"])}


registry.register_plane_source("refgeo", refgeo_plane)
