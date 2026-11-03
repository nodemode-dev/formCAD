import copy
import csv
import io
import math
import os

HEADER = "EMISSIONS"
MAX_ROWS = 500
MAX_FILE = 1_000_000
PROVENANCE = "Entered by the user; no external source recorded."

CAVEATS = [
    "Screening estimate: mass times an emission factor per material, not a life cycle assessment.",
    "The factor boundary (cradle-to-gate or not), geography, recycled content and the edition year are those of the table entry; check them before comparing results.",
    "Process energy, transport, use and end of life are included only where a process factor or a transport entry is given.",
    "FormCAD ships no emission factor table. UK government conversion factors (Open Government Licence v3.0, attribution required) are a permitted source once the user enters or imports rows; the ICE database may not be embedded or imported by a tool without its own licence.",
    "Mass comes from the model volume and the density of the assigned material; parts without a density or a factor are listed, not guessed.",
]
ATTRIBUTION = "Contains public sector information licensed under the Open Government Licence v3.0 (applies to rows entered from the UK government conversion factors)."


class EmissionError(ValueError):
    pass


def blank() -> dict:
    return {"factors": {}, "process_kg_per_h": {}, "transport": None}


def current(d) -> dict:
    out = blank()
    raw = d.header.get(HEADER)
    if isinstance(raw, dict):
        out["factors"] = copy.deepcopy(raw.get("factors") or {})
        out["process_kg_per_h"] = copy.deepcopy(raw.get("process_kg_per_h") or {})
        out["transport"] = copy.deepcopy(raw.get("transport"))
    return out


def num(v, label: str, high: float = 1e5) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise EmissionError("%s needs a number." % label)
    if not math.isfinite(x) or x < 0 or x > high:
        raise EmissionError("%s must be between 0 and %g." % (label, high))
    return x


def clean_factor(name: str, row: dict) -> dict:
    n = str(name or "").strip()
    if not n or len(n) > 80:
        raise EmissionError("A factor needs a material name of 1 to 80 characters.")
    if not isinstance(row, dict):
        raise EmissionError("A factor is an object.")
    out = {"kg_co2e_per_kg": num(row.get("kg_co2e_per_kg"), "Factor of %s" % n, 1e4)}
    for k in ("source", "boundary", "geography", "edition", "licence"):
        out[k] = str(row.get(k) or "")[:300]
    out["source"] = out["source"] or PROVENANCE
    if row.get("recycled_pct") not in (None, ""):
        out["recycled_pct"] = num(row["recycled_pct"], "Recycled content of %s" % n, 100.0)
    return out


def put(d, update: dict) -> dict:
    if not isinstance(update, dict):
        raise EmissionError("The emission table is an object.")
    cur = current(d)
    if "factors" in update:
        fs = update["factors"]
        if not isinstance(fs, dict) or len(fs) > MAX_ROWS:
            raise EmissionError("Factors is an object of up to %d materials." % MAX_ROWS)
        cur["factors"] = {str(k).strip(): clean_factor(k, v) for k, v in fs.items()}
    if "process_kg_per_h" in update:
        ps = update["process_kg_per_h"]
        if not isinstance(ps, dict):
            raise EmissionError("process_kg_per_h is an object by process.")
        cur["process_kg_per_h"] = {str(k): num(v, "Process factor %s" % k, 1e4) for k, v in ps.items() if k in ("machining", "sheet_metal", "additive")}
    if "transport" in update:
        t = update["transport"]
        cur["transport"] = None if t is None else {"kg_co2e_per_tonne_km": num(t.get("kg_co2e_per_tonne_km"), "Transport factor", 1e3), "km": num(t.get("km"), "Distance", 1e6), "source": str(t.get("source") or PROVENANCE)[:300]}
    d.set_header(HEADER, cur)
    return cur


def read_csv(path: str) -> dict:
    full = os.path.abspath(os.path.expanduser(str(path or "")))
    if not os.path.isfile(full) or os.path.splitext(full)[1].lower() != ".csv":
        raise EmissionError("Give the path of an existing .csv file.")
    if os.path.getsize(full) > MAX_FILE:
        raise EmissionError("The file is larger than %d bytes." % MAX_FILE)
    with open(full, "r", encoding="utf-8-sig", errors="replace", newline="") as fh:
        text = fh.read()
    try:
        rows = list(csv.DictReader(io.StringIO(text)))
    except csv.Error as err:
        raise EmissionError("The file could not be read as a table: %s." % err)
    if len(rows) > MAX_ROWS:
        raise EmissionError("The file has more than %d rows." % MAX_ROWS)
    out = {}
    for r in rows:
        r = {str(k or "").strip().lower(): v for k, v in r.items()}
        name = (r.get("material") or r.get("name") or "").strip()
        if not name:
            continue
        out[name] = clean_factor(name, {"kg_co2e_per_kg": r.get("kg_co2e_per_kg") or r.get("factor"), "source": r.get("source") or "imported from %s" % os.path.basename(full), "boundary": r.get("boundary"), "geography": r.get("geography"), "edition": r.get("edition") or r.get("year"), "licence": r.get("licence"), "recycled_pct": r.get("recycled_pct")})
    if not out:
        raise EmissionError("The file has no rows with material and kg_co2e_per_kg columns.")
    return out


def lookup(table: dict, material: str) -> dict | None:
    key = (material or "").strip().casefold()
    for k, v in table["factors"].items():
        if k.casefold() == key:
            return v
    return None


def estimate(rows: list, table: dict) -> dict:
    out_rows = []
    total = 0.0
    missing = []
    for r in rows:
        f = r["facts"]
        mass = f.get("mass")
        fac = lookup(table, f["material"])
        entry = {"part": r["label"], "qty": r["qty"], "material": f["material"], "mass_kg": mass, "factor": None, "kg_co2e": None}
        if mass is None or not f["material"]:
            missing.append("%s: no mass or no material" % r["label"])
        elif fac is None:
            missing.append("%s: no emission factor for %s" % (r["label"], f["material"]))
        else:
            mat_e = mass * fac["kg_co2e_per_kg"]
            proc_e = 0.0
            cyc = r.get("cycle_s") or 0.0
            pf = table["process_kg_per_h"].get(r.get("process"))
            if pf:
                proc_e = cyc / 3600.0 * pf
            tr = table.get("transport")
            tr_e = mass / 1000.0 * tr["kg_co2e_per_tonne_km"] * tr["km"] if tr else 0.0
            unit = mat_e + proc_e + tr_e
            entry.update(factor=fac, material_kg_co2e=mat_e, process_kg_co2e=proc_e, transport_kg_co2e=tr_e, kg_co2e=unit, total_kg_co2e=unit * r["qty"])
            total += unit * r["qty"]
        out_rows.append(entry)
    return {"total_kg_co2e": total, "rows": out_rows, "missing": missing, "caveats": list(CAVEATS), "attribution": ATTRIBUTION if any(v.get("licence", "").lower().startswith("ogl") for v in table["factors"].values()) else "", "factors_defined": len(table["factors"])}
