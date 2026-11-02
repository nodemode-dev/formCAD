import copy

from app.doc import layouts, viewports


def maximize(doc, handle: int) -> dict:
    d = doc.drawing
    vp = d.ents.get(handle)
    if vp is None or vp.kind != "viewport" or vp.owner != doc.tab:
        raise viewports.ViewportError("Select a viewport of this layout.")
    if doc.vp_max:
        minimize(doc, True)
    doc.space_views.setdefault("max:" + doc.tab, copy.deepcopy(doc.view))
    doc.active_vp = vp.handle
    doc.vp_max = vp.handle
    doc.view = {"center": [vp.view_center[0], vp.view_center[1]], "height": vp.view_height}
    layouts.announce(doc)
    return {"viewport": vp.handle, "view": dict(doc.view)}


def restore_view(doc) -> None:
    minimize(doc, True)


def minimize(doc, keep: bool = True) -> bool:
    handle = doc.vp_max
    if not handle:
        return False
    vp = doc.drawing.ents.get(handle)
    saved = doc.space_views.pop("max:" + doc.tab, None)
    doc.vp_max = 0
    if keep and vp is not None and vp.kind == "viewport" and not vp.locked:
        center, height = doc.view["center"], doc.view["height"]
        if abs(center[0] - vp.view_center[0]) > 1e-9 or abs(center[1] - vp.view_center[1]) > 1e-9 or abs(height - vp.view_height) > 1e-9 * max(1.0, height):
            with doc.transaction("VPMIN"):
                ent = doc.drawing.modify(handle)
                ent.view_center = [center[0], center[1], 0.0]
                ent.scale = viewports.clamp_scale(height / ent.height)
    if saved is not None:
        doc.view = saved
    layouts.announce(doc)
    return True
