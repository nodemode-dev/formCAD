def metric(doc):
    doc.set_var("INSUNITS", 4)
    return doc


def sketch(doc, plane, *drawing, offset=None, face=None):
    if face is not None:
        doc.command("partsketch", face=face)
    elif offset is None:
        doc.type("PARTSKETCH", plane)
    else:
        doc.command("partsketch", plane=plane, offset=offset)
    for line in drawing:
        doc.type(*line)
    doc.type("PARTSKETCHDONE")
    return tree(doc)["features"][-1]["label"]


def rectangle(doc, x0, y0, x1, y1, plane="XY", offset=None):
    return sketch(doc, plane, ("RECTANG", "%g,%g" % (x0, y0), "%g,%g" % (x1, y1)), offset=offset)


def tree(doc):
    return doc.get("/part")


def feature(doc, fid):
    return doc.get("/part/features/%s" % fid)


def add(doc, kind, params=None, refs=None, **extra):
    body = {"type": kind, "params": params or {}, "refs": refs or {}}
    body.update(extra)
    return doc.post("/part/features", body)


def extrude(doc, sketch_label, depth, **params):
    out = doc.command("featextrude", sketch=sketch_label, depth1=depth, params=params or None)
    return out["result"]["id"]


def cut(doc, sketch_label, depth, **params):
    out = doc.command("featcut", sketch=sketch_label, depth1=depth, params=params or None)
    return out["result"]["id"]


def box(doc, dx, dy, dz):
    return extrude(doc, rectangle(doc, 0, 0, dx, dy), dz)


def mass(doc):
    return doc.post("/bodies/massprops", {})


def volume(doc):
    return mass(doc)["doc"]["volume"]


def area(doc):
    return mass(doc)["doc"]["area"]


def centroid(doc):
    return mass(doc)["doc"]["centroid"]


def status(doc, fid):
    return feature(doc, fid)["state"]["status"]


def bodies(doc):
    return doc.get("/bodies")["bodies"]


def extents(doc):
    found = bodies(doc)
    lo = [min(b["summary"]["bbox"][i] for b in found) for i in range(3)]
    hi = [max(b["summary"]["bbox"][i + 3] for b in found) for i in range(3)]
    return lo, hi


def edge_ref(i):
    return {"index": i}


def face_ref(fid, role):
    return {"feature": fid, "role": role}
