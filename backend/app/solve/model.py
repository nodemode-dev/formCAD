import math
import time

import numpy as np

from . import constraints as K
from . import numeric as N
from .errors import SolverFault

PARAMS = {"point": 2, "line": 4, "circle": 3, "arc": 5, "ellipse": 5, "param": 1}
ELLIPSE_ARC = 7


class Ent:
    __slots__ = ("id", "kind", "off", "n", "meta")

    def __init__(self, eid, kind, off, n, meta=None):
        self.id = eid
        self.kind = kind
        self.off = off
        self.n = n
        self.meta = meta


class Report:
    def __init__(self):
        self.ok = True
        self.refused = False
        self.status = "unconstrained"
        self.dof = 0
        self.entities = {}
        self.redundant = []
        self.conflicts = []
        self.constraint = None
        self.iterations = 0
        self.moved = 0.0
        self.ms = 0.0
        self.message = ""

    def to_dict(self):
        return dict(self.__dict__)


class Sketch:
    def __init__(self):
        self._x = []
        self.ents = {}
        self.cons = {}
        self._eid = 1
        self._cid = 1
        self._count = {}
        self.weights = {}
        self.pweights = {}
        self.aux = {}
        self._reuse = []
        self._taken = []

    def xarray(self):
        return np.array(self._x, dtype=float)

    def _alloc(self, kind, vals, meta=None):
        eid = self._eid
        self._eid += 1
        self.ents[eid] = Ent(eid, kind, len(self._x), len(vals), meta)
        self._x.extend(float(v) for v in vals)
        return eid

    def add_spline(self, degree, knots, ctrl, weights=None, closed=False):
        p = int(degree)
        pts = [(float(q[0]), float(q[1])) for q in ctrl]
        nc = len(pts)
        if p < 1 or nc < p + 1 or len(knots) != nc + p + 1:
            raise SolverFault("the spline has an invalid knot vector")
        wrap = 0
        if closed and nc > 2 * p:
            tail = pts[nc - p:]
            if all(abs(a[0] - b[0]) <= 1e-9 and abs(a[1] - b[1]) <= 1e-9 for a, b in zip(tail, pts[:p])):
                wrap = p
        uniq = nc - wrap
        w = [float(v) for v in weights] if weights and len(weights) == nc and any(abs(float(v) - 1.0) > 1e-12 for v in weights) else None
        meta = K.SplineMeta(p, [float(k) for k in knots], w, uniq, nc, bool(closed and wrap))
        return self._alloc("spline", [c for q in pts[:uniq] for c in q], meta)

    def aux_param(self, value):
        if self._reuse:
            eid = self._reuse.pop(0)
            self._x[self.ents[eid].off] = float(value)
        else:
            eid = self._alloc("param", [value])
        self._taken.append(eid)
        return self.ents[eid]

    def _drop_aux(self, cid):
        for eid in self.aux.pop(cid, []):
            self.ents.pop(eid, None)

    def add_point(self, x, y):
        return self._alloc("point", [x, y])

    def add_line(self, x1, y1, x2, y2):
        return self._alloc("line", [x1, y1, x2, y2])

    def add_circle(self, cx, cy, r):
        return self._alloc("circle", [cx, cy, r])

    def add_arc(self, cx, cy, r, a0, a1):
        return self._alloc("arc", [cx, cy, r, a0, a1])

    def add_ellipse(self, cx, cy, mx, my, ratio, a0=None, a1=None):
        vals = [cx, cy, mx, my, ratio]
        if a0 is not None:
            vals += [a0, a1]
        return self._alloc("ellipse", vals)

    def values(self, eid):
        e = self.ents[eid]
        return list(self._x[e.off:e.off + e.n])

    def set_values(self, eid, vals):
        e = self.ents[eid]
        if len(vals) != e.n:
            raise SolverFault("wrong parameter count")
        self._x[e.off:e.off + e.n] = [float(v) for v in vals]

    def set_weight(self, eid, w):
        self.weights[eid] = float(w)

    def set_param_weight(self, eid, index, w):
        self.pweights[self.ents[eid].off + index] = float(w)

    def _weights(self):
        w = np.ones(len(self._x))
        for eid, v in self.weights.items():
            e = self.ents[eid]
            w[e.off:e.off + e.n] = v
        for i, v in self.pweights.items():
            w[i] = v
        return w

    def _make(self, kind, refs, value, name, ctx, cid):
        if kind in K.GEOMETRIC:
            group = "geometric"
        elif kind in K.DIMENSIONAL:
            group = "dimensional"
        else:
            raise SolverFault("unknown constraint kind '%s'" % kind)
        refs = list(refs)
        self._reuse = [e for e in self.aux.get(cid, []) if e in self.ents]
        self._taken = []
        ok = False
        try:
            fn, vars_, rows, ents = K.build(self, kind, refs, value, ctx)
            ok = True
        finally:
            taken, spare = self._taken, self._reuse
            self._reuse, self._taken = [], []
            for eid in spare + ([] if ok and cid else taken):
                self.ents.pop(eid, None)
            if ok and cid and taken:
                self.aux[cid] = taken
            else:
                self.aux.pop(cid, None)
        if group == "dimensional" and name is None:
            pre = K.PREFIX[kind]
            self._count[pre] = self._count.get(pre, 0) + 1
            name = "%s%d" % (pre, self._count[pre])
        return N.Cons(cid, kind, group, refs, value, name, rows, np.array(vars_, dtype=int), fn, ctx, ents)

    def _label(self, c):
        return {"id": c.id, "kind": c.kind, "name": c.name}

    def restore(self, cid, kind, refs, value=None, name=None, ctx=None):
        c = self._make(kind, refs, value, name, dict(ctx or {}), cid)
        self.cons[cid] = c
        self._cid = max(self._cid, cid + 1)
        return c

    def measure(self, kind, refs, ctx=None):
        probe = 1.0
        c = self._make(kind, refs, probe, "probe", dict(ctx or {}), 0)
        x = self.xarray()
        r = float(c.fn(x)[0])
        if kind == "angle":
            return math.degrees(K._wrap(r + math.radians(probe)))
        if kind in ("hdistance", "vdistance"):
            return abs(r + c.ctx.get("s", 1.0) * probe)
        return r + probe

    def add(self, kind, refs, value=None, name=None, force=False, cid=None, ctx=None):
        cid = self._cid if cid is None else cid
        c = self._make(kind, refs, value, name, dict(ctx or {}), cid)
        self._cid = max(self._cid, cid) + 1
        self.cons[cid] = c
        before = list(self._x)
        rep = self.solve()
        rep.constraint = self._label(c)
        if rep.ok and not rep.redundant:
            return rep
        if force and rep.ok:
            return rep
        self._x = before
        del self.cons[cid]
        self._drop_aux(cid)
        if c.name and c.group == "dimensional":
            pre = K.PREFIX[kind]
            self._count[pre] -= 1
        self._cid = cid
        rep.refused = True
        rep.ok = False
        if not rep.message:
            rep.message = "constraint %s refused as over-constraining" % kind
        return rep

    def remove(self, cid):
        if cid not in self.cons:
            raise SolverFault("unknown constraint")
        del self.cons[cid]
        self._drop_aux(cid)

    def set_value(self, cid, value):
        old = self.cons[cid]
        c = self._make(old.kind, old.refs, value, old.name, old.ctx, cid)
        self.cons[cid] = c
        rep = self.solve()
        if not rep.ok:
            self.cons[cid] = old
            rep.refused = True
        return rep

    def _components(self):
        parent = {}

        def find(a):
            while parent[a] != a:
                parent[a] = parent[parent[a]]
                a = parent[a]
            return a

        for eid in self.ents:
            parent[eid] = eid
        for c in self.cons.values():
            for e in c.ents[1:]:
                parent[find(e)] = find(c.ents[0])
        comps = {}
        for eid in self.ents:
            comps.setdefault(find(eid), [[], []])[0].append(eid)
        for c in self.cons.values():
            if c.ents:
                comps[find(c.ents[0])][1].append(c)
        return list(comps.values())

    def _probe_conflicts(self, cons, x0, w):
        base = N.residual(cons, x0)
        r = 0
        mag = []
        for c in cons:
            mag.append((float(np.max(np.abs(base[r:r + c.rows]))), c))
            r += c.rows
        mag.sort(key=lambda t: -t[0])
        found = []
        t0 = time.perf_counter()
        for _, c in mag[:48]:
            if found and time.perf_counter() - t0 > 0.75:
                break
            rest = [d for d in cons if d.id != c.id]
            ok, _, _, _ = N.solve_system(rest, x0, w, max_it=30)
            if ok:
                found.append(c)
        return found

    def _analyse(self, ent_ids, cons, x, rep):
        cols = []
        for eid in ent_ids:
            e = self.ents[eid]
            cols.extend(range(e.off, e.off + e.n))
        cmap = {c: k for k, c in enumerate(cols)}
        n = len(cols)
        owners = []
        for c in cons:
            owners.extend([c.id] * c.rows)
        null = None
        deps = {}
        if len(owners) > N.SPARSE_ROWS:
            _, Js = N.assemble_sparse(cons, x.copy(), cmap, n, central=True)
            _, null, dependent = N.echelon(Js)
            if dependent:
                deps = N.dependent_sparse(Js, dependent, owners)
        if null is None:
            if cons:
                F, J = N.assemble(cons, x.copy(), cmap, n, central=True)
            else:
                J = np.zeros((0, n))
            Jn, live = N.normalize_rows(J)
            null = N.null_basis(Jn[live], n) if cons else np.eye(n)
            deps = N.dependent_rows(Jn, live, owners) if cons else {}
        rep.dof += null.shape[1]
        by_id = {c.id: c for c in cons}
        touched = {}
        for cid, groups in deps.items():
            dup = sorted({d for g in groups for d in g if d != cid})
            rep.redundant.append({
                "id": cid, "kind": by_id[cid].kind, "name": by_id[cid].name,
                "rows": len(groups), "duplicates": [self._label(self.cons[d]) for d in dup],
            })
            for e in by_id[cid].ents:
                touched[e] = True
        used = {e for c in cons for e in c.ents}
        for eid in ent_ids:
            e = self.ents[eid]
            k = cmap[e.off]
            sub = null[k:k + e.n]
            dof = N.numeric_rank(sub) if sub.size else 0
            if touched.get(eid):
                st = "over"
            elif eid not in used:
                st = "unconstrained"
            elif dof == 0:
                st = "fully"
            else:
                st = "under"
            rep.entities[eid] = {"kind": e.kind, "dof": dof, "status": st}

    def solve(self, analyse=True):
        t0 = time.perf_counter()
        rep = Report()
        x0 = self.xarray()
        w = self._weights()
        x1 = x0.copy()
        failed = []
        comps = self._components()
        for ent_ids, cons in comps:
            if not cons:
                continue
            ok, xn, it, nf = N.solve_system(cons, x0, w)
            rep.iterations += it
            if ok:
                for c in cons:
                    for i in c.vars:
                        x1[i] = xn[i]
                for eid in ent_ids:
                    e = self.ents[eid]
                    x1[e.off:e.off + e.n] = xn[e.off:e.off + e.n]
            else:
                failed.append((ent_ids, cons))
        if failed:
            rep.ok = False
            seen = {}
            for ent_ids, cons in failed:
                for c in self._probe_conflicts(cons, x0, w) or [c for c in cons if np.max(np.abs(c.fn(x0))) > 1e-9]:
                    seen[c.id] = self._label(c)
            rep.conflicts = list(seen.values())
            rep.status = "conflict"
            rep.message = "constraints could not be satisfied: " + ", ".join(
                "%s %s" % (c["name"] or c["kind"], "#%d" % c["id"]) for c in rep.conflicts)
            if analyse:
                self._analyse_all(comps, x0, rep, keep_status=True)
            rep.ms = (time.perf_counter() - t0) * 1000.0
            return rep
        rep.moved = float(np.max(np.abs(x1 - x0))) if x0.size else 0.0
        self._x = [float(v) for v in x1]
        if analyse:
            self._analyse_all(comps, x1, rep)
        rep.ms = (time.perf_counter() - t0) * 1000.0
        return rep

    def _analyse_all(self, comps, x, rep, keep_status=False):
        for ent_ids, cons in comps:
            self._analyse(ent_ids, cons, x, rep)
        if keep_status:
            return
        if rep.redundant:
            rep.status = "over"
            rep.message = "redundant constraints: " + ", ".join(
                "%s #%d" % (r["name"] or r["kind"], r["id"]) for r in rep.redundant)
        elif not self.cons:
            rep.status = "unconstrained"
        elif rep.dof == 0:
            rep.status = "fully"
        else:
            rep.status = "under"
