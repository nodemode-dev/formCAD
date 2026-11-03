import numpy as np

from app.assembly import parts, walk
from app.bodies import materials
from app.joints import store as J
from app.param.units import mm_per_unit
from app.solid import work

MM3_TO_M3 = 1e-9
MM5_TO_M5 = 1e-15


def fetch(doc, cids: list, density: float, max_vertices: int = 48) -> dict:
    d = doc.drawing
    wanted = set(cids)
    insts = walk.instances(doc)
    tops = {i.cid: i.world for i in insts if i.depth == 0 and not i.index}
    rows = []
    items = []
    for inst in insts:
        lp = inst.part
        top = inst.path[0].split("#")[0].split("/")[0] if inst.path else inst.cid
        if top not in wanted or lp is None or getattr(lp, "is_assembly", False) or not lp.bodies or inst.suppressed:
            continue
        for b in lp.bodies:
            try:
                wid = parts.shapes(lp, b)
            except work.SolidError:
                continue
            key = "%s|%s|%s" % (top, inst.key, b.handle)
            dens = materials.density_of(lp.drawing, b)
            rel = np.linalg.inv(tops[top]) @ inst.world if top in tops else np.eye(4)
            rows.append({"key": key, "top": top, "rel": rel, "density": dens, "mmu": mm_per_unit(lp.drawing)})
            items.append({"key": key, "id": wid})
    if not items:
        raise J.MotionError("None of the components has a solid to simulate.")
    res = work.kcall("asm_proxy", {"items": items, "max_vertices": int(max_vertices)}, work.LONG)["proxies"]
    out = {}
    for row in rows:
        p = res.get(row["key"])
        if not p or p.get("error"):
            raise J.MotionError("Component %s has a body without extent." % row["top"])
        e = out.setdefault(row["top"], {"mass": 0.0, "moments": [], "pieces": [], "sources": set(), "bodies": 0})
        rel = row["rel"]
        dens = row["density"]
        e["sources"].add("material" if dens is not None else "default")
        dens = float(dens if dens is not None else density)
        r, t = rel[:3, :3], rel[:3, 3] * mm_per_unit(d)
        vol = float(p["volume"]) * MM3_TO_M3
        mass = dens * vol
        com = r @ (np.asarray(p["centroid"], dtype=float) * 1e-3) + t * 1e-3
        inertia = r @ (np.asarray(p["inertia"], dtype=float) * dens * MM5_TO_M5) @ r.T
        e["moments"].append((mass, com, inertia))
        e["mass"] += mass
        e["bodies"] += 1
        for piece in p["pieces"]:
            pts = (np.asarray(piece, dtype=float) @ r.T + t) * 1e-3
            e["pieces"].append(pts)
    for cid, e in out.items():
        total = e["mass"]
        if total <= 0:
            raise J.MotionError("Component %s has no volume, so it has no mass." % cid)
        com = sum(m * c for m, c, _ in e["moments"]) / total
        inertia = np.zeros((3, 3))
        for m, c, i in e["moments"]:
            s = c - com
            inertia += i + m * ((s @ s) * np.eye(3) - np.outer(s, s))
        e["com"] = com
        e["inertia"] = inertia
        e["source"] = "material" if e["sources"] == {"material"} else ("default" if e["sources"] == {"default"} else "mixed")
        e.pop("moments")
        e.pop("sources")
    missing = [c for c in cids if c not in out]
    if missing:
        raise J.MotionError("Component %s has no solid body to simulate." % ", ".join(missing))
    return out
