import math
import shutil

import numpy as np
import pytest

from tests.assembly.helpers import matrix, point


@pytest.fixture()
def frame(docs, fixtures, tmp_path):
    shutil.copytree(fixtures / "weld", tmp_path / "weld")
    return docs.open(tmp_path / "weld" / "frame.fcad")


@pytest.fixture()
def piping(docs, fixtures, tmp_path):
    shutil.copytree(fixtures / "route", tmp_path / "route")
    return docs.open(tmp_path / "route" / "piping.fcad")


@pytest.fixture()
def harness(docs, fixtures, tmp_path):
    shutil.copytree(fixtures / "route", tmp_path / "route")
    return docs.open(tmp_path / "route" / "harness.fcad")


def size_of(profile: str) -> float:
    return float(profile.split()[-1].split("x")[0])


def members(frame):
    return {m["mid"]: m for m in frame.get("/weld/members")["members"]}


def test_mitered_rails_are_cut_to_the_path_length_plus_the_profile_width(frame):
    rails = [m for m in members(frame).values() if m["mid"].startswith("R")]
    assert len(rails) == 4
    for m in rails:
        path = float(np.linalg.norm(np.subtract(m["b"], m["a"])))
        assert m["length"] == pytest.approx(path + size_of(m["profile"]), abs=1e-6)
        assert (m["angle1"], m["angle2"]) == pytest.approx((45.0, 45.0), abs=1e-9)


def test_legs_butted_under_the_rails_lose_half_the_rail_depth(frame):
    all_members = members(frame)
    legs = [m for m in all_members.values() if m["mid"].startswith("L")]
    assert len(legs) == 4
    for m in legs:
        rail = all_members[m["against2"][0]]
        path = float(np.linalg.norm(np.subtract(m["b"], m["a"])))
        assert m["length"] == pytest.approx(path - size_of(rail["profile"]) / 2.0, abs=1e-6)


def test_cross_members_butted_between_legs_lose_half_a_leg_at_each_end(frame):
    all_members = members(frame)
    cross = [m for m in all_members.values() if m["mid"].startswith("X")]
    assert len(cross) == 2
    for m in cross:
        path = float(np.linalg.norm(np.subtract(m["b"], m["a"])))
        trim = sum(size_of(all_members[k[0]]["profile"]) / 2.0 for k in (m["against1"], m["against2"]))
        assert m["length"] == pytest.approx(path - trim, abs=1e-6)


def test_the_cut_list_groups_equal_members_and_counts_every_one(frame):
    cut = frame.get("/weld/cutlist")
    assert cut["members"] == 11
    rows = [r for r in cut["rows"] if r["kind"] == "member"]
    assert sum(r["qty"] for r in rows) == 11
    by_length = sorted((r["qty"], round(r["length"], 2)) for r in rows)
    assert by_length == sorted([(2, 1040.0), (2, 640.0), (1, 953.75), (2, 760.0), (4, 780.0)])
    for r in rows:
        assert r["total_length"] == pytest.approx(r["qty"] * r["length"], abs=1e-6)
    assert {r["kind"]: r["qty"] for r in cut["rows"] if r["kind"] != "member"} == {"end_cap": 4, "gusset": 2}


def anchors(doc, run):
    comps = {c["id"]: matrix(c["transform"]) for c in doc.get("/assembly")["components"]}
    out = []
    for p in run["points"]:
        out.append(point(comps[p["component"]], p["local"]) if isinstance(p, dict) else np.asarray(p, dtype=float))
    return out


def bend_table(points, radius):
    dirs = [(b - a) / np.linalg.norm(b - a) for a, b in zip(points, points[1:])]
    lengths = [float(np.linalg.norm(b - a)) for a, b in zip(points, points[1:])]
    angles = [math.acos(max(-1.0, min(1.0, float(u @ v)))) for u, v in zip(dirs, dirs[1:])]
    setbacks = [radius * math.tan(t / 2.0) for t in angles]
    straights = [lengths[i] - (setbacks[i - 1] if i > 0 else 0.0) - (setbacks[i] if i < len(angles) else 0.0) for i in range(len(lengths))]
    normals = [np.cross(u, v) / np.linalg.norm(np.cross(u, v)) for u, v in zip(dirs, dirs[1:])]
    turns = [0.0]
    for k in range(1, len(normals)):
        along = dirs[k]
        s = float(along @ np.cross(normals[k - 1], normals[k]))
        c = float(normals[k - 1] @ normals[k])
        turns.append(math.degrees(math.atan2(s, c)) % 360.0)
    developed = sum(lengths) - 2.0 * sum(setbacks) + radius * sum(angles)
    return straights, [math.degrees(t) for t in angles], turns, developed


def test_a_bent_tube_has_the_developed_length_of_its_straights_and_bend_arcs(piping):
    run = piping.get("/pipes/runs/R1")
    run = run.get("run", run)
    pts = anchors(piping, run)
    straights, angles, turns, developed = bend_table(pts, run["clr"])
    solved = piping.get("/pipes/runs/R1/solve")
    assert solved["total"] == pytest.approx(developed, abs=1e-5)
    assert solved["total"] == pytest.approx(568.045, abs=1e-3)
    cut = next(r for r in piping.get("/pipes/cutlist")["rows"] if r["run"] == "R1")
    assert cut["length"] == pytest.approx(developed, abs=1e-3) and cut["bends"] == len(angles)


def test_the_bender_table_gives_each_straight_turn_and_bend_angle(piping):
    run = piping.get("/pipes/runs/R1")
    run = run.get("run", run)
    straights, angles, turns, _ = bend_table(anchors(piping, run), run["clr"])
    table = piping.get("/pipes/runs/R1/bender")
    rows = table["rows"]
    assert [r["length"] for r in rows] == pytest.approx(straights[:-1], abs=1e-5)
    assert table["tail"] == pytest.approx(straights[-1], abs=1e-5)
    assert [r["angle"] for r in rows] == pytest.approx(angles, abs=1e-4)
    assert [r["rotation"] for r in rows] == pytest.approx(turns, abs=1e-4)
    spec = piping.get("/pipes")["specs"][0]
    assert [r["machine_angle"] for r in rows] == pytest.approx([a + spec["springback"] for a in angles], abs=1e-4)


def test_moving_an_anchor_component_recomputes_the_bender_table(piping):
    piping.post("/assembly/components/C2/transform", {"translate": [300.0, 0.0, 0.0]})
    run = piping.get("/pipes/runs/R1")
    run = run.get("run", run)
    straights, angles, turns, developed = bend_table(anchors(piping, run), run["clr"])
    rows = piping.get("/pipes/runs/R1/bender")["rows"]
    assert rows[-1]["rotation"] == pytest.approx(turns[-1], abs=1e-4)
    assert turns[-1] == pytest.approx(213.69, abs=0.01)
    assert piping.get("/pipes/runs/R1/solve")["total"] == pytest.approx(developed, abs=1e-5)


def fillet_length(points, radius):
    pts = [np.asarray(p, dtype=float) for p in points]
    total = sum(float(np.linalg.norm(b - a)) for a, b in zip(pts, pts[1:]))
    for a, v, b in zip(pts, pts[1:], pts[2:]):
        u, w = (v - a) / np.linalg.norm(v - a), (b - v) / np.linalg.norm(b - v)
        t = math.acos(max(-1.0, min(1.0, float(u @ w))))
        total += radius * t - 2.0 * radius * math.tan(t / 2.0)
    return total


def test_each_harness_segment_is_as_long_as_its_filleted_path_through_the_clips(harness):
    report = harness.get("/harness/report")
    nodes = report["nodes"]
    for seg in report["segments"]:
        chain = [seg["a"]] + list(seg["via"]) + [seg["b"]]
        pts = [nodes[n]["p"] for n in chain]
        assert seg["length"] == pytest.approx(fillet_length(pts, seg["radius_used"]), abs=1e-3)


def test_each_wire_is_cut_to_its_route_length_plus_both_end_allowances(harness):
    report = harness.get("/harness/report")
    seg_len = {s["id"]: s["length"] for s in report["segments"]}
    stated = {w["id"]: w for w in harness.get("/harness")["wires"]}
    rows = report["wires"]
    assert len(rows) == 11 and {w["id"] for w in rows} == set(stated)
    for w in rows:
        run = sum(seg_len[s] for s in w["route"])
        allowance = stated[w["id"]]["allowance_from"] + stated[w["id"]]["allowance_to"]
        assert w["run"] == pytest.approx(run, abs=1e-3)
        assert w["cut"] == pytest.approx(run + allowance, abs=1e-3)
