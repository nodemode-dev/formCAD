import json
import os

from app.core import config
from app.doc import papers

FORMAT = "formcad-plotter"
VERSION = 1
MAX_PAPERS = 512
MAX_DEVICES = 64
MAX_FILE = 1024 * 1024
OUTPUTS = ("pdf", "png", "svg")
EXT = ".fcplotter"
ISO_MARGIN = 5.0
INCH_MARGIN = 6.35


class DeviceError(Exception):
    pass


def standard_papers():
    out = []
    for r in papers.SIZES:
        m = ISO_MARGIN if r["name"].startswith("ISO") else INCH_MARGIN
        out.append({"name": r["name"], "width": r["width"], "height": r["height"], "margins": [m, m, m, m]})
    return out


def builtin_devices():
    base = standard_papers()
    out = {}
    for name, output, desc in (("FormCAD PDF", "pdf", "Writes a vector PDF file."), ("FormCAD PNG", "png", "Writes an image at the device resolution."), ("FormCAD SVG", "svg", "Writes a vector SVG file.")):
        out[papers.fold(name)] = {"name": name, "description": desc, "output": output, "resolution": 300, "orientation": "landscape", "paper": "ISO A4 (210.00 x 297.00 MM)", "papers": base, "builtin": True}
    return out


BUILTIN = builtin_devices()


def folder():
    return os.path.join(config.data_dir(), "plotters")


def clean_device(raw):
    if not isinstance(raw, dict):
        raise DeviceError("A plotter file must hold an object.")
    name = str(raw.get("name", "")).strip()
    if not name or len(name) > 100 or any(ord(c) < 32 for c in name):
        raise DeviceError("A device name is 1 to 100 characters without control characters.")
    output = str(raw.get("output", "pdf")).strip().lower()
    if output not in OUTPUTS:
        raise DeviceError("A device output is pdf, png or svg.")
    try:
        res = int(raw.get("resolution", 300))
    except (TypeError, ValueError):
        raise DeviceError("The resolution is a number from 50 to 2400.")
    if not 50 <= res <= 2400:
        raise DeviceError("The resolution is a number from 50 to 2400.")
    orient = str(raw.get("orientation", "landscape")).strip().lower()
    if orient not in ("landscape", "portrait"):
        orient = "landscape"
    plist = raw.get("papers", [])
    if not isinstance(plist, list) or not plist:
        raise DeviceError("A device needs a paper list.")
    seen = set()
    out = []
    for p in plist[:MAX_PAPERS]:
        if not isinstance(p, dict):
            continue
        pn = str(p.get("name", "")).strip()
        if not pn or len(pn) > 100 or any(ord(c) < 32 for c in pn) or papers.fold(pn) in seen:
            continue
        try:
            w, h = float(p["width"]), float(p["height"])
            m = [float(v) for v in p.get("margins", [0, 0, 0, 0])]
        except (KeyError, TypeError, ValueError):
            continue
        if not papers.sane(w, h) or len(m) != 4 or any(not 0.0 <= v <= 1000.0 for v in m):
            continue
        lo, hi = min(w, h), max(w, h)
        if m[0] + m[2] >= lo or m[1] + m[3] >= hi:
            continue
        seen.add(papers.fold(pn))
        out.append({"name": pn, "width": lo, "height": hi, "margins": m})
    if not out:
        raise DeviceError("The device has no usable paper.")
    default = str(raw.get("paper", out[0]["name"]))
    if papers.fold(default) not in seen:
        default = out[0]["name"]
    return {"name": name, "description": str(raw.get("description", ""))[:255], "output": output, "resolution": res, "orientation": orient, "paper": default, "papers": out}


def user_devices():
    base = folder()
    out = {}
    if not os.path.isdir(base):
        return out
    for fn in sorted(os.listdir(base)):
        if not fn.endswith(EXT) or len(out) >= MAX_DEVICES:
            continue
        full = os.path.join(base, fn)
        try:
            if os.path.getsize(full) > MAX_FILE:
                continue
            with open(full, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if not isinstance(raw, dict) or raw.get("format") != FORMAT or int(raw.get("version", 0)) > VERSION:
                continue
            dev = clean_device(raw)
        except (OSError, ValueError, DeviceError, UnicodeDecodeError):
            continue
        dev["file"] = full
        out.setdefault(papers.fold(dev["name"]), dev)
    return out


def all_devices():
    out = dict(BUILTIN)
    out.update(user_devices())
    return out


def find(name):
    key = papers.fold(name or "")
    if not key or key == "none":
        return None
    return all_devices().get(key)


def default_for(output):
    for d in BUILTIN.values():
        if d["output"] == output:
            return d
    return next(iter(BUILTIN.values()))


def paper_of(device, name):
    key = papers.fold(name or "")
    for p in device["papers"]:
        if papers.fold(p["name"]) == key:
            return p
    rec = papers.lookup(name)
    if rec is not None:
        for p in device["papers"]:
            if abs(p["width"] - min(rec["width"], rec["height"])) < 0.6 and abs(p["height"] - max(rec["width"], rec["height"])) < 0.6:
                return p
    return None


def summary(dev):
    return {"name": dev["name"], "description": dev["description"], "output": dev["output"], "resolution": dev["resolution"], "orientation": dev["orientation"], "paper": dev["paper"], "builtin": bool(dev.get("builtin")), "file": dev.get("file", ""), "papers": len(dev["papers"])}


def listing():
    return [summary(d) for d in all_devices().values()]


def save_device(raw):
    dev = clean_device(raw)
    os.makedirs(folder(), exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_ ()" else "_" for c in dev["name"])
    path = os.path.join(folder(), safe + EXT)
    body = {"format": FORMAT, "version": VERSION, **{k: dev[k] for k in ("name", "description", "output", "resolution", "orientation", "paper", "papers")}}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(body, fh, indent=1, ensure_ascii=False)
    return path
