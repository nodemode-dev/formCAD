import math
import struct
import time
from collections import Counter

MM = 4


def metric(doc):
    doc.set_var("INSUNITS", MM)
    return doc


def handle_of(reply):
    res = reply.get("result") or {}
    if "handle" in res:
        return int(res["handle"])
    if res.get("handles"):
        return int(res["handles"][0])
    raise AssertionError("no handle in %r" % (reply.get("error") or res))


def box(doc, size, corner=(0, 0, 0)):
    return handle_of(doc.command("box", size=list(size), corner=list(corner)))


def read_stl(path):
    data = open(path, "rb").read()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        tris = []
        pts = []
        for line in data.decode("ascii").splitlines():
            parts = line.split()
            if parts and parts[0] == "vertex":
                pts.append(tuple(float(v) for v in parts[1:4]))
                if len(pts) == 3:
                    tris.append(tuple(pts))
                    pts = []
        return tris
    count = struct.unpack_from("<I", data, 80)[0]
    assert len(data) == 84 + 50 * count, "binary STL size does not match its triangle count"
    tris = []
    for i in range(count):
        v = struct.unpack_from("<12f", data, 84 + 50 * i)
        tris.append((tuple(v[3:6]), tuple(v[6:9]), tuple(v[9:12])))
    return tris


def write_stl(path, tris):
    out = bytearray(b"formcad lane test".ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<12fH", 0.0, 0.0, 0.0, *a, *b, *c, 0)
    open(path, "wb").write(bytes(out))


def indexed(tris, digits=4):
    keys = {}
    verts = []
    faces = []
    for t in tris:
        f = []
        for p in t:
            k = tuple(round(c, digits) for c in p)
            if k not in keys:
                keys[k] = len(verts)
                verts.append(p)
            f.append(keys[k])
        faces.append(tuple(f))
    return verts, faces


def volume(tris):
    total = 0.0
    for a, b, c in tris:
        total += (a[0] * (b[1] * c[2] - b[2] * c[1]) - a[1] * (b[0] * c[2] - b[2] * c[0]) + a[2] * (b[0] * c[1] - b[1] * c[0])) / 6.0
    return total


def area(tris):
    total = 0.0
    for a, b, c in tris:
        u = [b[i] - a[i] for i in range(3)]
        w = [c[i] - a[i] for i in range(3)]
        n = (u[1] * w[2] - u[2] * w[1], u[2] * w[0] - u[0] * w[2], u[0] * w[1] - u[1] * w[0])
        total += 0.5 * math.sqrt(sum(x * x for x in n))
    return total


def open_edges(tris):
    _verts, faces = indexed(tris)
    directed = Counter()
    for f in faces:
        if len(set(f)) < 3:
            continue
        for i in range(3):
            directed[(f[i], f[(i + 1) % 3])] += 1
    bad = 0
    for (a, b), n in directed.items():
        if n != 1 or directed.get((b, a), 0) != 1:
            bad += 1
    return bad


def export_stl(doc, path, handles=None):
    if handles is not None:
        doc.select(handles=list(handles), mode="set")
    reply = doc.command("export", path=str(path), binary=True)
    assert not reply.get("error"), reply.get("error")
    return read_stl(path)


def record(doc, kind, **fields):
    return doc.post("/sim/records", {"kind": kind, "fields": fields})["record"]["id"]


def run_study(doc, sid, mode="run", timeout=300.0):
    job = doc.post("/sim/studies/%s/%s" % (sid, mode))["job"]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        view = doc.get("/sim/jobs/%s" % job["job"])["job"]
        if view["state"] not in ("queued", "running"):
            return view
        time.sleep(0.1)
    raise AssertionError("the study did not finish in %g s" % timeout)


def solved(doc, sid, mode="run"):
    view = run_study(doc, sid, mode)
    assert view["state"] == "done", view["message"]
    return doc.get("/sim/studies/%s/result" % sid)["result"]["summary"]


def probe(doc, sid, points, mode=0):
    return doc.post("/sim/studies/%s/result/probe" % sid, {"points": [list(p) for p in points], "mode": mode})["probes"]
