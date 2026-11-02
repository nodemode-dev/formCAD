from app.display.shapes import builder, grip_list, xy


@builder("viewport")
def viewport(e, ctx):
    verts = [[v["p"][0], v["p"][1], v["bulge"], 0.0, 0.0] for v in e.outline()]
    g = {"type": "poly", "verts": verts, "closed": True, "elev": 0.0}
    box = e.bounds()
    return g, [], grip_list([(xy(e.center), "cen")]), [box[0], box[1], box[2], box[3]]
