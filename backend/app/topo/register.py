from app.sim import registry
from app.sim.fem import SimError

TOPOLOGY_OPTIONS = {
    "reduction": {"default": 0.5, "min": 0.02, "max": 0.95, "label": "Mass to remove (share of the starting mass)"},
    "stress_limit_mpa": {"default": None, "label": "Stress limit in MPa (leave empty to use the yield strength over the safety factor)"},
    "safety_factor": {"default": 1.5, "min": 1.0, "label": "Safety factor on yield"},
    "cells": {"default": 3000, "label": "Target number of design cells"},
    "cell_mm": {"default": None, "label": "Cell size in mm (overrides the cell count)"},
    "preserve": {"default": [], "label": "Regions kept solid: bodies, boxes, cylinders or spheres"},
    "obstacles": {"default": [], "label": "Regions kept empty: bodies, boxes, cylinders or spheres"},
    "symmetry": {"default": [], "label": "Mirror planes by axis: x, y, z"},
    "extrusion": {"default": None, "label": "Keep the cross section constant along an axis: x, y, z"},
    "penalty": {"default": 3.0, "min": 1.0, "max": 6.0, "label": "Stiffness penalty"},
    "radius_cells": {"default": 1.5, "min": 1.0, "max": 8.0, "label": "Density filter radius in cells (the smallest member size)"},
    "iterations": {"default": 100, "min": 1, "max": 1000, "label": "Iterations per pass"},
    "max_outer": {"default": 6, "min": 1, "max": 8, "label": "Optimisation passes while the stress is verified"},
    "relief_passes": {"default": 0, "min": 0, "max": 4, "label": "Stress relief passes before adding material (experimental)"},
    "projection": {"default": True, "label": "Sharpen the density to solid and void"},
    "auto_preserve": {"default": True, "label": "Keep the cells next to loads and fixtures solid"},
}

SHAPE_OPTIONS = {
    "variables": {"default": [], "label": "Document parameters to vary: name, minimum, maximum"},
    "objective": {"default": "mass", "label": "Minimise mass or compliance"},
    "stress_limit_mpa": {"default": None, "label": "Stress limit in MPa"},
    "cells": {"default": 1500, "label": "Target number of analysis cells"},
    "evaluations": {"default": 40, "label": "Most candidates to try"},
}


def run(ctx):
    raise SimError("Topology and shape studies run from the optimisation routes, not from the general study run: POST /api/docs/{id}/topo/studies/{study}/run.")


registry.register("topology", "Topology optimisation", run, needs=("material", "loads", "fixtures"), options=TOPOLOGY_OPTIONS, order=70, mesh_order=0)
registry.register("shape", "Shape optimisation", run, needs=("material", "loads", "fixtures"), options=SHAPE_OPTIONS, order=71, mesh_order=0)
