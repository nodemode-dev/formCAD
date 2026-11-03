import math
import time

from app.sheetmetal import bend as B
from app.sheetmetal import flat as sm
from app.views import model
from app.views.model import ViewError

TAU = 2.0 * math.pi


def curve_of(seg, c):
    t = seg["t"]
    if t == "line":
        return {"t": "line", "a": [seg["a"][0] - c[0], seg["a"][1] - c[1]], "b": [seg["b"][0] - c[0], seg["b"][1] - c[1]]}
    if t == "arc":
        return {"t": "arc", "c": [seg["c"][0] - c[0], seg["c"][1] - c[1]], "r": seg["r"], "a0": seg["a0"] % TAU, "a1": seg["a1"] % TAU}
    if t == "circle":
        return {"t": "circle", "c": [seg["c"][0] - c[0], seg["c"][1] - c[1]], "r": seg["r"]}
    return {"t": "poly", "pts": [[p[0] - c[0], p[1] - c[1]] for p in seg["pts"]]}


def note_of(b, report) -> str:
    angle = math.degrees(b["angle"] if report != "open" else math.pi - b["angle"])
    return "%s %.1f DEG R%.3g" % (b["direction"].upper(), angle, b["radius"])


def compute(doc, view, items) -> tuple:
    d = doc.drawing
    if view.source.get("doc"):
        raise ViewError("A flat pattern view needs a part in this drawing, not another file.")
    bodies = [i for i in items if i.kind == "body"]
    if len(bodies) != 1:
        raise ViewError("A flat pattern view needs exactly one sheet metal body; give the body handle as the view component.")
    t0 = time.perf_counter()
    try:
        data = sm.compute(d, bodies[0].body.handle)
    except (sm.FlatError, B.BendError) as err:
        raise ViewError(str(err))
    box = data["bbox"]
    c = [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0]
    recs = []
    for lp in data["loops"]:
        for seg in lp["segs"]:
            recs.append(curve_of(seg, c))
    classes = {k: [] for k in model.CLASSES}
    classes["sharp_v"] = recs
    bends = []
    report = data.get("angle_report", "bend")
    for b in data["bends"]:
        bends.append({"id": b["id"], "a": [b["a"][0] - c[0], b["a"][1] - c[1]], "b": [b["b"][0] - c[0], b["b"][1] - c[1]], "direction": b["direction"], "angle": b["angle"], "radius": b["radius"], "k": b["k"], "note": note_of(b, report)})
    half = [(box[2] - box[0]) / 2.0, (box[3] - box[1]) / 2.0]
    bounds = [-half[0], -half[1], half[0], half[1]]
    res = {
        "classes": classes, "faces": [], "extra": [], "bounds": bounds, "frame": {"x": [1.0, 0.0, 0.0], "y": [0.0, 1.0, 0.0], "n": [0.0, 0.0, 1.0]},
        "origin": [0.0, 0.0, 0.0], "model_bbox": [box[0], box[1], 0.0, box[2], box[3], 0.0], "counts": {"edges": len(recs), "bends": len(bends)},
        "stats": {"mode": "flat", "round_trip_ms": (time.perf_counter() - t0) * 1000.0}, "bends": bends, "breaks": [],
    }
    return res
