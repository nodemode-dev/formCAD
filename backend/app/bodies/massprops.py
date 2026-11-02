import numpy as np

from app.bodies import materials, refgeo
from app.solid import work

MM3_TO_M3 = 1e-9
MAX_BODIES = 2000


class MassError(ValueError):
    pass


def parallel_axis(mass: float, r) -> np.ndarray:
    r = np.asarray(r, dtype=float)
    return mass * (float(r @ r) * np.eye(3) - np.outer(r, r))


def pick_bodies(d, handles) -> list:
    if handles:
        out = []
        for h in handles:
            b = d.get(int(h))
            if b is None or b.kind != "solidbody":
                raise MassError("There is no solid body with handle %s." % h)
            out.append(b)
        return out
    return [e for e in d.ents.values() if e.kind == "solidbody" and d.visible(e)][:MAX_BODIES]


def body_row(d, body, density_override):
    wid = work.worker_id(d, body)
    raw = work.kcall("body_props", {"id": wid, "eps": 1e-9}, work.SHORT)
    density = density_override if density_override is not None else materials.density_of(d, body)
    return body, raw, density


def compute(d, handles=None, cs=None, density=None) -> dict:
    if density is not None:
        try:
            density = float(density)
        except (TypeError, ValueError):
            raise MassError("The density must be a number in kg/m3.")
        if not density > 0 or density > 30000:
            raise MassError("The density must be between 0 and 30000 kg/m3.")
    bodies = pick_bodies(d, handles)
    if not bodies:
        raise MassError("There are no solid bodies.")
    try:
        frame = refgeo.cs_frame(d, cs)
    except refgeo.RefError as err:
        raise MassError(str(err))
    s = work.mm(d)
    rows = [body_row(d, b, density) for b in bodies]
    per = []
    notes = []
    area = sum(float(r[1]["area"]) for r in rows)
    solids_ok = all(r[1]["volume"] is not None for r in rows)
    out = {"bodies": per, "count": len(rows), "cs": frame["name"], "units": {"length": "mm", "mass": "kg", "volume": "mm3", "area": "mm2", "inertia": "kg*mm2", "density": "kg/m3"}, "mm_per_unit": s, "area": area, "notes": notes}
    for body, raw, dens in rows:
        entry = {"handle": body.handle, "name": body.name, "material": body.material or None, "density": dens, "volume": raw["volume"], "area": raw["area"], "closed": raw["closed"], "valid": raw["valid"]}
        if raw["volume"] is None:
            entry["note"] = raw.get("note", "")
            notes.append("%s: %s" % (body.name or body.handle, raw.get("note", "No volume.")))
        elif dens is not None:
            entry["mass"] = raw["volume"] * MM3_TO_M3 * dens
        per.append(entry)
    if not solids_ok:
        out.update(volume=None, mass=None, centroid=None, inertia=None, principal=None, axes=None, inertia_origin=None, centroid_cs=None, doc=None)
        out["note"] = "Volume is reported only when every body is a closed valid solid."
        return out
    vols = np.array([r[1]["volume"] for r in rows])
    cents = np.array([r[1]["centroid"] for r in rows], dtype=float)
    volume = float(vols.sum())
    centroid = (cents * vols[:, None]).sum(axis=0) / volume
    missing = [b.name or str(b.handle) for b, _r, dens in rows if dens is None]
    weights = vols
    mass = None
    unit_scale = MM3_TO_M3
    if not missing:
        masses = np.array([v * MM3_TO_M3 * dens for v, (_b, _r, dens) in zip(vols, rows)])
        mass = float(masses.sum())
        weights = masses
        centroid = (cents * masses[:, None]).sum(axis=0) / mass
        inertia = sum(np.array(raw["inertia"], dtype=float) * (dens * unit_scale) + parallel_axis(m, cents[i] - centroid) for i, (m, (_b, raw, dens)) in enumerate(zip(masses, rows)))
    else:
        notes.append("No density for %s; assign a material or give a density to get the mass and inertia." % ", ".join(missing))
        inertia = sum(np.array(raw["inertia"], dtype=float) + parallel_axis(v, cents[i] - centroid) for i, (v, (_b, raw, _d)) in enumerate(zip(vols, rows)))
    total = mass if mass is not None else volume
    inertia = np.asarray(inertia, dtype=float)
    inertia = (inertia + inertia.T) / 2.0
    vals, vecs = np.linalg.eigh(inertia)
    origin = np.array(frame["origin"], dtype=float) * s
    basis = np.column_stack([frame["x"], frame["y"], frame["z"]])
    rel = np.asarray(centroid) - origin
    about_origin = inertia + parallel_axis(total, rel)
    in_cs = basis.T @ about_origin @ basis
    in_cs = (in_cs + in_cs.T) / 2.0
    cs_com = basis.T @ rel
    out.update(
        volume=volume,
        mass=mass,
        mass_basis="density" if mass is not None else "unit-density",
        centroid=centroid.tolist(),
        inertia=inertia.tolist(),
        principal=[float(v) for v in vals],
        axes=[vecs[:, i].tolist() for i in range(3)],
        inertia_cs=in_cs.tolist(),
        centroid_cs=cs_com.tolist(),
        doc={"volume": volume / s**3, "area": area / s**2, "centroid": (centroid / s).tolist(), "centroid_cs": (cs_com / s).tolist()},
    )
    if mass is None:
        out["inertia_note"] = "Inertia is per unit density, in mm5, because a body has no material."
    return out


def exit_check(d) -> dict:
    rows = []
    worst = 0.0
    for b in d.ents.values():
        if b.kind != "solidbody" or not isinstance(b.source, dict) or not isinstance(b.source.get("expect"), dict):
            continue
        exp = b.source["expect"]
        got = compute(d, [b.handle])
        diffs = {}
        for key in ("volume", "mass"):
            if exp.get(key) is not None and got.get(key) is not None:
                diffs[key] = abs(got[key] - exp[key]) / abs(exp[key])
        if exp.get("centroid") is not None and got.get("centroid") is not None:
            ref = np.array(exp["centroid"], dtype=float)
            have = np.array(got["centroid"], dtype=float)
            diffs["centroid"] = float(np.abs(have - ref).max() / max(float(np.abs(ref).max()), 1e-12))
        worst = max([worst, *diffs.values()])
        rows.append({"handle": b.handle, "name": b.name, "relative_error": diffs})
    return {"bodies": rows, "worst": worst, "tolerance": 1e-6, "passes": bool(rows) and worst <= 1e-6}
