import math
import re

from app.doc import curvepath
from app.param import store as S
from app.solve import Sketch
from app.solve.errors import SolverFault

TAU = math.tau
POINT_PARTS = {
    "line": ("whole", "start", "end", "mid"),
    "point": ("whole",),
    "circle": ("whole", "center"),
    "arc": ("whole", "center", "start", "end", "mid"),
    "ellipse": ("whole", "center", "major"),
    "spline": ("whole", "start", "end"),
}
KIND_NAMES = {"line": "line", "point": "point", "circle": "circle", "arc": "arc", "ellipse": "ellipse", "lwpolyline": "polyline", "spline": "spline"}
SEG_RE = re.compile(r"^([vs])(\d+)$")
MOVE_TOL = 1e-12


class Binding:
    def __init__(self, handle, kind, ids, closed=False, nv=0, arc=False):
        self.handle = handle
        self.kind = kind
        self.ids = ids
        self.closed = closed
        self.nv = nv
        self.arc = arc


def constrainable(ent) -> bool:
    return ent is not None and ent.kind in KIND_NAMES


def refuse_text(ent) -> str:
    return "%s objects cannot be constrained." % ent.kind


def normal_angle(a: float) -> float:
    a = math.fmod(a, TAU)
    return a + TAU if a < 0 else a


def sanitize_part(part) -> str:
    return str(part or "whole").lower()


class Network:
    def __init__(self, d, scope=None):
        self.d = d
        self.scope = scope or S.Scope(d)
        self.sk = Sketch()
        self.bind = {}
        self.recs = {}
        self.driven = []
        self.next_implicit = S.IMPLICIT_BASE

    def entity(self, handle):
        ent = self.d.get(handle)
        if ent is None:
            raise S.ParamError("Object %s does not exist." % handle)
        if not constrainable(ent):
            raise S.ParamError(refuse_text(ent))
        return ent

    def binding(self, handle) -> Binding:
        b = self.bind.get(handle)
        if b is not None:
            return b
        ent = self.entity(handle)
        sk = self.sk
        k = ent.kind
        if k == "line":
            b = Binding(handle, k, [sk.add_line(ent.start[0], ent.start[1], ent.end[0], ent.end[1])])
        elif k == "point":
            b = Binding(handle, k, [sk.add_point(ent.position[0], ent.position[1])])
        elif k == "circle":
            b = Binding(handle, k, [sk.add_circle(ent.center[0], ent.center[1], ent.radius)])
        elif k == "arc":
            b = Binding(handle, k, [sk.add_arc(ent.center[0], ent.center[1], ent.radius, ent.start_angle, ent.end_angle)])
        elif k == "ellipse":
            sweep = abs(ent.end_param - ent.start_param)
            full = sweep < 1e-12 or abs(sweep - TAU) < 1e-9
            if full:
                eid = sk.add_ellipse(ent.center[0], ent.center[1], ent.major[0], ent.major[1], ent.ratio)
            else:
                eid = sk.add_ellipse(ent.center[0], ent.center[1], ent.major[0], ent.major[1], ent.ratio, ent.start_param, ent.end_param)
            b = Binding(handle, k, [eid], arc=not full)
        elif k == "spline":
            c = curvepath.spline_curve(ent)
            if c is None:
                raise S.ParamError("The spline has no valid control points to constrain.")
            try:
                eid = sk.add_spline(c.degree, c.knots, c.ctrl, c.weights, c.closed)
            except SolverFault as err:
                raise S.ParamError(str(err))
            b = Binding(handle, k, [eid], closed=bool(c.closed), nv=len(c.ctrl))
            b.curve = c
        else:
            verts = ent.vertices
            nv = len(verts)
            if nv < 2:
                raise S.ParamError("A polyline needs two vertices to be constrained.")
            closed = bool(ent.closed) and nv >= 3
            count = nv if closed else nv - 1
            ids = []
            for i in range(count):
                a, c = verts[i]["p"], verts[(i + 1) % nv]["p"]
                ids.append(sk.add_line(a[0], a[1], c[0], c[1]))
            b = Binding(handle, k, ids, closed, nv)
            for i in range(count - 1):
                self.implicit(ids[i], ids[i + 1])
            if closed:
                self.implicit(ids[-1], ids[0])
        self.bind[handle] = b
        return b

    def implicit(self, a, b) -> None:
        cid = self.next_implicit
        self.next_implicit += 1
        self.sk.restore(cid, "coincident", [(a, "end"), (b, "start")])

    def ref(self, handle, part):
        b = self.binding(handle)
        part = sanitize_part(part)
        if b.kind != "lwpolyline":
            allowed = POINT_PARTS[b.kind]
            if b.kind == "ellipse" and b.arc:
                allowed = allowed + ("start", "end")
            if part not in allowed:
                raise S.ParamError("A %s has no '%s' reference." % (KIND_NAMES[b.kind], part))
            return (b.ids[0], part)
        n = b.nv
        if part == "start" and not b.closed:
            part = "v0"
        elif part == "end" and not b.closed:
            part = "v%d" % (n - 1)
        m = SEG_RE.match(part)
        if m is None:
            raise S.ParamError("A polyline reference is v<n> for a vertex or s<n> for a segment (counting from 0).")
        i = int(m.group(2))
        if m.group(1) == "v":
            if i >= n:
                raise S.ParamError("The polyline has no vertex %d." % i)
            if b.closed or i < n - 1:
                return (b.ids[i], "start")
            return (b.ids[-1], "end")
        if i >= len(b.ids):
            raise S.ParamError("The polyline has no segment %d." % i)
        return (b.ids[i], "whole")

    def refs(self, raw) -> list:
        return [self.ref(int(h), p) for h, p in raw]

    def add_record(self, rec: dict, value=None, record_ctx=True):
        refs = self.refs(rec["refs"])
        if value is None and rec.get("label"):
            value = self.scope.lookup(rec["label"]) if rec.get("driving", True) else rec.get("value")
        elif value is None:
            value = rec.get("value")
        try:
            self.sk.restore(rec["id"], rec["kind"], refs, value, rec.get("label") or None, dict(rec.get("ctx") or {}))
        except SolverFault as err:
            raise S.ParamError(str(err))
        self.recs[rec["id"]] = rec

    def load_driven(self, rec: dict) -> None:
        self.refs(rec["refs"])
        self.driven.append(rec)

    def hold(self, handles, weight: float) -> None:
        for h in handles:
            b = self.bind.get(h)
            if b is not None:
                for eid in b.ids:
                    self.sk.set_weight(eid, weight)

    def hold_changed(self, handle, old, weight: float) -> None:
        b = self.bind.get(handle)
        ent = self.d.get(handle)
        if b is None or ent is None:
            return
        before = params_of(old)
        after = params_of(ent)
        if before is None or after is None or len(before) != len(after):
            self.hold([handle], weight)
            return
        for eid, pa, pb in zip(b.ids, before, after):
            if len(pa) != len(pb):
                self.sk.set_weight(eid, weight)
                continue
            for j, (x, y) in enumerate(zip(pa, pb)):
                same = _angle_close(x, y) if (b.kind == "arc" and j >= 3) else abs(x - y) <= MOVE_TOL
                if not same:
                    self.sk.set_param_weight(eid, j, weight)

    def measure(self, rec: dict) -> float:
        refs = self.refs(rec["refs"])
        try:
            return self.sk.measure(rec["kind"], refs, rec.get("ctx"))
        except SolverFault as err:
            raise S.ParamError(str(err))

    def driven_values(self) -> dict:
        out = {}
        for rec in self.driven:
            try:
                out[rec["id"]] = self.measure(rec)
            except S.ParamError:
                continue
        return out

    def entity_values(self, handle) -> dict:
        b = self.bind[handle]
        sk = self.sk
        if b.kind == "lwpolyline":
            pts = []
            for i, eid in enumerate(b.ids):
                v = sk.values(eid)
                pts.append([v[0], v[1]])
            if not b.closed:
                v = sk.values(b.ids[-1])
                pts.append([v[2], v[3]])
            return {"points": pts}
        return {"v": sk.values(b.ids[0])}

    def write_back(self) -> list:
        changed = []
        for h, b in self.bind.items():
            ent = self.d.get(h)
            if ent is None:
                continue
            if self.apply_one(ent, b):
                changed.append(h)
        return changed

    def apply_one(self, ent, b) -> bool:
        vals = self.entity_values(ent.handle)
        k = b.kind
        if k == "lwpolyline":
            pts = vals["points"]
            if all(abs(pts[i][0] - v["p"][0]) <= MOVE_TOL and abs(pts[i][1] - v["p"][1]) <= MOVE_TOL for i, v in enumerate(ent.vertices)):
                return False
            ent = self.d.modify(ent.handle)
            for i, v in enumerate(ent.vertices):
                v["p"] = [pts[i][0], pts[i][1]] + list(v["p"][2:])
            return True
        v = vals["v"]
        if k == "line":
            cur = [ent.start[0], ent.start[1], ent.end[0], ent.end[1]]
            if _close(cur, v):
                return False
            ent = self.d.modify(ent.handle)
            ent.start = [v[0], v[1]] + list(ent.start[2:])
            ent.end = [v[2], v[3]] + list(ent.end[2:])
        elif k == "point":
            if _close([ent.position[0], ent.position[1]], v):
                return False
            ent = self.d.modify(ent.handle)
            ent.position = [v[0], v[1]] + list(ent.position[2:])
        elif k == "circle":
            if _close([ent.center[0], ent.center[1], ent.radius], v):
                return False
            ent = self.d.modify(ent.handle)
            ent.center = [v[0], v[1]] + list(ent.center[2:])
            ent.radius = v[2]
        elif k == "arc":
            a0, a1 = normal_angle(v[3]), normal_angle(v[4])
            if _close([ent.center[0], ent.center[1], ent.radius], v[:3]) and _angle_close(ent.start_angle, a0) and _angle_close(ent.end_angle, a1):
                return False
            ent = self.d.modify(ent.handle)
            ent.center = [v[0], v[1]] + list(ent.center[2:])
            ent.radius = v[2]
            ent.start_angle = a0
            ent.end_angle = a1
        elif k == "spline":
            c = b.curve
            uniq = len(v) // 2
            ctrl = [[v[2 * (i % uniq)], v[2 * (i % uniq) + 1]] + list(c.ctrl[i][2:]) for i in range(len(c.ctrl))]
            if all(_close(p[:2], q[:2]) for p, q in zip(ctrl, c.ctrl)):
                return False
            ent = self.d.modify(ent.handle)
            ent.control_points = ctrl
            ent.knots = list(c.knots)
            ent.weights = list(c.weights) if c.weights else []
            ent.degree = c.degree
            ent.fit_points = []
        else:
            cur = [ent.center[0], ent.center[1], ent.major[0], ent.major[1], ent.ratio]
            if _close(cur, v[:5]) and (not b.arc or _close([ent.start_param, ent.end_param], v[5:7])):
                return False
            ent = self.d.modify(ent.handle)
            ent.center = [v[0], v[1]] + list(ent.center[2:])
            ent.major = [v[2], v[3]] + list(ent.major[2:])
            ent.ratio = v[4]
            if b.arc:
                ent.start_param, ent.end_param = v[5], v[6]
        return True

    def entity_status(self, rep) -> dict:
        order = {"unconstrained": 0, "fully": 1, "under": 2, "over": 3}
        out = {}
        for h, b in self.bind.items():
            dof = 0
            worst = None
            for eid in b.ids:
                info = rep.entities.get(eid)
                if info is None:
                    continue
                dof += info["dof"]
                if worst is None or order[info["status"]] > order[worst]:
                    worst = info["status"]
            if b.kind == "lwpolyline" and worst in ("fully", "unconstrained"):
                pass
            out[h] = {"status": worst or "unconstrained", "dof": dof}
        return out


def params_of(ent):
    k = ent.kind
    if k == "line":
        return [[ent.start[0], ent.start[1], ent.end[0], ent.end[1]]]
    if k == "point":
        return [[ent.position[0], ent.position[1]]]
    if k == "circle":
        return [[ent.center[0], ent.center[1], ent.radius]]
    if k == "arc":
        return [[ent.center[0], ent.center[1], ent.radius, ent.start_angle, ent.end_angle]]
    if k == "ellipse":
        vals = [ent.center[0], ent.center[1], ent.major[0], ent.major[1], ent.ratio]
        sweep = abs(ent.end_param - ent.start_param)
        if not (sweep < 1e-12 or abs(sweep - TAU) < 1e-9):
            vals += [ent.start_param, ent.end_param]
        return [vals]
    if k == "spline":
        c = curvepath.spline_curve(ent)
        if c is None:
            return None
        uniq = len(c.ctrl) - (c.degree if c.closed and len(c.ctrl) > 2 * c.degree else 0)
        return [[v for p in c.ctrl[:uniq] for v in p[:2]]]
    if k == "lwpolyline":
        n = len(ent.vertices)
        closed = bool(ent.closed) and n >= 3
        count = n if closed else n - 1
        return [[ent.vertices[i]["p"][0], ent.vertices[i]["p"][1], ent.vertices[(i + 1) % n]["p"][0], ent.vertices[(i + 1) % n]["p"][1]] for i in range(count)]
    return None


def _close(a, b) -> bool:
    return all(abs(x - y) <= MOVE_TOL for x, y in zip(a, b))


def _angle_close(a, b) -> bool:
    d = abs(normal_angle(a) - normal_angle(b))
    return d <= MOVE_TOL or abs(d - TAU) <= MOVE_TOL


def handles_of(rec: dict) -> list:
    return [int(r[0]) for r in rec["refs"]]


def load(d, seeds=None, sketch=None, scope=None, everything=False):
    net = Network(d, scope)
    recs = [r for r in S.constraints(d) if not r.get("dangling")]
    by_handle = {}
    for r in recs:
        for h in set(handles_of(r)):
            by_handle.setdefault(h, []).append(r)
    chosen = {}
    todo = list(seeds or [])
    seen = set()
    sk_rec = S.get_sketch(d, sketch) if sketch else None
    if sk_rec is not None:
        todo.extend(h for h in S.members(d, sk_rec) if d.get(h) is not None)
    if everything:
        todo.extend(by_handle.keys())
    while todo:
        h = todo.pop()
        if h in seen:
            continue
        seen.add(h)
        for r in by_handle.get(h, ()):
            if r["id"] not in chosen:
                chosen[r["id"]] = r
                todo.extend(handles_of(r))
    for h in sorted(seen):
        if d.get(h) is not None:
            net.binding(h)
    for cid in sorted(chosen):
        r = chosen[cid]
        if r.get("label") and not r.get("driving", True):
            net.load_driven(r)
        else:
            net.add_record(r)
    return net
