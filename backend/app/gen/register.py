from app.gen import run as gen_run
from app.sim import registry
from app.sim.fem import SimError

GENERATIVE_OPTIONS = {
    "generative": {"default": gen_run.DEFAULTS, "label": "Generative matrix: objective (min_mass, min_compliance), safety_factor, volume_fractions, methods (additive, milling3, cutting, casting with direction, directions or axis), min_member_cells, passes, iterations"},
    "preserve": {"default": [], "label": "Regions kept solid: bodies, boxes, cylinders or spheres"},
    "obstacles": {"default": [], "label": "Regions kept empty: bodies, boxes, cylinders or spheres"},
    "symmetry": {"default": [], "label": "Mirror planes by axis: x, y, z"},
    "cells": {"default": 3000, "label": "Target number of design cells"},
    "cell_mm": {"default": None, "label": "Cell size in mm (overrides the cell count)"},
    "auto_preserve": {"default": True, "label": "Keep the cells next to loads and fixtures solid"},
}


def run(ctx):
    raise SimError("Generative studies run from the generative routes, not from the general study run: POST /api/docs/{id}/gen/studies/{study}/run.")


registry.register("generative", "Generative design", run, needs=("material", "loads", "fixtures"), options=GENERATIVE_OPTIONS, order=72, mesh_order=0)
