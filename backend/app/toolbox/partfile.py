import hashlib
import json
import os

from app.assembly import props
from app.core.outputs import OutputRefused, checked
from app.doc.service import DocumentFault, service
from app.solid import work
from app.toolbox import gens


class PartFileError(ValueError):
    pass


def file_stem(kind: str, p: dict) -> str:
    key = json.dumps([kind, {k: (round(v, 6) if isinstance(v, float) else v) for k, v in sorted(p.items())}], sort_keys=True)
    return "%s_%s" % (gens.safe_name(gens.designation(kind, p)), hashlib.sha1(key.encode("utf-8")).hexdigest()[:6])


def build_in(doc, kind: str, p: dict, label: str = "") -> dict:
    d = doc.drawing
    work.reset_if_restarted()
    wid = gens.build(kind, p)
    summary = work.kcall("shape_summary", {"id": wid})["summary"]
    name = label or gens.designation(kind, p)
    body = work.new_body(d, wid, summary, name, {"op": "toolbox", "kind": kind, "params": p})
    handle = d.add_entity(body)
    return {"handle": handle, "summary": summary, "name": name}


def properties(kind: str, p: dict, extra: dict | None = None) -> dict:
    spec = gens.KINDS[kind]
    out = {"description": spec["label"], "part_number": gens.designation(kind, p), "note": "Toolbox part from entered sizes; not checked against a standard."}
    out.update({k: v for k, v in (extra or {}).items() if v not in (None, "")})
    return out


def make(kind: str, raw: dict | None, folder: str, extra: dict | None = None, stem: str = "") -> dict:
    p = gens.clean(kind, raw)
    full_folder = os.path.abspath(os.path.expanduser(str(folder or "")))
    if not folder or not os.path.isdir(full_folder):
        raise PartFileError("The folder %s does not exist." % folder)
    name = os.path.basename(str(stem or "").replace("\\", "/")).strip(". ") or file_stem(kind, p)
    try:
        path = checked(os.path.join(full_folder, name + ".fcad"), (".fcad",), ".fcad")
    except OutputRefused as err:
        raise PartFileError(str(err))
    existing = os.path.isfile(path)
    if existing:
        return {"path": path, "kind": kind, "params": p, "designation": gens.designation(kind, p), "reused": True, "volume_expected": gens.expected_volume(kind, p)}
    doc = service.new(name, "part")
    try:
        with doc.lock:
            with doc.transaction("TOOLBOX"):
                info = build_in(doc, kind, p)
                props.put(doc.drawing, properties(kind, p, extra))
            service.save(doc, path)
    except (DocumentFault, work.SolidError) as err:
        raise PartFileError(str(err))
    finally:
        service.close(doc, force=True)
    return {"path": path, "kind": kind, "params": p, "designation": gens.designation(kind, p), "reused": False, "volume_expected": gens.expected_volume(kind, p), "summary": info["summary"]}
