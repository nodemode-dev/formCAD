import os
import tempfile

import numpy as np

from app.core import guard
from app.plastic import job, rule
from app.solid.work import SolidError
from app.solid import work

DEFAULT_VERTICES = 20000
SPHERE_VERTICES = 4000
AGENT_VERTICES = 6000
AGENT_SPHERE_VERTICES = 1500
HARD_VERTICES = 60000
HARD_SPHERE = 6000


def vertex_limit(method: str, asked) -> int:
    agent = bool(guard.CALLER.get())
    cap = (AGENT_SPHERE_VERTICES if agent else HARD_SPHERE) if method == "sphere" else (AGENT_VERTICES if agent else HARD_VERTICES)
    default = SPHERE_VERTICES if method == "sphere" else DEFAULT_VERTICES
    n = default if asked is None else int(asked)
    return max(100, min(n, cap))


def wall_values(doc, spec: dict, bodies: list, detail: float) -> tuple:
    from app.analysis import service as an

    d = doc.drawing
    s = work.mm(d)
    per = {}
    for b in bodies:
        pos, data = an.shape_data(d, b, detail, False)
        if len(pos) > spec["max_vertices"]:
            raise SolidError("%s has %d vertices; wall thickness with the %s method takes up to %d. Lower the detail." % (b.name or "A body", len(pos), spec["method"], spec["max_vertices"]))
        wid = an.base_worker_id(d, b)
        with tempfile.TemporaryDirectory(prefix="fcwl_") as tmp:
            pts = os.path.join(tmp, "p.pts")
            nrm = os.path.join(tmp, "n.nrm")
            out = os.path.join(tmp, "o.wal")
            np.ascontiguousarray(pos, dtype="<f4").tofile(pts)
            np.ascontiguousarray(data[:, :3], dtype="<f4").tofile(nrm)
            with job.running(doc, "plasticwall", SolidError) as act:
                act.step("Measuring the wall thickness", 0.1)
                job.interruptible(act, work.kcall, "pl_wall", {"id": wid, "method": spec["method"], "points_path": pts, "normals_path": nrm, "out_path": out}, work.LONG)
            arr = np.fromfile(out, dtype="<f4")
        if len(arr) != len(pos):
            raise SolidError("The wall thickness values do not follow the display mesh; lower the detail and try again.")
        per[b.handle] = (arr.astype(np.float64) / s).astype(np.float32)
    from app.interchange import fileunits

    return per, fileunits.document_unit(d)[0]


def limits(d, spec: dict, scale: float) -> tuple:
    lo, hi = spec.get("low"), spec.get("high")
    rl = rule.current(d)
    if lo is None and rl["wall_min"] is not None:
        lo = rl["wall_min"] / scale
    if hi is None and rl["wall_max"] is not None:
        hi = rl["wall_max"] / scale
    if lo is not None and hi is not None and hi <= lo:
        return None, None
    return lo, hi
