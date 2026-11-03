from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.cmd.commands import subd as subd_cmds
from app.doc.service import DocumentFault, service
from app.param.units import mm_per_unit
from app.subd import edit, store, sym as symmetry
from app.subd.cc import SubdError

router = APIRouter(tags=["subd"])


class SoftBody(BaseModel):
    vertices: list[int] = Field(default_factory=list, max_length=60000)
    edges: list[list[int]] = Field(default_factory=list, max_length=200000)
    faces: list[int] = Field(default_factory=list, max_length=20000)
    radius: float = 0.0
    falloff: str = "smooth"
    symmetry: bool = True


class LimitBody(BaseModel):
    level: int = 2


class AnalyzeBody(BaseModel):
    levels: int = 2


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _form(doc, handle: int):
    ent = doc.drawing.get(int(handle))
    if ent is None or ent.kind != "subdbody":
        raise HTTPException(404, "There is no form with that handle.")
    return ent


@router.get("/{doc_id}/subd")
def subd_list(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rows = []
        for e in doc.drawing.entities("model"):
            if e.kind == "subdbody":
                rows.append({"handle": e.handle, "name": e.name, "summary": e.summary, "display": e.display, "level": e.level, "sym": e.sym, "version": e.version})
        return {"cages": rows, "rev": doc.rev}


@router.get("/{doc_id}/subd/{handle}")
def subd_get(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _form(doc, handle)
        cage = store.load(ent)
        edges, owners = cage.edge_faces()
        return {
            "handle": ent.handle, "name": ent.name, "layer": ent.layer, "rgb": ent.rgb, "offset": ent.offset, "version": ent.version,
            "v": ent.v, "f": ent.f, "crease": ent.crease, "sym": ent.sym, "display": ent.display, "level": ent.level, "summary": ent.summary,
            "edges": [list(e) for e in edges], "edge_faces": owners, "valence": cage.valence().tolist(),
            "boundary_edges": [i for i, o in enumerate(owners) if len(o) == 1], "unit_mm": mm_per_unit(doc.drawing),
        }


@router.post("/{doc_id}/subd/{handle}/soft")
def subd_soft(doc_id: str, handle: int, body: SoftBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _form(doc, handle)
        cage = store.load(ent)
        try:
            sel = edit.selection_vertices(cage, body.vertices, body.edges, body.faces)
            weights = edit.soft_weights(cage, sel, body.radius, body.falloff)
            images = []
            if body.symmetry and symmetry.active(ent.sym):
                pl = symmetry.perms(cage, ent.sym)
                images = sorted(symmetry.image_set(pl, sel) - sel)
        except SubdError as err:
            raise HTTPException(400, str(err))
        return {"weights": [round(float(w), 6) for w in weights], "selected": sorted(sel), "images": images}


@router.post("/{doc_id}/subd/{handle}/analyze")
def subd_analyze(doc_id: str, handle: int, body: AnalyzeBody | None = None) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _form(doc, handle)
        cage = store.load(ent)
        levels = body.levels if body else 2
        return subd_cmds.info_report(cage, ent.sym, levels)


@router.post("/{doc_id}/subd/{handle}/limit")
def subd_limit(doc_id: str, handle: int, body: LimitBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ent = _form(doc, handle)
        cage = store.load(ent)
        try:
            v, quads, root = store.limit_mesh(cage, body.level)
        except SubdError as err:
            raise HTTPException(400, str(err))
        return {"vertices": v.tolist(), "quads": quads.tolist(), "face_of": root.tolist(), "level": body.level}
