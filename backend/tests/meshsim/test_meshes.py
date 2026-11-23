import math

import pytest

from tests.meshsim import helpers as h

pytestmark = pytest.mark.kernel


def cube_triangles(size, at=(0.0, 0.0, 0.0)):
    x0, y0, z0 = at
    p = [(x0 + size * i, y0 + size * j, z0 + size * k) for k in (0, 1) for j in (0, 1) for i in (0, 1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    out = []
    for a, b, c, d in quads:
        out.append((p[a], p[b], p[c]))
        out.append((p[a], p[c], p[d]))
    return out


def imported(doc, tmp_path, tris, name):
    path = tmp_path / name
    h.write_stl(path, tris)
    before = {e["handle"] for e in doc.entities("meshbody")}
    reply = doc.command("import", path=str(path), unit="mm")
    assert not reply.get("error"), reply.get("error")
    made = [e["handle"] for e in doc.entities("meshbody") if e["handle"] not in before]
    assert len(made) == 1
    return made[0]


def mesh_of_solid(doc, solid, detail=1.0):
    return h.handle_of(doc.command("meshfromsolid", handle=solid, detail=detail))


def report(doc, handle):
    return doc.get("/meshes/%d/report" % handle)["report"]


def test_a_mesh_made_from_a_box_has_the_box_volume_and_area_and_is_watertight(doc, tmp_path):
    h.metric(doc)
    a, b, c = 10.0, 20.0, 30.0
    m = mesh_of_solid(doc, h.box(doc, [a, b, c]))
    tris = h.export_stl(doc, tmp_path / "box.stl", [m])
    assert h.volume(tris) == pytest.approx(a * b * c, rel=1e-6)
    assert h.area(tris) == pytest.approx(2 * (a * b + b * c + a * c), rel=1e-6)
    assert h.open_edges(tris) == 0
    r = report(doc, m)
    assert r["closed"] and r["naked_edges"] == 0
    assert r["volume"] == pytest.approx(h.volume(tris), rel=1e-6)


def test_a_mesh_made_from_a_sphere_is_closed_inscribed_and_within_one_percent_of_its_volume(doc, tmp_path):
    h.metric(doc)
    radius = 10.0
    m = mesh_of_solid(doc, h.handle_of(doc.command("sphere", center=[0, 0, 0], radius=radius)))
    tris = h.export_stl(doc, tmp_path / "sphere.stl", [m])
    exact = 4.0 / 3.0 * math.pi * radius ** 3
    v = h.volume(tris)
    assert v < exact and v == pytest.approx(exact, rel=1e-2)
    assert h.area(tris) == pytest.approx(4 * math.pi * radius ** 2, rel=1e-2)
    assert h.open_edges(tris) == 0
    assert max(abs(math.dist(p, (0, 0, 0)) - radius) for t in tris for p in t) < 1e-4 * radius


@pytest.mark.parametrize("command, args", [("meshrepair", {}), ("meshfill", {"max_edges": 8})])
def test_closing_a_one_triangle_hole_restores_a_watertight_cube_of_the_right_volume(doc, tmp_path, command, args):
    h.metric(doc)
    tris = cube_triangles(10.0)
    del tris[3]
    m = imported(doc, tmp_path, tris, "holed.stl")
    before = report(doc, m)
    assert before["naked_edges"] == 3 and not before["closed"]
    reply = doc.command(command, handle=m, **args)
    assert not reply.get("error"), reply.get("error")
    fixed = h.export_stl(doc, tmp_path / "fixed.stl", [m])
    assert h.open_edges(fixed) == 0
    assert len(fixed) == 12
    assert h.volume(fixed) == pytest.approx(1000.0, rel=1e-9)
    assert report(doc, m)["closed"]


def test_reducing_a_sphere_mesh_cuts_the_triangles_and_stays_within_the_reported_deviation(doc, tmp_path):
    h.metric(doc)
    radius = 10.0
    m = mesh_of_solid(doc, h.handle_of(doc.command("sphere", center=[0, 0, 0], radius=radius)))
    original = h.export_stl(doc, tmp_path / "a.stl", [m])
    chord = max(radius - abs(sum(n * v for n, v in zip(normal(t), t[0]))) for t in original)
    res = doc.command("meshreduce", handle=m, mode="proportion", value=0.25)["result"]["results"][0]
    reduced = h.export_stl(doc, tmp_path / "b.stl", [m])
    assert res["before"] == len(original) and res["after"] == len(reduced)
    assert len(reduced) <= 0.26 * len(original)
    assert h.open_edges(reduced) == 0
    bound = res["deviation_max"] + chord
    assert max(abs(math.dist(p, (0, 0, 0)) - radius) for t in reduced for p in t) <= bound + 1e-6
    assert abs(h.volume(reduced) - h.volume(original)) <= h.area(original) * res["deviation_max"]


def normal(t):
    a, b, c = t
    u = [b[i] - a[i] for i in range(3)]
    w = [c[i] - a[i] for i in range(3)]
    n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
    s = math.sqrt(sum(x * x for x in n))
    return [x / s for x in n]


@pytest.mark.parametrize("op, expected", [("union", 1000 + 1000 - 336), ("intersection", 336), ("difference", 1000 - 336)])
def test_mesh_booleans_of_two_overlapping_cubes_follow_inclusion_and_exclusion(doc, tmp_path, op, expected):
    h.metric(doc)
    a = imported(doc, tmp_path, cube_triangles(10.0), "a.stl")
    b = imported(doc, tmp_path, cube_triangles(10.0, (4.0, 3.0, 2.0)), "b.stl")
    reply = doc.command("meshboolean", op=op, base=a, tools=[b])
    assert not reply.get("error"), reply.get("error")
    assert reply["result"]["volume"] == pytest.approx(expected, rel=1e-9)
    tris = h.export_stl(doc, tmp_path / "out.stl", [a])
    assert h.volume(tris) == pytest.approx(expected, rel=1e-9)
    assert h.open_edges(tris) == 0
    assert [e["handle"] for e in doc.entities("meshbody")] == [a]


def test_a_box_mesh_converted_to_a_solid_and_back_keeps_its_volume_and_six_faces(doc, tmp_path):
    h.metric(doc)
    m = imported(doc, tmp_path, cube_triangles(10.0, (1.0, 2.0, 3.0)), "cube.stl")
    res = doc.command("meshtobrep", handle=m, merge_planar=True)["result"]
    assert res["valid"] and res["closed"] and res["solids"] == 1
    assert res["faces"] == 6
    props = doc.get("/solids/%d/massprops" % res["handle"])
    assert props["volume"] == pytest.approx(1000.0, rel=1e-9)
    assert props["centroid"] == pytest.approx([6.0, 7.0, 8.0], abs=1e-9)
    back = mesh_of_solid(doc, res["handle"])
    tris = h.export_stl(doc, tmp_path / "back.stl", [back])
    assert h.volume(tris) == pytest.approx(1000.0, rel=1e-6)
    assert h.open_edges(tris) == 0


@pytest.mark.xfail(strict=True, reason="DEFECT: MESHFROMSOLID prompts 'Detail (1 is the display detail, larger is finer)', but a detail of 4 gives the same or fewer triangles than 1, because the chord tolerance grows with detail (solid/work.py detail_params); larger should be finer.")
def test_a_larger_mesh_from_solid_detail_gives_a_finer_mesh(doc, tmp_path):
    h.metric(doc)
    s = h.handle_of(doc.command("sphere", center=[0, 0, 0], radius=10.0))
    coarse = h.export_stl(doc, tmp_path / "a.stl", [mesh_of_solid(doc, s, 1.0)])
    fine = h.export_stl(doc, tmp_path / "b.stl", [mesh_of_solid(doc, s, 4.0)])
    exact = 4.0 / 3.0 * math.pi * 1000.0
    assert len(fine) > len(coarse)
    assert abs(h.volume(fine) - exact) < abs(h.volume(coarse) - exact)
