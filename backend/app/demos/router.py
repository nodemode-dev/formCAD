from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["demos"])

FOLDER = Path(__file__).resolve().parents[1] / "data" / "demos"

DEMOS = (
    {"id": "drafting", "title": "Studio floor plan", "line": "Layers, hatched walls, door and window blocks, dimensions and a title block on an A3 sheet", "kind": "drawing", "name": "Studio plan"},
    {"id": "part", "title": "Plate with boss", "line": "A parametric part: sketches, extrudes, shell, pocket, hole pattern, fillets and a chamfer in the feature tree", "kind": "part", "name": "Boss plate"},
    {"id": "graph", "title": "Plate with bolt holes", "line": "A node graph that drives a plate, a polar ring of holes and a section, baked into the drawing", "kind": "graph", "name": "Bolt plate graph"},
)


def _find(demo_id: str) -> dict:
    for demo in DEMOS:
        if demo["id"] == demo_id:
            return demo
    raise HTTPException(404, "Unknown demo " + demo_id + ".")


@router.get("")
def list_demos() -> dict:
    return {"demos": [{k: d[k] for k in ("id", "title", "line", "kind")} for d in DEMOS]}


@router.post("/{demo_id}/open")
def open_demo(demo_id: str) -> dict:
    demo = _find(demo_id)
    path = FOLDER / (demo["id"] + ".fcad")
    if not path.is_file():
        raise HTTPException(404, "The demo " + demo_id + " is not installed.")
    try:
        return service.new(demo["name"], str(path)).summary()
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)
    except CommandFailed as err:
        raise HTTPException(409, str(err))
