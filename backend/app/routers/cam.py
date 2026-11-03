from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cam import export, feeds, gen, jobs, limits, model, post, registry, store, tools
from app.cam import hook as _hook
from app.cam.limits import CamError
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["cam"])
GUARDED = (CamError, CommandFailed, ValueError, KeyError)


class Body(BaseModel):
    model_config = {"extra": "allow"}


class GenerateIn(BaseModel):
    setup: Optional[str] = None
    ops: Optional[list[str]] = None
    wait: bool = False


class ExportIn(BaseModel):
    out: str
    post: str = "linuxcnc"
    setup: Optional[str] = None
    ops: Optional[list[str]] = None
    options: Optional[dict[str, Any]] = None


class PreviewIn(BaseModel):
    post: str = "linuxcnc"
    setup: Optional[str] = None
    ops: Optional[list[str]] = None
    options: Optional[dict[str, Any]] = None


class MoveIn(BaseModel):
    index: int


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    if isinstance(err, KeyError):
        raise HTTPException(404, str(err.args[0]) if err.args else "Not found.")
    raise HTTPException(400, str(err))


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
    try:
        return fn(doc)
    except GUARDED as err:
        _fail(err)


@router.get("/cam/ops")
def get_ops() -> dict:
    return {"ops": registry.listing(), "tool_kinds": list(tools.KINDS)}


@router.get("/cam/limits")
def get_limits() -> dict:
    return limits.get()


@router.get("/cam/posts")
def get_posts() -> dict:
    return {"posts": post.list_posts()}


@router.get("/cam/posts/{pid}")
def get_post(pid: str) -> dict:
    try:
        return post.load_raw(pid)
    except GUARDED as err:
        raise HTTPException(404, str(err))


@router.put("/cam/posts/{pid}")
def put_post(pid: str, body: Body) -> dict:
    spec = dict(body.model_dump())
    spec["id"] = pid
    try:
        return post.save_user(spec)
    except GUARDED as err:
        _fail(err)


@router.delete("/cam/posts/{pid}")
def delete_post(pid: str) -> dict:
    try:
        post.delete_user(pid)
    except GUARDED as err:
        _fail(err)
    return {"ok": True}


@router.get("/cam/tools")
def get_tools() -> dict:
    try:
        return {"tools": tools.load_all(), "kinds": list(tools.KINDS)}
    except GUARDED as err:
        _fail(err)


@router.post("/cam/tools")
def add_tool(body: Body) -> dict:
    try:
        return tools.add(body.model_dump())
    except GUARDED as err:
        _fail(err)


@router.put("/cam/tools/{tid}")
def edit_tool(tid: str, body: Body) -> dict:
    try:
        return tools.update(tid, body.model_dump())
    except GUARDED as err:
        _fail(err)


@router.delete("/cam/tools/{tid}")
def delete_tool(tid: str) -> dict:
    try:
        tools.remove(tid)
    except GUARDED as err:
        _fail(err)
    return {"ok": True}


@router.post("/cam/feeds")
def calc_feeds(body: Body) -> dict:
    try:
        return feeds.calculate(body.model_dump())
    except GUARDED + (TypeError,) as err:
        _fail(err)


@router.get("/docs/{doc_id}/cam")
def get_cam(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return store.view(doc)


@router.post("/docs/{doc_id}/cam/setups")
def add_setup(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "CAM SETUP", lambda d: store.add_setup(d, body.model_dump()))


@router.put("/docs/{doc_id}/cam/setups/{sid}")
def edit_setup(doc_id: str, sid: str, body: Body) -> dict:
    return _edit(doc_id, "CAM SETUP", lambda d: store.update_setup(d, sid, body.model_dump()))


@router.delete("/docs/{doc_id}/cam/setups/{sid}")
def delete_setup(doc_id: str, sid: str) -> dict:
    out = _edit(doc_id, "CAM DELETE SETUP", lambda d: store.delete_setup(d, sid))
    for oid in out:
        gen.drop_cache(doc_id, oid)
    return {"removed": out}


@router.post("/docs/{doc_id}/cam/tools")
def import_tool(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "CAM TOOL", lambda d: store.import_tool(d, body.model_dump()))


@router.delete("/docs/{doc_id}/cam/tools/{number}")
def drop_tool(doc_id: str, number: int) -> dict:
    _edit(doc_id, "CAM TOOL", lambda d: store.delete_tool(d, number))
    return {"ok": True}


@router.post("/docs/{doc_id}/cam/ops")
def add_op(doc_id: str, body: Body) -> dict:
    return _edit(doc_id, "CAM OPERATION", lambda d: store.add_op(d, body.model_dump()))


@router.put("/docs/{doc_id}/cam/ops/{oid}")
def edit_op(doc_id: str, oid: str, body: Body) -> dict:
    out = _edit(doc_id, "CAM OPERATION", lambda d: store.update_op(d, oid, body.model_dump()))
    return out


@router.delete("/docs/{doc_id}/cam/ops/{oid}")
def delete_op(doc_id: str, oid: str) -> dict:
    _edit(doc_id, "CAM DELETE OPERATION", lambda d: store.delete_op(d, oid))
    gen.drop_cache(doc_id, oid)
    return {"ok": True}


@router.post("/docs/{doc_id}/cam/ops/{oid}/move")
def move_op(doc_id: str, oid: str, body: MoveIn) -> dict:
    return _edit(doc_id, "CAM REORDER", lambda d: store.move_op(d, oid, body.index))


@router.post("/docs/{doc_id}/cam/generate")
def generate(doc_id: str, body: GenerateIn) -> dict:
    doc = _doc(doc_id)
    try:
        with doc.lock:
            ids = jobs.ops_for(doc, body.setup, body.ops)
        job = jobs.start(doc, ids, body.wait)
    except GUARDED as err:
        _fail(err)
    return job.view()


@router.get("/docs/{doc_id}/cam/jobs")
def list_jobs(doc_id: str) -> dict:
    return {"jobs": jobs.listing(doc_id)}


@router.get("/docs/{doc_id}/cam/jobs/{jid}")
def get_job(doc_id: str, jid: str) -> dict:
    job = jobs.get(jid)
    if job is None or job.doc_id != doc_id:
        raise HTTPException(404, "There is no job %s." % jid)
    return job.view()


@router.post("/docs/{doc_id}/cam/jobs/{jid}/cancel")
def cancel_job(doc_id: str, jid: str) -> dict:
    job = jobs.get(jid)
    if job is None or job.doc_id != doc_id:
        raise HTTPException(404, "There is no job %s." % jid)
    jobs.cancel(jid)
    return {"ok": True}


@router.get("/docs/{doc_id}/cam/ops/{oid}/toolpath")
def get_toolpath(doc_id: str, oid: str, flat: bool = False, tol: float = 0.01, regenerate: bool = True) -> dict:
    def run(doc):
        path = gen.toolpath_of(doc, oid, regenerate)
        out = {"op": oid, "meta": path.meta, "summary": path.summary()}
        if flat:
            out["segments"] = path.flatten(max(tol, 0.001))
        else:
            if len(path.moves) > 400000 and limits.limited():
                raise CamError("The toolpath is too large to return to a macro or agent.")
            out["moves"] = path.to_json()
        return out

    return _read(doc_id, run)


@router.get("/docs/{doc_id}/cam/time")
def get_time(doc_id: str, setup: Optional[str] = None) -> dict:
    return _read(doc_id, lambda doc: export.time_report(doc, setup))


@router.post("/docs/{doc_id}/cam/preview")
def preview(doc_id: str, body: PreviewIn) -> dict:
    return _read(doc_id, lambda doc: export.post_text(doc, body.post, body.setup, body.ops, body.options))


@router.post("/docs/{doc_id}/cam/export")
def export_file(doc_id: str, body: ExportIn) -> dict:
    return _read(doc_id, lambda doc: export.write_file(doc, body.out, body.post, body.setup, body.ops, body.options))
