import copy
import json
import math

import numpy as np

from app.cam import geom, limits, model
from app.cam import toolpath as T
from app.cam.ctx import GenCtx
from app.cam.limits import CamError
from app.cam3d.kinematics import Reach


class OrientedCtx(GenCtx):
    def __init__(self, doc, setup, op, tool_rec, params, job, default_geometry, R):
        self.R = np.asarray(R, dtype=float)
        super().__init__(doc, setup, op, tool_rec, params, job, default_geometry)

    @property
    def stock(self) -> dict:
        if self._stock is None:
            sb = model.stock_box(self.doc, self.setup)
            lo, hi = np.asarray(sb["min"], dtype=float), np.asarray(sb["max"], dtype=float)
            corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            c = corners @ self.R
            self._stock = {"min": c.min(axis=0).tolist(), "max": c.max(axis=0).tolist(), "kind": "box", "origin": sb.get("origin"), "polygon": None}
        return self._stock

    def stock_polygon(self) -> list:
        sb = self.stock
        return [geom.rect_ring(sb["min"][0], sb["min"][1], sb["max"][0], sb["max"][1])]

    def triangles(self):
        if self._tris is None:
            base = model.setup_triangles(self.doc, self.setup)
            self._tris = base @ self.R
            limits.need(len(self._tris), "triangles", "Model")
        return self._tris

    def fixture_triangles(self):
        t = super().fixture_triangles()
        return None if t is None else t @ self.R

    def region(self):
        if self._region is None:
            g = self.op.get("geometry") or self.default_geometry or {}
            if not g:
                raise CamError("The operation has no geometry. Pick an outline, entities or a model section.")
            if g.get("kind") in ("polygons", "rect", "entities"):
                raise CamError("A 3+2 operation can take its region from the model or the stock, not from sketch outlines, which are not turned with the tool axis.")
            sz = None if self.h.bottom is None else self.h.bottom + 0.05
            tris = self.triangles() if g.get("kind") in ("section", "removal") else None
            self._region = geom.Region(model.build_region(self.doc, self.setup, g, self.tool.radius, sz, tris))
            limits.need(geom.vertex_count(self._region.rings), "region_vertices", "Region")
        return self._region

    def points(self) -> list:
        g = self.op.get("geometry") or {}
        tris = self.triangles() if g.get("kind") == "model_holes" else None
        return model.build_points(self.doc, self.setup, g, tris)


def orientation(machine, a, c, axis):
    if axis is not None and any(v is not None for v in axis):
        k = np.array([float(v or 0.0) for v in axis])
        try:
            a, c = machine.solve_axis(k, {"a": 0.0, "c": 0.0})
        except Reach as err:
            raise CamError(str(err))
    else:
        a, c = float(a), float(c)
        if not machine.a_lim[0] - 1e-9 <= a <= machine.a_lim[1] + 1e-9:
            raise CamError("A %.3f degrees is outside the machine range %g to %g." % (a, machine.a_lim[0], machine.a_lim[1]))
        if not machine.c_lim[0] - 1e-9 <= c <= machine.c_lim[1] + 1e-9:
            raise CamError("C %.3f degrees is outside the machine range." % c)
    R = machine.frame_in_part(a, c)
    return a, c, R


def to_tcp(moves, R, a, c, arc_tol=0.005):
    k = R @ np.array([0.0, 0.0, 1.0])
    ax = [round(float(v), 6) for v in k]
    abc = [round(a, 4), 0.0, round(c, 4)]
    out = []
    pos = None

    def pt(q):
        v = R @ np.asarray(q, dtype=float)
        return [float(v[0]), float(v[1]), float(v[2])]

    def opts(base=None):
        o = dict(base or {})
        o["ax"] = ax
        o["abc"] = abc
        return o

    for m in moves:
        kind = m[0]
        o = T.opts_of(m)
        base = {kk: vv for kk, vv in o.items() if kk == "k"}
        if kind == "rapid":
            q = pt(m[1:4])
            out.append(["rapid", q[0], q[1], q[2], opts(base)])
            pos = tuple(m[1:4])
        elif kind == "feed":
            q = pt(m[1:4])
            out.append(["feed", q[0], q[1], q[2], m[4], opts(base)])
            pos = tuple(m[1:4])
        elif kind == "arc":
            if pos is None:
                raise CamError("An arc cannot be the first move.")
            for p in T.arc_points(pos, m, arc_tol):
                q = pt(p)
                out.append(["feed", q[0], q[1], q[2], m[8], opts(base)])
            pos = tuple(m[2:5])
        elif kind == "cycle":
            _, ck, x, y, zb, zr, qq, pp, f = m[:9]
            top = (float(x), float(y), float(zr))
            q = pt(top)
            out.append(["rapid", q[0], q[1], q[2], opts({"k": "approach"})])
            peck = float(qq) if qq else 0.0
            z = float(zr)
            if ck in ("peck", "chip") and peck > 0:
                while z > float(zb) + 1e-9:
                    z = max(z - peck, float(zb))
                    q = pt((float(x), float(y), z))
                    out.append(["feed", q[0], q[1], q[2], f, opts({"k": "cut"})])
                    q = pt(top)
                    out.append(["rapid", q[0], q[1], q[2], opts({"k": "retract"})])
                    if z > float(zb) + 1e-9:
                        q = pt((float(x), float(y), z + 0.254))
                        out.append(["rapid", q[0], q[1], q[2], opts({"k": "approach"})])
            else:
                q = pt((float(x), float(y), float(zb)))
                out.append(["feed", q[0], q[1], q[2], f, opts({"k": "cut"})])
                if pp:
                    out.append(["dwell", float(pp)])
                q = pt(top)
                out.append(["rapid", q[0], q[1], q[2], opts({"k": "retract"})])
            pos = top
        elif kind == "comp":
            raise CamError("Cutter compensation cannot be used in a 3+2 operation; use computer compensation on the base operation.")
        else:
            out.append(list(m))
    return out


def build(parent, kind, base_params_text, machine, a, c, axis):
    from app.cam import registry

    if kind in ("indexed", "swarf", "flowline"):
        raise CamError("The base operation of a 3+2 setup cannot be %s." % kind)
    typ = registry.get(kind)
    try:
        raw = json.loads(base_params_text or "{}")
    except ValueError:
        raise CamError("The base parameters are not valid JSON.")
    if not isinstance(raw, dict):
        raise CamError("The base parameters are a JSON object.")
    params = typ.clean(raw)
    a, c, R = orientation(machine, a, c, axis)
    op = copy.deepcopy(parent.op)
    op["type"] = kind
    op["params"] = params
    ctx = OrientedCtx(parent.doc, parent.setup, op, parent.tool.rec, params, parent.job, typ.default_geometry, R)
    ctx.warnings = parent.warnings
    ctx.started = parent.started
    out = typ.generate(ctx)
    path = out if isinstance(out, T.Toolpath) else T.Toolpath(out, getattr(ctx, "meta", {}))
    moves = to_tcp(path.moves, R, a, c)
    meta = dict(path.meta)
    meta.update({"indexed": True, "a": round(a, 4), "c": round(c, 4), "base": kind, "axis": [round(float(v), 6) for v in (R @ np.array([0.0, 0.0, 1.0]))]})
    return T.Toolpath(moves, meta)
