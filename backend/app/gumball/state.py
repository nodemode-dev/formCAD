import numpy as np

from app.analysis import snaps
from app.gumball import frame as fr
from app.solid import work
from app.solid.work import SolidError

KEY = "gumball"
ALIGNS = ("world", "cplane", "object", "view")
CURVE_KINDS = ("line", "circle", "arc", "ellipse", "lwpolyline", "polyline3d", "spline", "nurbscurve")


class GumballError(Exception):
    pass


def blank() -> dict:
    return {"on": False, "align": "world", "plane": None, "object": None, "face": None, "manual": False, "origin": None, "seq": 0}


def memory(doc) -> dict:
    mem = doc.get_runner().memory
    if KEY not in mem:
        mem[KEY] = blank()
    return mem[KEY]


def touch(st: dict) -> None:
    st["seq"] = int(st.get("seq", 0)) + 1


def plane_record(raw) -> dict:
    try:
        o = fr.vec(raw["origin"], "plane origin")
        x = fr.unit(raw["x"], "plane x axis")
        z = fr.unit(raw["z"], "plane z axis")
    except (KeyError, TypeError):
        raise GumballError("A plane needs origin, x and z.")
    except fr.FrameError as err:
        raise GumballError(str(err))
    axes = fr.frame_from(x, z)
    return {"name": str(raw.get("name", "Plane"))[:40], "origin": o.tolist(), "x": axes[0], "y": axes[1], "z": axes[2]}


def selection_handles(doc, handles=None) -> list:
    d = doc.drawing
    raw = handles if handles is not None else doc.selection
    out = []
    for h in raw or []:
        try:
            e = d.get(int(h))
        except (TypeError, ValueError):
            e = None
        if e is not None and e.handle not in out:
            out.append(e.handle)
    return out


def entity_points(d, e, s: float) -> np.ndarray:
    k = e.kind
    if k == "solidbody":
        try:
            from app.solid import scene as scene_mod

            mesh = scene_mod.parse(work.mesh_for(d, e, 1.0))
            if mesh["nv"]:
                return mesh["pos"].astype(np.float64) / s + np.asarray(e.offset, dtype=np.float64)
        except SolidError:
            pass
        box = e.summary.get("bbox")
        if box:
            lo, hi = np.asarray(box[:3], dtype=np.float64) / s, np.asarray(box[3:], dtype=np.float64) / s
            off = np.asarray(e.offset, dtype=np.float64)
            return np.asarray([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) + off
        return np.zeros((0, 3))
    if k == "nurbscurve":
        from app.nurbs3d.form import FormError, NurbsForm

        try:
            return np.asarray(NurbsForm.from_entity(e).sample(8), dtype=np.float64).reshape(-1, 3)
        except FormError:
            return np.asarray([list(q) + [0.0] * (3 - len(q)) for q in e.poles], dtype=np.float64)[:, :3]
    pts = []
    for name in e.POINTS:
        v = getattr(e, name, None)
        if v is not None:
            pts.append([float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0])
    for name in e.POINT_LISTS:
        for v in getattr(e, name, []):
            pts.append([float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0])
    for name in getattr(e, "VERTEX_LISTS", ()):
        for v in getattr(e, name, []):
            p = v["p"]
            pts.append([float(p[0]), float(p[1]), float(getattr(e, "elevation", 0.0))])
    b = e.bounds() if not pts else None
    if b is not None and len(b) >= 4:
        z = float(getattr(e, "elevation", 0.0))
        pts.extend([[b[0], b[1], z], [b[2], b[3], z]])
    return np.asarray(pts, dtype=np.float64).reshape(-1, 3)


def selection_points(doc, handles: list) -> np.ndarray:
    d = doc.drawing
    s = work.mm(d)
    chunks = [entity_points(d, d.get(h), s) for h in handles]
    chunks = [c for c in chunks if len(c)]
    return np.concatenate(chunks) if chunks else np.zeros((0, 3))


def object_frame(doc, handle, face=None) -> list:
    d = doc.drawing
    e = d.get(int(handle))
    if e is None:
        raise GumballError("Object %s does not exist." % handle)
    s = work.mm(d)
    if e.kind == "solidbody":
        wid = work.worker_id(d, e)
        if face is not None:
            if int(face) not in e.face_ids:
                raise GumballError("That face no longer exists.")
            g = work.kcall("geometry", {"id": wid, "face": e.face_ids.index(int(face))}, work.SHORT)
            if g.get("kind") != "plane":
                raise GumballError("Choose a flat face to align the gumball with.")
            return fr.frame_from(g["xdir"], g["normal"])
        try:
            props = work.kcall("body_props", {"id": wid}, work.SHORT)
        except SolidError:
            props = {}
        if props.get("axes"):
            a = props["axes"]
            return fr.frame_from(a[0], np.cross(a[0], a[1]))
        return fr.IDENTITY
    if e.kind in ("circle", "arc", "ellipse", "lwpolyline"):
        return fr.IDENTITY
    if e.kind in CURVE_KINDS:
        pts = entity_points(d, e, s)
        if len(pts) < 3:
            raise GumballError("That curve has no plane.")
        c = pts.mean(axis=0)
        _u, sv, vt = np.linalg.svd(pts - c, full_matrices=False)
        if sv[0] < 1e-12 or sv[-1] > 1e-6 * sv[0]:
            raise GumballError("That curve is not flat, so it has no plane to align with.")
        n = vt[-1]
        if float(np.dot(n, [0.0, 0.0, 1.0])) < 0 or (abs(n[2]) < 1e-9 and float(np.dot(n, [0.0, 1.0, 0.0])) < 0):
            n = -n
        return fr.frame_from(vt[0], n)
    raise GumballError("A %s has no frame to align the gumball with." % e.kind)


def current_frame(doc, st: dict) -> list:
    mode = st["align"]
    if mode in ("cplane", "view") and st.get("plane"):
        p = st["plane"]
        return [p["x"], p["y"], p["z"]]
    if mode == "object" and st.get("object"):
        return object_frame(doc, st["object"], st.get("face"))
    return fr.IDENTITY


def describe(doc, handles=None) -> dict:
    with doc.lock:
        st = memory(doc)
        picked = selection_handles(doc, handles)
        axes = current_frame(doc, st)
        pts = selection_points(doc, picked)
        box = None
        auto = None
        if len(pts):
            f = np.asarray(axes, dtype=np.float64)
            local = pts @ f.T
            lo, hi = local.min(axis=0), local.max(axis=0)
            centre_local = 0.5 * (lo + hi)
            auto = (centre_local @ f).tolist()
            box = {"min": lo.tolist(), "max": hi.tolist(), "size": (hi - lo).tolist(), "diagonal": float(np.linalg.norm(hi - lo))}
        origin = st["origin"] if st["manual"] and st.get("origin") else auto
        d = doc.drawing
        kinds = {}
        for h in picked:
            kinds[d.get(h).kind] = kinds.get(d.get(h).kind, 0) + 1
        return {
            "on": bool(st["on"]), "align": st["align"], "plane": st.get("plane"), "object": st.get("object"), "face": st.get("face"), "manual": bool(st["manual"]),
            "origin": origin, "auto_origin": auto, "axes": axes, "selection": picked, "kinds": kinds, "box": box, "seq": st["seq"],
            "mm_per_unit": work.mm(d), "handles": ["move", "rotate", "scale"],
        }


def set_on(doc, on: bool) -> dict:
    st = memory(doc)
    st["on"] = bool(on)
    touch(st)
    return describe(doc)


def set_align(doc, mode: str, plane=None, obj=None, face=None) -> dict:
    mode = str(mode).lower()
    if mode not in ALIGNS:
        raise GumballError("Align with world, cplane, object or view.")
    st = memory(doc)
    if mode in ("cplane", "view"):
        if plane is None:
            raise GumballError("Give the %s as a plane with origin, x and z." % ("construction plane" if mode == "cplane" else "view"))
        st["plane"] = plane_record(plane)
        st["object"] = st["face"] = None
    elif mode == "object":
        if obj is None:
            raise GumballError("Name the object to align with.")
        object_frame(doc, obj, face)
        st["object"], st["face"], st["plane"] = int(obj), (int(face) if face is not None else None), None
    else:
        st["plane"] = st["object"] = st["face"] = None
    st["align"] = mode
    touch(st)
    return describe(doc)


def relocate(doc, point=None, ray=None, aperture=None, modes=None, base=None, plane=None, handles=None) -> dict:
    st = memory(doc)
    snapped = None
    if ray is not None:
        got = snaps.query(doc, ray, float(aperture) if aperture else 1.0, modes if modes is not None else ["vertex", "end", "mid", "centre", "quadrant", "intersection", "nearest"], base, plane, handles, 5)
        points = [c for c in got["candidates"] if c["kind"] != "surface"] or got["candidates"]
        if points:
            snapped = points[0]
            point = points[0]["point"]
    if point is None:
        raise GumballError("Give a point or a pick ray to move the gumball to.")
    try:
        p = fr.vec(point, "gumball position")
    except fr.FrameError as err:
        raise GumballError(str(err))
    st["origin"] = p.tolist()
    st["manual"] = True
    touch(st)
    out = describe(doc, handles)
    out["snapped"] = snapped
    return out


def reset(doc) -> dict:
    st = memory(doc)
    st.update(blank(), on=st["on"], seq=st["seq"])
    touch(st)
    return describe(doc)
