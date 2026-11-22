import math

from app.part import store
from app.part.features_bodies import tool_ids
from app.part.registry import FeatureType, Param, PartError, RefLost, RefSlot, register
from app.solid import holes

CYLINDER_KIND = 1
ALIGN = 0.9999


def cosmetic_near(step, sig):
    held = getattr(step.rb.cache, "cosmetic", None) or {}
    order = store.tree(step.d)["order"]
    fid = step.feat["id"]
    earlier = order[: order.index(fid)] if fid in order else order
    n, c = sig.get("n") or [0.0, 0.0, 1.0], sig.get("c") or [0.0, 0.0, 0.0]
    tol = max(1e-3, 1e-3 * float(sig.get("r") or 1.0))
    out = []
    for hid in earlier:
        for rec in held.get(hid) or []:
            axis, pos = rec.get("axis") or [0, 0, 0], rec.get("position") or [0, 0, 0]
            ln = math.sqrt(sum(v * v for v in axis)) or 1.0
            if abs(sum(axis[i] * n[i] for i in range(3))) / ln < ALIGN:
                continue
            w = [pos[i] - c[i] for i in range(3)]
            along = sum(w[i] * n[i] for i in range(3))
            if math.sqrt(max(sum(v * v for v in w) - along * along, 0.0)) <= tol:
                out.append(rec)
    return out


def thread_plan(step):
    idx = step.face("face")
    sig = step.signatures("faces").get(str(idx)) or {}
    if sig.get("k") != CYLINDER_KIND or not sig.get("r"):
        raise PartError("A thread needs a cylindrical face; choose the outside of a shaft or the wall of a hole.")
    diameter = 2.0 * float(sig["r"])
    near = cosmetic_near(step, sig)
    cands = holes.thread_candidates(str(step.p("size") or "").strip(), str(step.p("standard") or ""), diameter, near)
    pitch = step.length("pitch")
    if pitch is not None and pitch <= 0:
        raise PartError("The pitch must be positive.")
    if pitch is None and not any(c and c.get("pitch") for c in cands.values()):
        raise PartError("No thread size in the hole table matches the face diameter %.4g mm; choose a size or type the pitch." % diameter)
    step.cosmetic_match = near
    p = {"face": idx, "op": step.p("op") or "cut", "candidates": cands, "pitch": pitch, "length": step.length("length"), "offset": step.length("offset") or 0.0, "hand": step.p("hand") or "right", "flip": bool(step.p("flip"))}
    return {"method": "feat_thread", "params": p}


def thread_finish(step, res):
    info = res.get("thread") or {}
    if info.get("note"):
        step.warn(info["note"])
    if info.get("from_hole"):
        for rec in getattr(step, "cosmetic_match", None) or []:
            rec["modelled"] = step.feat["id"]
    held = getattr(step.rb.cache, "threads", None)
    if held is None:
        held = {}
        step.rb.cache.threads = held
    held[step.feat["id"]] = info


def thicken_plan(step):
    t = step.length("thickness")
    if not t or t <= 0:
        raise PartError("The thickness must be positive.")
    faces = step.faces("faces") if step.refs("faces") else []
    sheets = tool_ids(step, "thicken") if step.p("tools") else []
    if not faces and not sheets:
        raise RefLost("Choose the faces or the sheet bodies to thicken.", "faces")
    if step.base is None and (step.p("op") or "add") == "cut":
        raise PartError("There is no body to cut with the thickened sheet yet.")
    return {"method": "feat_thicken", "params": {"faces": faces, "sheets": sheets, "thickness": t, "side": step.p("side") or "first", "op": step.p("op") or "add"}}


def delete_face_plan(step):
    faces = step.faces("faces")
    if not faces:
        raise RefLost("Choose the faces to delete.", "faces")
    return {"method": "feat_delete_face", "params": {"faces": faces, "mode": step.p("mode") or "heal", "tangent": bool(step.p("tangent"))}}


register(FeatureType("thread", "Thread", group="shape features", needs_body=True, plan=thread_plan, finish=thread_finish, params=[
    Param("op", "enum", "cut", choices=["cut", "add"], label="Cut into or add onto the face"),
    Param("standard", "text", "iso_metric_coarse", label="Standard"),
    Param("size", "text", "", label="Size"),
    Param("pitch", "length", None, min=0.0, label="Pitch"),
    Param("length", "length", None, min=0.0, label="Length"),
    Param("offset", "length", 0.0, min=0.0, label="Start offset"),
    Param("hand", "enum", "right", choices=["right", "left"], label="Hand"),
    Param("flip", "bool", False, label="Start at the other end"),
], refs=[RefSlot("face", "face", label="Cylindrical face")], roles=("thread:*",)))

register(FeatureType("thicken", "Thicken", group="shape features", needs_body=False, plan=thicken_plan, params=[
    Param("thickness", "length", 1.0, min=0.0, label="Thickness"),
    Param("side", "enum", "first", choices=["first", "second", "both"], label="Side"),
    Param("op", "enum", "add", choices=["add", "cut"], label="Combine with the body"),
    Param("tools", "json", None, label="Sheet bodies"),
], refs=[RefSlot("faces", "face", multi=True, required=False, label="Faces")], roles=("thicken:*",)))

register(FeatureType("delete_face", "Delete Face", group="dressup", needs_body=True, plan=delete_face_plan, params=[
    Param("mode", "enum", "heal", choices=["heal", "patch"], label="Method"),
    Param("tangent", "bool", False, label="Patch tangent to the neighbours"),
], refs=[RefSlot("faces", "face", multi=True, label="Faces to delete")], roles=("patch.*",)))
