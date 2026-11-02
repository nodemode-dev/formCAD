from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.doc import find as F
from app.doc import props as P
from app.doc import qselect as Q
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["properties"])


class PropertiesBody(BaseModel):
    handles: Optional[list[int]] = None
    changes: dict[str, Any] = Field(default_factory=dict)
    kind: Optional[str] = None
    skip_locked: Optional[bool] = Field(True, alias="skipLocked")


class FindBody(BaseModel):
    text: str
    replace: Optional[str] = None
    match_case: Optional[bool] = Field(False, alias="matchCase")
    whole_word: Optional[bool] = Field(False, alias="wholeWord")
    select: Optional[bool] = True


class QSelectBody(BaseModel):
    scope: str = "all"
    kind: Optional[str] = None
    property: Optional[str] = None
    operator: str = "="
    value: str = ""
    how: str = "include"
    append: bool = False


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _handles(doc, handles):
    if handles is not None:
        return handles
    return doc.get_runner().current_selection()


@router.get("/{doc_id}/properties")
def get_properties(doc_id: str, handles: str = "") -> dict:
    doc = _doc(doc_id)
    try:
        wanted = [int(h) for h in handles.split(",") if h.strip()] if handles.strip() else None
    except ValueError:
        raise HTTPException(400, "handles must be a comma list of integers.")
    with doc.lock:
        out = P.inspect(doc.drawing, _handles(doc, wanted))
        out["rev"] = doc.rev
        return out


@router.put("/{doc_id}/properties")
def put_properties(doc_id: str, body: PropertiesBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        d = doc.drawing
        wanted = _handles(doc, body.handles)
        ents = [d.get(h) for h in wanted if d.get(h) is not None]
        locked = 0
        if body.skip_locked:
            live = [e for e in ents if not d.layer_locked(e.layer)]
            locked = len(ents) - len(live)
            ents = live
        try:
            with doc.transaction("PROPERTIES"):
                changed = P.apply_changes(d, ents, body.changes, body.kind)
        except P.PropError as err:
            raise HTTPException(400, str(err))
        except CommandFailed as err:
            raise HTTPException(409, str(err))
        out = P.inspect(d, [e.handle for e in ents])
        return {"changed": changed, "locked": locked, "rev": doc.rev, "properties": out}


@router.get("/{doc_id}/qselect")
def qselect_info(doc_id: str, scope: str = "all", kind: str = "") -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        d = doc.drawing
        ents = [e for e in d.entities(doc.current_space) if d.visible(e)]
        return Q.info(ents, scope, list(doc.selection), kind or None)


@router.post("/{doc_id}/qselect")
def qselect_run(doc_id: str, body: QSelectBody) -> dict:
    doc = _doc(doc_id)
    state = doc.get_runner().run_command("qselect", body.model_dump())
    if state.get("error"):
        raise HTTPException(400, state["error"])
    out = state.get("result") or {"handles": [], "count": 0}
    out["rev"] = doc.rev
    return out


@router.post("/{doc_id}/find")
def find_text(doc_id: str, body: FindBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            rx = F.pattern(body.text, bool(body.match_case), bool(body.whole_word))
        except F.FindError as err:
            raise HTTPException(400, str(err))
        d = doc.drawing
        space = doc.current_space
        if body.replace is None:
            rows = F.scan(d, space, rx)
            if body.select:
                doc.selection = [r["handle"] for r in rows]
                doc.announce("selection")
            return {"matches": rows, "total": sum(r["hits"] for r in rows), "selected": [r["handle"] for r in rows] if body.select else [], "rev": doc.rev}
        try:
            with doc.transaction("FIND"):
                out = F.replace(d, space, rx, body.replace)
        except CommandFailed as err:
            raise HTTPException(409, str(err))
        out["total"] = out["hits"]
        out["rev"] = doc.rev
        return out
