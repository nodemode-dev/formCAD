from app.cam import toolpath as T
from app.cam.limits import CamError
from app.cam.registry import Field, OpType, register
from app.probing import cycles as C
from app.turning import emit

_ = emit

LABELS = {"surface": "Probe a surface", "edge": "Probe an edge and set the work offset", "bore": "Probe a bore", "boss": "Probe a boss", "width": "Probe a slot or web", "corner": "Probe a corner", "skew": "Probe skew"}
DESCRIPTIONS = {
    "surface": "Touch one face along an axis; reports the surface and its error against the nominal and can shift the work offset.",
    "edge": "Touch a stock edge and set the work offset on that axis to the nominal value.",
    "bore": "Four touches inside a bore, then a second round from the measured centre; centre and diameter, optionally setting the work offset to the centre.",
    "boss": "Four touches around a boss, then a second round from the measured centre; centre and diameter.",
    "width": "Two opposite touches across a slot (inside) or a web (outside); width and centre.",
    "corner": "Two touches on the faces of an outside corner; sets X and Y of the work offset to the corner.",
    "skew": "Two touches along an edge a span apart; the angle of the part, written as the rotation of the work offset.",
}
TYPES = {"axis": ("x", "y", "z"), "direction": (1, -1), "qx": (1, -1), "qy": (1, -1)}
LABEL_OF = {"slot": "Work offset slot", "update": "Write the work offset", "radius": "Stylus ball radius (0 takes the tool)", "feed": "Probe feed", "refine_feed": "Second touch feed", "touches": "Touches per point", "backoff": "Back off before the second touch", "travel": "Probe travel", "clearance": "Safe height z", "z": "Top of the feature z", "depth": "Probe depth below the top", "approach": "Approach distance", "rounds": "Rounds"}


def fields_for(kind):
    out = []
    for k, v in C.defaults(kind).items():
        label = LABEL_OF.get(k, k.replace("_", " ").capitalize())
        if k in TYPES:
            out.append(Field(k, "choice", v, label, choices=TYPES[k], group="Cycle"))
        elif isinstance(v, bool):
            out.append(Field(k, "bool", v, label, group="Cycle"))
        elif k in ("slot", "touches", "rounds"):
            out.append(Field(k, "int", v, label, min=1, max=9, group="Cycle"))
        elif k == "radius":
            out.append(Field(k, "number", None, label, min=0.0, max=20, unit="mm", group="Probe"))
        else:
            lo, hi = C.LIMITS.get(k, (-100000.0, 100000.0))
            out.append(Field(k, "number", v, label, min=lo, max=hi, unit="mm", group="Cycle"))
    return out


def make(kind):
    def gen(ctx):
        t = ctx.tool
        raw = dict(ctx.p)
        if not raw.get("radius"):
            raw["radius"] = t.diameter / 2.0
        try:
            built = C.build(kind, raw)
        except C.ProbeError as err:
            raise CamError(str(err))
        moves = [["comment", "%s T%d %s" % (LABELS[kind], t.number, t.name)], T.tool_change(t.number, 0.0, t.name)]
        moves.extend(built["moves"])
        meta = {"probing": True, "kind": kind, "outputs": built["outputs"], "radius": built["params"]["radius"]}
        return T.Toolpath(moves, meta)

    return gen


for kind in C.KINDS:
    register(OpType(kind="probe_" + kind, label=LABELS[kind], group="probing", generate=make(kind), tool_kinds=("probe",), needs_feeds=False, description=DESCRIPTIONS[kind], fields=fields_for(kind)))
