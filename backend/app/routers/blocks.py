from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc import attribs, battman, blockdefs, dataextract, purge
from app.doc.entities import Insert
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["blocks"])


class DefineBody(BaseModel):
    name: str
    handles: list[int]
    base: list[float] = [0.0, 0.0, 0.0]
    description: str = ""
    annotative: bool = False
    explodable: bool = True
    redefine: bool = False


class PurgeBody(BaseModel):
    type: str = "all"
    name: str = "*"


class ValuesBody(BaseModel):
    values: dict[str, str]


class AttributeOp(BaseModel):
    op: str
    tag: Optional[str] = None
    tags: Optional[list[str]] = None
    changes: Optional[dict[str, Any]] = None
    sync: bool = True


class ExtractBody(BaseModel):
    blocks: str = "*"
    combine: bool = True
    file: Optional[str] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _idle(doc) -> None:
    if doc.get_runner().run is not None:
        raise HTTPException(409, "A command is running; finish it first.")


def _record(d, name: str) -> dict:
    rec = blockdefs.lookup(d, name)
    if rec is None:
        raise HTTPException(404, "No such block.")
    return rec


@router.get("/{doc_id}/blocks")
def list_blocks(doc_id: str, anonymous: bool = False) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return {"blocks": blockdefs.listing(doc.drawing, anonymous)}


@router.get("/{doc_id}/blocks/{name}")
def get_block(doc_id: str, name: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        d = doc.drawing
        rec = _record(d, name)
        kids = blockdefs.children(d, rec["name"])
        return {"block": dict(rec), "objects": [e.handle for e in kids], "attributes": battman.listing(d, rec["name"]), "references": [e.handle for e in blockdefs.references(d, rec["name"])]}


@router.post("/{doc_id}/blocks")
def define_block(doc_id: str, body: DefineBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        _idle(doc)
        d = doc.drawing
        missing = [h for h in body.handles if d.get(h) is None]
        if missing or not body.handles:
            raise HTTPException(400, "No objects selected.")
        try:
            with doc.transaction("BLOCK"):
                ents = blockdefs.clones_of(d, body.handles)
                rec = blockdefs.define(d, body.name, ents, body.base, body.description, body.annotative, body.explodable, body.redefine)
        except blockdefs.BlockError as err:
            raise HTTPException(400, str(err))
        return {"block": dict(rec)}


@router.post("/{doc_id}/blocks/purge")
def purge_blocks(doc_id: str, body: PurgeBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        _idle(doc)
        try:
            cat = purge.canonical(body.type)
            with doc.transaction("PURGE"):
                res = purge.run(doc.drawing, cat, body.name or "*")
        except (purge.PurgeError, blockdefs.BlockError) as err:
            raise HTTPException(400, str(err))
        return {"purged": res["purged"], "count": res["count"], "lines": res["lines"]}


def _insert(doc, handle: int) -> Insert:
    ent = doc.drawing.get(handle)
    if not isinstance(ent, Insert):
        raise HTTPException(404, "No such block reference.")
    return ent


@router.get("/{doc_id}/inserts/{handle}/attributes")
def get_attributes(doc_id: str, handle: int) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        ins = _insert(doc, handle)
        d = doc.drawing
        defs = {a.tag.casefold(): a for a in attribs.definitions(d, ins.block)}
        rows = []
        for att in ins.attributes or []:
            adef = defs.get(att["tag"].casefold())
            rows.append({"tag": att["tag"], "value": att.get("value", ""), "prompt": adef.prompt if adef else "", "invisible": bool(adef and attribs.mode_of(adef, "invisible")), "lock_position": bool(att.get("lock_position")), "layer": att.get("layer"), "color": att.get("color")})
        constants = [{"tag": a.tag, "value": a.default} for a in attribs.constant_defs(d, ins.block)]
        return {"block": ins.block, "attributes": rows, "constants": constants}


@router.put("/{doc_id}/inserts/{handle}/attributes")
def put_attributes(doc_id: str, handle: int, body: ValuesBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        _idle(doc)
        ins = _insert(doc, handle)
        if doc.drawing.layer_locked(ins.layer):
            raise HTTPException(409, "The block reference is on a locked layer.")
        try:
            with doc.transaction("ATTEDIT"):
                live = doc.drawing.modify(handle)
                for tag, val in body.values.items():
                    att = attribs.find(live, tag)
                    if att is None:
                        raise HTTPException(400, 'Block reference has no attribute "%s".' % tag)
                    att["value"] = attribs.check_value(val)
                attribs.refresh_cache(doc.drawing, live)
        except attribs.AttribError as err:
            raise HTTPException(400, str(err))
        return {"changed": len(body.values)}


@router.get("/{doc_id}/blocks/{name}/attributes")
def get_definitions(doc_id: str, name: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        rec = _record(doc.drawing, name)
        return {"block": rec["name"], "attributes": battman.listing(doc.drawing, rec["name"])}


@router.post("/{doc_id}/blocks/{name}/attributes")
def edit_definitions(doc_id: str, name: str, body: AttributeOp) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        _idle(doc)
        d = doc.drawing
        rec = _record(d, name)
        n = rec["name"]
        try:
            with doc.transaction("BATTMAN"):
                if body.op == "edit":
                    res = battman.edit(d, n, body.tag or "", body.changes or {}, body.sync)
                elif body.op == "remove":
                    res = battman.remove(d, n, body.tag or "", body.sync)
                elif body.op == "order":
                    res = battman.reorder(d, n, body.tags or [], body.sync)
                elif body.op in ("up", "down"):
                    res = battman.move(d, n, body.tag or "", -1 if body.op == "up" else 1, body.sync)
                elif body.op == "sync":
                    res = {"synchronized": battman.sync(d, n)}
                else:
                    raise HTTPException(400, "Unknown operation.")
        except (battman.BattmanError, attribs.AttribError) as err:
            raise HTTPException(400, str(err))
        return {**res, "attributes": battman.listing(d, n)}


@router.post("/{doc_id}/dataextract")
def extract_data(doc_id: str, body: ExtractBody) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        try:
            res = dataextract.extract(doc.drawing, body.blocks or "*", body.combine, doc.current_space)
            if body.file:
                res["file"] = dataextract.write_file(body.file, res["columns"], res["rows"])
        except dataextract.ExtractError as err:
            raise HTTPException(400, str(err))
        return res
