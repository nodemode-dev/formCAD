import math
import re

from app.drawann import settings

DIMENSIONAL = ("distance", "hdistance", "vdistance", "radius", "diameter")
SEG = re.compile(r"^([vs])(\d+)$")


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _unit(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


class Plane:
    def __init__(self, rec):
        self.o = [float(c) for c in rec["origin"]]
        self.x = _unit(rec["x"])
        self.n = _unit(rec["normal"])
        self.y = _unit(_cross(self.n, self.x))

    def to3(self, p):
        return [self.o[i] + p[0] * self.x[i] + p[1] * self.y[i] for i in range(3)]


def _vertex(ent, i):
    v = ent.vertices[i % len(ent.vertices)]["p"]
    return (float(v[0]), float(v[1]))


def ref_points(ent, part):
    k = ent.kind
    if k == "lwpolyline":
        m = SEG.match(str(part))
        if m is None:
            return None
        i = int(m.group(2))
        if m.group(1) == "v":
            return [_vertex(ent, i)]
        return [_vertex(ent, i), _vertex(ent, i + 1)]
    if k == "line":
        if part == "start":
            return [(ent.start[0], ent.start[1])]
        if part == "end":
            return [(ent.end[0], ent.end[1])]
        if part == "mid":
            return [((ent.start[0] + ent.end[0]) / 2.0, (ent.start[1] + ent.end[1]) / 2.0)]
        return [(ent.start[0], ent.start[1]), (ent.end[0], ent.end[1])]
    if k in ("circle", "arc") and part in ("center",):
        return [(ent.center[0], ent.center[1])]
    if k == "point":
        return [(ent.position[0], ent.position[1])]
    return None


def sketch_items(dm) -> list:
    out = []
    for rec in dm.tables["constraints"].values():
        kind = rec.get("kind")
        if kind not in DIMENSIONAL or not rec.get("driving", True) or rec.get("value") is None:
            continue
        sk = dm.tables["sketches"].get(rec.get("sketch", ""))
        if sk is None:
            continue
        plane = Plane(sk["plane"])
        ents = []
        for ref in rec.get("refs", []):
            e = dm.get(int(ref[0]))
            ents.append((e, ref[1] if len(ref) > 1 else "whole"))
        if any(e is None for e, _p in ents):
            continue
        label = rec.get("label") or rec.get("name", "")
        item = {"id": "c%s" % rec["id"], "label": label, "value": float(rec["value"]), "sketch": rec["sketch"], "normal": plane.n, "source": "sketch"}
        if kind in ("radius", "diameter"):
            e = ents[0][0]
            if e.kind not in ("circle", "arc"):
                continue
            item.update({"kind": kind, "center": plane.to3((e.center[0], e.center[1])), "radius": float(e.radius), "x": plane.x})
            out.append(item)
            continue
        pts = []
        for e, part in ents:
            got = ref_points(e, part)
            if got is None:
                pts = []
                break
            pts.extend(got)
        if len(pts) != 2:
            continue
        item.update({"kind": {"distance": "linear", "hdistance": "linear", "vdistance": "linear"}[kind], "a": plane.to3(pts[0]), "b": plane.to3(pts[1])})
        if kind != "distance":
            item["along"] = plane.x if kind == "hdistance" else plane.y
        out.append(item)
    return out


def feature_items(dm) -> list:
    from app.part import rebuild, registry

    out = []
    sketches = {}
    for rec in dm.tables["features"].values():
        if rec.get("type") == "sketch":
            sk = dm.tables["sketches"].get(rec["params"].get("sketch", ""))
            if sk is not None:
                sketches[rec["id"]] = sk
    for rec in dm.tables["features"].values():
        if rec.get("suppressed") or rec.get("type") not in ("extrude", "extrude_cut"):
            continue
        ref = (rec.get("refs") or {}).get("sketch") or {}
        sk = sketches.get(ref.get("id"))
        if sk is None:
            continue
        try:
            vals = rebuild.evaluate(dm, registry.get(rec["type"]), rec.get("params"))
        except Exception:
            continue
        if vals.get("end1") != "blind" or not vals.get("depth1"):
            continue
        plane = Plane(sk["plane"])
        sign = -1.0 if vals.get("flip") else 1.0
        depth = float(vals["depth1"])
        a = list(plane.o)
        b = [a[i] + plane.n[i] * depth * sign for i in range(3)]
        out.append({"id": "%s.depth1" % rec["id"], "label": rec.get("label", rec["id"]), "kind": "linear", "value": depth, "a": a, "b": b, "sketch": sk["name"], "normal": plane.n, "source": "feature"})
    return out


def items(dm) -> list:
    return sketch_items(dm) + feature_items(dm)
