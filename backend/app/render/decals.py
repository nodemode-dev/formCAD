import copy
import math
import re

TABLE = "render"
PREFIX = "decal:"
MAX_DECALS = 64
MAX_IMAGE_CHARS = 400000
DATA_URL = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class DecalError(ValueError):
    pass


def _vec(rec: dict, key: str, size: int = 3) -> list:
    v = rec.get(key)
    if not isinstance(v, (list, tuple)) or len(v) != size:
        raise DecalError("%s needs %d numbers." % (key, size))
    try:
        out = [float(x) for x in v]
    except (TypeError, ValueError):
        raise DecalError("%s needs numbers." % key)
    if not all(math.isfinite(x) and abs(x) < 1.0e9 for x in out):
        raise DecalError("%s has a value that is out of range." % key)
    return out


def clean(rec: dict, name: str) -> dict:
    body = str(rec.get("body") or "")
    if not (body.startswith("i:") or body.startswith("h:")) or len(body) > 400:
        raise DecalError("A decal belongs to a body key like i:<instance> or h:<handle>.")
    out = {"name": PREFIX + name, "label": str(rec.get("label") or name)[:80], "body": body}
    out["position"] = _vec(rec, "position")
    normal = _vec(rec, "normal")
    up = _vec(rec, "up") if rec.get("up") is not None else [0.0, 0.0, 1.0]
    if math.sqrt(sum(x * x for x in normal)) < 1e-9:
        raise DecalError("The decal normal cannot be zero.")
    out["normal"] = normal
    out["up"] = up
    size = _vec(rec, "size", 2)
    if not all(0 < x < 1.0e7 for x in size):
        raise DecalError("The decal size must be positive.")
    out["size"] = size
    depth = rec.get("depth")
    out["depth"] = float(depth) if depth is not None and math.isfinite(float(depth)) and float(depth) > 0 else max(size) * 0.5
    kind = str(rec.get("kind") or "color")
    if kind not in ("color", "image"):
        raise DecalError("A decal is a colour or an image.")
    out["kind"] = kind
    color = str(rec.get("color") or "#ffffff")
    if not HEX.match(color):
        raise DecalError("Decal colour must be like #rrggbb.")
    out["color"] = color.lower()
    img = rec.get("image") or ""
    if kind == "image":
        if not isinstance(img, str) or len(img) > MAX_IMAGE_CHARS or not DATA_URL.match(img):
            raise DecalError("A decal image is a png, jpeg or webp data address of at most %d characters." % MAX_IMAGE_CHARS)
    else:
        img = ""
    out["image"] = img
    try:
        out["opacity"] = min(1.0, max(0.0, float(rec.get("opacity", 1.0))))
        out["roughness"] = min(1.0, max(0.0, float(rec.get("roughness", 0.5))))
        out["rotation"] = float(rec.get("rotation", 0.0))
    except (TypeError, ValueError):
        raise DecalError("Decal opacity, roughness and rotation need numbers.")
    out["visible"] = bool(rec.get("visible", True))
    return out


def _check_name(name: str) -> str:
    n = str(name or "").strip()
    if not n or len(n) > 60 or any(ord(c) < 32 for c in n) or ":" in n:
        raise DecalError("A decal needs a name of 1 to 60 characters without a colon.")
    return n


def listing(d) -> list:
    t = d.tables.get(TABLE)
    if t is None:
        return []
    return [copy.deepcopy(r) for r in t.values() if str(r.get("name", "")).startswith(PREFIX)]


def add(d, name: str, rec: dict) -> dict:
    name = _check_name(name)
    t = d.tables.get(TABLE)
    if t is not None and t.has(PREFIX + name):
        raise DecalError("A decal called %s already exists." % name)
    if len(listing(d)) >= MAX_DECALS:
        raise DecalError("A document holds at most %d decals." % MAX_DECALS)
    out = clean(rec, name)
    d.table_set(TABLE, out)
    return out


def update(d, name: str, rec: dict) -> dict:
    t = d.tables.get(TABLE)
    old = t.get(PREFIX + name) if t is not None else None
    if old is None:
        raise DecalError("There is no decal called %s." % name)
    merged = dict(old)
    merged.update({k: v for k, v in rec.items() if k != "name"})
    out = clean(merged, name)
    d.table_set(TABLE, out)
    return out


def remove(d, name: str) -> dict:
    t = d.tables.get(TABLE)
    if t is None or not t.has(PREFIX + name):
        raise DecalError("There is no decal called %s." % name)
    d.table_remove(TABLE, PREFIX + name)
    return {"removed": name}
