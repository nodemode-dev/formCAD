import math

import numpy as np
import pytest

from tests.assembly.helpers import copy_fixture, crank_slider_lengths, mates_by_label, copy_parts, flat, matrix, point, pose, transform_of, wrap, z_angle


@pytest.fixture()
def mechanism(docs, fixtures, tmp_path):
    return docs.open(copy_fixture(fixtures, tmp_path, "mechanism.fcad", "mechanism"))


@pytest.fixture()
def linkage(docs, engine, fixtures, tmp_path):
    d = docs.open(copy_fixture(fixtures, tmp_path, "linkage.fcad", "linkage"))
    d.engine.put(d.url("/assembly/settings"), {"search_folders": [str(tmp_path / "linkage")]})
    d.post("/assembly/refresh")
    return d


@pytest.fixture()
def pair(engine, fixtures, tmp_path):
    parts = copy_parts(fixtures, tmp_path / "parts", ("base", "pin"))
    a = engine.new_doc("", "assembly")
    a.post("/assembly/components", {"path": str(parts / "base.fcad")})
    a.post("/assembly/components", {"path": str(parts / "pin.fcad"), "transform": flat(pose(None, (10.0, 5.0, 0.0)))})
    yield a
    engine.raw("POST", a.url("/close"), json={"force": True})


def test_the_mechanism_fixture_opens_fully_constrained_with_all_parts_loaded(mechanism):
    listing = mechanism.get("/assembly")
    assert listing["counts"]["components"] == 10 and listing["counts"]["missing"] == 0
    status = mechanism.get("/mates/status")
    assert status["state"] == "fully" and status["dof"] == 0 and len(status["mates"]) == 16


def test_crank_slider_follows_the_closed_form_through_a_full_turn(mechanism):
    r, l = crank_slider_lengths(mechanism)
    angles = [float(a) for a in range(0, 361, 10)]
    out = mechanism.post("/mates/M16/drive", {"values": angles, "commit": False, "report": True, "components": ["C6", "C9"]})
    assert out["ok"] and len(out["samples"]) == len(angles)
    xs = []
    for s in out["samples"]:
        t = math.radians(s["value"])
        x = r * math.cos(t) + math.sqrt(l * l - (r * math.sin(t)) ** 2)
        slider = matrix(s["poses"]["C6"])
        assert abs(slider[0, 3] - x) < 1e-6
        assert abs(slider[1, 3]) < 1e-6
        crank_pin = matrix(s["poses"]["C9"])[:3, 3]
        assert np.linalg.norm(crank_pin[:2] - (r * math.cos(t), r * math.sin(t))) < 1e-6
        xs.append(slider[0, 3])
    assert abs(max(xs) - (r + l)) < 1e-6 and abs(min(xs) - (l - r)) < 1e-6
    assert (r + l, l - r) == pytest.approx((105.0, 55.0), abs=1e-9)


def test_the_gear_pair_turns_the_pinion_by_the_inverse_ratio_in_the_opposite_sense(mechanism):
    ratio = mates_by_label(mechanism)["gear pair"]["value"]
    out = mechanism.post("/mates/M16/drive", {"values": [10.0, 25.0, 40.0], "commit": False, "report": True, "components": ["C2", "C3"]})
    for s in out["samples"]:
        gear = z_angle(s["poses"]["C3"])
        pinion = z_angle(s["poses"]["C2"])
        assert abs(wrap(gear - s["value"])) < 1e-6
        assert abs(wrap(pinion + s["value"] / ratio)) < 1e-6


def four_bar_rocker(theta, start_b, ground, crank, coupler, rocker):
    a = np.array([crank * math.cos(theta), crank * math.sin(theta)])
    o4 = np.array([ground, 0.0])
    d = float(np.linalg.norm(o4 - a))
    along = (coupler * coupler - rocker * rocker + d * d) / (2 * d)
    h = math.sqrt(coupler * coupler - along * along)
    u = (o4 - a) / d
    mid = a + along * u
    perp = np.array([-u[1], u[0]])
    options = [mid + h * perp, mid - h * perp]
    b = min(options, key=lambda q: float(np.linalg.norm(q - start_b)))
    return b, math.degrees(math.atan2(b[1] - o4[1], b[0] - o4[0]))


def test_the_four_bar_rocker_follows_the_closed_form_through_a_full_crank_turn(linkage):
    joints = {j["name"]: j for j in linkage.get("/joints")["joints"]}
    o = lambda name, side: np.asarray(joints[name][side]["frame"]["o"][:2])
    ground = float(np.linalg.norm(o("M4", "a") - o("M1", "a")))
    crank = float(np.linalg.norm(o("M2", "a") - o("M1", "b")))
    coupler = float(np.linalg.norm(o("M3", "a") - o("M2", "b")))
    rocker = float(np.linalg.norm(o("M3", "b") - o("M4", "b")))
    assert (ground, crank, coupler, rocker) == pytest.approx((100.0, 30.0, 90.0, 70.0), abs=1e-9)
    start_crank = z_angle(transform_of(linkage, "C2"))
    rocker_m = transform_of(linkage, "C4")
    b = point(rocker_m, (rocker, 0.0, 0.0))[:2]
    values = [float(v) for v in range(0, 361, 10)]
    out = linkage.post("/joints/M1/drive", {"coord": "rz", "values": values, "commit": False, "report": True, "components": ["C4", "C2"]})
    assert out["ok"] and len(out["samples"]) == len(values)
    for s in out["samples"]:
        theta = math.radians(start_crank + s["value"])
        b, phi = four_bar_rocker(theta, b, ground, crank, coupler, rocker)
        assert abs(wrap(z_angle(s["poses"]["C4"]) - phi)) < 1e-6
        assert abs(wrap(z_angle(s["poses"]["C2"]) - math.degrees(theta))) < 1e-6


def test_the_linkage_fixture_opens_with_one_degree_of_freedom_and_finds_parts_in_the_search_folder(linkage):
    listing = linkage.get("/assembly")
    assert listing["counts"]["missing"] == 0
    assert {c["status"]["found_by"] for c in listing["components"]} == {"search_folders"}
    status = linkage.get("/joints")["status"]
    assert status["state"] == "under" and status["dof"] == 1


@pytest.mark.kernel
def test_the_crank_turn_study_stops_when_the_rocker_reaches_the_bracket(linkage):
    job = linkage.post("/motion/studies/S1/run", {"wait": True})
    result = job.get("result") or job
    stopped = result["stopped"]
    assert stopped["reason"] == "contact" and sorted(stopped["pair"]) == ["C4", "C5"]
    assert stopped["time"] == pytest.approx(1.0979, abs=5e-4)
    assert stopped["gap_mm"] <= 0.01
    turned = 330.0 / 4.0 * stopped["time"]
    assert turned == pytest.approx(90.578, abs=0.01)


@pytest.mark.parametrize("kind,count", [("revolute", 1), ("slider", 1), ("cylindrical", 2), ("pinslot", 2), ("planar", 3), ("ball", 3)])
def test_each_joint_type_leaves_its_number_of_degrees_of_freedom(pair, kind, count):
    frame = {"origin": [10.0, 5.0, 0.0], "z": [0.0, 0.0, 1.0]}
    out = pair.post("/joints", {"type": kind, "a": {"comp": "C1", "frame": frame}, "b": {"comp": "C2", "frame": frame}})
    assert out["joint"]["dof"] == count
    assert pair.get("/joints")["status"]["components"]["C2"]["dof"] == count


def test_driving_a_revolute_joint_turns_the_part_about_the_joint_axis(pair):
    frame = {"origin": [10.0, 5.0, 0.0], "z": [0.0, 0.0, 1.0]}
    pair.post("/joints", {"type": "revolute", "a": {"comp": "C1", "frame": frame}, "b": {"comp": "C2", "frame": frame}})
    pair.post("/joints/M1/drive", {"coord": "rz", "value": 40.0})
    m = transform_of(pair, "C2")
    assert abs(z_angle(m) - 40.0) < 1e-6
    assert np.allclose(m[:3, 2], (0, 0, 1), atol=1e-9)
    assert np.linalg.norm(point(m, (0, 0, 0)) - (10, 5, 0)) < 1e-6


def test_driving_a_slider_joint_moves_the_part_along_the_joint_axis_without_turning(pair):
    frame = {"origin": [10.0, 5.0, 0.0], "z": [0.0, 1.0, 0.0]}
    pair.post("/joints", {"type": "slider", "a": {"comp": "C1", "frame": frame}, "b": {"comp": "C2", "frame": frame}})
    pair.post("/joints/M1/drive", {"coord": "tz", "value": 12.0})
    m = transform_of(pair, "C2")
    assert np.allclose(m[:3, :3], np.eye(3), atol=1e-9)
    assert np.allclose(m[:3, 3], (10, 17, 0), atol=1e-6)


def test_a_joint_limit_stops_the_drive_at_the_limit(pair):
    frame = {"origin": [10.0, 5.0, 0.0], "z": [0.0, 0.0, 1.0]}
    pair.post("/joints", {"type": "revolute", "a": {"comp": "C1", "frame": frame}, "b": {"comp": "C2", "frame": frame}, "limits": {"rz": {"min": -10.0, "max": 45.0}}})
    out = pair.post("/joints/M1/drive", {"coord": "rz", "value": 90.0})
    assert out["final"] == pytest.approx(45.0, abs=1e-9) and out["samples"][-1].get("limited")
    assert abs(z_angle(transform_of(pair, "C2")) - 45.0) < 1e-6


@pytest.mark.kernel
def test_interference_reports_the_overlap_volume_of_two_planted_bars(engine, tmp_path):
    made = engine.post("/api/toolbox/part", {"source": {"kind": "flat_bar", "params": {"b": 40, "t": 5, "length": 100}}, "folder": str(tmp_path)})
    box = made["summary"]["bbox"]
    spans = [box[i + 3] - box[i] for i in range(3)]
    long_axis = int(np.argmax(spans))
    a = engine.new_doc("", "assembly")
    try:
        a.post("/assembly/components", {"path": made["path"]})
        a.post("/assembly/components", {"path": made["path"]})
        shift = [0.0, 0.0, 0.0]
        shift[long_axis] = 70.0
        a.post("/assembly/components/C2/transform", {"translate": shift})
        found = a.post("/mates/interference", {})["interferences"]
        overlap = (spans[long_axis] - 70.0) * float(np.prod([s for i, s in enumerate(spans) if i != long_axis]))
        assert len(found) == 1 and sorted(found[0]["components"]) == ["C1", "C2"]
        assert found[0]["volume_mm3"] == pytest.approx(overlap, rel=1e-6)
        shift[long_axis] = 120.0
        a.post("/assembly/components/C2/transform", {"translate": shift})
        assert a.post("/mates/interference", {})["interferences"] == []
    finally:
        engine.raw("POST", a.url("/close"), json={"force": True})
