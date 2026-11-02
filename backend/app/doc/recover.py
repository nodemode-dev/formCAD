import json
import os
import zipfile

from app.doc import container
from app.doc.entities import entity_from_dict
from app.doc.model import Drawing


class RecoverError(Exception):
    pass


def _lenient(name):
    return float("nan") if name == "NaN" else float(name.replace("Infinity", "inf"))


def tolerant(path: str):
    full = os.path.realpath(os.path.expanduser(path))
    notes = []
    try:
        d, man = container.load(full)
        return d, man, notes
    except container.ContainerError as err:
        notes.append("The file did not open cleanly (%s); recovering what can be read." % err.message)
    try:
        zf = zipfile.ZipFile(full)
    except (zipfile.BadZipFile, OSError) as err:
        raise RecoverError("The file cannot be recovered: %s" % err)
    with zf:
        man = {}
        try:
            man = json.loads(zf.read(container.MANIFEST))
            if not isinstance(man, dict):
                man = {}
        except (KeyError, ValueError, zipfile.BadZipFile, RuntimeError):
            notes.append("The manifest is unreadable; defaults used.")
        try:
            raw = zf.read(container.DOCUMENT)
        except (KeyError, zipfile.BadZipFile, RuntimeError, OSError) as err:
            raise RecoverError("The drawing data cannot be read: %s" % err)
    try:
        data = json.loads(raw, parse_constant=_lenient)
    except ValueError as err:
        raise RecoverError("The drawing data is not valid: %s" % err)
    if not isinstance(data, dict):
        raise RecoverError("The drawing data has no content.")
    clean = {"metric": bool(data.get("metric", True)), "header": data.get("header") if isinstance(data.get("header"), dict) else {}}
    tables = data.get("tables") if isinstance(data.get("tables"), dict) else {}
    clean["tables"] = {k: [r for r in v if isinstance(r, dict) and r.get("name")] for k, v in tables.items() if isinstance(v, list)}
    clean["spaces"] = [s for s in data.get("spaces", []) if isinstance(s, str)] if isinstance(data.get("spaces"), list) else []
    ents = []
    skipped = 0
    for item in data.get("entities", []) if isinstance(data.get("entities"), list) else []:
        try:
            if not isinstance(item, dict) or not isinstance(item.get("handle"), int):
                raise ValueError
            e = entity_from_dict(item)
            if not isinstance(e.owner, str) or not e.owner:
                raise ValueError
            e.bounds()
            e.valid()
            ents.append(e.to_dict())
        except Exception:
            skipped += 1
    if skipped:
        notes.append("%d object%s could not be read and %s left out." % (skipped, "" if skipped == 1 else "s", "was" if skipped == 1 else "were"))
    clean["entities"] = ents
    nh = data.get("next_handle")
    clean["next_handle"] = nh if isinstance(nh, int) and nh > 0 else 0x100
    for k in ("relations", "foreign"):
        if isinstance(data.get(k), dict):
            clean[k] = data[k]
    try:
        d = Drawing.from_dict(clean)
    except Exception as err:
        raise RecoverError("The drawing cannot be rebuilt: %s" % err)
    container.repair(d)
    return d, man, notes
