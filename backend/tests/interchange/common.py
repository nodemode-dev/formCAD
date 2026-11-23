import math
from collections import Counter

LAYERS = {"Walls": 1, "Holes": 3, "Paths": 5, "Notes": 2, "Fill": 4, "Dims": 6}
ACADVER = {"R12": "AC1009", "R2000": "AC1015", "R2004": "AC1018", "R2007": "AC1021", "R2010": "AC1024", "R2013": "AC1027", "R2018": "AC1032"}


def cmd(doc, _command, **args):
    out = doc.post("/command", {"command": _command, "args": args})
    doc.last = out
    return out


def ok(doc, _command, **args):
    out = cmd(doc, _command, **args)
    assert not out.get("error"), "%s refused: %s" % (_command, out.get("error"))
    return out.get("result") or {}


def metric(doc):
    doc.set_var("INSUNITS", 4)
    return doc


def layer(doc, name):
    ok(doc, "layer", name=name, color=LAYERS[name], make=True)


def draw_sample(doc):
    metric(doc)
    layer(doc, "Walls")
    ok(doc, "line", points=[[0, 0], [30, 40]])
    layer(doc, "Holes")
    ok(doc, "circle", center=[100, 50], radius=12.5)
    ok(doc, "arc", points=[[0, 100], [10, 110], [20, 100]])
    layer(doc, "Paths")
    ok(doc, "pline", vertices=[{"point": [0, 0], "bulge": 0}, {"point": [10, 0], "bulge": 1}, {"point": [10, 10]}])
    ok(doc, "ellipse", center=[50, 50], major=[20, 0], ratio=0.5)
    layer(doc, "Notes")
    ok(doc, "text", text="HELLO", point=[5, 5], height=2.5)
    layer(doc, "Fill")
    ok(doc, "line", points=[[200, 0], [260, 0], [260, 40], [200, 40]], closed=True)
    ok(doc, "hatch", points=[[230, 20]], pattern="ANSI31")
    layer(doc, "Dims")
    ok(doc, "dimlinear", p13=[0, 0], p14=[30, 0], location=[15, -10])
    peg = ok(doc, "circle", center=[0, 0], radius=2)["handle"]
    ok(doc, "block", name="PEG", handles=[peg], base=[0, 0], mode="delete")
    ok(doc, "insert", name="PEG", point=[300, 300])
    return doc


def model(doc):
    return [e for e in doc.entities() if e["owner"] == "model"]


def model_kinds(doc):
    return Counter(e["kind"] for e in model(doc))


def extents(ents):
    pts = []
    for e in ents:
        k = e["kind"]
        if k == "line":
            pts += [e["start"], e["end"]]
        elif k == "circle":
            c, r = e["center"], e["radius"]
            pts += [[c[0] - r, c[1] - r], [c[0] + r, c[1] + r]]
        elif k == "lwpolyline":
            pts += [v["p"] for v in e["vertices"]]
        elif k in ("text", "insert"):
            pts.append(e["position"])
    xs = [float(p[0]) for p in pts]
    ys = [float(p[1]) for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def layer_table(doc):
    rows = doc.get("/layers")["layers"]
    return {r["name"]: r for r in rows}


def lw_vertices(record):
    verts = []
    for code, value in record.codes:
        if code == 10:
            verts.append([float(value), None, 0.0])
        elif code == 20 and verts:
            verts[-1][1] = float(value)
        elif code == 42 and verts:
            verts[-1][2] = float(value)
    return [(x, y, b) for x, y, b in verts]


def polyline_length(verts, closed=False):
    total = 0.0
    n = len(verts)
    for i in range(n if closed else n - 1):
        x0, y0, b = verts[i]
        x1, y1, _ = verts[(i + 1) % n]
        chord = math.hypot(x1 - x0, y1 - y0)
        if abs(b) < 1e-12:
            total += chord
        else:
            theta = 4.0 * math.atan(abs(b))
            total += theta * chord / (2.0 * math.sin(theta / 2.0))
    return total


def nurbs_point(degree, poles, weights, knots, t):
    n = len(poles)
    w = list(weights) if weights else [1.0] * n
    k = len(knots) - 1 - degree - 1
    span = degree
    while span < k and knots[span + 1] <= t:
        span += 1
    d = [[poles[j][i] * w[j] for i in range(3)] + [w[j]] for j in range(span - degree, span + 1)]
    for r in range(1, degree + 1):
        for j in range(degree, r - 1, -1):
            i = span - degree + j
            den = knots[i + degree - r + 1] - knots[i]
            a = 0.0 if den == 0 else (t - knots[i]) / den
            d[j] = [(1.0 - a) * d[j - 1][m] + a * d[j][m] for m in range(4)]
    p = d[degree]
    return p[0] / p[3], p[1] / p[3], p[2] / p[3]


def nurbs_samples(e, count=41):
    knots = []
    for kv, m in zip(e["knots"], e["mults"]):
        knots += [float(kv)] * int(m)
    poles = [list(map(float, p)) + [0.0] * (3 - len(p)) for p in e["poles"]]
    lo, hi = knots[e["degree"]], knots[len(knots) - e["degree"] - 1]
    return [nurbs_point(e["degree"], poles, e["weights"], knots, lo + (hi - lo) * i / (count - 1)) for i in range(count)]
