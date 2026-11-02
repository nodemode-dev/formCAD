from app.display.shapes import box, builder, grip_list
from app.nurbs3d.form import FormError, NurbsForm

MAX_SAMPLES = 6000


@builder("nurbscurve")
def nurbscurve(e, ctx):
    try:
        form = NurbsForm.from_entity(e)
    except FormError:
        return {"type": "compound", "parts": []}, [], [], None
    spans = max(len(form.knots) - 1, 1)
    per = max(4, min(48, MAX_SAMPLES // spans))
    pts = form.sample(per)
    verts = [[p[0], p[1], 0.0, 0.0, 0.0] for p in pts]
    g = {"type": "poly", "verts": verts, "closed": False, "elev": 0.0}
    xy = [(p[0], p[1]) for p in pts]
    return g, [], grip_list([(p, "ctrl") for p in xy[:1]]), box(xy)
