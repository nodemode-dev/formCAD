from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc import tableops as O
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["tables"])


class TableBody(BaseModel):
    cells: Optional[list[dict[str, Any]]] = None
    ops: Optional[list[dict[str, Any]]] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _table(doc, handle: int):
    ent = doc.drawing.get(handle)
    if ent is None or ent.kind != "table":
        raise HTTPException(404, "No such table.")
    return ent


@router.get("/{doc_id}/table/{handle}")
def get_table(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _table(doc, handle)
        return O.describe(doc.drawing, ent)


@router.put("/{doc_id}/table/{handle}")
def put_table(doc_id: str, handle: int, body: TableBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _table(doc, handle)
        runner = doc.get_runner()
        if runner.run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        if doc.drawing.layer_locked(ent.layer):
            raise HTTPException(409, "The table is on a locked layer.")
        steps = []
        for c in body.cells or []:
            steps.append({"op": "set", **c})
        steps.extend(body.ops or [])
        if not steps:
            return O.describe(doc.drawing, ent)
        try:
            with doc.transaction("TABLE"):
                t = doc.drawing.modify(handle)
                for op in steps:
                    O.apply_op(doc.drawing, t, op)
                O.ensure_heights(doc.drawing, t)
                O.recalc(doc.drawing, t)
        except O.TableError as err:
            raise HTTPException(400, str(err))
        except (KeyError, TypeError, ValueError) as err:
            raise HTTPException(400, "Invalid table change: %s" % err)
        return O.describe(doc.drawing, doc.drawing.get(handle))
