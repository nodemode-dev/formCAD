import math

import pytest

from tests.manufacture.helpers import box_triangles, dist_to_polygon, inside, open_mesh, sample_points
from tests.manufacture.test_cam_fixtures import assert_apart
from tests.support.gcode import Program

PARTS = [
    {"name": "plate", "qty": 5, "loops": [{"pts": [[0, 0], [40, 0], [40, 30], [0, 30]]}]},
    {"name": "disc", "qty": 3, "loops": [{"circle": {"c": [0, 0], "r": 15}}]},
    {"name": "ell", "qty": 2, "loops": [{"pts": [[0, 0], [50, 0], [50, 10], [10, 10], [10, 40], [0, 40]]}]},
]


@pytest.fixture()
def sheet_doc(docs, tmp_path):
    return open_mesh(docs, tmp_path, box_triangles((0, 0, 0), (1, 1, 1)), "blank")


def nest(doc, sheets, margin=5.0, clearance=4.0, parts=PARTS):
    return doc.post("/cam/nest", {"parts": parts, "sheets": sheets, "margin": margin, "clearance": clearance, "kerf": 0.0, "seconds": 3.0, "restarts": 2, "seed": 3})


def outlines(doc, nid, sheet):
    shapes = doc.get("/cam/nests/%s/shapes" % nid, sheet=sheet)
    return shapes, [(p["name"].split(" #")[0], [tuple(q) for q in next(l for l in p["loops"] if l["outer"])["pts"]]) for p in shapes["parts"]]


@pytest.mark.parametrize("margin,clearance", [(5.0, 4.0), (10.0, 1.0)])
def test_a_nest_places_every_part_inside_the_sheet_margin_apart_by_the_clearance_with_the_requested_counts(sheet_doc, margin, clearance):
    res = nest(sheet_doc, [{"width": 300, "height": 200, "qty": 2}], margin, clearance)
    assert res["placed"] == 10 and res["unplaced"] == []
    counts = {}
    for s in range(1, res["sheet_count"] + 1):
        shapes, polys = outlines(sheet_doc, res["id"], s)
        for name, poly in polys:
            counts[name] = counts.get(name, 0) + 1
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            assert min(xs) >= margin - 0.01 and min(ys) >= margin - 0.01
            assert max(xs) <= shapes["width"] - margin + 0.01 and max(ys) <= shapes["height"] - margin + 0.01
        assert_apart([p for _, p in polys], clearance)
    assert counts == {"plate": 5, "disc": 3, "ell": 2}


def test_a_placed_part_keeps_its_shape_and_area(sheet_doc):
    res = nest(sheet_doc, [{"width": 300, "height": 200, "qty": 2}])
    _, polys = outlines(sheet_doc, res["id"], 1)
    areas = {"plate": 1200.0, "disc": math.pi * 225.0, "ell": 50 * 10 + 10 * 30}
    for name, poly in polys:
        a = abs(sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1] for i in range(len(poly)))) / 2.0
        assert a == pytest.approx(areas[name], rel=0.01)


def test_parts_that_do_not_fit_are_reported_unplaced_and_the_rest_counted(sheet_doc):
    many = [{"name": "plate", "qty": 12, "loops": [{"pts": [[0, 0], [40, 0], [40, 30], [0, 30]]}]}]
    res = nest(sheet_doc, [{"width": 100, "height": 100, "qty": 1}], parts=many)
    fits = 4
    assert res["placed"] <= fits
    assert res["placed"] + len(res["unplaced"]) == 12
    assert res["placed"] >= 2


@pytest.mark.parametrize("post,kind,on", [("cut_grbl_laser", "laser", "M4"), ("cut_linuxcnc_plasma", "plasma", "M3"), ("cut_linuxcnc_waterjet", "waterjet", "M3")])
def test_cutting_code_for_a_nest_cuts_every_outline_half_a_kerf_outside_with_one_pierce_per_loop(sheet_doc, data_dir, post, kind, on):
    plates = [{"name": "plate", "qty": 2, "loops": [{"pts": [[0, 0], [40, 0], [40, 30], [0, 30]]}, {"circle": {"c": [20, 15], "r": 5}, "outer": False}]}]
    res = nest(sheet_doc, [{"width": 150, "height": 100, "qty": 1}], parts=plates)
    _, polys = outlines(sheet_doc, res["id"], 1)
    kerf = 0.8
    proc = {"kind": kind, "kerf": kerf, "feed": 1500.0, "lead_in": {"type": "arc", "length": 2.0, "angle": 45.0}, "lead_out": {"type": "none"}}
    out = data_dir / ("lane9-nest-%s%s" % (kind, ".nc" if "grbl" in post else ".ngc"))
    files = sheet_doc.post("/cam/nests/%s/export" % res["id"], {"process": proc, "post": post, "path": str(out)})["files"]
    text = open(files[0]["path"], encoding="utf-8").read()
    program = Program(text)
    assert program.unknown == [] and program.ended and not program.spindle_on
    pierces = sum(1 for ln in text.splitlines() if ln.strip().startswith(on))
    assert pierces == 4
    outer = [p for _, p in polys]
    centres = [((min(q[0] for q in poly) + max(q[0] for q in poly)) / 2.0, (min(q[1] for q in poly) + max(q[1] for q in poly)) / 2.0) for poly in outer]
    pts = sample_points(program.cutting())
    on_outer = on_hole = 0
    for p in pts:
        if min(abs(dist_to_polygon(p, poly) - kerf / 2.0) for poly in outer) < 0.02 and not any(inside(p, poly) for poly in outer):
            on_outer += 1
            continue
        d_hole = min(math.dist(p[:2], c) for c in centres)
        if abs(d_hole - (5.0 - kerf / 2.0)) < 0.02:
            on_hole += 1
            continue
        assert d_hole < 5.0 - kerf / 2.0 or not any(inside(p, poly) for poly in outer)
    assert on_outer > 0.4 * len(pts) and on_hole > 0.05 * len(pts)
