from app.nurbs3d.form import FormError, NurbsForm

MAX_GRIPS = 4000


def _g(p, kind, gid):
    return {"id": gid, "p": [float(p[0]), float(p[1])], "kind": kind}


def points(e) -> list:
    try:
        form = NurbsForm.from_entity(e)
    except FormError:
        return []
    out = [_g(q, "ctrl", "c%d" % i) for i, q in enumerate(form.poles[:MAX_GRIPS])]
    room = MAX_GRIPS - len(out)
    for i, u in enumerate(form.edit_params()[: max(room, 0)]):
        out.append(_g(form.point(u), "edit", "e%d" % i))
    return out


def stretch(e, gid: str, target) -> None:
    form = NurbsForm.from_entity(e)
    index = int(str(gid)[1:])
    if gid[0] == "c":
        if not 0 <= index < len(form.poles):
            raise FormError("No such control point.")
        z = form.poles[index][2]
        form.poles[index] = [float(target[0]), float(target[1]), z]
    elif gid[0] == "e":
        params = form.edit_params()
        if not 0 <= index < len(params):
            raise FormError("No such edit point.")
        u = params[index]
        z = form.point(u)[2]
        form.move_edit_point(u, [float(target[0]), float(target[1]), z])
    else:
        raise FormError("No such grip.")
    e.poles = [list(q) for q in form.poles]
