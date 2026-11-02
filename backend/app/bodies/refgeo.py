import copy
import math
import re

from app.solid import planes as P
from app.solid import work

TABLE = "refgeo"
STATE = "@order"
KINDS = ("plane", "axis", "point", "cs")
METHODS = {
    "plane": ("world", "face", "offset", "parallel_point", "three_points", "edge_point", "angle", "midplane", "perpendicular"),
    "axis": ("two_points", "edge", "cylinder", "planes", "point_direction", "plane_normal"),
    "point": ("coordinates", "vertex", "edge_midpoint", "edge_centre", "face_centre", "axis_plane", "centre_of_mass", "offset"),
    "cs": ("world", "three_points", "origin_directions", "plane"),
}
PREFIX = {"plane": "Plane", "axis": "Axis", "point": "Point", "cs": "Coordinate system"}
NAME = re.compile(r"^[^\x00-\x1f@][^\x00-\x1f]{0,79}$")
TINY = 1e-9
MAX_REFS = 2000


class RefError(ValueError):
    pass


def num(v, what="a number") -> float:
    if isinstance(v, bool):
        raise RefError("Give %s." % what)
    try:
        out = float(v)
    except (TypeError, ValueError):
        raise RefError("Give %s." % what)
    if not math.isfinite(out):
        raise RefError("Give %s." % what)
    return out


def v3(value, what="point") -> tuple:
    try:
        return P.vec(value, what)
    except P.PlaneError as err:
        raise RefError(str(err))


def add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a, k):
    return (a[0] * k, a[1] * k, a[2] * k)


def unit3(a, what="A direction"):
    n = P.length(a)
    if n < TINY:
        raise RefError("%s has no length." % what)
    return (a[0] / n, a[1] / n, a[2] / n)


def frame_from_z(name, origin, z, hint=None):
    z = unit3(z)
    if hint is not None:
        x = (hint[0] - P.dot(hint, z) * z[0], hint[1] - P.dot(hint, z) * z[1], hint[2] - P.dot(hint, z) * z[2])
        if P.length(x) > 1e-6:
            x = unit3(x)
            return P.make(name, origin, x, P.cross(z, x), z)
    plane = P.on_face(origin, z)
    return P.make(name, origin, plane["x"], plane["y"], plane["z"])


class Resolver:
    def __init__(self, d):
        self.d = d
        self.s = work.mm(d)
        self.cache = {}

    def record(self, name):
        t = self.d.tables.get(TABLE)
        rec = t.get(name) if t is not None else None
        if rec is None or rec.get("kind") not in KINDS:
            raise RefError("There is no reference geometry called %s." % name)
        if rec.get("status") != "ok":
            raise RefError("%s is in error: %s" % (rec["name"], rec.get("message", "")))
        return rec

    def body(self, handle):
        try:
            b = self.d.get(int(handle))
        except (TypeError, ValueError):
            b = None
        if b is None or b.kind != "solidbody":
            raise RefError("The body %s no longer exists." % handle)
        return b

    def index_of(self, body, pid, which):
        ids = body.face_ids if which == "face" else body.edge_ids
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise RefError("A %s reference needs its id." % which)
        if pid in ids:
            return ids.index(pid)
        kids = [c for c in ids if body.lineage.get(str(c)) == pid]
        if len(kids) == 1:
            return ids.index(kids[0])
        raise RefError("The %s %s of %s was lost by an edit%s." % (which, pid, body.name or "the body", "; it became several faces, pick one again" if kids else ""))

    def kernel(self, ref, which):
        body = self.body(ref.get("body"))
        key = (body.handle, body.version, which, ref.get(which))
        if key in self.cache:
            return self.cache[key]
        if which == "vertex":
            index = int(num(ref.get("vertex"), "a vertex index"))
        else:
            index = self.index_of(body, ref.get(which), which)
        try:
            raw = work.kcall("geometry", {"id": work.worker_id(self.d, body), which: index})
        except work.SolidError as err:
            raise RefError(str(err))
        out = self.to_doc(raw)
        self.cache[key] = out
        return out

    def to_doc(self, raw):
        s = self.s
        out = dict(raw)
        for key in ("origin", "centroid", "start", "end", "mid", "centre", "axis_origin", "point"):
            if raw.get(key) is not None:
                out[key] = tuple(c / s for c in raw[key])
        for key in ("radius", "major", "minor"):
            if raw.get(key) is not None:
                out[key] = raw[key] / s
        if raw.get("area") is not None:
            out["area"] = raw["area"] / (s * s)
        return out

    def point(self, ref):
        if isinstance(ref, (list, tuple)):
            return v3(ref)
        if isinstance(ref, dict):
            if "ref" in ref:
                rec = self.record(ref["ref"])
                g = rec["geometry"]
                if rec["kind"] == "point":
                    return tuple(g["point"])
                if rec["kind"] in ("cs", "plane"):
                    return tuple(g["origin"])
                raise RefError("%s is not a point." % rec["name"])
            if "vertex" in ref:
                return tuple(self.kernel(ref, "vertex")["point"])
            if "point" in ref:
                return v3(ref["point"])
        raise RefError("A point is three numbers, a vertex or a named point.")

    def plane(self, ref):
        if isinstance(ref, str):
            try:
                return P.world(ref)
            except P.PlaneError as err:
                raise RefError(str(err))
        if isinstance(ref, dict):
            if "ref" in ref:
                rec = self.record(ref["ref"])
                if rec["kind"] in ("plane", "cs"):
                    g = rec["geometry"]
                    return P.make(rec["name"], g["origin"], g["x"], g["y"], g["z"])
                raise RefError("%s is not a plane." % rec["name"])
            if "face" in ref:
                g = self.kernel(ref, "face")
                if g.get("kind") != "plane":
                    raise RefError("That face is not flat, so it does not give a plane.")
                return frame_from_z("Face", g["origin"], g["normal"], g.get("xdir"))
            if "world" in ref:
                return P.world(ref["world"], v3(ref.get("origin", [0, 0, 0]), "origin"))
        raise RefError("A plane is a face, a named plane or a world plane.")

    def line(self, ref):
        if isinstance(ref, dict):
            if "ref" in ref:
                rec = self.record(ref["ref"])
                if rec["kind"] != "axis":
                    raise RefError("%s is not an axis." % rec["name"])
                g = rec["geometry"]
                return tuple(g["origin"]), tuple(g["direction"])
            if "edge" in ref:
                g = self.kernel(ref, "edge")
                if g["kind"] == "line":
                    return tuple(g["start"]), unit3(g["direction"])
                if g["kind"] == "circle":
                    return tuple(g["centre"]), unit3(g["axis"])
                raise RefError("That edge is not a straight line or a circle.")
            if "face" in ref:
                g = self.kernel(ref, "face")
                if g["kind"] in ("cylinder", "cone"):
                    return tuple(g["axis_origin"]), unit3(g["axis"])
                raise RefError("That face is not a cylinder or a cone, so it has no axis.")
        raise RefError("An axis is a line edge, a round face, a circle edge or a named axis.")


def rotate_about(vec, axis, degrees):
    a = math.radians(degrees)
    c, s = math.cos(a), math.sin(a)
    k = axis
    kv = P.cross(k, vec)
    kd = P.dot(k, vec)
    return (vec[0] * c + kv[0] * s + k[0] * kd * (1 - c), vec[1] * c + kv[1] * s + k[1] * kd * (1 - c), vec[2] * c + kv[2] * s + k[2] * kd * (1 - c))


def need(params, key):
    if key not in params or params[key] is None:
        raise RefError("%s is missing." % key)
    return params[key]


def refof(p, key):
    v = need(p, key)
    if isinstance(v, int) and not isinstance(v, bool):
        return {"body": p.get("body"), key: v}
    return v


def make_plane(r: Resolver, method, p):
    if method == "world":
        return P.world(str(need(p, "world")), v3(p.get("origin", [0, 0, 0]), "origin"))
    if method == "face":
        return r.plane(refof(p, "face"))
    if method == "offset":
        pl = r.plane(need(p, "plane"))
        k = num(need(p, "distance"), "a distance")
        return P.make("Offset", add(pl["origin"], scale(pl["z"], k)), pl["x"], pl["y"], pl["z"])
    if method == "parallel_point":
        pl = r.plane(need(p, "plane"))
        return P.make("Parallel", r.point(need(p, "point")), pl["x"], pl["y"], pl["z"])
    if method == "three_points":
        pts = need(p, "points")
        if not isinstance(pts, list) or len(pts) != 3:
            raise RefError("Give three points.")
        try:
            return P.through_points(*[r.point(x) for x in pts])
        except P.PlaneError as err:
            raise RefError(str(err))
    if method == "edge_point":
        o, dr = r.line(refof(p, "edge"))
        pt = r.point(need(p, "point"))
        n = P.cross(dr, P.sub(pt, o))
        if P.length(n) < 1e-9 * max(1.0, P.length(P.sub(pt, o))):
            raise RefError("The point is on the line, so it does not fix a plane.")
        return frame_from_z("Edge and point", o, n, dr)
    if method == "angle":
        pl = r.plane(need(p, "plane"))
        o, dr = r.line(need(p, "axis"))
        if abs(P.dot(dr, pl["z"])) > 1e-6:
            raise RefError("The axis must lie in, or be parallel to, the starting plane.")
        deg = num(need(p, "degrees"), "an angle in degrees")
        x, z = rotate_about(pl["x"], dr, deg), rotate_about(pl["z"], dr, deg)
        return P.make("Angle", o, unit3(x), unit3(P.cross(z, x)), unit3(z))
    if method == "midplane":
        pair = need(p, "planes")
        if not isinstance(pair, list) or len(pair) != 2:
            raise RefError("Give two planes.")
        a, b = r.plane(pair[0]), r.plane(pair[1])
        if abs(abs(P.dot(a["z"], b["z"])) - 1.0) > 1e-6:
            raise RefError("The two planes are not parallel, so there is no middle plane.")
        mid = scale(add(a["origin"], b["origin"]), 0.5)
        gap = abs(P.dot(P.sub(b["origin"], a["origin"]), a["z"]))
        if gap < 1e-9:
            raise RefError("The two planes are the same plane.")
        off = P.dot(P.sub(mid, a["origin"]), a["z"])
        return P.make("Middle", add(a["origin"], scale(a["z"], off)), a["x"], a["y"], a["z"])
    if method == "perpendicular":
        o, dr = r.line(need(p, "axis"))
        at = r.point(p["point"]) if p.get("point") is not None else o
        return frame_from_z("Normal to axis", at, dr)
    raise RefError("Unknown plane method %s." % method)


def make_axis(r: Resolver, method, p):
    if method == "two_points":
        pts = need(p, "points")
        if not isinstance(pts, list) or len(pts) != 2:
            raise RefError("Give two points.")
        a, b = r.point(pts[0]), r.point(pts[1])
        return {"origin": a, "direction": unit3(P.sub(b, a), "The two points are the same, so the axis")}
    if method == "edge":
        o, dr = r.line(refof(p, "edge"))
        return {"origin": o, "direction": dr}
    if method == "cylinder":
        o, dr = r.line(refof(p, "face"))
        return {"origin": o, "direction": dr}
    if method == "planes":
        pair = need(p, "planes")
        if not isinstance(pair, list) or len(pair) != 2:
            raise RefError("Give two planes.")
        a, b = r.plane(pair[0]), r.plane(pair[1])
        d = P.cross(a["z"], b["z"])
        if P.length(d) < 1e-9:
            raise RefError("The two planes are parallel, so they do not meet in a line.")
        na, nb = a["z"], b["z"]
        ha, hb = P.dot(na, a["origin"]), P.dot(nb, b["origin"])
        dd = P.dot(d, d)
        pt = scale(add(scale(P.cross(d, nb), ha), scale(P.cross(na, d), hb)), 1.0 / dd)
        return {"origin": pt, "direction": unit3(d)}
    if method == "point_direction":
        return {"origin": r.point(need(p, "point")), "direction": unit3(v3(need(p, "direction"), "direction"))}
    if method == "plane_normal":
        pl = r.plane(need(p, "plane"))
        at = r.point(p["point"]) if p.get("point") is not None else pl["origin"]
        return {"origin": at, "direction": pl["z"]}
    raise RefError("Unknown axis method %s." % method)


def make_point(r: Resolver, method, p):
    if method == "coordinates":
        return {"point": v3(need(p, "xyz"), "coordinates")}
    if method == "vertex":
        return {"point": r.point(refof(p, "vertex"))}
    if method in ("edge_midpoint", "edge_centre"):
        g = r.kernel(refof(p, "edge"), "edge")
        if method == "edge_midpoint":
            return {"point": tuple(g["mid"])}
        if g["kind"] != "circle":
            raise RefError("That edge is not a circle or an arc, so it has no centre.")
        return {"point": tuple(g["centre"])}
    if method == "face_centre":
        g = r.kernel(refof(p, "face"), "face")
        return {"point": tuple(g["centroid"])}
    if method == "axis_plane":
        o, dr = r.line(need(p, "axis"))
        pl = r.plane(need(p, "plane"))
        den = P.dot(dr, pl["z"])
        if abs(den) < 1e-9:
            raise RefError("The axis is parallel to the plane, so they do not meet.")
        t = P.dot(P.sub(pl["origin"], o), pl["z"]) / den
        return {"point": add(o, scale(dr, t))}
    if method == "centre_of_mass":
        from app.bodies import massprops

        handles = p.get("bodies") or ([p["body"]] if p.get("body") is not None else [])
        if not handles:
            raise RefError("Give the body.")
        res = massprops.compute(r.d, [int(h) for h in handles])
        if res.get("centroid") is None:
            raise RefError("The bodies have no centre of mass: %s" % res.get("note", ""))
        return {"point": tuple(res["doc"]["centroid"])}
    if method == "offset":
        return {"point": add(r.point(need(p, "point")), v3(need(p, "vector"), "vector"))}
    raise RefError("Unknown point method %s." % method)


def make_cs(r: Resolver, method, p):
    o = r.point(p["origin"]) if p.get("origin") is not None else (0.0, 0.0, 0.0)
    if method == "world":
        return {"origin": o, "x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
    if method == "three_points":
        x = unit3(P.sub(r.point(need(p, "x_point")), o), "The x point is at the origin, so the x direction")
        yv = P.sub(r.point(need(p, "y_point")), o)
        z = P.cross(x, yv)
        if P.length(z) < 1e-9 * max(1.0, P.length(yv)):
            raise RefError("The three points are on one line.")
        z = unit3(z)
        return {"origin": o, "x": x, "y": P.cross(z, x), "z": z}
    if method == "origin_directions":
        x = unit3(v3(need(p, "x"), "x direction"))
        yv = v3(need(p, "y"), "y direction")
        z = P.cross(x, yv)
        if P.length(z) < 1e-9 * max(1.0, P.length(yv)):
            raise RefError("The x and y directions are parallel.")
        z = unit3(z)
        return {"origin": o, "x": x, "y": P.cross(z, x), "z": z}
    if method == "plane":
        pl = r.plane(need(p, "plane"))
        return {"origin": r.point(p["origin"]) if p.get("origin") is not None else pl["origin"], "x": pl["x"], "y": pl["y"], "z": pl["z"]}
    raise RefError("Unknown coordinate system method %s." % method)


def clean(value):
    if isinstance(value, (tuple, list)):
        return [clean(v) for v in value]
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise RefError("The result is not a finite number.")
    if isinstance(value, float):
        return 0.0 if abs(value) < 1e-14 else value
    return value


def resolve(d, kind, method, params, resolver=None) -> dict:
    if kind not in KINDS:
        raise RefError("Choose a kind: %s." % ", ".join(KINDS))
    if method not in METHODS[kind]:
        raise RefError("Choose a %s method: %s." % (kind, ", ".join(METHODS[kind])))
    if not isinstance(params, dict):
        raise RefError("The parameters must be an object.")
    r = resolver or Resolver(d)
    if kind == "plane":
        pl = make_plane(r, method, params)
        return clean({"origin": pl["origin"], "x": pl["x"], "y": pl["y"], "z": pl["z"]})
    if kind == "cs":
        return clean(make_cs(r, method, params))
    if kind == "axis":
        return clean(make_axis(r, method, params))
    return clean(make_point(r, method, params))


def records(d) -> list:
    t = d.tables.get(TABLE)
    rows = [r for r in (t.values() if t is not None else []) if r.get("kind") in KINDS]
    return sorted(rows, key=lambda r: r.get("seq", 0))


def next_seq(d) -> int:
    rows = records(d)
    return (max(r.get("seq", 0) for r in rows) + 1) if rows else 1


def unique_name(d, kind) -> str:
    t = d.tables[TABLE]
    n = 1
    while t.has("%s%d" % (PREFIX[kind], n)):
        n += 1
    return "%s%d" % (PREFIX[kind], n)


def check_name(d, name, ignore=""):
    if not isinstance(name, str) or not NAME.match(name):
        raise RefError("A name has 1 to 80 characters and does not start with @.")
    t = d.tables[TABLE]
    if t.has(name) and name.casefold() != ignore.casefold():
        raise RefError("%s is already used." % name)


def create(d, kind, method, params, name=None) -> dict:
    if len(records(d)) >= MAX_REFS:
        raise RefError("The document holds too many reference items.")
    geometry = resolve(d, kind, method, params)
    nm = name or unique_name(d, kind)
    check_name(d, nm)
    rec = {"name": nm, "kind": kind, "method": method, "params": copy.deepcopy(params), "geometry": geometry, "visible": True, "status": "ok", "message": "", "seq": next_seq(d)}
    d.table_set(TABLE, rec)
    return rec


def uses(rec, name) -> bool:
    text = repr(rec.get("params"))
    return ("'ref': %r" % name) in text


def update(d, name, params=None, new_name=None, visible=None) -> dict:
    t = d.tables[TABLE]
    old = t.get(name)
    if old is None or old.get("kind") not in KINDS:
        raise RefError("There is no reference geometry called %s." % name)
    rec = copy.deepcopy(old)
    if params is not None:
        rec["geometry"] = resolve(d, rec["kind"], rec["method"], params)
        rec["params"] = copy.deepcopy(params)
        rec["status"], rec["message"] = "ok", ""
    if visible is not None:
        rec["visible"] = bool(visible)
    renamed = new_name and new_name != old["name"]
    if renamed:
        check_name(d, new_name, old["name"])
        rec["name"] = new_name
        d.table_remove(TABLE, old["name"])
        for other in records(d):
            if uses(other, old["name"]):
                fixed = copy.deepcopy(other)
                fixed["params"] = rename_in(fixed["params"], old["name"], new_name)
                d.table_set(TABLE, fixed)
    d.table_set(TABLE, rec)
    if params is not None:
        rebuild(d)
    return t.get(rec["name"])


def rename_in(value, old, new):
    if isinstance(value, dict):
        return {k: (new if (k == "ref" and v == old) else rename_in(v, old, new)) for k, v in value.items()}
    if isinstance(value, list):
        return [rename_in(v, old, new) for v in value]
    return value


def delete(d, name) -> dict:
    t = d.tables[TABLE]
    rec = t.get(name)
    if rec is None or rec.get("kind") not in KINDS:
        raise RefError("There is no reference geometry called %s." % name)
    users = [r["name"] for r in records(d) if r["name"] != rec["name"] and uses(r, rec["name"])]
    if users:
        raise RefError("%s is used by %s; remove those first." % (rec["name"], ", ".join(users)))
    d.table_remove(TABLE, rec["name"])
    return {"removed": rec["name"]}


def rebuild(d) -> dict:
    r = Resolver(d)
    bad = []
    for rec in records(d):
        try:
            g = resolve(d, rec["kind"], rec["method"], rec["params"], r)
            status, msg = "ok", ""
        except (RefError, work.SolidError) as err:
            g, status, msg = rec["geometry"], "error", str(err)
            bad.append(rec["name"])
        if g != rec["geometry"] or status != rec["status"] or msg != rec["message"]:
            fixed = copy.deepcopy(rec)
            fixed.update(geometry=g, status=status, message=msg)
            d.table_set(TABLE, fixed)
    return {"errors": bad}


def describe(d) -> list:
    return [dict(r) for r in records(d)]


def cs_frame(d, spec):
    if spec in (None, "", "world"):
        return {"name": "World", "origin": (0.0, 0.0, 0.0), "x": (1.0, 0.0, 0.0), "y": (0.0, 1.0, 0.0), "z": (0.0, 0.0, 1.0)}
    if isinstance(spec, str):
        rec = Resolver(d).record(spec)
        if rec["kind"] not in ("cs", "plane"):
            raise RefError("%s is not a coordinate system." % spec)
        g = rec["geometry"]
        return {"name": rec["name"], "origin": tuple(g["origin"]), "x": tuple(g["x"]), "y": tuple(g["y"]), "z": tuple(g["z"])}
    if isinstance(spec, dict):
        if "ref" in spec:
            return cs_frame(d, spec["ref"])
        g = resolve(d, "cs", str(spec.get("method") or "origin_directions"), {k: v for k, v in spec.items() if k != "method"})
        return {"name": "Custom", "origin": tuple(g["origin"]), "x": tuple(g["x"]), "y": tuple(g["y"]), "z": tuple(g["z"])}
    raise RefError("Name a coordinate system, give one, or use world.")
