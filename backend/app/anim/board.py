import copy
import math

from app.core import guard

HEADER = "STORYBOARDS"
SCHEMA = 1
EASINGS = ("linear", "ease", "ease_in", "ease_out", "hold")
STYLES = ("shaded", "outline", "white_fill", "flat_colour", "hidden_dashed")
SOURCES = ("viewport", "raster", "path")
DRIVER_KINDS = ["mate"]
LIMITS = {"shots": 200, "keys": 24, "boards": 40, "seconds": 600.0, "frames": 18000, "fps": 60, "width": 3840, "height": 2160, "pixels_x_frames": 3840 * 2160 * 3600, "samples": 1024, "sample_frames": 200000}
AGENT_LIMITS = {"shots": 40, "keys": 8, "boards": 10, "seconds": 30.0, "frames": 900, "fps": 30, "width": 1920, "height": 1080, "pixels_x_frames": 1920 * 1080 * 900, "samples": 64, "sample_frames": 20000}


class BoardRefused(ValueError):
    pass


def limits() -> dict:
    return AGENT_LIMITS if guard.CALLER.get() else LIMITS


def blank() -> dict:
    return {"schema": SCHEMA, "next_shot": 1, "boards": {}}


def header(d) -> dict:
    out = blank()
    raw = d.header.get(HEADER)
    if isinstance(raw, dict):
        for k, v in raw.items():
            out[k] = copy.deepcopy(v)
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def _num(v, name: str, lo=None, hi=None) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BoardRefused("%s must be a number." % name)
    if not math.isfinite(x):
        raise BoardRefused("%s must be a finite number." % name)
    if lo is not None and x < lo:
        raise BoardRefused("%s must be at least %g." % (name, lo))
    if hi is not None and x > hi:
        raise BoardRefused("%s must be at most %g." % (name, hi))
    return x


def _vec(v, name: str) -> list:
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise BoardRefused("%s is three numbers." % name)
    return [_num(x, name) for x in v]


def clean_camera(spec) -> dict:
    if not isinstance(spec, dict):
        raise BoardRefused("A camera key is an object with position, target and height.")
    pos = _vec(spec.get("position"), "Camera position")
    tgt = _vec(spec.get("target"), "Camera target")
    if math.dist(pos, tgt) < 1e-9:
        raise BoardRefused("The camera position and target are the same point.")
    proj = spec.get("projection", "perspective")
    if proj not in ("perspective", "parallel"):
        raise BoardRefused("Projection is perspective or parallel.")
    return {"position": pos, "target": tgt, "up": [0.0, 0.0, 1.0], "projection": proj, "fov": _num(spec.get("fov", 38.0), "Field of view", 1.0, 120.0), "height": _num(spec.get("height", 100.0), "Camera height", 1e-6, 1e9)}


def clean_shot(spec: dict, sid: int, lim: dict) -> dict:
    if not isinstance(spec, dict):
        raise BoardRefused("A shot is an object.")
    out = {"id": int(sid), "name": str(spec.get("name") or "Shot %d" % sid)[:80]}
    out["duration"] = _num(spec.get("duration", 2.0), "Shot duration", 0.0, lim["seconds"])
    ease = spec.get("ease", "ease")
    if ease not in EASINGS:
        raise BoardRefused("Easing is one of %s." % ", ".join(EASINGS))
    out["ease"] = ease
    ex = spec.get("explode")
    if ex:
        view = str(ex.get("view") or "")
        if not view:
            raise BoardRefused("An explode move names the explode view.")
        item = {"view": view}
        for k in ("from", "to"):
            if ex.get(k) is not None:
                item[k] = _num(ex[k], "Explode %s" % k, 0.0, 10000.0)
        out["explode"] = item
    dr = spec.get("drive")
    if dr:
        mate = str(dr.get("mate") or "")
        if not mate:
            raise BoardRefused("A drive move names the mate.")
        kind = str(dr.get("kind") or "mate")
        if kind not in DRIVER_KINDS:
            raise BoardRefused("A drive kind is one of %s." % ", ".join(DRIVER_KINDS))
        item = {"mate": mate}
        if kind != "mate":
            item["kind"] = kind
        for k in ("from", "to"):
            if dr.get(k) is not None:
                item[k] = _num(dr[k], "Drive %s" % k)
        if "to" not in item:
            raise BoardRefused("A drive move needs a target value.")
        out["drive"] = item
    cam = spec.get("camera")
    if cam:
        keys = cam.get("keys") or []
        if len(keys) > lim["keys"]:
            raise BoardRefused("A shot holds at most %d camera keys." % lim["keys"])
        ks = []
        for k in keys:
            ks.append({"at": _num(k.get("at", 0.0), "Camera key time", 0.0, 1.0), "camera": clean_camera(k.get("camera"))})
        ks.sort(key=lambda k: k["at"])
        item = {"keys": ks}
        if cam.get("orbit") is not None:
            item["orbit"] = _num(cam["orbit"], "Orbit degrees", -3600.0, 3600.0)
        out["camera"] = item
    elif spec.get("orbit") is not None:
        out["camera"] = {"keys": [], "orbit": _num(spec["orbit"], "Orbit degrees", -3600.0, 3600.0)}
    if spec.get("loop"):
        out["loop"] = True
    style = spec.get("style")
    if style:
        if style not in STYLES:
            raise BoardRefused("Style is one of %s." % ", ".join(STYLES))
        out["style"] = style
    return out


def clean_board(name: str, spec: dict, d) -> dict:
    lim = limits()
    h = header(d)
    spec = spec or {}
    out = {"name": name, "fps": int(_num(spec.get("fps", 30), "Frames per second", 1, lim["fps"])), "width": int(_num(spec.get("width", 1280), "Width", 16, lim["width"])), "height": int(_num(spec.get("height", 720), "Height", 16, lim["height"]))}
    out["width"] -= out["width"] % 2
    out["height"] -= out["height"] % 2
    style = spec.get("style", "shaded")
    if style not in STYLES:
        raise BoardRefused("Style is one of %s." % ", ".join(STYLES))
    out["style"] = style
    source = spec.get("source", "viewport")
    if source not in SOURCES:
        raise BoardRefused("Frame source is one of %s." % ", ".join(SOURCES))
    out["source"] = source
    out["samples"] = int(_num(spec.get("samples", 16), "Samples per frame", 1, lim["samples"]))
    shots = spec.get("shots") or []
    if len(shots) > lim["shots"]:
        raise BoardRefused("A storyboard holds at most %d shots." % lim["shots"])
    cleaned = []
    seen = set()
    for s in shots:
        sid = s.get("id") if isinstance(s, dict) else None
        if not isinstance(sid, int) or isinstance(sid, bool) or sid < 1 or sid in seen:
            sid = int(h["next_shot"])
            h["next_shot"] = sid + 1
        seen.add(sid)
        cleaned.append(clean_shot(s, sid, lim))
    out["shots"] = cleaned
    plan = plan_of(out)
    if plan["seconds"] > lim["seconds"]:
        raise BoardRefused("The storyboard runs %.1f s; the limit is %g s%s." % (plan["seconds"], lim["seconds"], " for a macro or agent" if guard.CALLER.get() else ""))
    if plan["frames"] > lim["frames"]:
        raise BoardRefused("The storyboard has %d frames; the limit is %d%s." % (plan["frames"], lim["frames"], " for a macro or agent" if guard.CALLER.get() else ""))
    if out["width"] * out["height"] * plan["frames"] > lim["pixels_x_frames"]:
        raise BoardRefused("The video is too large for its length: lower the resolution, the frame rate or the duration.")
    if source == "path" and out["samples"] * plan["frames"] > lim["sample_frames"]:
        raise BoardRefused("Path tracing %d samples for %d frames is %d sample passes; the limit is %d%s." % (out["samples"], plan["frames"], out["samples"] * plan["frames"], lim["sample_frames"], " for a macro or agent" if guard.CALLER.get() else ""))
    h["boards"][name] = out
    save(d, h)
    return out


def frames_in(shot: dict, fps: int) -> int:
    n = int(round(shot["duration"] * fps))
    return max(n, 1) if shot["duration"] > 0 else 0


def plan_of(board: dict) -> dict:
    fps = board["fps"]
    spans = []
    at = 0
    for s in board["shots"]:
        n = frames_in(s, fps)
        spans.append({"id": s["id"], "name": s["name"], "first": at, "frames": n})
        at += n
    return {"frames": at, "seconds": at / fps if fps else 0.0, "fps": fps, "spans": spans}


def get(d, name: str) -> dict:
    b = header(d)["boards"].get(name)
    if b is None:
        raise BoardRefused("There is no storyboard %s." % name)
    return b


def listing(d) -> dict:
    h = header(d)
    return {"boards": {k: {**copy.deepcopy(v), "plan": plan_of(v)} for k, v in h["boards"].items()}, "limits": limits(), "styles": list(STYLES), "easings": list(EASINGS)}


def create(d, name: str, spec: dict) -> dict:
    name = str(name or "").strip()[:60]
    if not name:
        raise BoardRefused("Give the storyboard a name.")
    h = header(d)
    if name in h["boards"]:
        raise BoardRefused("There is already a storyboard %s." % name)
    if len(h["boards"]) >= limits()["boards"]:
        raise BoardRefused("A document holds at most %d storyboards." % limits()["boards"])
    return clean_board(name, spec, d)


def replace(d, name: str, spec: dict) -> dict:
    get(d, name)
    new_name = str(spec.get("name") or name).strip()[:60] or name
    if new_name != name:
        h = header(d)
        if new_name in h["boards"]:
            raise BoardRefused("There is already a storyboard %s." % new_name)
        del h["boards"][name]
        save(d, h)
    return clean_board(new_name, spec, d)


def delete(d, name: str) -> None:
    get(d, name)
    h = header(d)
    del h["boards"][name]
    save(d, h)


def seed_from_explode(d, name: str, view: str, hold: float = 1.0, run: float = 4.0, orbit: float = 0.0, fps: int = 30, width: int = 1280, height: int = 720, camera=None) -> dict:
    from app.mates import explode

    v = explode.get_view(d, view)
    n = len(v["steps"])
    if n == 0:
        raise BoardRefused("The explode view %s has no steps." % view)
    shots = [{"name": "Hold", "duration": hold, "ease": "hold", "explode": {"view": view, "from": 0.0, "to": 0.0}}, {"name": "Explode", "duration": run, "ease": "ease", "explode": {"view": view, "from": 0.0, "to": float(n)}}]
    if camera:
        shots[0]["camera"] = {"keys": [{"at": 0.0, "camera": camera}]}
    if orbit:
        shots[1]["camera"] = {"keys": [], "orbit": orbit}
    shots += [{"name": "Hold exploded", "duration": hold, "ease": "hold", "explode": {"view": view, "from": float(n), "to": float(n)}}, {"name": "Collapse", "duration": run * 0.6, "ease": "ease", "explode": {"view": view, "from": float(n), "to": 0.0}}]
    return create(d, name, {"fps": fps, "width": width, "height": height, "shots": shots})
