from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cmd.commands import text_common as tc
from app.cmd.context import CommandError, Context
from app.cmd.prompts import Input
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["mtext"])


class MTextBody(BaseModel):
    handle: Optional[int] = None
    contents: str
    props: Optional[dict[str, Any]] = None


def _doc(doc_id):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _pending(doc):
    rn = doc.get_runner()
    run = rn.run
    if run is None or run.spec.name != "mtext" or "mtext_pending" not in rn.memory:
        return None
    return rn


def _read(ent):
    plain = ent.contents
    return {"handle": ent.handle, "contents": ent.contents, "props": tc.mtext_props(ent), "plain": plain, "layer": ent.layer}


@router.get("/{doc_id}/mtext")
def read_pending(doc_id: str, handle: Optional[int] = None) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        if handle is None:
            rn = _pending(doc)
            if rn is None:
                raise HTTPException(404, "No multiline text is being created.")
            return {"pending": True, "props": dict(rn.memory["mtext_pending"])}
        ent = doc.drawing.get(handle)
        if ent is None or ent.kind != "mtext":
            raise HTTPException(404, "No multiline text with that handle.")
        return _read(ent)


@router.get("/{doc_id}/mtext/{handle}")
def read_one(doc_id: str, handle: int) -> dict:
    return read_pending(doc_id, handle)


@router.post("/{doc_id}/mtext")
def write_mtext(doc_id: str, body: MTextBody) -> dict:
    doc = _doc(doc_id)
    props = dict(body.props or {})
    contents = body.contents
    if not contents.strip():
        raise HTTPException(400, "Text is empty.")
    with doc.lock:
        rn = doc.get_runner()
        if body.handle is None:
            pend = _pending(doc)
            if pend is not None:
                pend.begin_call()
                pend._deliver(Input("text", contents, text=contents))
                if pend.run is not None and pend.run.spec.name == "mtext":
                    pend._deliver(Input("enter"))
                doc.live_touch()
                handle = pend.memory.get("last_mtext")
                return {"handle": handle, "created": True, "state": pend.state()}
        ctx = Context(rn, doc)
        try:
            with doc.transaction("MTEXT"):
                if body.handle is None:
                    if "position" not in props:
                        props["position"] = [0.0, 0.0]
                    handle = tc.create_mtext(ctx, contents, props)
                    created = True
                else:
                    ent = doc.drawing.get(body.handle)
                    if ent is None or ent.kind != "mtext":
                        raise HTTPException(404, "No multiline text with that handle.")
                    if ctx.locked(ent):
                        raise HTTPException(409, "That object is on a locked layer.")
                    rec = doc.drawing.modify(body.handle)
                    tc.apply_mtext_props(ctx, rec, props)
                    rec.contents = tc.check_text(contents, tc.MAX_CONTENTS)
                    handle = body.handle
                    created = False
        except CommandError as err:
            raise HTTPException(400, str(err))
        except CommandFailed as err:
            raise HTTPException(409, str(err))
        return {"handle": handle, "created": created, "rev": doc.rev}
