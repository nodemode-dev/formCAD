import math

import pytest

from tests.meshsim import helpers as h

pytestmark = [pytest.mark.kernel, pytest.mark.mesher, pytest.mark.slow]

E = 200e9
NU = 0.3
RHO = 7850.0
L, B, H = 100.0, 10.0, 10.0
F = 100.0
I = (B * 1e-3) * (H * 1e-3) ** 3 / 12.0
LM = L * 1e-3


def deflection(x_mm, force=F):
    x = x_mm * 1e-3
    return force * x * x * (3 * LM - x) / (6 * E * I)


@pytest.fixture(scope="module")
def cantilever(engine, kernel, mesher):
    doc = h.metric(engine.new_doc())
    body = h.box(doc, [L, B, H])
    mat = h.record(doc, "material", E=E, nu=NU, rho=RHO)
    load = h.record(doc, "load", type="force", value=F, direction=[0, 0, -1], select={"plane": {"axis": "x", "value": L}})
    fix = h.record(doc, "fixture", type="fixed", select={"plane": {"axis": "x", "value": 0}})
    sid = h.record(doc, "study", type="static", geometry={"body": body}, material=mat, loads=[load], fixtures=[fix], mesh={"maxh_mm": 4})
    summary = h.solved(doc, sid)
    yield {"doc": doc, "sid": sid, "summary": summary, "body": body, "mat": mat, "fix": fix}
    engine.raw("POST", doc.url("/close"), json={"force": True})


def test_cantilever_tip_deflection_matches_the_beam_formula_within_three_percent(cantilever):
    tip = h.probe(cantilever["doc"], cantilever["sid"], [(L, B / 2, H / 2)])[0]
    expected_mm = F * LM ** 3 / (3 * E * I) * 1e3
    assert tip["inside"]
    assert tip["displacement_mm"][2] < 0
    assert abs(-tip["displacement_mm"][2] - expected_mm) <= 0.03 * expected_mm
    assert abs(cantilever["summary"]["max_displacement_m"] * 1e3 - expected_mm) <= 0.03 * expected_mm


@pytest.mark.parametrize("x", [25.0, 50.0, 75.0])
def test_cantilever_deflection_along_the_span_follows_the_elastic_curve(cantilever, x):
    got = h.probe(cantilever["doc"], cantilever["sid"], [(x, B / 2, H / 2)])[0]["displacement_mm"][2]
    expected = deflection(x) * 1e3
    assert abs(-got - expected) <= 0.03 * expected


def test_cantilever_root_bending_stress_matches_m_c_over_i_within_ten_percent(cantilever):
    expected = F * LM * (H * 1e-3 / 2) / I
    assert abs(cantilever["summary"]["max_von_mises_pa"] - expected) <= 0.10 * expected


def test_cantilever_reactions_balance_the_applied_load(cantilever):
    s = cantilever["summary"]
    reaction = s["reactions_n"][cantilever["fix"]]
    assert math.isclose(reaction[2], F, rel_tol=1e-6)
    assert abs(reaction[0]) < 1e-6 * F and abs(reaction[1]) < 1e-6 * F
    assert math.isclose(s["applied_n"][2], -F, rel_tol=1e-9)
    assert s["equilibrium_error_n"] < 1e-6 * F


def test_points_on_the_fixed_face_do_not_move(cantilever):
    points = [(0.0, y, z) for y in (0.5, 5.0, 9.5) for z in (0.5, 5.0, 9.5)]
    for p in h.probe(cantilever["doc"], cantilever["sid"], points):
        assert p["inside"]
        assert max(abs(c) for c in p["displacement_mm"]) < 1e-12


def test_a_bar_pulled_on_symmetry_planes_stretches_by_fl_over_ae_with_uniform_stress(doc):
    h.metric(doc)
    length, side, force = 50.0, 10.0, 1000.0
    area = (side * 1e-3) ** 2
    body = h.box(doc, [length, side, side])
    mat = h.record(doc, "material", E=E, nu=NU, rho=RHO)
    load = h.record(doc, "load", type="force", value=force, direction=[1, 0, 0], select={"plane": {"axis": "x", "value": length}})
    fixes = [h.record(doc, "fixture", type="symmetry", axis=k, select={"plane": {"axis": "xyz"[k], "value": 0}}) for k in range(3)]
    sid = h.record(doc, "study", type="static", geometry={"body": body}, material=mat, loads=[load], fixtures=fixes, mesh={"maxh_mm": 5})
    s = h.solved(doc, sid)
    stress = force / area
    strain = stress / E
    corner = h.probe(doc, sid, [(length, side, side)])[0]["displacement_mm"]
    assert math.isclose(corner[0], strain * length, rel_tol=5e-3)
    assert math.isclose(corner[1], -NU * strain * side, rel_tol=5e-3)
    assert math.isclose(corner[2], -NU * strain * side, rel_tol=5e-3)
    assert math.isclose(s["max_von_mises_pa"], stress, rel_tol=1e-2)
    assert math.isclose(s["max_principal_pa"], stress, rel_tol=1e-2)
    middle = h.probe(doc, sid, [(length / 2, side / 2, side / 2)])[0]
    assert math.isclose(middle["von_mises_pa"], stress, rel_tol=1e-2)
    assert math.isclose(middle["displacement_mm"][0], strain * length / 2, rel_tol=5e-3)


def test_the_first_natural_frequency_of_a_cantilever_matches_euler_bernoulli_within_five_percent(cantilever):
    doc = cantilever["doc"]
    sid = h.record(doc, "study", type="modal", geometry={"body": cantilever["body"]}, material=cantilever["mat"], fixtures=[cantilever["fix"]], mesh={"maxh_mm": 4}, options={"modes": 2})
    s = h.solved(doc, sid)
    area = (B * 1e-3) * (H * 1e-3)
    expected = 1.8751040687 ** 2 / (2 * math.pi) * math.sqrt(E * I / (RHO * area * LM ** 4))
    f1, f2 = s["frequencies_hz"][:2]
    assert abs(f1 - expected) <= 0.05 * expected
    assert abs(f2 - f1) <= 0.02 * f1
    assert math.isclose(s["mass_kg"], RHO * area * LM, rel_tol=1e-6)


def test_the_nonlinear_solver_agrees_with_the_linear_one_for_a_small_load(cantilever):
    doc = cantilever["doc"]
    small = h.record(doc, "load", type="force", value=1.0, direction=[0, 0, -1], select={"plane": {"axis": "x", "value": L}})
    common = {"geometry": {"body": cantilever["body"]}, "material": cantilever["mat"], "loads": [small], "fixtures": [cantilever["fix"]], "mesh": {"maxh_mm": 5}}
    linear = h.solved(doc, h.record(doc, "study", type="static", **common))
    nonlinear = h.solved(doc, h.record(doc, "study", type="nonlinear_static", options={"material_model": "elastic", "steps": 1}, **common))
    assert nonlinear["converged_to_full_load"]
    assert math.isclose(nonlinear["max_displacement_m"], linear["max_displacement_m"], rel_tol=1e-2)
    assert math.isclose(nonlinear["max_displacement_m"], deflection(L, 1.0), rel_tol=3e-2)
    assert math.isclose(nonlinear["reactions_n"][2], 1.0, rel_tol=1e-3)


def test_a_static_study_without_a_fixture_is_refused_with_a_message_naming_the_fixture(cantilever):
    doc = cantilever["doc"]
    load = h.record(doc, "load", type="force", value=F, direction=[0, 0, -1], select={"plane": {"axis": "x", "value": L}})
    sid = h.record(doc, "study", type="static", geometry={"body": cantilever["body"]}, material=cantilever["mat"], loads=[load], mesh={"maxh_mm": 8})
    view = h.run_study(doc, sid)
    assert view["state"] == "error"
    assert "fixture" in view["message"].lower()
    assert doc.get("/sim/studies/%s/result" % sid)["result"] is None


def test_a_static_study_without_a_material_is_refused_with_a_message_naming_the_material(cantilever):
    doc = cantilever["doc"]
    load = h.record(doc, "load", type="force", value=F, direction=[0, 0, -1], select={"plane": {"axis": "x", "value": L}})
    sid = h.record(doc, "study", type="static", geometry={"body": cantilever["body"]}, loads=[load], fixtures=[cantilever["fix"]], mesh={"maxh_mm": 8})
    view = h.run_study(doc, sid)
    assert view["state"] == "error"
    assert "material" in view["message"].lower()


def test_steady_conduction_through_a_bar_carries_k_a_delta_t_over_l(doc):
    h.metric(doc)
    length, side, k = 50.0, 10.0, 50.0
    hot, cold = 373.15, 293.15
    body = h.box(doc, [length, side, side])
    mat = h.record(doc, "material", E=E, nu=NU, rho=RHO, k=k)
    a = h.record(doc, "fixture", type="temperature", value=hot, select={"plane": {"axis": "x", "value": 0}})
    b = h.record(doc, "fixture", type="temperature", value=cold, select={"plane": {"axis": "x", "value": length}})
    sid = h.record(doc, "study", type="thermal", geometry={"body": body}, material=mat, fixtures=[a, b], mesh={"maxh_mm": 6})
    s = h.solved(doc, sid)
    flow = k * (side * 1e-3) ** 2 * (hot - cold) / (length * 1e-3)
    assert math.isclose(s["heat_flow_w"][a], flow, rel_tol=1e-3)
    assert math.isclose(s["heat_flow_w"][b], -flow, rel_tol=1e-3)
    mid = h.probe(doc, sid, [(length / 4, side / 2, side / 2)])[0]["temperature_k"]
    assert math.isclose(mid, hot - (hot - cold) / 4, abs_tol=1e-6)

