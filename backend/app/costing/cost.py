import math

from app.costing import facts as F
from app.costing import profile as PR


def line(key: str, label: str, amount: float, basis: str) -> dict:
    return {"key": key, "label": label, "amount": amount, "basis": basis}


def machining_cycle(f: dict, p: dict) -> tuple:
    if p.get("use_cam") and f.get("cam"):
        return f["cam"]["time_s"], "CAM cycle time of %d operations" % f["cam"]["ops"], f["cam"]["source"]
    box = f.get("bbox")
    if not box or p["mrr_cm3_min"] <= 0:
        return 0.0, "no time: no bounding box or no removal rate", "none"
    a = p["stock_allowance_mm"]
    dims = [box[3 + i] - box[i] + 2 * a for i in range(3)]
    stock = dims[0] * dims[1] * dims[2]
    removed = max(stock - f["volume"], 0.0)
    t = removed / 1000.0 / p["mrr_cm3_min"] * 60.0
    return t, "removed %.1f cm3 at %.2f cm3/min" % (removed / 1000.0, p["mrr_cm3_min"]), "removal volume over a user removal rate (no CAM time in the file)"


def sheet_cycle(f: dict, p: dict) -> tuple:
    sh = f["sheet"]
    cut = float(sh["cutting_length_outside"]) + float(sh["cutting_length_inside"])
    pierces = 1 + int(sh["num_cutouts"])
    t = cut / p["cut_speed_mm_min"] * 60.0 + pierces * p["pierce_s"] + int(sh["num_bends"]) * p["bend_time_s"]
    return t, "cut %.0f mm at %.0f mm/min, %d pierces, %d bends x %.1f s" % (cut, p["cut_speed_mm_min"], pierces, sh["num_bends"], p["bend_time_s"]), "cut length over speed, pierces, bend count (bend time is a placeholder)"


def additive_cycle(f: dict, p: dict) -> tuple:
    if p.get("use_slicer") and f.get("additive"):
        a = f["additive"]
        return a["time_s"], "slicer time of %d plate(s) shared by volume" % a["plates"], a["source"]
    if p["build_rate_cm3_h"] <= 0:
        return 0.0, "no build rate", "none"
    vol = f["volume"] * (1.0 + p["support_fraction"]) / 1000.0
    layers = 0.0
    if f.get("bbox") and p["layer_height_mm"] > 0:
        layers = (f["bbox"][5] - f["bbox"][2]) / p["layer_height_mm"]
    t = vol / p["build_rate_cm3_h"] * 3600.0 + layers * p["recoat_s_per_layer"]
    return t, "%.1f cm3 with supports at %.2f cm3/h plus %d layers recoat" % (vol, p["build_rate_cm3_h"], layers), "volume over a user build rate (no slice in the file)"


def part_cost(f: dict, prof: dict, process: str = "", batch: int | None = None, volume: int | None = None) -> dict:
    proc = F.process_of(f, process)
    p = prof["processes"][proc]
    batch = int(batch or prof["batch"])
    volume = int(volume or prof["volume"])
    lines: list = []
    notes: list = list(f["warnings"])
    props = f["props"]
    price, price_src = F.price_of(prof, f["material"], props)
    mass = f.get("mass") or 0.0
    cycle_s, cycle_basis, cycle_src = 0.0, "", ""
    if proc == "purchased":
        unit = None
        try:
            unit = float(props["unit_cost"]) if props.get("unit_cost") else None
        except ValueError:
            notes.append("unit_cost is not a number.")
        if unit is None:
            unit = mass * price
            notes.append("No unit_cost property: priced as material only (%s)." % price_src)
            lines.append(line("material", "Material", unit, "%.4f kg x %.2f per kg (%s)" % (mass, price, price_src)))
        else:
            lines.append(line("purchased", "Purchased price", unit, "property unit_cost"))
        sub = unit
    else:
        mat_mass = mass
        loss = prof["scrap"]
        if proc == "machining":
            cycle_s, cycle_basis, cycle_src = machining_cycle(f, p)
            if f.get("bbox") and f.get("mass") and f["volume"] > 0:
                a = p["stock_allowance_mm"]
                dims = [f["bbox"][3 + i] - f["bbox"][i] + 2 * a for i in range(3)]
                dens = f["mass"] / (f["volume"] * F.MM3_TO_M3)
                mat_mass = dims[0] * dims[1] * dims[2] * F.MM3_TO_M3 * dens
                loss = 0.0
        elif proc == "sheet_metal":
            if not f.get("sheet"):
                notes.append("The part has no flat pattern, so it is not costed as sheet metal.")
                cycle_s, cycle_basis, cycle_src = 0.0, "no sheet data", "none"
            else:
                cycle_s, cycle_basis, cycle_src = sheet_cycle(f, p)
                sh = f["sheet"]
                dens = (f["mass"] / (f["volume"] * F.MM3_TO_M3)) if f["volume"] and f.get("mass") else 0.0
                util = max(p["utilisation"], 1e-6)
                mat_mass = sh["blank_area"] * sh["thickness"] * F.MM3_TO_M3 * dens / util
                loss = 0.0
        else:
            cycle_s, cycle_basis, cycle_src = additive_cycle(f, p)
            sup = (f["additive"] or {}).get("support_volume_mm3") if f.get("additive") and p.get("use_slicer") else f["volume"] * p["support_fraction"]
            if f["volume"] and f.get("mass"):
                dens = f["mass"] / (f["volume"] * F.MM3_TO_M3)
                mat_mass = (f["volume"] + (sup or 0.0)) * F.MM3_TO_M3 * dens
        material = mat_mass * price * (1.0 + loss)
        machine = cycle_s / 3600.0 * p["rate_per_h"]
        setup = p["setup_h"] * p["rate_per_h"] / batch
        labour = p["post_min"] / 60.0 * p["labour_per_h"]
        tooling = p["tooling"] / volume
        lines.append(line("material", "Material", material, "%.4f kg stock x %.2f per kg x (1 + %.0f%% loss), %s" % (mat_mass, price, loss * 100, price_src)))
        lines.append(line("machine", "Machine time", machine, "%.1f s x %.2f per h; %s" % (cycle_s, p["rate_per_h"], cycle_basis)))
        lines.append(line("setup", "Setup over batch", setup, "%.2f h x %.2f per h / batch of %d" % (p["setup_h"], p["rate_per_h"], batch)))
        lines.append(line("labour", "Labour and post-processing", labour, "%.1f min x %.2f per h" % (p["post_min"], p["labour_per_h"])))
        sub = material + machine + setup + labour + tooling
        if proc == "machining" and p["tool_life_min"] > 0:
            wear = (cycle_s / 60.0 / p["tool_life_min"]) * (p["tool_change_min"] / 60.0 * p["rate_per_h"] + p["tool_price"])
            lines.append(line("tool_wear", "Tool wear", wear, "cycle %.1f min / life %.0f min x (change %.1f min x rate + tool %.2f)" % (cycle_s / 60.0, p["tool_life_min"], p["tool_change_min"], p["tool_price"])))
            sub += wear
        lines.append(line("tooling", "Tooling over volume", tooling, "%.2f / volume of %d" % (p["tooling"], volume)))
    defect = sub * p["defect_pct"] / 100.0
    if defect:
        lines.append(line("defect", "Defect allowance", defect, "%.1f%% of the above" % p["defect_pct"]))
    base = sub + defect
    over = base * p["overhead_pct"] / 100.0
    margin = (base + over) * p["margin_pct"] / 100.0
    if over:
        lines.append(line("overhead", "Overhead", over, "%.1f%%" % p["overhead_pct"]))
    if margin:
        lines.append(line("margin", "Margin", margin, "%.1f%% on cost plus overhead" % p["margin_pct"]))
    unit = base + over + margin
    if not all(math.isfinite(x["amount"]) for x in lines):
        raise PR.ProfileError("A cost line is not a number; check the profile.")
    return {"process": proc, "unit_cost": unit, "lines": lines, "cycle_s": cycle_s, "cycle_basis": cycle_basis, "cycle_source": cycle_src, "mass_kg": f.get("mass"), "material": f["material"], "batch": batch, "volume": volume, "notes": notes}


def roll_up(rows: list) -> dict:
    total = sum(r["cost"]["unit_cost"] * r["qty"] for r in rows)
    by: dict = {}
    for r in rows:
        for ln in r["cost"]["lines"]:
            by[ln["key"]] = by.get(ln["key"], 0.0) + ln["amount"] * r["qty"]
    return {"total": total, "by_line": by, "parts": len(rows), "units": sum(r["qty"] for r in rows)}
