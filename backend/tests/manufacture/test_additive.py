import math
import re

import pytest

from tests.manufacture.helpers import box_triangles, open_mesh, prism_triangles

START = "G28\nG90\nM83\nG92 E0"
BASE = {"layer_height": 0.2, "first_layer_height": 0.2, "skirt_loops": 0, "brim_width": 0.0, "start_gcode": START, "end_gcode": "M104 S0\nM84"}
WORD = re.compile(r"([XYZEF])(-?[\d.]+)")


def sliced(docs, tmp_path, data_dir, triangles, name, **settings):
    doc = open_mesh(docs, tmp_path, triangles, name)
    body = doc.entities()[0]["handle"]
    prof = doc.post("/additive/profiles", {"name": name, "settings": dict(BASE, **settings)})
    plate = doc.post("/additive/plates", {"bodies": [body], "profile": prof["id"]})
    res = doc.post("/additive/plates/%s/slice" % plate["id"])
    out = data_dir / ("lane9-%s.gcode" % name)
    doc.post("/additive/plates/%s/export" % plate["id"], {"kind": "gcode", "path": str(out)})
    return res["summary"], read_gcode(out.read_text())


def read_gcode(text):
    layers, layer, kind = [], None, None
    pos = {"X": 0.0, "Y": 0.0, "Z": 0.0}
    extruded = 0.0
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(";LAYER:"):
            layer = {"z": None, "moves": []}
            layers.append(layer)
            continue
        if line.startswith(";TYPE:"):
            kind = line[6:]
            continue
        code = line.split(";", 1)[0].strip()
        if not code.startswith(("G0", "G1")):
            continue
        words = dict((k, float(v)) for k, v in WORD.findall(code))
        start = dict(pos)
        pos.update({k: v for k, v in words.items() if k in "XYZ"})
        e = words.get("E", 0.0)
        extruded += e
        if layer is not None and e > 0 and (start["X"], start["Y"]) != (pos["X"], pos["Y"]):
            layer["z"] = pos["Z"]
            layer["moves"].append((kind, (start["X"], start["Y"]), (pos["X"], pos["Y"]), e))
    return {"layers": layers, "extruded_mm": extruded}


def filament_volume(mm, diameter=1.75):
    return mm * math.pi * (diameter / 2.0) ** 2


def test_slicing_a_10_mm_cube_at_0_2_mm_gives_50_layers_each_one_layer_height_apart(docs, tmp_path, data_dir):
    summary, g = sliced(docs, tmp_path, data_dir, box_triangles((0, 0, 0), (10, 10, 10)), "cube")
    assert summary["layers"] == 50
    zs = [L["z"] for L in g["layers"]]
    assert len(zs) == 50
    assert zs == pytest.approx([0.2 * (k + 1) for k in range(50)], abs=1e-6)


def test_every_layer_of_a_cube_has_an_outer_wall_whose_outline_is_the_10_by_10_face(docs, tmp_path, data_dir):
    _, g = sliced(docs, tmp_path, data_dir, box_triangles((0, 0, 0), (10, 10, 10)), "cubewall", outer_width=0.45, first_layer_width=0.5)
    for k, L in enumerate(g["layers"]):
        pts = [p for kind, a, b, _ in L["moves"] if kind == "WALL-OUTER" for p in (a, b)]
        assert pts
        half = (0.5 if k == 0 else 0.45) / 2.0
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        side_x, side_y = max(xs) - min(xs) + 2 * half, max(ys) - min(ys) + 2 * half
        assert side_x * side_y == pytest.approx(100.0, abs=0.05)


def test_a_solid_cube_uses_filament_whose_volume_is_the_cube_volume(docs, tmp_path, data_dir):
    summary, g = sliced(docs, tmp_path, data_dir, box_triangles((0, 0, 0), (10, 10, 10)), "solid", infill_density=100.0, infill_pattern="rectilinear")
    assert filament_volume(g["extruded_mm"]) == pytest.approx(1000.0, rel=0.03)
    assert summary["filament_mm"] == pytest.approx(g["extruded_mm"], rel=1e-3)
    assert summary["model_volume_mm3"] == pytest.approx(1000.0, abs=0.01)


def test_a_sparse_cube_uses_less_filament_in_line_with_its_infill_density(docs, tmp_path, data_dir):
    cube = box_triangles((0, 0, 0), (20, 20, 20))
    common = {"infill_pattern": "rectilinear", "perimeters": 2, "top_layers": 3, "bottom_layers": 3}
    full, _ = sliced(docs, tmp_path, data_dir, cube, "full", infill_density=100.0, **common)
    empty, _ = sliced(docs, tmp_path, data_dir, cube, "empty", infill_density=0.0, **common)
    half, _ = sliced(docs, tmp_path, data_dir, cube, "half", infill_density=50.0, **common)
    assert filament_volume(full["filament_mm"]) == pytest.approx(8000.0, rel=0.03)
    expected = empty["filament_mm"] + 0.5 * (full["filament_mm"] - empty["filament_mm"])
    assert half["filament_mm"] == pytest.approx(expected, rel=0.05)


def ledge(angle_from_vertical):
    run = 20.0 * math.tan(math.radians(angle_from_vertical))
    return prism_triangles([(0.0, 0.0), (10.0, 0.0), (10.0 + run, 20.0), (0.0, 20.0)], 0.0, 10.0)


@pytest.mark.parametrize("angle,needs", [(0.0, False), (30.0, False), (60.0, True)])
def test_an_overhang_gets_support_only_when_it_leans_past_the_support_angle(docs, tmp_path, data_dir, angle, needs):
    summary, g = sliced(docs, tmp_path, data_dir, ledge(angle), "lean%d" % int(angle), support=True, support_angle=45.0, support_min_area=0.0)
    support = [m for L in g["layers"] for m in L["moves"] if m[0] and m[0].startswith("SUPPORT")]
    assert (summary["support_volume_mm3"] > 0.0) == needs
    assert bool(support) == needs


def test_support_under_a_flat_ledge_stands_only_below_the_ledge(docs, tmp_path, data_dir):
    shape = prism_triangles([(0.0, 0.0), (10.0, 0.0), (10.0, 17.0), (25.0, 17.0), (25.0, 20.0), (0.0, 20.0)], 0.0, 10.0)
    summary, g = sliced(docs, tmp_path, data_dir, shape, "ledge", support=True, support_angle=45.0)
    assert summary["support_volume_mm3"] > 0.0
    bed = summary["bbox"]
    x0 = bed[0]
    support = [(m, L["z"]) for L in g["layers"] for m in L["moves"] if m[0] and m[0].startswith("SUPPORT")]
    assert support
    for (kind, a, b, _), z in support:
        assert z < 17.0
        for p in (a, b):
            assert x0 + 10.0 - 1e-3 <= p[0] <= x0 + 25.0 + 1e-3
