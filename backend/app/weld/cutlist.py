import csv
import io

from app.core import csvsafe
from app.param import units as U
from app.weld import records

DEFAULT_TOL_MM = 0.5
COLUMNS = ["item", "qty", "profile", "length", "angle1", "angle2", "description"]
TITLES = {"item": "Item", "qty": "Qty", "profile": "Profile", "length": "Length", "angle1": "Angle 1", "angle2": "Angle 2", "description": "Description", "total_length": "Total length", "mass": "Mass"}


class CutError(ValueError):
    pass


def norm_deg(a):
    a = (a + 180.0) % 360.0 - 180.0
    return 180.0 if a == -180.0 else a


def check_tol(tol):
    try:
        v = float(DEFAULT_TOL_MM if tol is None else tol)
    except (TypeError, ValueError):
        raise CutError("The tolerance must be a number.")
    if not 1e-6 <= v <= 100.0:
        raise CutError("The tolerance must be between 0.000001 and 100 mm.")
    return v


def build(d, tol=None) -> dict:
    tol = check_tol(tol)
    members = records.rows(d, "member")
    groups = {}
    for m in members:
        rel = (m["rot2"] - m["rot1"]) % 360.0
        if m["angle1"] < 1e-6 or m["angle2"] < 1e-6:
            rel = 0.0
        key = (m["profile"], round(m["length"] / tol), round(m["angle1"], 2), round(m["angle2"], 2), round(rel, 1))
        groups.setdefault(key, []).append(m)
    rows = []
    for key in sorted(groups, key=lambda k: (k[0], -k[1], k[2], k[3], k[4])):
        g = groups[key]
        notes = "; ".join(sorted({n for x in g for n in (x.get("notes") or [])}))
        f = g[0]
        length = sum(x["length"] for x in g) / len(g)
        dens = f.get("density")
        mass = None if not dens else sum(x["volume"] for x in g) * 1e-9 * float(dens)
        rows.append({
            "kind": "member", "qty": len(g), "profile": f["profile"], "length": length, "angle1": f["angle1"], "angle2": f["angle2"],
            "rotation1": f["rot1"], "rotation2": f["rot2"], "relative": key[4], "ends": [f["kind1"], f["kind2"]], "description": notes,
            "members": [x["mid"] for x in g], "total_length": length * len(g), "mass": mass, "group": f.get("group", ""),
        })
    plates = {}
    for p in records.rows(d):
        if p.get("kind") in ("end_cap", "gusset"):
            key = (p["kind"], p["profile"], round(p["thickness"], 4), round(p["length"] / tol), round(p.get("width", 0.0) / tol))
            plates.setdefault(key, []).append(p)
    for key in sorted(plates):
        g = plates[key]
        f = g[0]
        dens = f.get("density")
        mass = None if not dens else sum(x["volume"] for x in g) * 1e-9 * float(dens)
        rows.append({
            "kind": f["kind"], "qty": len(g), "profile": f["profile"], "length": f["length"], "angle1": 0.0, "angle2": 0.0, "rotation1": 0.0, "rotation2": 0.0, "relative": 0.0,
            "ends": ["plate", "plate"], "description": "%s, %.4g thick" % ("End cap" if f["kind"] == "end_cap" else "Gusset", f["thickness"]),
            "members": [x["id"].split("/", 1)[-1] for x in g], "total_length": f["length"] * len(g), "mass": mass, "group": "", "thickness": f["thickness"],
        })
    for i, r in enumerate(rows, 1):
        r["item"] = i
    summary = {}
    for r in rows:
        if r["kind"] != "member":
            continue
        s = summary.setdefault(r["profile"], {"profile": r["profile"], "count": 0, "total_length": 0.0})
        s["count"] += r["qty"]
        s["total_length"] += r["total_length"]
    return {"rows": rows, "summary": list(summary.values()), "tolerance": tol, "members": len(members)}


def fmt(v, digits=2):
    s = ("%." + str(digits) + "f") % v
    return s.rstrip("0").rstrip(".") if "." in s else s


def cells(d, rows, columns=None) -> list:
    cols = list(columns or COLUMNS)
    for c in cols:
        if c not in TITLES:
            raise CutError("Unknown column %s." % c)
    mm = U.mm_per_unit(d)
    out = []
    for r in rows:
        line = []
        for c in cols:
            if c == "length":
                v = fmt(r["length"] / mm)
            elif c == "total_length":
                v = fmt(r["total_length"] / mm)
            elif c in ("angle1", "angle2"):
                v = fmt(r[c], 2) if r["kind"] == "member" else ""
            elif c == "mass":
                v = "" if r.get("mass") is None else fmt(r["mass"], 3)
            else:
                v = str(r.get(c, ""))
            line.append(v)
        out.append(line)
    return out


def csv_text(d, tol=None, columns=None) -> str:
    res = build(d, tol)
    cols = list(columns or COLUMNS)
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([TITLES[c] for c in cols])
    for line in cells(d, res["rows"], cols):
        w.writerow([csvsafe.cell(x) for x in line])
    return out.getvalue()
