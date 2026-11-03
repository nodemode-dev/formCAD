from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.ecadout import files, interop, link
from app.ecadout import view as V
from app.pcb.store import PcbRecordError
from app.routers.part import _doc
from app.solid.work import SolidError

router = APIRouter(tags=["ecadout"])


class OutBody(BaseModel):
    out: str
    zip: bool = False
    options: Optional[dict[str, Any]] = None


class SettingsBody(BaseModel):
    mask_margin: Optional[float] = None
    paste_margin: Optional[float] = None
    tent_vias: Optional[bool] = None


class RefBody(BaseModel):
    ref: dict[str, Any]


class SyncBody(BaseModel):
    ref: Optional[dict[str, Any]] = None


class PushBody(BaseModel):
    doc: Optional[str] = None
    plane_z: float = 0.0
    name: str = link.SKETCH


class FlagBody(BaseModel):
    enabled: bool


class PathBody(BaseModel):
    path: str


def run(doc_id: str, fn, write: bool = False):
    doc = _doc(doc_id)
    with doc.lock:
        if write and doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            return fn(doc)
        except (V.OutputError, PcbRecordError, interop.kicad.KicadError) as err:
            raise HTTPException(400, str(err))
        except SolidError as err:
            raise HTTPException(503, str(err))


@router.post("/{doc_id}/ecad/export/gerber")
def export_gerber(doc_id: str, body: OutBody) -> dict:
    return run(doc_id, lambda d: files.export_gerber(d, body.out, body.zip, body.options))


@router.post("/{doc_id}/ecad/export/drill")
def export_drill(doc_id: str, body: OutBody) -> dict:
    return run(doc_id, lambda d: files.export_drill(d, body.out, body.options))


@router.post("/{doc_id}/ecad/export/idf")
def export_idf(doc_id: str, body: OutBody) -> dict:
    return run(doc_id, lambda d: files.export_idf(d, body.out, body.options))


@router.post("/{doc_id}/ecad/export/step")
def export_step(doc_id: str, body: OutBody) -> dict:
    return run(doc_id, lambda d: files.export_step(d, body.out, body.options))


@router.get("/{doc_id}/ecad/export/settings")
def export_settings(doc_id: str) -> dict:
    return run(doc_id, lambda d: files.link_header(d.drawing)["export"])


@router.put("/{doc_id}/ecad/export/settings")
def set_export_settings(doc_id: str, body: SettingsBody) -> dict:
    def go(doc):
        new = {k: v for k, v in body.model_dump().items() if v is not None}
        if "mask_margin" in new and not -1.0 <= new["mask_margin"] <= 1.0:
            raise V.OutputError("The mask margin is between -1 and 1 mm.")
        if "paste_margin" in new and not -1.0 <= new["paste_margin"] <= 1.0:
            raise V.OutputError("The paste margin is between -1 and 1 mm.")
        with doc.transaction("ECADEXPORT"):
            lk = files.link_header(doc.drawing)
            lk["export"] = {**lk["export"], **new}
            files.save_link(doc.drawing, lk)
        return lk["export"]

    return run(doc_id, go, True)


@router.get("/{doc_id}/ecad/board3d")
def board3d(doc_id: str) -> dict:
    return run(doc_id, files.board_summary)


@router.get("/{doc_id}/ecad/board3d/mesh")
def board3d_mesh(doc_id: str, which: str = "board", detail: float = 1.0) -> Response:
    if which not in ("board", "components") or not 0.1 <= detail <= 4.0:
        raise HTTPException(400, "which is board or components; detail is between 0.1 and 4.")
    data, info = run(doc_id, lambda d: files.board_mesh(d, which, detail))
    return Response(content=data, media_type="application/octet-stream", headers={"Cache-Control": "no-store", "X-FormCAD-Board": "%s;%s" % (info["thickness"], info["components"])})


@router.get("/{doc_id}/ecad/link")
def link_get(doc_id: str) -> dict:
    return run(doc_id, link.status)


@router.put("/{doc_id}/ecad/link")
def link_put(doc_id: str, body: RefBody) -> dict:
    return run(doc_id, lambda d: link.link_set(d, body.ref), True)


@router.delete("/{doc_id}/ecad/link")
def link_delete(doc_id: str) -> dict:
    return run(doc_id, link.unlink, True)


@router.post("/{doc_id}/ecad/link/sync")
def link_sync(doc_id: str, body: Optional[SyncBody] = None) -> dict:
    return run(doc_id, lambda d: link.sync_from_part(d, body.ref if body else None), True)


@router.post("/{doc_id}/ecad/link/push")
def link_push(doc_id: str, body: PushBody) -> dict:
    def go(doc):
        target = body.doc or (files.link_header(doc.drawing).get("outline_ref") or {}).get("doc")
        if not target:
            raise V.OutputError("Name the part document to push the outline to.")
        return link.push_to_part(doc, target, body.plane_z, body.name)

    return run(doc_id, go, True)


@router.get("/{doc_id}/ecad/kicad")
def kicad_get(doc_id: str) -> dict:
    return run(doc_id, lambda d: {"enabled": interop.enabled(d.drawing)})


@router.put("/{doc_id}/ecad/kicad")
def kicad_put(doc_id: str, body: FlagBody) -> dict:
    return run(doc_id, lambda d: interop.set_enabled(d, body.enabled), True)


@router.post("/{doc_id}/ecad/export/kicad")
def export_kicad(doc_id: str, body: OutBody) -> dict:
    return run(doc_id, lambda d: interop.export_board(d, body.out))


@router.post("/{doc_id}/ecad/import/kicad")
def import_kicad(doc_id: str, body: PathBody) -> dict:
    return run(doc_id, lambda d: interop.import_board(d, body.path), True)
