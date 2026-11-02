import math

from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_SOLID

import kernel_mesh as mesh
import kernel_store as store


def inertia_rows(props):
    m = props.MatrixOfInertia()
    return [[m.Value(r, c) for c in (1, 2, 3)] for r in (1, 2, 3)]


def mass_properties(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    density = float(p.get("density", 1.0))
    summary = store.summarize(shape)
    area_props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, area_props)
    out = {"area": area_props.Mass(), "solids": summary["solids"], "closed": summary["closed"], "valid": summary["valid"], "density": density}
    if summary["solids"] == 0:
        out.update(volume=None, mass=None, centroid=None, inertia=None, principal=None, note="The body has no solid, so it has no volume.")
        return out
    if not summary["closed"] or not summary["valid"]:
        out.update(volume=None, mass=None, centroid=None, inertia=None, principal=None, note="The body is not a closed valid solid, so the volume is not reported.")
        return out
    vol = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, vol, False, False, False)
    c = vol.CentreOfMass()
    volume = vol.Mass()
    pr = vol.PrincipalProperties()
    moments = pr.Moments()
    out.update(
        volume=volume,
        mass=volume * density,
        centroid=[c.X(), c.Y(), c.Z()],
        inertia=[[v * density for v in row] for row in inertia_rows(vol)],
        principal=[v * density for v in moments],
    )
    return out


def bounds(p):
    ident = p.get("id")
    shape = store.shape_of(ident)
    exact = str(p.get("mode", "geometry")) != "mesh"
    box = Bnd_Box()
    if exact:
        BRepBndLib.AddOptimal_s(shape, box, False, False)
        used = "geometry"
    else:
        rough = store.bbox_of(shape)
        if rough is None:
            raise RuntimeError("The shape has no extent.")
        diag = math.dist(rough[:3], rough[3:])
        linear = float(p.get("linear") or max(diag * 0.0005, 1e-4))
        angular = float(p.get("angular") or 0.3)
        mesh.run_mesh(shape, linear, angular)
        BRepBndLib.AddOptimal_s(shape, box, True, False)
        used = "mesh"
    if box.IsVoid():
        raise RuntimeError("The shape has no extent.")
    return {"min": [box.GetXMin(), box.GetYMin(), box.GetZMin()], "max": [box.GetXMax(), box.GetYMax(), box.GetZMax()], "source": used}


def check(p):
    shape = store.shape_of(p.get("id"))
    analyzer = BRepCheck_Analyzer(shape)
    return {"valid": bool(analyzer.IsValid()), "summary": store.summarize(shape)}


def tessellate(p):
    return mesh.build(str(p.get("id")), float(p.get("linear", 0.0)), float(p.get("angular", 0.3)), store.absolute_path(p.get("path"), (".mesh",)))


METHODS = {"mass_properties": mass_properties, "bounds": bounds, "check": check, "tessellate": tessellate}
