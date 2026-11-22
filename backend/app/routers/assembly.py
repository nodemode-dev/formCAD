from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.assembly import api, bom, cfg, light, model, parts, store
from app.assembly import props as P
from app.assembly.store import AssemblyError
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.solid.work import SolidError

router = APIRouter(tags=["assembly"])


class InsertBody(BaseModel):
    path: str
    label: Optional[str] = None
    transform: Optional[Any] = None
    config: str = ""
    relative: bool = True
    fixed: Optional[bool] = None
    visible: bool = True


class ComponentEdit(BaseModel):
    label: Optional[str] = None
    visible: Optional[bool] = None
    suppressed: Optional[bool] = None
    fixed: Optional[bool] = None
    config: Optional[str] = None
    props: Optional[dict[str, str]] = None
    remove_props: Optional[list[str]] = None
    note: Optional[str] = None


class TransformBody(BaseModel):
    matrix: Optional[Any] = None
    translate: Optional[list[float]] = None
    rotate: Optional[Any] = None
    frame: Optional[dict[str, Any]] = None
    relative: bool = False
    force: bool = False


class FindBody(BaseModel):
    folder: Optional[list[str]] = None
    deep: bool = False
    relink: bool = True
    relative: bool = True


class ReplaceBody(BaseModel):
    path: str
    relative: bool = True


class EmbedBody(BaseModel):
    handles: list[int]
    label: Optional[str] = None
    fixed: Optional[bool] = None


class PatternBody(BaseModel):
    kind: str
    seed: str
    params: dict[str, Any] = {}
    label: str = ""


class PatternEdit(BaseModel):
    params: Optional[dict[str, Any]] = None
    label: Optional[str] = None
    skip: Optional[list[int]] = None
    suppressed: Optional[bool] = None


class ConfigBody(BaseModel):
    name: str
    description: str = ""
    suppress: Optional[dict[str, bool]] = None
    visible: Optional[dict[str, bool]] = None
    component_config: Optional[dict[str, str]] = None
    patterns: Optional[dict[str, bool]] = None
    copy_from: Optional[str] = None


class ConfigEdit(BaseModel):
    description: Optional[str] = None
    suppress: Optional[dict[str, bool]] = None
    visible: Optional[dict[str, bool]] = None
    component_config: Optional[dict[str, str]] = None
    patterns: Optional[dict[str, bool]] = None
    new_name: Optional[str] = None


class ExportBody(BaseModel):
    path: str
    mode: str = "indented"
    columns: Optional[list[str]] = None
    include_suppressed: bool = False


class SettingsBody(BaseModel):
    search_folders: Optional[list[str]] = None
    search_order: Optional[list[str]] = None
    embed_cache: Optional[bool] = None
    lightweight: Optional[bool] = None


class ResolveBody(BaseModel):
    components: Optional[list[str]] = None


class PropsBody(BaseModel):
    values: dict[str, str] = {}
    remove: list[str] = []


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, SolidError):
        raise HTTPException(503, str(err))
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    if isinstance(err, KeyError):
        raise HTTPException(400, str(err.args[0]) if err.args else "Not found.")
    raise HTTPException(400, str(err))


FAILURES = (AssemblyError, P.PropError, SolidError, ValueError, KeyError, CommandFailed)


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return fn(doc)
        except FAILURES as err:
            _fail(err)


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(doc)
        except FAILURES as err:
            _fail(err)


def _folders(value):
    return [v for v in (value or []) if str(v).strip()]


@router.get("/{doc_id}/assembly")
def listing(doc_id: str) -> dict:
    return _read(doc_id, api.listing)


@router.get("/{doc_id}/assembly/schema")
def schema(doc_id: str) -> dict:
    _doc(doc_id)
    return {"schema": store.SCHEMA, "tables": [store.COMPONENTS, store.PATTERNS, store.CONFIGS], "header": store.HEADER, "types": list(store.TYPES), "search_steps": list(store.SEARCH_STEPS), "pattern_kinds": ["linear", "circular", "feature"], "bom_columns": list(bom.COLUMNS), "bom_modes": list(bom.MODES)}


@router.get("/{doc_id}/assembly/instances")
def instances(doc_id: str, suppressed: bool = False) -> dict:
    return _read(doc_id, lambda doc: api.instances_view(doc, suppressed))


@router.get("/{doc_id}/assembly/tree")
def tree(doc_id: str) -> dict:
    return _read(doc_id, api.tree_view)


@router.post("/{doc_id}/assembly/refresh")
def refresh(doc_id: str) -> dict:
    parts.forget()
    return _read(doc_id, api.listing)


@router.post("/{doc_id}/assembly/components")
def insert(doc_id: str, body: InsertBody) -> dict:
    return _edit(doc_id, "ASMINSERT", lambda doc: api.component_view(model.insert(doc, body.path, body.label, body.transform, body.config, body.relative, body.fixed, body.visible), None))


@router.post("/{doc_id}/assembly/embed")
def embed(doc_id: str, body: EmbedBody) -> dict:
    return _edit(doc_id, "ASMEMBED", lambda doc: api.component_view(model.embed(doc, body.handles, body.label, body.fixed), None))


@router.get("/{doc_id}/assembly/components/{cid}")
def get_component(doc_id: str, cid: str) -> dict:
    return _read(doc_id, lambda doc: api.component_detail(doc, cid))


def _apply_edit(doc, cid, body: ComponentEdit):
    rec = store.find_component(doc.drawing, cid)
    cid = rec["id"]
    if body.label is not None:
        model.rename(doc, cid, body.label)
    if body.visible is not None or body.suppressed is not None or body.fixed is not None:
        model.set_flags(doc, cid, body.visible, body.suppressed, body.fixed)
    if body.config is not None:
        model.set_config(doc, cid, body.config)
    if body.props is not None or body.remove_props:
        model.set_props(doc, cid, body.props or {}, body.remove_props or ())
    if body.note is not None:
        model.set_note(doc, cid, body.note)
    return api.component_detail(doc, cid)


@router.patch("/{doc_id}/assembly/components/{cid}")
def edit_component(doc_id: str, cid: str, body: ComponentEdit) -> dict:
    return _edit(doc_id, "ASMEDIT", lambda doc: _apply_edit(doc, cid, body))


@router.delete("/{doc_id}/assembly/components/{cid}")
def remove_component(doc_id: str, cid: str) -> dict:
    return _edit(doc_id, "ASMREMOVE", lambda doc: model.remove(doc, store.find_component(doc.drawing, cid)["id"]))


@router.post("/{doc_id}/assembly/components/{cid}/transform")
def transform(doc_id: str, cid: str, body: TransformBody) -> dict:
    spec = body.model_dump(exclude_none=True)
    relative, force = spec.pop("relative", False), spec.pop("force", False)
    value = spec.get("matrix") if list(spec) == ["matrix"] else spec
    return _edit(doc_id, "ASMMOVE", lambda doc: model.set_transform(doc, store.find_component(doc.drawing, cid)["id"], value, relative, force))


@router.post("/{doc_id}/assembly/components/{cid}/reload")
def reload_component(doc_id: str, cid: str, body: FindBody = FindBody()) -> dict:
    return _edit(doc_id, "ASMRELOAD", lambda doc: model.reload(doc, store.find_component(doc.drawing, cid)["id"], _folders(body.folder), body.deep, body.relative))


@router.post("/{doc_id}/assembly/components/{cid}/replace")
def replace_component(doc_id: str, cid: str, body: ReplaceBody) -> dict:
    return _edit(doc_id, "ASMREPLACE", lambda doc: model.replace(doc, store.find_component(doc.drawing, cid)["id"], body.path, body.relative))


@router.post("/{doc_id}/assembly/components/{cid}/find")
def find_component(doc_id: str, cid: str, body: FindBody = FindBody()) -> dict:
    return _edit(doc_id, "ASMFIND", lambda doc: model.find(doc, store.find_component(doc.drawing, cid)["id"], _folders(body.folder), body.deep, body.relink, body.relative))


@router.post("/{doc_id}/assembly/rebase")
def rebase(doc_id: str) -> dict:
    return _edit(doc_id, "ASMREBASE", model.rebase)


@router.get("/{doc_id}/assembly/patterns")
def list_patterns(doc_id: str) -> dict:
    return _read(doc_id, api.patterns_view)


@router.post("/{doc_id}/assembly/patterns")
def add_pattern(doc_id: str, body: PatternBody) -> dict:
    return _edit(doc_id, "ASMPATTERN", lambda doc: model.add_pattern(doc, body.kind, body.seed, body.params, body.label))


@router.patch("/{doc_id}/assembly/patterns/{pid}")
def edit_pattern(doc_id: str, pid: str, body: PatternEdit) -> dict:
    return _edit(doc_id, "ASMPATTERN", lambda doc: model.edit_pattern(doc, pid, body.params, body.label, body.skip, body.suppressed))


@router.delete("/{doc_id}/assembly/patterns/{pid}")
def delete_pattern(doc_id: str, pid: str) -> dict:
    return _edit(doc_id, "ASMPATTERN", lambda doc: model.delete_pattern(doc, pid))


@router.get("/{doc_id}/assembly/configs")
def list_configs(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: cfg.listing(doc.drawing))


@router.post("/{doc_id}/assembly/configs")
def create_config(doc_id: str, body: ConfigBody) -> dict:
    return _edit(doc_id, "ASMCONFIG", lambda doc: cfg.create(doc.drawing, body.name, body.description, body.suppress, body.visible, body.component_config, body.patterns, body.copy_from))


@router.put("/{doc_id}/assembly/configs/{name}")
def edit_config(doc_id: str, name: str, body: ConfigEdit) -> dict:
    return _edit(doc_id, "ASMCONFIG", lambda doc: cfg.update(doc.drawing, name, body.description, body.suppress, body.visible, body.component_config, body.patterns, body.new_name))


@router.delete("/{doc_id}/assembly/configs/{name}")
def delete_config(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "ASMCONFIG", lambda doc: cfg.delete(doc.drawing, name))


@router.post("/{doc_id}/assembly/configs/{name}/activate")
def activate_config(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "ASMCONFIG", lambda doc: cfg.activate(doc.drawing, name))


@router.put("/{doc_id}/assembly/settings")
def settings(doc_id: str, body: SettingsBody) -> dict:
    return _edit(doc_id, "ASMSEARCH", lambda doc: model.settings(doc, body.search_folders, body.search_order, body.embed_cache, body.lightweight))


@router.post("/{doc_id}/assembly/resolve")
def resolve(doc_id: str, body: ResolveBody = ResolveBody()) -> dict:
    return _read(doc_id, lambda doc: light.resolve(doc, body.components))


@router.post("/{doc_id}/assembly/lightweight")
def lightweight(doc_id: str, body: ResolveBody = ResolveBody()) -> dict:
    return _read(doc_id, lambda doc: light.lighten(doc, body.components))


@router.get("/{doc_id}/assembly/bom")
def get_bom(doc_id: str, mode: str = "indented", suppressed: bool = False) -> dict:
    return _read(doc_id, lambda doc: bom.build(doc, mode, suppressed))


@router.post("/{doc_id}/assembly/bom/export")
def export_bom(doc_id: str, body: ExportBody) -> dict:
    return _edit(doc_id, "ASMBOM", lambda doc: bom.export_csv(doc, body.path, body.mode, body.columns, body.include_suppressed))


@router.post("/{doc_id}/assembly/bom/renumber")
def renumber(doc_id: str) -> dict:
    return _edit(doc_id, "ASMBOM", bom.renumber)


@router.get("/{doc_id}/docprops")
def get_props(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"properties": P.get(doc.drawing)})


@router.put("/{doc_id}/docprops")
def put_props(doc_id: str, body: PropsBody) -> dict:
    return _edit(doc_id, "PARTPROPS", lambda doc: {"properties": P.put(doc.drawing, body.values, body.remove)})
