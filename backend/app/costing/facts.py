from app.assembly import props as P
from app.bodies import massprops, materials
from app.cam import model as cam_model
from app.sheetmetal import flat
from app.solid import work

MM3_TO_M3 = 1e-9


def material_row(profile: dict, name: str) -> dict:
    mats = profile.get("materials") or {}
    key = (name or "").strip().casefold()
    for k, v in mats.items():
        if k.casefold() == key:
            return v
    return {}


def price_of(profile: dict, name: str, props: dict) -> tuple:
    try:
        own = float(props.get("material_price")) if props.get("material_price") else None
    except ValueError:
        own = None
    if own is not None:
        return own, "property material_price"
    row = material_row(profile, name)
    if row.get("price_per_kg") is not None:
        return float(row["price_per_kg"]), "profile material %s" % name
    return float(profile["default_price_per_kg"]), "profile default price (placeholder)"


def cam_time(d, handles: set) -> dict | None:
    try:
        rows = cam_model.ops(d)
    except Exception:
        return None
    total, used = 0.0, 0
    for r in rows:
        if not r.get("enabled", True):
            continue
        st = r.get("state") or {}
        if st.get("status") != "ok":
            continue
        total += float((st.get("summary") or {}).get("time_s") or 0.0)
        used += 1
    if not used:
        return None
    return {"time_s": total, "ops": used, "source": "CAM operation times (state of each op, as last generated)"}


def additive_time(d, volumes: dict) -> dict | None:
    from app.additive import store as astore

    h = astore.header(d)
    t_total, sup, used = 0.0, 0.0, 0
    for plate in h["plates"]:
        last = plate.get("last") or {}
        if not last.get("time_s"):
            continue
        handles = [int(it["body"]) for it in plate.get("items", [])]
        mine = [x for x in handles if x in volumes]
        if not mine:
            continue
        plate_vol = sum(volumes.get(x, 0.0) for x in handles) or 1.0
        share = sum(volumes[x] for x in mine) / plate_vol
        t_total += float(last["time_s"]) * share
        sup += float(last.get("support_volume_mm3") or 0.0) * share
        used += 1
    if not used:
        return None
    return {"time_s": t_total, "support_volume_mm3": sup, "plates": used, "source": "slicer plate time shared by volume (last slice of each plate)"}


def part_facts(d, profile: dict, label: str = "", extra: dict | None = None) -> dict:
    props = P.get(d)
    props.update({k: v for k, v in (extra or {}).items() if v not in ("", None)})
    warnings: list = []
    out = {"label": label, "props": props, "bodies": [], "volume": 0.0, "mass": 0.0, "bbox": None, "sheet": None, "cam": None, "additive": None, "warnings": warnings, "material": props.get("material", "")}
    try:
        res = massprops.compute(d, None)
    except (massprops.MassError, work.SolidError) as err:
        warnings.append("No mass properties: %s" % err)
        return out
    mats = set()
    volumes: dict = {}
    lo, hi = None, None
    s = work.mm(d)
    for b in res["bodies"]:
        vol = b.get("volume")
        if vol is None:
            warnings.append("%s is not a closed solid, so it has no volume." % (b.get("name") or b.get("handle")))
            continue
        name = b.get("material") or props.get("material") or ""
        mats.add(name)
        dens = b.get("density")
        if dens is None:
            dens = material_row(profile, name).get("density")
            if dens is None and name:
                lib = materials.find(name)
                dens = float(lib["density"]) if lib is not None else None
            if dens is None:
                dens = profile.get("fallback_density")
            if dens is None:
                warnings.append("%s has no density: give its material a density, or set a fallback density in the costing profile." % (b.get("name") or b.get("handle")))
        mass = vol * MM3_TO_M3 * dens if dens is not None else None
        ent = d.get(int(b["handle"]))
        box = [c * s for c in (ent.summary or {}).get("bbox", [])] if ent is not None and (ent.summary or {}).get("bbox") else None
        out["bodies"].append({"handle": b["handle"], "name": b.get("name"), "volume": vol, "density": dens, "mass": mass, "material": name, "bbox": box})
        volumes[int(b["handle"])] = vol
        out["volume"] += vol
        out["mass"] = (out["mass"] or 0.0) + (mass or 0.0)
        if box:
            lo = box[:3] if lo is None else [min(a, c) for a, c in zip(lo, box[:3])]
            hi = box[3:] if hi is None else [max(a, c) for a, c in zip(hi, box[3:])]
    if lo is not None:
        out["bbox"] = lo + hi
    out["material"] = sorted(mats)[0] if mats else props.get("material", "")
    if not out["bodies"]:
        warnings.append("The part has no solid body.")
        return out
    if len(out["bodies"]) == 1:
        try:
            if flat.is_sheet(d, d.get(int(out["bodies"][0]["handle"]))):
                out["sheet"] = flat.cutlist_of(d, out["bodies"][0]["handle"])
        except Exception as err:
            warnings.append("Sheet metal properties not read: %s" % err)
    out["cam"] = cam_time(d, set(volumes))
    try:
        out["additive"] = additive_time(d, volumes)
    except Exception:
        out["additive"] = None
    return out


def process_of(facts: dict, forced: str = "") -> str:
    props = facts["props"]
    want = (forced or props.get("process") or "").strip().lower().replace(" ", "_")
    if want in ("machining", "sheet_metal", "additive", "purchased"):
        return want
    if props.get("unit_cost") or str(props.get("note", "")).startswith("Toolbox part"):
        return "purchased"
    if facts.get("sheet"):
        return "sheet_metal"
    if facts.get("additive"):
        return "additive"
    return "machining"
