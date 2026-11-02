from app.display.shapes import builder, grip_list, xy


@builder("viewport")
def viewport(e, ctx):
    pts = [xy(p) for p in e.corners()]
    verts = [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts]
    g = {"type": "poly", "verts": verts, "closed": True, "elev": 0.0}
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return g, [], grip_list([(xy(e.center), "cen")]), [min(xs), min(ys), max(xs), max(ys)]
