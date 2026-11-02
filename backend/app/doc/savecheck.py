import os
import tempfile

from app.doc import refedit

LOSSY = (".dxf", ".dwg", ".dwt")
MAX_TYPES = 8
MAX_NAME = 40


def guard(doc) -> str:
    if refedit.current(doc.drawing) is not None:
        return "A block reference is being edited in place: finish with REFCLOSE (Save or Discard) before saving."
    return ""


def loss(doc, path: str = "") -> dict:
    target = (path or doc.path or "").strip()
    ext = os.path.splitext(target)[1].lower()
    if ext not in LOSSY:
        return {"dropped": {}, "types": [], "more": 0, "backup": backup_note(doc, target)}
    from app.interchange import dxf_write, dxfcommon
    from app.interchange.errors import InterchangeError, Report

    fx = (doc.drawing.foreign or {}).get("dxf", {})
    ver = dxfcommon.default_version(fx["acadver"]) if fx.get("acadver") else "R2018"
    report = Report()
    with tempfile.TemporaryDirectory(prefix="fcsv_") as tmp:
        try:
            dxf_write.write_file(doc.drawing, os.path.join(tmp, "check.dxf"), ver or "R2018", report, 6)
        except InterchangeError:
            return {"dropped": {}, "types": [], "more": 0, "backup": backup_note(doc, target)}
    dropped = dict(report.dropped)
    names = [(k[:MAX_NAME], n) for k, n in sorted(dropped.items(), key=lambda kv: (-kv[1], kv[0]))]
    return {"dropped": dropped, "types": [{"name": k, "count": n} for k, n in names[:MAX_TYPES]], "more": max(0, len(names) - MAX_TYPES), "backup": backup_note(doc, target)}


def backup_note(doc, target: str) -> str:
    from app.sysvars import registry as sv

    if not target or not os.path.exists(target):
        return "new"
    return "kept" if int(sv.session_value("ISAVEBAK")) else "replaced"


def agreed(doc, path: str, res: dict) -> bool:
    key = (os.path.realpath(path or doc.path or ""), tuple(sorted(res["dropped"].items())))
    return key in getattr(doc, "save_agreed", set())


def agree(doc, path: str, res: dict) -> None:
    key = (os.path.realpath(path or doc.path or ""), tuple(sorted(res["dropped"].items())))
    if not hasattr(doc, "save_agreed"):
        doc.save_agreed = set()
    doc.save_agreed.add(key)
