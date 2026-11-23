import math

import pytest

from tests.electronics.gerber_reader import contour_area
from tests.electronics.kit import board, gerbers, netlist, place, smd, tht

POUR = [[2, 2], [28, 2], [28, 18], [2, 18]]


def inside(contours, p) -> bool:
    x, y = p
    hit = False
    for c in contours:
        for k in range(len(c)):
            (x0, y0), (x1, y1) = c[k], c[(k + 1) % len(c)]
            if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
                hit = not hit
    return hit


def seg_point(a, b, p) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(a[0] + t * dx - p[0], a[1] + t * dy - p[1])


def poured(doc, tmp_path, connect="thermal"):
    board(doc, (0, 0, 30, 20))
    netlist(doc, {"GND": ["J1.1", "J2.1"], "SIG": ["U1.1"]})
    place(doc, "J1", 8, 10, [tht(1, 0, 0, 1.8, 1.0)])
    place(doc, "J2", 14, 10, [tht(1, 0, 0, 1.8, 1.0)])
    place(doc, "U1", 21, 10, [smd(1, 0, 0, 1.0, 1.0)], side="bottom")
    doc.post("/pcb/zones", {"net": "GND", "layer": "B.Cu", "polygon": POUR, "clearance": 0.3, "connect": connect, "gap": 0.3, "spoke": 0.4, "spokes": 4})
    g = gerbers(doc, tmp_path / connect)["layers"]["Copper,L2,Bot"]
    return g, [c for r in g.regions if r.polarity == "D" for c in r.contours]


def test_the_poured_region_in_the_gerber_has_the_fill_area_the_board_reports(doc, tmp_path):
    g, contours = poured(doc, tmp_path)
    reported = doc.get("/pcb/zones/fill")["areas"]
    assert math.isclose(sum(abs(contour_area(c)) for c in contours), sum(reported.values()), rel_tol=1e-4)
    assert sum(reported.values()) < 26 * 16
    assert not inside(contours, (21.0, 10.0)) and inside(contours, (5.0, 5.0))


@pytest.mark.xfail(strict=True, reason="DEFECT: the pour's clearance cut-out around a pad of another net is an inscribed polygon, so the copper written to the Gerber comes about 0.003 mm inside the 0.3 mm clearance the zone states at each rounded corner; clearance is a minimum and the cut-out should be circumscribed (zone clearance setting, design rule check chapter 19)")
def test_the_pour_keeps_its_clearance_from_a_pad_of_another_net(doc, tmp_path):
    _g, contours = poured(doc, tmp_path)
    corners = [(20.5, 9.5), (21.5, 9.5), (21.5, 10.5), (20.5, 10.5)]
    nearest = min(seg_point(c[k], c[(k + 1) % len(c)], q) for c in contours for k in range(len(c)) for q in corners)
    assert nearest >= 0.3 - 1e-3


def ring_arcs(contours, centre, radius, steps=720) -> int:
    flags = [inside(contours, (centre[0] + radius * math.cos(2 * math.pi * (k + 0.5) / steps), centre[1] + radius * math.sin(2 * math.pi * (k + 0.5) / steps))) for k in range(steps)]
    return sum(1 for k in range(steps) if flags[k] and not flags[k - 1])


@pytest.mark.parametrize("connect, arcs", [("thermal", 4), ("solid", 0)])
def test_a_pad_of_the_pour_net_joins_it_by_spokes_with_thermal_relief_and_fully_when_solid(doc, tmp_path, connect, arcs):
    _g, contours = poured(doc, tmp_path, connect)
    ring = 0.9 + 0.15
    if connect == "solid":
        assert all(inside(contours, (8 + ring * math.cos(a / 10), 10 + ring * math.sin(a / 10))) for a in range(63))
    else:
        assert ring_arcs(contours, (8, 10), ring) == arcs
    assert doc.get("/pcb/ratsnest")["ratsnest"] == []


def test_without_the_pour_the_two_ground_pads_are_left_unconnected(doc, tmp_path):
    poured(doc, tmp_path)
    doc.delete("/pcb/zones/%s" % doc.get("/pcb")["zones"][0]["id"])
    assert [r["net"] for r in doc.get("/pcb/ratsnest")["ratsnest"]] == ["GND"]
