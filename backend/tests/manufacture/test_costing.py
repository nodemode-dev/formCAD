import pytest

RATE, SETUP_H, LABOUR, POST_MIN, TOOLING = 90.0, 0.5, 30.0, 3.0, 50.0
DEFECT, OVERHEAD, MARGIN = 2.0, 10.0, 20.0
MRR, ALLOW, DENSITY, PRICE = 5.0, 2.0, 2700.0, 4.0
BATCH, VOLUME = 10, 100
SIZE = (50.0, 40.0, 20.0)

PROFILE = {
    "fallback_density": DENSITY,
    "default_price_per_kg": PRICE,
    "scrap": 0.05,
    "batch": BATCH,
    "volume": VOLUME,
    "processes": {"machining": {"rate_per_h": RATE, "setup_h": SETUP_H, "labour_per_h": LABOUR, "post_min": POST_MIN, "tooling": TOOLING, "defect_pct": DEFECT, "overhead_pct": OVERHEAD, "margin_pct": MARGIN, "mrr_cm3_min": MRR, "stock_allowance_mm": ALLOW, "tool_life_min": 0.0, "use_cam": False}},
}


def hand_cost(batch):
    part = SIZE[0] * SIZE[1] * SIZE[2]
    stock = (SIZE[0] + 2 * ALLOW) * (SIZE[1] + 2 * ALLOW) * (SIZE[2] + 2 * ALLOW)
    material = stock * 1e-9 * DENSITY * PRICE
    seconds = (stock - part) / 1000.0 / MRR * 60.0
    machine = seconds / 3600.0 * RATE
    sub = material + machine + SETUP_H * RATE / batch + POST_MIN / 60.0 * LABOUR + TOOLING / VOLUME
    base = sub * (1 + DEFECT / 100.0)
    return {"material": material, "machine": machine, "seconds": seconds, "unit": base * (1 + OVERHEAD / 100.0) * (1 + MARGIN / 100.0)}


@pytest.fixture()
def block(doc, kernel):
    doc.set_var("INSUNITS", 4)
    doc.command("box", corner=[0, 0, 0], size=list(SIZE))
    doc.put("/costing/profile", PROFILE)
    return doc


@pytest.mark.kernel
def test_a_machined_block_costs_stock_mass_times_price_plus_removal_time_times_rate_and_the_profile_terms(block):
    want = hand_cost(BATCH)
    est = block.get("/costing/estimate", process="machining")
    assert est["placeholder"] is False
    row = est["rows"][0]["cost"]
    lines = {ln["key"]: ln["amount"] for ln in row["lines"]}
    assert row["mass_kg"] == pytest.approx(SIZE[0] * SIZE[1] * SIZE[2] * 1e-9 * DENSITY, rel=1e-6)
    assert lines["material"] == pytest.approx(want["material"], rel=1e-6)
    assert row["cycle_s"] == pytest.approx(want["seconds"], rel=1e-6)
    assert lines["machine"] == pytest.approx(want["machine"], rel=1e-6)
    assert row["unit_cost"] == pytest.approx(want["unit"], rel=1e-6)
    assert est["total"] == pytest.approx(want["unit"], rel=1e-6)


@pytest.mark.kernel
def test_a_larger_batch_spreads_only_the_setup_cost(block):
    small = block.get("/costing/estimate", process="machining", batch=10)["total"]
    large = block.get("/costing/estimate", process="machining", batch=50)["total"]
    assert small - large == pytest.approx(hand_cost(10)["unit"] - hand_cost(50)["unit"], rel=1e-6)
    assert large == pytest.approx(hand_cost(50)["unit"], rel=1e-6)


@pytest.mark.kernel
def test_an_estimate_without_a_profile_of_your_own_is_flagged_as_placeholder(doc, kernel):
    doc.set_var("INSUNITS", 4)
    doc.command("box", corner=[0, 0, 0], size=list(SIZE))
    est = doc.get("/costing/estimate", process="machining")
    assert est["placeholder"] is True and est["note"]
