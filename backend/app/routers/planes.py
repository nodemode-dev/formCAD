from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.solid import planes

router = APIRouter(tags=["planes"])


class PlaneIn(BaseModel):
    world: Optional[str] = None
    origin: Optional[Any] = None
    points: Optional[Any] = None
    face: Optional[Any] = None


class GridIn(BaseModel):
    plane: Any
    target: Any = None
    visible: float = 1.0
    radius: float = 1.0
    point: Optional[Any] = None
    step: Optional[float] = None


def _check(doc_id: str) -> None:
    try:
        service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


@router.post("/{doc_id}/plane")
def make_plane(doc_id: str, body: PlaneIn) -> dict:
    _check(doc_id)
    try:
        if body.world is not None:
            return {"plane": planes.world(body.world, planes.vec(body.origin if body.origin is not None else [0, 0, 0], "origin"))}
        if body.points is not None:
            if not isinstance(body.points, list) or len(body.points) != 3:
                raise planes.PlaneError("Give three points.")
            a, b, c = (planes.vec(p) for p in body.points)
            return {"plane": planes.through_points(a, b, c)}
        if body.face is not None:
            if not isinstance(body.face, dict):
                raise planes.PlaneError("The face needs a point and a normal.")
            return {"plane": planes.on_face(planes.vec(body.face.get("point"), "point"), planes.vec(body.face.get("normal"), "normal"))}
    except planes.PlaneError as err:
        raise HTTPException(400, str(err))
    raise HTTPException(400, "Give world, points or face.")


@router.post("/{doc_id}/grid")
def grid_for_plane(doc_id: str, body: GridIn) -> dict:
    _check(doc_id)
    try:
        plane = planes.frame(body.plane)
        out = planes.grid_lines(plane, planes.vec(body.target if body.target is not None else plane["origin"], "target"), body.visible, body.radius)
        if body.point is not None:
            step = body.step if body.step else out["step"]
            out["snapped"] = list(planes.quantise(plane, planes.vec(body.point), step))
        return out
    except planes.PlaneError as err:
        raise HTTPException(400, str(err))
