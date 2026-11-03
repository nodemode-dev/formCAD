import os
import tempfile
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.anim import board as B
from app.anim import sample
from app.core import guard, outputs
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.mates import store as S
from app.solid.work import SolidError

router = APIRouter(tags=["storyboards"])

MAX_VIDEO = 1 << 30
VIDEO_TYPES = (".mp4", ".webm")


class BoardBody(BaseModel):
    name: Optional[str] = None
    fps: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    style: Optional[str] = None
    source: Optional[str] = None
    samples: Optional[int] = None
    shots: Optional[list[dict[str, Any]]] = None


class SeedBody(BaseModel):
    name: str
    view: str
    hold: float = 1.0
    run: float = 4.0
    orbit: float = 0.0
    fps: int = 30
    width: int = 1280
    height: int = 720
    camera: Optional[dict[str, Any]] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, (B.BoardRefused, S.MateRefused)):
        raise HTTPException(409, getattr(err, "message", None) or str(err))
    raise HTTPException(400, str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc)
        except (B.BoardRefused, S.MateRefused, SolidError, ValueError, KeyError) as err:
            _fail(err)
        except CommandFailed as err:
            raise HTTPException(409, str(err))


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except (B.BoardRefused, S.MateRefused, SolidError, ValueError, KeyError) as err:
            _fail(err)


def _with_plan(b: dict) -> dict:
    return {**b, "plan": B.plan_of(b)}


@router.get("/{doc_id}/storyboards")
def list_boards(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: B.listing(doc.drawing))


@router.post("/{doc_id}/storyboards")
def create_board(doc_id: str, body: BoardBody) -> dict:
    return _edit(doc_id, "STORYBOARD", lambda doc: _with_plan(B.create(doc.drawing, body.name or "", body.model_dump(exclude_none=True))))


@router.post("/{doc_id}/storyboards/from-explode")
def seed_board(doc_id: str, body: SeedBody) -> dict:
    def run(doc):
        return _with_plan(B.seed_from_explode(doc.drawing, body.name, body.view, body.hold, body.run, body.orbit, body.fps, body.width, body.height, body.camera))

    return _edit(doc_id, "STORYBOARD", run)


@router.put("/{doc_id}/storyboards/{name}")
def replace_board(doc_id: str, name: str, body: BoardBody) -> dict:
    return _edit(doc_id, "STORYBOARD", lambda doc: _with_plan(B.replace(doc.drawing, name, body.model_dump(exclude_none=True))))


@router.delete("/{doc_id}/storyboards/{name}")
def delete_board(doc_id: str, name: str) -> dict:
    def run(doc):
        B.delete(doc.drawing, name)
        return {"deleted": name}

    return _edit(doc_id, "STORYBOARD", run)


@router.get("/{doc_id}/storyboards/{name}/frames")
def board_frames(doc_id: str, name: str, first: int = 0, count: int = 60) -> dict:
    return _read(doc_id, lambda doc: sample.run(doc, name, first, count))


@router.put("/{doc_id}/storyboards/{name}/video")
async def write_video(doc_id: str, name: str, request: Request, path: str = "") -> dict:
    _doc(doc_id)
    try:
        full = outputs.checked(path, VIDEO_TYPES)
    except outputs.OutputRefused as err:
        raise HTTPException(409, str(err))
    cap = (64 << 20) if guard.CALLER.get() else MAX_VIDEO
    total = 0
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(full), prefix=".video-", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                total += len(chunk)
                if total > cap:
                    raise HTTPException(413, "The video is larger than the %d MB limit." % (cap >> 20))
                fh.write(chunk)
        if total == 0:
            raise HTTPException(409, "The video is empty.")
        os.chmod(tmp, 0o644)
        os.replace(tmp, full)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return {"path": full, "bytes": total}
