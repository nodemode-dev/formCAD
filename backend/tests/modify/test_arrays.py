import math

import pytest

from tests.modify.draw import circle, tag
from tests.support import geometry


def centres(doc):
    return sorted((round(e["center"][0], 9), round(e["center"][1], 9)) for e in doc.entities("circle"))


def test_rectangular_array_places_rows_times_columns_copies_at_the_exact_spacing(doc):
    c = circle(doc, "2,3", 1)
    doc.type("ARRAYRECT", tag(c), "", "AS", "N", "COU", "3", "2", "S", "15", "25", "")
    expected = sorted((2.0 + 15 * i, 3.0 + 25 * j) for i in range(3) for j in range(2))
    assert centres(doc) == expected
    assert all(geometry.close(e["radius"], 1.0) for e in doc.entities("circle"))


@pytest.mark.parametrize("items,fill,step", [(6, "360", 60.0), (3, "180", 90.0), (4, "-90", -30.0)])
def test_polar_array_spaces_items_evenly_over_the_fill_angle(doc, items, fill, step):
    c = circle(doc, "10,0", 1)
    doc.type("ARRAYPOLAR", tag(c), "", "0,0", "I", str(items), "F", fill, "AS", "N", "")
    expected = sorted((round(10 * math.cos(math.radians(step * k)), 9), round(10 * math.sin(math.radians(step * k)), 9)) for k in range(items))
    got = centres(doc)
    assert len(got) == items
    assert all(geometry.same_point(p, q, 1e-9) for p, q in zip(got, expected))
