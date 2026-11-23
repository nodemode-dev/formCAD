import math

import numpy as np
import pytest

from tests.assembly.helpers import copy_fixture, copy_parts, crank_slider_lengths, matrix, transform_of

SERVICE = [(("C6", "C10"), 60.0), (("C5",), 45.0), (("C4", "C9"), 30.0), (("C2", "C3"), 15.0), (("C7", "C8"), 70.0)]
SHOTS = [("Hold", 1.0), ("Explode", 4.0), ("Hold exploded", 1.0), ("Collapse", 2.4), ("Run mechanism", 3.0)]


@pytest.fixture()
def mechanism(docs, fixtures, tmp_path):
    return docs.open(copy_fixture(fixtures, tmp_path, "mechanism.fcad", "mechanism"))


@pytest.fixture()
def storyboard(docs, fixtures, tmp_path):
    return docs.open(copy_fixture(fixtures, tmp_path, "mechanism-storyboard.fcad", "mechanism"))


def expected_lift(steps_done: int) -> dict:
    out = {}
    for comps, dist in SERVICE[:steps_done]:
        for c in comps:
            out[c] = out.get(c, 0.0) + dist
    return out


@pytest.mark.parametrize("t", [1, 3, 5])
def test_the_service_explode_moves_each_group_up_by_its_step_distance(mechanism, t):
    pose = mechanism.get("/mates/explode/Service/pose", t=t)
    lift = expected_lift(t)
    for cid in ["C%d" % n for n in range(2, 11)]:
        base = transform_of(mechanism, cid)
        if cid not in lift:
            assert cid not in pose["matrices"] or np.allclose(matrix(pose["matrices"][cid]), base, atol=1e-12)
            continue
        moved = matrix(pose["matrices"][cid])
        expect = base.copy()
        expect[2, 3] += lift[cid]
        assert np.allclose(moved, expect, atol=1e-9)


def test_a_new_explode_step_moves_the_part_by_the_distance_along_the_unit_direction(engine, fixtures, tmp_path):
    parts = copy_parts(fixtures, tmp_path / "parts", ("base", "pin"))
    a = engine.new_doc("", "assembly")
    try:
        a.post("/assembly/components", {"path": str(parts / "base.fcad")})
        a.post("/assembly/components", {"path": str(parts / "pin.fcad")})
        a.post("/mates/explode", {"name": "Out"})
        a.post("/mates/explode/Out/steps", {"comps": ["C2"], "dir": [3, 4, 0], "dist": 10.0})
        a.post("/mates/explode/Out/steps", {"comps": ["C2"], "dir": "z", "dist": 25.0})
        one = matrix(a.get("/mates/explode/Out/pose", t=1)["matrices"]["C2"])
        two = matrix(a.get("/mates/explode/Out/pose", t=2)["matrices"]["C2"])
        assert np.allclose(one[:3, 3], (6.0, 8.0, 0.0), atol=1e-9)
        assert np.allclose(two[:3, 3], (6.0, 8.0, 25.0), atol=1e-9)
        assert np.allclose(transform_of(a, "C2")[:3, 3], 0.0)
    finally:
        engine.raw("POST", a.url("/close"), json={"force": True})


def test_the_storyboard_plan_has_the_frames_of_its_shot_durations(storyboard):
    board = storyboard.get("/storyboards")["boards"]["Exploded"]
    plan = board["plan"]
    fps = board["fps"]
    assert fps == 30
    assert [(s["name"], s["frames"]) for s in plan["spans"]] == [(n, round(d * fps)) for n, d in SHOTS]
    assert plan["frames"] == 342 and plan["seconds"] == pytest.approx(11.4, abs=1e-9)
    firsts = [s["first"] for s in plan["spans"]]
    assert firsts == [round(sum(d for _, d in SHOTS[:k]) * fps) for k in range(len(SHOTS))]


def test_the_run_mechanism_shot_turns_the_crank_linearly_and_moves_the_slider_by_the_closed_form(storyboard):
    span = next(s for s in storyboard.get("/storyboards")["boards"]["Exploded"]["plan"]["spans"] if s["name"] == "Run mechanism")
    frames = storyboard.get("/storyboards/Exploded/frames", first=span["first"] + 10, count=20)["frames"]
    values = [f["drive"]["value"] for f in frames]
    steps = np.diff(values)
    assert np.allclose(steps, 180.0 / span["frames"], atol=1e-9)
    r, l = crank_slider_lengths(storyboard)
    for f in frames:
        t = math.radians(f["drive"]["value"])
        x = r * math.cos(t) + math.sqrt(l * l - (r * math.sin(t)) ** 2)
        assert abs(matrix(f["matrices"]["C6"])[0, 3] - x) < 1e-6
