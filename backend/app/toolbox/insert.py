import os

import numpy as np

from app.assembly import model, xform
from app.assembly.store import AssemblyError
from app.mates import ops as mate_ops
from app.mates import pick
from app.mates import store as mate_store
from app.toolbox import gens, library, partfile
from app.toolbox.partfile import PartFileError

ERRORS = (AssemblyError, mate_store.MateRefused, pick.PickError, PartFileError, gens.GenError, library.LibraryError)
MAX_BATCH = 200


def source_of(src: dict) -> tuple:
    if not isinstance(src, dict):
        raise gens.GenError("Give source as an object: kind and params, or family and row.")
    if src.get("family"):
        kind, params = library.resolve(str(src["family"]), str(src.get("row") or ""))
        return kind, {**params, **(src.get("params") or {})}
    return str(src.get("kind") or ""), dict(src.get("params") or {})


def folder_for(doc, folder) -> str:
    if folder:
        full = os.path.abspath(os.path.expanduser(str(folder)))
    else:
        if not getattr(doc, "path", ""):
            raise PartFileError("Save the assembly first, or give a folder for the toolbox part files.")
        full = os.path.join(os.path.dirname(os.path.realpath(doc.path)), "toolbox")
    if not os.path.isdir(full):
        parent = os.path.dirname(full)
        if not os.path.isdir(parent):
            raise PartFileError("The folder %s does not exist." % parent)
        os.mkdir(full)
    return full


def unit(v):
    a = np.array(v, dtype=float)
    n = float(np.linalg.norm(a))
    if n < 1e-12:
        raise AssemblyError("A direction has no length.")
    return a / n


def world_of(doc, ref: dict) -> dict:
    g = pick.resolve(doc, ref)
    pick.finite(g)
    if g.get("comp") is None:
        return {"kind": g["kind"], "p": np.array(g["p"], dtype=float), "d": np.array(g["d"], dtype=float) if g.get("d") is not None else None}
    inst = pick.instance_of(doc, g["comp"])
    m = np.array(inst.world, dtype=float)
    p = (m @ np.array([*g["p"], 1.0]))[:3]
    d = m[:3, :3] @ np.array(g["d"], dtype=float) if g.get("d") is not None else None
    return {"kind": g["kind"], "p": p, "d": d, "r": g.get("r")}


def frame_matrix(origin, z) -> np.ndarray:
    z = unit(z)
    pick_axis = np.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
    x = unit(np.cross(pick_axis, z))
    y = np.cross(z, x)
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, np.array(origin, dtype=float)
    return m


def placement(doc, hole: dict | None, seat: dict | None, at: dict | None, offset: float, flip: bool) -> tuple:
    if at:
        origin = np.array(at.get("point") or [0.0, 0.0, 0.0], dtype=float)
        z = unit(at.get("axis") or [0.0, 0.0, 1.0])
        return frame_matrix(origin, -z if flip else z), None, None
    if not hole:
        return np.eye(4), None, None
    h = world_of(doc, hole)
    if h["kind"] != "axis":
        raise AssemblyError("The hole reference must be a cylinder face, a circle edge or an axis.")
    axis = unit(h["d"])
    origin = h["p"]
    s = None
    if seat:
        s = world_of(doc, seat)
        if s["kind"] != "plane":
            raise AssemblyError("The seat reference must be a flat face.")
        n = unit(s["d"])
        if abs(float(axis @ n)) < 1e-6:
            raise AssemblyError("The hole axis lies in the seat plane; they must cross.")
        t = float((s["p"] - origin) @ n) / float(axis @ n)
        origin = origin + axis * t
        z = n if not flip else -n
        axis = z
    else:
        axis = -axis if flip else axis
    origin = origin + axis * float(offset or 0.0)
    return frame_matrix(origin, axis), h, s


def one(doc, src: dict, hole=None, seat=None, at=None, folder=None, label=None, offset=0.0, flip=False, mates=True, extra=None) -> dict:
    kind, params = source_of(src)
    part = partfile.make(kind, params, folder_for(doc, folder), extra)
    mm = placement(doc, hole, seat, at, offset, flip)[0]
    rec = model.insert(doc, part["path"], label or part["designation"], xform.to_list(mm), fixed=False)
    cid = rec["id"]
    made = []
    if mates and hole:
        own_axis = {"comp": cid, "geom": {"kind": "axis", "p": [0, 0, 0], "d": [0, 0, 1]}}
        made.append(mate_ops.add_mate(doc, "concentric", [own_axis, hole], None, {}, "", False))
        if seat:
            own_plane = {"comp": cid, "geom": {"kind": "plane", "p": [0, 0, 0], "d": [0, 0, -1]}}
            if float(offset or 0.0) > 1e-9:
                made.append(mate_ops.add_mate(doc, "distance", [own_plane, seat], float(offset), {}, "", False))
            else:
                made.append(mate_ops.add_mate(doc, "coincident", [own_plane, seat], None, {}, "", False))
    return {"component": cid, "label": rec["label"], "path": part["path"], "designation": part["designation"], "reused": part["reused"], "mates": [{"id": m_["mate"]["id"], "name": m_["mate"]["name"], "kind": m_["mate"]["kind"]} for m_ in made], "dof": made[-1]["status"]["dof"] if made else None, "transform": xform.to_list(mm)}


def many(doc, items: list, **kw) -> dict:
    if not isinstance(items, list) or not items:
        raise AssemblyError("Give items, a list of insertions.")
    if len(items) > MAX_BATCH:
        raise AssemblyError("At most %d insertions at once." % MAX_BATCH)
    out = []
    for it in items:
        args = {**kw, **{k: v for k, v in it.items() if k in ("source", "hole", "seat", "at", "label", "offset", "flip", "mates", "extra", "folder")}}
        src = args.pop("source", None)
        out.append(one(doc, src, **args))
    return {"inserted": out, "count": len(out)}
