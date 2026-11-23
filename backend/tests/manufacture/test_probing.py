import pytest

BLOCK = [[-40, -40], [40, -40], [40, 40], [-40, 40]]


def simulate(engine, kind, params, solids, start=(0, 0, 20)):
    return engine.post("/api/cam/probing/simulate", {"kind": kind, "params": params, "world": {"solids": solids, "start": list(start)}})


@pytest.mark.parametrize("centre,radius,stylus", [((3.0, 4.0), 10.5, 1.0), ((-2.5, 1.5), 8.0, 2.0)])
def test_a_bore_cycle_finds_the_true_centre_and_diameter_of_an_offset_hole_net_of_the_stylus(engine, centre, radius, stylus):
    hole = [{"kind": "poly", "z0": -20, "z1": 0, "pts": BLOCK, "holes": [{"c": list(centre), "r": radius}]}]
    res = simulate(engine, "bore", {"cx": 0, "cy": 0, "diameter": 2 * radius - 1.0, "radius": stylus}, hole)
    out = res["outputs"]
    assert (out["center_x"], out["center_y"]) == pytest.approx(centre, abs=1e-6)
    assert out["diameter"] == pytest.approx(2 * radius, abs=1e-6)
    assert res["origin"][:2] == pytest.approx(list(centre), abs=1e-6)
    assert res["crashes"] == 0


def test_a_corner_cycle_sets_the_work_origin_on_the_outside_corner(engine):
    part = [{"kind": "poly", "z0": -20, "z1": 0, "pts": [[5, 7], [60, 7], [60, 50], [5, 50]]}]
    res = simulate(engine, "corner", {"cx": 0, "cy": 0, "qx": 1, "qy": 1}, part)
    assert (res["outputs"]["corner_x"], res["outputs"]["corner_y"]) == pytest.approx((5.0, 7.0), abs=1e-6)
    assert res["origin"][:2] == pytest.approx([5.0, 7.0], abs=1e-6)


def test_a_bore_cycle_over_solid_material_reports_the_probe_crashing_into_it(engine):
    solid = [{"kind": "poly", "z0": -20, "z1": 0, "pts": BLOCK}]
    res = simulate(engine, "bore", {"cx": 0, "cy": 0, "diameter": 20}, solid)
    assert res["crashes"] > 0
