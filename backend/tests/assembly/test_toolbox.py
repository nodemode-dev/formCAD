import math
import shutil

import pytest

ISO_4032 = {
    "M6": (1.0, 10.0, 5.2),
    "M8": (1.25, 13.0, 6.8),
    "M10": (1.5, 16.0, 8.4),
    "M12": (1.75, 18.0, 10.8),
    "M16": (2.0, 24.0, 14.8),
    "M20": (2.5, 30.0, 18.0),
    "M24": (3.0, 36.0, 21.5),
}

ISO_4762 = {
    "M16": (2.0, 24.0, 16.0, 14.0),
    "M20": (2.5, 30.0, 20.0, 17.0),
    "M24": (3.0, 36.0, 24.0, 19.0),
    "M30": (3.5, 45.0, 30.0, 22.0),
}


def checked(engine, kind, params):
    return engine.post("/api/toolbox/check", {"source": {"kind": kind, "params": params}})


@pytest.mark.parametrize("size", sorted(ISO_4032))
def test_a_standard_hex_nut_takes_the_iso_4032_pitch_across_flats_and_height(engine, size):
    pitch, flats, height = ISO_4032[size]
    p = checked(engine, "hex_nut", {"size": size})["params"]
    assert p["d"] == float(size[1:])
    assert (p["pitch"], p["across_flats"], p["thickness"]) == pytest.approx((pitch, flats, height), abs=1e-9)


@pytest.mark.parametrize("size", sorted(ISO_4762))
def test_a_standard_socket_head_cap_screw_takes_the_iso_4762_head_and_socket_sizes(engine, size):
    pitch, head_d, head_h, socket = ISO_4762[size]
    p = checked(engine, "socket_screw", {"size": size, "length": 60.0})["params"]
    assert p["d"] == float(size[1:]) and p["length"] == 60.0
    assert (p["pitch"], p["head_d"], p["head_h"], p["socket_s"]) == pytest.approx((pitch, head_d, head_h, socket), abs=1e-9)


@pytest.mark.kernel
def test_a_generated_m8_nut_spans_its_across_flats_across_corners_and_height(engine, tmp_path):
    made = engine.post("/api/toolbox/part", {"source": {"kind": "hex_nut", "params": {"size": "M8"}}, "folder": str(tmp_path)})
    box = made["summary"]["bbox"]
    spans = sorted(box[i + 3] - box[i] for i in range(3))
    assert spans == pytest.approx(sorted([13.0, 13.0 * 2.0 / math.sqrt(3.0), 6.8]), abs=1e-6)
    assert made["summary"]["valid"] and made["summary"]["closed"]


@pytest.mark.kernel
def test_the_toolbox_assembly_fixture_has_eight_parts_no_interference_and_six_free_spins(docs, fixtures, tmp_path):
    shutil.copytree(fixtures / "toolbox", tmp_path / "toolbox")
    doc = docs.open(tmp_path / "toolbox" / "assembly.fcad")
    listing = doc.get("/assembly")
    assert listing["counts"]["components"] == 8 and listing["counts"]["missing"] == 0
    found = doc.post("/mates/interference", {})
    assert found["interferences"] == [] and found["stats"]["pairs"] == 8 * 7 // 2
    status = doc.get("/mates/status")
    assert status["dof"] == 6
    spinning = [c for c, v in status["components"].items() if v["dof"] == 1]
    assert len(spinning) == 6
    for c in spinning:
        assert [m["type"] for m in status["components"][c]["modes"]] == ["rotation"]
