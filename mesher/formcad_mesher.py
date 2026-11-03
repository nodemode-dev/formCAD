import json
import math
import os
import sys
from importlib import metadata

MAX_ELEMENTS = 400000
MIN_ELEMENTS_FACTOR = 0.1178
EDGE_SLOTS = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))
OUT = sys.stdout


def versions() -> dict:
    out = {"python": sys.version.split()[0]}
    for name in ("netgen-mesher", "netgen-occt", "numpy"):
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = "unknown"
    return out


def isolate_stdout() -> None:
    global OUT
    try:
        saved = os.dup(1)
        OUT = os.fdopen(saved, "w", encoding="utf-8", buffering=1)
        os.dup2(2, 1)
    except OSError:
        OUT = sys.stdout


def prepare_frozen() -> None:
    if not getattr(sys, "frozen", False):
        return
    import ctypes
    import glob
    import importlib.metadata as metadata

    folder = os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)), "occt")
    if os.name == "nt":
        os.add_dll_directory(folder)
        os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
    pending = sorted(glob.glob(os.path.join(folder, "*TK*")))
    for _ in range(len(pending) + 1):
        retry = []
        for path in pending:
            try:
                ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL if hasattr(ctypes, "RTLD_GLOBAL") else 0)
            except OSError:
                retry.append(path)
        if not retry or len(retry) == len(pending):
            break
        pending = retry
    original = metadata.metadata

    def patched(name):
        if str(name).lower().replace("_", "-") == "netgen-occt":
            raise metadata.PackageNotFoundError(name)
        return original(name)

    metadata.metadata = patched


def load(path: str):
    from netgen.occ import OCCGeometry

    if not isinstance(path, str) or not os.path.isfile(path):
        raise ValueError("The shape file was not found.")
    if not path.lower().endswith((".brep", ".step", ".stp")):
        raise ValueError("The shape file must be a BRep or STEP file.")
    return OCCGeometry(path)


def face_rows(shape) -> list:
    rows = []
    for i, f in enumerate(shape.faces):
        lo, hi = f.bounding_box
        rows.append({"index": i, "center": [float(v) for v in f.center], "bbox": [[float(v) for v in lo], [float(v) for v in hi]], "area": float(f.mass)})
    return rows


def hello(_params: dict) -> dict:
    out = versions()
    out["methods"] = sorted(METHODS)
    out["units"] = "mm"
    out["protocol"] = 1
    return out


def faces(params: dict) -> dict:
    geo = load(params.get("path"))
    rows = face_rows(geo.shape)
    return {"faces": rows, "volume": float(sum(s.mass for s in geo.shape.solids)), "solids": len(list(geo.shape.solids))}


def pick(rows: list, sel: dict) -> list:
    if not isinstance(sel, dict):
        raise ValueError("A face selector is an object.")
    tol = float(sel.get("tol", 1e-3))
    if "faces" in sel:
        ids = sorted({int(i) for i in sel["faces"]})
        for i in ids:
            if not 0 <= i < len(rows):
                raise ValueError("There is no face %d." % i)
        return ids
    if "box" in sel:
        lo, hi = sel["box"]
        return [r["index"] for r in rows if all(r["bbox"][0][k] >= float(lo[k]) - tol and r["bbox"][1][k] <= float(hi[k]) + tol for k in range(3))]
    if "plane" in sel:
        p = sel["plane"]
        axis = "xyz".index(str(p.get("axis", "x")).lower())
        value = float(p.get("value", 0.0))
        return [r["index"] for r in rows if abs(r["bbox"][0][axis] - value) <= tol and abs(r["bbox"][1][axis] - value) <= tol]
    if "point" in sel:
        pt = [float(v) for v in sel["point"]]
        best = min(rows, key=lambda r: sum((r["center"][k] - pt[k]) ** 2 for k in range(3)))
        return [best["index"]]
    if sel.get("all"):
        return [r["index"] for r in rows]
    raise ValueError("A face selector needs faces, box, plane, point or all.")


def estimate(volume: float, maxh: float) -> float:
    return volume / (MIN_ELEMENTS_FACTOR * maxh ** 3)


def mesh(params: dict) -> dict:
    import numpy as np
    from netgen.meshing import MeshingParameters

    out_path = params.get("out")
    if not isinstance(out_path, str) or not out_path.endswith(".npz"):
        raise ValueError("The mesh output must be an .npz file path.")
    geo = load(params.get("path"))
    shape = geo.shape
    rows = face_rows(shape)
    volume = float(sum(s.mass for s in shape.solids))
    lo = [min(r["bbox"][0][k] for r in rows) for k in range(3)]
    hi = [max(r["bbox"][1][k] for r in rows) for k in range(3)]
    diag = math.sqrt(sum((hi[k] - lo[k]) ** 2 for k in range(3)))
    maxh = float(params.get("maxh") or diag / 20.0)
    if not maxh > 0:
        raise ValueError("The element size must be positive.")
    cap = min(int(params.get("max_elements") or MAX_ELEMENTS), MAX_ELEMENTS)
    refine = params.get("refine") or []
    if len(refine) > 64:
        raise ValueError("At most 64 mesh controls are allowed.")
    smallest = maxh
    for item in refine:
        h = float(item.get("maxh", 0))
        if not h > 0:
            raise ValueError("A mesh control needs a positive element size.")
        for i in pick(rows, item.get("select") or {}):
            shape.faces[i].maxh = h
            smallest = min(smallest, h)
    groups = {}
    for name, sel in (params.get("groups") or {}).items():
        groups[str(name)] = pick(rows, sel)
    for i, f in enumerate(shape.faces):
        f.name = "f%d" % i
    guess = estimate(volume, maxh)
    if guess > cap * 1.5:
        raise ValueError("The mesh would hold about %d elements, over the limit of %d. Use a larger element size." % (guess, cap))
    geo = type(geo)(shape)
    mp = MeshingParameters(maxh=maxh, grading=float(params.get("grading") or 0.3), curvaturesafety=float(params.get("curvature") or 2.0))
    m = geo.GenerateMesh(mp)
    ne = len(m.Elements3D())
    if ne == 0:
        raise ValueError("The mesher produced no volume elements. Check that the shape is a closed solid.")
    if ne > cap:
        raise ValueError("The mesh holds %d elements, over the limit of %d. Use a larger element size." % (ne, cap))
    nv = len(m.Points())
    nodes = np.array(m.Coordinates(), dtype=np.float64).reshape(-1, 3)[:nv]
    tets = np.array([[v.nr - 1 for v in e.vertices] for e in m.Elements3D()], dtype=np.int32)
    domain = np.array([e.index for e in m.Elements3D()], dtype=np.int32)
    tris = np.array([[v.nr - 1 for v in e.vertices] for e in m.Elements2D()], dtype=np.int32).reshape(-1, 3)
    names = [m.GetBCName(i) for i in range(max(e.index for e in m.Elements2D()))]
    tri_face = np.array([int(names[e.index - 1][1:]) if names[e.index - 1].startswith("f") else -1 for e in m.Elements2D()], dtype=np.int32)
    curved = False
    pairs = np.zeros((0, 2), dtype=np.int32)
    mids = np.zeros((0, 3))
    if params.get("second_order", True):
        m.SecondOrder()
        allp = np.array(m.Coordinates(), dtype=np.float64).reshape(-1, 3)
        table = {}
        for e in m.Elements3D():
            pts = [p.nr - 1 for p in e.points]
            for slot, (a, b) in enumerate(EDGE_SLOTS):
                key = (min(pts[a], pts[b]), max(pts[a], pts[b]))
                table[key] = pts[4 + slot]
        keys = np.array(sorted(table), dtype=np.int32).reshape(-1, 2)
        ids = np.array([table[(int(a), int(b))] for a, b in keys], dtype=np.int64)
        mids = allp[ids]
        straight = 0.5 * (nodes[keys[:, 0]] + nodes[keys[:, 1]])
        dev = np.abs(mids - straight).max() if len(keys) else 0.0
        curved = bool(dev > 1e-7 * max(diag, 1.0))
        pairs = keys
    meta = {"groups": groups, "faces": len(rows), "maxh": maxh, "curved": curved, "volume": volume, "bbox": [lo, hi]}
    np.savez_compressed(out_path[:-4], nodes=nodes, tets=tets, tet_domain=domain, tris=tris, tri_face=tri_face, edge_mid_pairs=pairs if curved else pairs[:0], edge_mid_xyz=mids if curved else mids[:0], meta=np.array(json.dumps(meta)))
    return {"out": out_path, "nodes": int(len(nodes)), "tets": int(len(tets)), "tris": int(len(tris)), "curved": curved, "faces": len(rows), "groups": groups, "volume": volume, "bbox": [lo, hi], "maxh": maxh, "smallest": smallest}


METHODS = {"hello": hello, "faces": faces, "mesh": mesh}


def reply(obj: dict) -> None:
    OUT.write(json.dumps(obj) + "\n")
    OUT.flush()


def serve() -> int:
    isolate_stdout()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            ident = request.get("id")
            method = request.get("method")
        except (ValueError, AttributeError):
            reply({"id": None, "error": {"message": "The request is not a JSON object."}})
            continue
        if method == "shutdown":
            reply({"id": ident, "result": {"ok": True}})
            return 0
        handler = METHODS.get(method)
        if handler is None:
            reply({"id": ident, "error": {"message": "Unknown method %s." % method}})
            continue
        try:
            reply({"id": ident, "result": handler(request.get("params") or {})})
        except Exception as err:
            reply({"id": ident, "error": {"message": str(err)}})
    return 0


def selfcheck() -> int:
    info = versions()
    try:
        import netgen.meshing
        import netgen.occ

        info["netgen"] = "ok"
    except Exception as err:
        info["netgen"] = "missing: %s" % err
        print(json.dumps(info))
        return 1
    print(json.dumps(info))
    return 0


if __name__ == "__main__":
    prepare_frozen()
    if "--selfcheck" in sys.argv:
        sys.exit(selfcheck())
    sys.exit(serve())
