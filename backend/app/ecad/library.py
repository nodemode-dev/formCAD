import copy
import re

from app.ecad import footprints, symbols
from app.ecad.store import EcadError, header

MAX_USER_SYMBOLS = 2000
MAX_USER_FOOTPRINTS = 2000


def get_symbol(d, sid: str):
    return sym_in(header(d), sid)


def get_footprint(d, fid: str):
    return fp_in(header(d), fid)


def fp_in(h: dict, fid: str):
    fp = h["lib"]["footprints"].get(fid)
    if fp is not None:
        return copy.deepcopy(fp)
    return footprints.preset(fid)


def sym_in(h: dict, sid: str):
    sym = h["lib"]["symbols"].get(sid)
    if sym is not None:
        return copy.deepcopy(sym)
    sym = symbols.BUILTIN.get(sid)
    if sym is None and sid.startswith("PWR:"):
        name = sid[4:]
        if re.fullmatch(r"[A-Za-z0-9+\-_.]{1,24}", name):
            return symbols.power_symbol(name, sid)
    return copy.deepcopy(sym) if sym is not None else None


def list_symbols(d, query: str = "") -> list:
    h = header(d)
    items = {**symbols.BUILTIN, **h["lib"]["symbols"]}
    q = query.strip().lower()
    out = []
    for sid, s in sorted(items.items()):
        if q and q not in (sid + " " + s["name"] + " " + s["description"] + " " + " ".join(s["keywords"])).lower():
            continue
        out.append({"id": sid, "name": s["name"], "prefix": s["prefix"], "power": s["power"], "pins": len(s["pins"]), "units": s["units"], "default_footprint": s["default_footprint"], "source": s["source"]})
    return out


def list_footprints(d, query: str = "") -> list:
    h = header(d)
    q = query.strip().lower()
    out = []
    for fid in sorted(set(footprints.preset_ids()) | set(h["lib"]["footprints"])):
        fp = fp_in(h, fid)
        if q and q not in (fid + " " + fp.get("description", "") + " " + fp.get("family", "")).lower():
            continue
        out.append({"id": fid, "family": fp["family"], "pads": len(fp["pads"]), "attrs": fp["attrs"], "source": fp["source"], "description": fp.get("description", "")})
    return out


def save_symbol(h: dict, sym: dict) -> dict:
    rec = symbols.validate(sym)
    if rec["id"] not in h["lib"]["symbols"] and len(h["lib"]["symbols"]) >= MAX_USER_SYMBOLS:
        raise EcadError("The user symbol library is full.")
    h["lib"]["symbols"][rec["id"]] = rec
    return rec


def delete_symbol(h: dict, sid: str) -> None:
    if sid not in h["lib"]["symbols"]:
        raise EcadError("There is no user symbol %s." % sid)
    del h["lib"]["symbols"][sid]


def save_footprint(h: dict, fp: dict) -> dict:
    fid = str(fp.get("id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_+\-.:x]{1,64}", fid):
        raise EcadError("A footprint id is 1 to 64 letters, digits or _+-.:")
    if not fp.get("pads") or len(fp["pads"]) > 1000:
        raise EcadError("A footprint has 1 to 1000 pads.")
    for p in fp["pads"]:
        if p.get("shape") not in ("rect", "roundrect", "circle", "oval", "poly"):
            raise EcadError("Unknown pad shape %s." % p.get("shape"))
        if len(p.get("size", [])) != 2 or len(p.get("pos", [])) != 2:
            raise EcadError("A pad has pos [x, y] and size [w, h].")
    if fid not in h["lib"]["footprints"] and len(h["lib"]["footprints"]) >= MAX_USER_FOOTPRINTS:
        raise EcadError("The user footprint library is full.")
    rec = copy.deepcopy(fp)
    rec["id"] = rec["name"] = fid
    rec["source"] = "user"
    rec.setdefault("attrs", ["smd"])
    rec.setdefault("family", "custom")
    rec.setdefault("courtyard", [])
    rec.setdefault("silk", [])
    rec.setdefault("fab", [])
    rec.setdefault("body", {"shape": "box", "size": [1, 1, 1], "pos": [0, 0], "z0": 0.0})
    h["lib"]["footprints"][fid] = rec
    return rec


def delete_footprint(h: dict, fid: str) -> None:
    if fid not in h["lib"]["footprints"]:
        raise EcadError("There is no user footprint %s." % fid)
    del h["lib"]["footprints"][fid]
