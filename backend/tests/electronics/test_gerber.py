import math

import pytest

from tests.electronics.gerber_reader import Gerber, contour_area
from tests.electronics.kit import HOLE, NETS, TRACK_A, TRACK_B, VIA, expected_pads, gerbers, near, output_board

NET_OF = {tuple(p.split(".")): n for n, pins in NETS.items() for p in pins}
TOL = 1e-6


@pytest.fixture()
def out(doc, tmp_path):
    output_board(doc)
    return gerbers(doc, tmp_path / "board", mask_margin=0.1, paste_margin=0.0, tent_vias=True)


def test_the_reader_follows_the_format_statement_units_apertures_and_operations():
    text = "%MOIN*%\n%FSLAX24Y24*%\n%ADD10C,0.01*%\n%ADD11R,0.1X0.05*%\nD10*\nX0Y0D02*\nX10000Y0D01*\nD11*\nX5000Y-2500D03*\nG36*\nX0Y0D02*\nX10000Y0D01*\nX10000Y10000D01*\nX0Y0D01*\nG37*\nM02*\n"
    g = Gerber(text)
    assert g.units == "in" and g.format == (2, 4)
    assert g.draws[0].start == (0.0, 0.0) and math.isclose(g.draws[0].end[0], 25.4)
    assert near((g.flashes[0].x, g.flashes[0].y), (12.7, -6.35)) and near(g.extent(11), (2.54, 1.27))
    assert math.isclose(abs(contour_area(g.regions[0].contours[0])), 25.4 * 25.4 / 2)
    with pytest.raises(ValueError):
        Gerber("%MOMM*%\n%FSLAX24Y24*%\n%ADD10C,1*%\nD10*\nX1234567Y0D03*\nM02*\n")


def test_a_two_layer_board_writes_every_layer_with_its_gerber_x2_file_function_and_polarity(out):
    layers = out["layers"]
    assert set(layers) == {"Copper,L1,Top", "Copper,L2,Bot", "Soldermask,Top", "Soldermask,Bot", "Paste,Top", "Paste,Bot", "Legend,Top", "Legend,Bot", "Profile,NP"}
    assert layers["Copper,L1,Top"].polarity() == "Positive" and layers["Copper,L2,Bot"].polarity() == "Positive"
    assert all(g.units == "mm" and g.format is not None for g in layers.values())


@pytest.mark.parametrize("function, layer", [("Copper,L1,Top", "F.Cu"), ("Copper,L2,Bot", "B.Cu")])
def test_copper_layers_flash_every_pad_and_via_at_its_position_with_its_size_and_net(out, function, layer):
    g = out["layers"][function]
    want = expected_pads(layer)
    pads = g.pad_flashes()
    assert set(pads) == set(want)
    for key, ((x, y), (w, h), _q) in want.items():
        f = pads[key]
        assert near((f.x, f.y), (x, y), TOL), key
        assert near(g.extent(f.aperture), (w, h), TOL), key
        assert f.attrs[".N"] == [NET_OF[key]]
    others = [f for f in g.flashes if ".P" not in f.attrs]
    assert len(others) == 1
    assert near((others[0].x, others[0].y), (VIA["x"], VIA["y"])) and near(g.extent(others[0].aperture), (VIA["dia"], VIA["dia"]))


@pytest.mark.parametrize("function, track", [("Copper,L1,Top", TRACK_A), ("Copper,L2,Bot", TRACK_B)])
def test_tracks_are_drawn_on_their_layer_with_a_round_aperture_of_their_width(out, function, track):
    g = out["layers"][function]
    pts = track["points"]
    want = {frozenset({tuple(map(float, pts[i])), tuple(map(float, pts[i + 1]))}) for i in range(len(pts) - 1)}
    got = {frozenset({tuple(round(v, 6) for v in d.start), tuple(round(v, 6) for v in d.end)}) for d in g.draws}
    assert got == want
    for d in g.draws:
        assert g.apertures[d.aperture].template == "C" and math.isclose(g.extent(d.aperture)[0], track["width"], abs_tol=TOL)
        assert d.mode == "G01" and d.attrs[".N"] == [track["net"]]


@pytest.mark.parametrize("function, layer", [("Soldermask,Top", "F.Cu"), ("Soldermask,Bot", "B.Cu")])
def test_the_solder_mask_opens_over_every_pad_grown_by_the_mask_margin_and_keeps_tented_vias_covered(out, function, layer):
    g = out["layers"][function]
    assert g.polarity() == "Negative"
    want = expected_pads(layer)
    flashes = [f for f in g.flashes if not near((f.x, f.y), (HOLE["x"], HOLE["y"]))]
    assert len(flashes) == len(want)
    for (x, y), (w, h), _q in want.values():
        match = [f for f in flashes if near((f.x, f.y), (x, y))]
        assert len(match) == 1
        assert near(g.extent(match[0].aperture), (w + 0.2, h + 0.2), TOL)
    assert not [f for f in g.flashes if near((f.x, f.y), (VIA["x"], VIA["y"]))]


def test_an_untented_via_gets_a_mask_opening_of_its_diameter_plus_the_margin(doc, tmp_path):
    output_board(doc)
    g = gerbers(doc, tmp_path / "board", mask_margin=0.1, tent_vias=False)["layers"]["Soldermask,Top"]
    via = [f for f in g.flashes if near((f.x, f.y), (VIA["x"], VIA["y"]))]
    assert len(via) == 1 and near(g.extent(via[0].aperture), (VIA["dia"] + 0.2, VIA["dia"] + 0.2))


def test_the_paste_layer_covers_surface_pads_at_their_size_and_leaves_through_hole_pads_bare(out):
    g = out["layers"]["Paste,Top"]
    want = {k: v for k, v in expected_pads("F.Cu").items() if not v[2].get("drill")}
    assert len(g.flashes) == len(want)
    for (x, y), (w, h), _q in want.values():
        match = [f for f in g.flashes if near((f.x, f.y), (x, y))]
        assert len(match) == 1 and near(g.extent(match[0].aperture), (w, h), TOL)


def test_the_outline_layer_traces_the_board_edge_as_one_closed_loop_of_the_board_area(out):
    g = out["layers"]["Profile,NP"]
    assert all(d.mode == "G01" for d in g.draws)
    for a, b in zip(g.draws, g.draws[1:]):
        assert near(a.end, b.start)
    assert near(g.draws[0].start, g.draws[-1].end)
    loop = [d.start for d in g.draws]
    assert math.isclose(abs(contour_area(loop)), 40.0 * 30.0, abs_tol=1e-6)
    xs, ys = [p[0] for p in loop], [p[1] for p in loop]
    assert (min(xs), min(ys), max(xs), max(ys)) == (0.0, 0.0, 40.0, 30.0)


def test_a_board_away_from_the_origin_keeps_pads_and_holes_in_place_relative_to_its_outline(doc, tmp_path):
    output_board(doc, origin=(50.0, 40.0))
    got = gerbers(doc, tmp_path / "board")
    edge = got["layers"]["Profile,NP"]
    x0 = min(min(d.start[0], d.end[0]) for d in edge.draws)
    y0 = min(min(d.start[1], d.end[1]) for d in edge.draws)
    top = got["layers"]["Copper,L1,Top"].pad_flashes()
    for key, ((x, y), _wh, _q) in expected_pads("F.Cu").items():
        assert near((top[key].x - x0, top[key].y - y0), (x, y)), key
    holes = [(h.x - x0, h.y - y0) for d in got["drills"] for h in d.hits]
    for key in (("J1", "1"), ("J1", "2")):
        f = top[key]
        assert any(near((f.x - x0, f.y - y0), h) for h in holes), key
    assert any(near(h, (HOLE["x"], HOLE["y"])) for h in holes)


def test_rounded_pads_from_the_land_pattern_generator_flash_at_their_pads_with_the_pad_extent(doc, tmp_path):
    from tests.electronics.kit import board, part, schematic, wire, world

    schematic(doc, part("R", 0, 0, value="1k"), part("R", 20, -20, value="1k"), part("LED", 60, -40), wire("R1.2", "R2.1"), wire("R2.2", "D1.2"))
    board(doc, (0, 0, 30, 20))
    doc.post("/pcb/sync")
    g = gerbers(doc, tmp_path / "lib")["layers"]["Copper,L1,Top"]
    pads = g.pad_flashes()
    placed = doc.get("/pcb")["parts"]
    assert len(pads) == sum(len(p["pads"]) for p in placed) == 6
    for p in placed:
        for q in p["pads"]:
            f = pads[(p["refdes"], q["number"])]
            assert near((f.x, f.y), world(p["x"], p["y"], (q["x"], q["y"]), p["rot"], p["side"]))
            assert q["shape"] == "roundrect" and g.apertures[f.aperture].template in g.macros
            assert near(g.extent(f.aperture), (q["w"], q["h"]), TOL)
