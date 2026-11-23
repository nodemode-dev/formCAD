import json
import math
import shutil
import zipfile

import numpy as np

PARTS = ("base", "pin", "rod", "cap", "clamp")


def matrix(flat) -> np.ndarray:
    return np.asarray(flat, dtype=float).reshape(4, 4)


def flat(m) -> list:
    return [float(v) for v in np.asarray(m, dtype=float).reshape(-1)]


def rot(axis, degrees) -> np.ndarray:
    a = np.asarray(axis, dtype=float)
    a = a / np.linalg.norm(a)
    t = math.radians(degrees)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]])
    return np.eye(3) + math.sin(t) * k + (1 - math.cos(t)) * (k @ k)


def pose(r=None, t=(0.0, 0.0, 0.0)) -> np.ndarray:
    m = np.eye(4)
    if r is not None:
        m[:3, :3] = r
    m[:3, 3] = t
    return m


def point(m, p) -> np.ndarray:
    m = matrix(m) if not isinstance(m, np.ndarray) or m.shape != (4, 4) else m
    return m[:3, :3] @ np.asarray(p, dtype=float) + m[:3, 3]


def direction(m, d) -> np.ndarray:
    m = matrix(m) if not isinstance(m, np.ndarray) or m.shape != (4, 4) else m
    v = m[:3, :3] @ np.asarray(d, dtype=float)
    return v / np.linalg.norm(v)


def z_angle(m) -> float:
    m = matrix(m) if not isinstance(m, np.ndarray) or m.shape != (4, 4) else m
    return math.degrees(math.atan2(m[1, 0], m[0, 0]))


def wrap(deg) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def copy_parts(fixtures, dest, names=PARTS):
    dest.mkdir(parents=True, exist_ok=True)
    for n in names:
        shutil.copy(fixtures / "assembly" / ("%s.fcad" % n), dest / ("%s.fcad" % n))
    return dest


def copy_fixture(fixtures, tmp_path, top, folder):
    shutil.copytree(fixtures / folder, tmp_path / folder)
    shutil.copy(fixtures / top, tmp_path / top)
    return tmp_path / top


def component(doc, cid) -> dict:
    return doc.get("/assembly/components/%s" % cid)


def transform_of(doc, cid) -> np.ndarray:
    return matrix(component(doc, cid)["transform"])


def instances(doc) -> dict:
    return {i["key"]: i for i in doc.get("/assembly/instances")["instances"]}


def read_fcad(path) -> tuple:
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("manifest.json")), json.loads(z.read("document.json"))


def plane(comp, p, d) -> dict:
    return {"comp": comp, "geom": {"kind": "plane", "p": list(p), "d": list(d)}}


def axis(comp, p, d, r=None) -> dict:
    g = {"kind": "axis", "p": list(p), "d": list(d)}
    if r is not None:
        g["r"] = r
    return {"comp": comp, "geom": g}


def spot(comp, p) -> dict:
    return {"comp": comp, "geom": {"kind": "point", "p": list(p)}}


def mates_by_label(doc):
    return {m["label"]: m for m in doc.get("/mates")["mates"]}


def crank_slider_lengths(doc):
    m = mates_by_label(doc)
    r = float(np.linalg.norm(m["crank pin"]["opt"]["rel_t"][:2]))
    hinge_a = np.asarray(m["rod hinge A"]["geom"][1]["p"][:2])
    hinge_b = np.asarray(m["rod hinge B"]["geom"][1]["p"][:2])
    return r, float(np.linalg.norm(hinge_b - hinge_a))
