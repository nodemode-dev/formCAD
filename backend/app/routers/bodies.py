from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from app.bodies import configs, massprops, materials, multibody, planesource, refgeo
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.param import ops
from app.param import store as S
from app.solid.work import SolidError

router = APIRouter(tags=["bodies"])


class CombineIn(BaseModel):
    op: str
    handles: list[int]
    keep_tools: bool = False
    fuzzy: Optional[float] = None
    force: bool = False
    retry: bool = True


class SplitIn(BaseModel):
    handle: int
    planes: list[Any] = []
    tools: list[int] = []
    keep_tools: bool = True
    fuzzy: Optional[float] = None
    force: bool = False


class MoveIn(BaseModel):
    handles: list[int]
    translate: Optional[list[float]] = None
    rotate: Optional[dict[str, Any]] = None
    count: int = 1


class MaterialAssign(BaseModel):
    material: str = ""
    refresh: bool = False


class MassIn(BaseModel):
    handles: list[int] = []
    cs: Any = None
    density: Optional[float] = None


class MaterialRow(BaseModel):
    name: Optional[str] = None
    grade: Optional[str] = None
    density: Optional[float] = None
    youngs_modulus: Optional[float] = None
    poissons_ratio: Optional[float] = None
    provenance: Optional[str] = None


class RefIn(BaseModel):
    kind: str
    method: str
    params: dict[str, Any] = {}
    name: Optional[str] = None


class RefEdit(BaseModel):
    params: Optional[dict[str, Any]] = None
    new_name: Optional[str] = None
    visible: Optional[bool] = None


class ConfigIn(BaseModel):
    name: str
    description: str = ""
    values: dict[str, Any] = {}
    suppress: dict[str, Any] = {}
    materials: dict[str, Any] = {}
    copy_from: Optional[str] = None


class ConfigEdit(BaseModel):
    description: Optional[str] = None
    values: dict[str, Any] = {}
    suppress: dict[str, Any] = {}
    materials: dict[str, Any] = {}
    new_name: Optional[str] = None


class GridIn(BaseModel):
    rows: list[Any]


class PathIn(BaseModel):
    path: str


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, ops.Refused):
        raise HTTPException(409, {"message": err.message, "explanation": err.explanation})
    if isinstance(err, SolidError):
        raise HTTPException(503, str(err))
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    raise HTTPException(400, str(err))


GUARDED = (multibody.BodyError, configs.ConfigError, refgeo.RefError, materials.MaterialError, massprops.MassError, S.ParamError, SolidError, CommandFailed, ValueError, KeyError)


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc.drawing)
        except GUARDED as err:
            _fail(err)


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc.drawing)
        except GUARDED as err:
            _fail(err)


@router.get("/{doc_id}/bodies")
def list_bodies(doc_id: str) -> dict:
    return _read(doc_id, lambda d: {"bodies": multibody.describe(d)})


@router.post("/{doc_id}/bodies/combine")
def combine_bodies(doc_id: str, body: CombineIn) -> dict:
    return _edit(doc_id, "COMBINE", lambda d: multibody.combine(d, body.op.lower(), body.handles, body.keep_tools, body.fuzzy, body.force, body.retry))


@router.post("/{doc_id}/bodies/split")
def split_body(doc_id: str, body: SplitIn) -> dict:
    return _edit(doc_id, "SPLITBODY", lambda d: multibody.split(d, body.handle, body.planes, body.tools, body.keep_tools, body.fuzzy, body.force))


@router.post("/{doc_id}/bodies/move")
def move_bodies(doc_id: str, body: MoveIn) -> dict:
    return _edit(doc_id, "MOVEBODY", lambda d: multibody.move(d, body.handles, {"translate": body.translate, "rotate": body.rotate}))


@router.post("/{doc_id}/bodies/copy")
def copy_bodies(doc_id: str, body: MoveIn) -> dict:
    return _edit(doc_id, "COPYBODY", lambda d: multibody.copy_bodies(d, body.handles, {"translate": body.translate, "rotate": body.rotate}, body.count))


@router.put("/{doc_id}/bodies/{handle}/material")
def assign_material(doc_id: str, handle: int, body: MaterialAssign) -> dict:
    return _edit(doc_id, "MATERIAL", lambda d: materials.assign(d, multibody.solid(d, handle), body.material.strip(), body.refresh))


@router.post("/{doc_id}/bodies/massprops")
def mass_properties(doc_id: str, body: MassIn) -> dict:
    return _read(doc_id, lambda d: massprops.compute(d, body.handles, body.cs, body.density))


@router.get("/{doc_id}/bodies/exitcheck")
def exit_check(doc_id: str) -> dict:
    return _read(doc_id, massprops.exit_check)


@router.get("/{doc_id}/materials")
def get_materials(doc_id: str) -> dict:
    return _read(doc_id, lambda d: {**materials.library(), "document": materials.doc_rows(d)})


@router.post("/{doc_id}/materiallib")
def add_material(doc_id: str, body: MaterialRow) -> dict:
    _doc(doc_id)
    try:
        return materials.add_user(body.model_dump(exclude_none=True))
    except GUARDED as err:
        _fail(err)


@router.put("/{doc_id}/materiallib/{name}")
def edit_material(doc_id: str, name: str, body: MaterialRow) -> dict:
    _doc(doc_id)
    try:
        return materials.update_user(name, body.model_dump(exclude_none=True))
    except GUARDED as err:
        _fail(err)


@router.delete("/{doc_id}/materiallib/{name}")
def remove_material(doc_id: str, name: str) -> dict:
    _doc(doc_id)
    try:
        return materials.delete_user(name)
    except GUARDED as err:
        _fail(err)


@router.get("/{doc_id}/refgeo")
def list_refgeo(doc_id: str) -> dict:
    return _read(doc_id, lambda d: {"items": refgeo.describe(d), "methods": {k: list(v) for k, v in refgeo.METHODS.items()}})


@router.post("/{doc_id}/refgeo")
def make_refgeo(doc_id: str, body: RefIn) -> dict:
    return _edit(doc_id, "REF" + body.kind.upper(), lambda d: refgeo.create(d, body.kind.lower(), body.method.lower(), body.params, body.name))


@router.post("/{doc_id}/refgeo/rebuild")
def rebuild_refgeo(doc_id: str) -> dict:
    return _edit(doc_id, "REFREBUILD", refgeo.rebuild)


@router.put("/{doc_id}/refgeo/{name}")
def edit_refgeo(doc_id: str, name: str, body: RefEdit) -> dict:
    return _edit(doc_id, "REFEDIT", lambda d: refgeo.update(d, name, body.params, body.new_name, body.visible))


@router.delete("/{doc_id}/refgeo/{name}")
def delete_refgeo(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "REFDELETE", lambda d: refgeo.delete(d, name))


@router.get("/{doc_id}/configs")
def list_configs(doc_id: str) -> dict:
    return _read(doc_id, configs.listing)


@router.post("/{doc_id}/configs")
def make_config(doc_id: str, body: ConfigIn) -> dict:
    return _edit(doc_id, "CONFIG", lambda d: configs.create(d, body.name, body.description, body.values, body.suppress, body.materials, body.copy_from))


@router.put("/{doc_id}/configs/{name}")
def edit_config(doc_id: str, name: str, body: ConfigEdit) -> dict:
    return _edit(doc_id, "CONFIG", lambda d: configs.update(d, name, body.description, body.values, body.suppress, body.materials, body.new_name))


@router.delete("/{doc_id}/configs/{name}")
def delete_config(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "CONFIGDELETE", lambda d: configs.delete(d, name))


@router.post("/{doc_id}/configs/{name}/activate")
def activate_config(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "CONFIGACTIVATE", lambda d: configs.activate(d, name))


@router.get("/{doc_id}/designtable")
def get_design_table(doc_id: str) -> dict:
    return _read(doc_id, configs.grid)


@router.get("/{doc_id}/designtable/csv")
def get_design_table_csv(doc_id: str) -> PlainTextResponse:
    return PlainTextResponse(_read(doc_id, configs.to_csv), media_type="text/csv")


@router.put("/{doc_id}/designtable")
def set_design_table(doc_id: str, body: GridIn) -> dict:
    return _edit(doc_id, "DESIGNTABLE", lambda d: configs.apply_grid(d, {"rows": body.rows}))


@router.post("/{doc_id}/designtable/export")
def export_design_table(doc_id: str, body: PathIn) -> dict:
    return _read(doc_id, lambda d: configs.export_file(d, body.path))


@router.post("/{doc_id}/designtable/import")
def import_design_table(doc_id: str, body: PathIn) -> dict:
    return _edit(doc_id, "DESIGNTABLE", lambda d: configs.import_file(d, body.path))
