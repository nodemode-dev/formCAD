import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.render import appearances, decals, environments, jobs, settings, targets

router = APIRouter(tags=["render"])


class AppearanceIn(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    base_color: Optional[str] = None
    metallic: Optional[float] = None
    roughness: Optional[float] = None
    ior: Optional[float] = None
    transmission: Optional[float] = None
    thickness: Optional[float] = None
    clearcoat: Optional[float] = None
    clearcoat_roughness: Optional[float] = None
    sheen: Optional[float] = None
    sheen_roughness: Optional[float] = None
    sheen_color: Optional[str] = None
    emissive: Optional[str] = None
    emissive_intensity: Optional[float] = None
    opacity: Optional[float] = None
    attenuation_color: Optional[str] = None
    attenuation_distance: Optional[float] = None
    provenance: Optional[str] = None
    sources: Optional[dict[str, str]] = None


class AssignIn(BaseModel):
    keys: list[str]
    appearance: Optional[str] = None


class JobIn(BaseModel):
    backend: str = "page"
    out: str = ""
    view: Optional[dict[str, Any]] = None
    engine: str = "path"
    origin: str = ""
    timeout: int = 0
    output: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    environment: Optional[dict[str, Any]] = None
    ground: Optional[dict[str, Any]] = None
    camera: Optional[dict[str, Any]] = None


GUARDED = (appearances.AppearanceError, environments.EnvironmentError_, settings.SettingsError, targets.TargetError, decals.DecalError, jobs.JobError, CommandFailed, ValueError, KeyError)


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
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
    with doc.lock:
        try:
            return fn(doc)
        except GUARDED as err:
            _fail(err)


def _job(job_id: str):
    try:
        return jobs.get(job_id)
    except jobs.JobError as err:
        raise HTTPException(404, str(err))


@router.get("/render/library")
def get_library() -> dict:
    return appearances.library()


@router.post("/render/library")
def add_appearance(body: AppearanceIn) -> dict:
    try:
        return appearances.add_user(body.model_dump(exclude_none=True))
    except GUARDED as err:
        _fail(err)


@router.put("/render/library/{name}")
def edit_appearance(name: str, body: AppearanceIn) -> dict:
    try:
        return appearances.update_user(name, body.model_dump(exclude_none=True))
    except GUARDED as err:
        _fail(err)


@router.delete("/render/library/{name}")
def remove_appearance(name: str) -> dict:
    try:
        return appearances.delete_user(name)
    except GUARDED as err:
        _fail(err)


@router.get("/render/environments")
def get_environments() -> dict:
    return environments.listing()


@router.get("/render/environments/{eid}/{res}")
def get_environment_file(eid: str, res: str) -> Response:
    try:
        data = environments.read_bytes(eid, res)
    except GUARDED as err:
        raise HTTPException(404, str(err))
    return Response(content=data, media_type="application/octet-stream", headers={"Cache-Control": "private, max-age=3600"})


@router.post("/render/environments/{eid}/{res}/download")
def download_environment(eid: str, res: str) -> dict:
    try:
        return environments.download(eid, res)
    except GUARDED as err:
        _fail(err)


@router.get("/render/limits")
def get_limits() -> dict:
    return settings.limits()


@router.get("/docs/{doc_id}/render/settings")
def get_settings(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"settings": settings.read(doc.drawing), "limits": settings.limits()})


@router.put("/docs/{doc_id}/render/settings")
def put_settings(doc_id: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "RENDERSETTINGS", lambda d: {"settings": settings.write(d, body), "limits": settings.limits()})


@router.get("/docs/{doc_id}/render/bodies")
def get_bodies(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"bodies": targets.rows(doc), "assignments": targets.assignments(doc.drawing)})


@router.put("/docs/{doc_id}/render/assign")
def put_assign(doc_id: str, body: AssignIn) -> dict:
    return _edit(doc_id, "RENDERASSIGN", lambda d: targets.assign(d, body.keys, body.appearance))


@router.get("/docs/{doc_id}/render/decals")
def get_decals(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"decals": decals.listing(doc.drawing)})


@router.post("/docs/{doc_id}/render/decals")
def add_decal(doc_id: str, body: dict[str, Any]) -> dict:
    name = str(body.get("name") or "")
    return _edit(doc_id, "RENDERDECAL", lambda d: decals.add(d, name, body))


@router.put("/docs/{doc_id}/render/decals/{name}")
def edit_decal(doc_id: str, name: str, body: dict[str, Any]) -> dict:
    return _edit(doc_id, "RENDERDECAL", lambda d: decals.update(d, name, body))


@router.delete("/docs/{doc_id}/render/decals/{name}")
def remove_decal(doc_id: str, name: str) -> dict:
    return _edit(doc_id, "RENDERDECAL", lambda d: decals.remove(d, name))


@router.post("/docs/{doc_id}/renderjobs")
def create_job(doc_id: str, body: JobIn, request: Request) -> dict:
    doc = _doc(doc_id)
    try:
        with doc.lock:
            job = jobs.create(doc, body.backend, body.model_dump(exclude_none=True), str(request.base_url).rstrip("/"))
    except GUARDED as err:
        _fail(err)
    return job.brief()


@router.get("/render/jobs")
def list_jobs() -> dict:
    return {"jobs": [j.brief() for j in sorted(jobs.JOBS.values(), key=lambda j: j.created, reverse=True)]}


@router.get("/render/jobs/{job_id}")
def get_job(job_id: str, spec: bool = False) -> dict:
    job = _job(job_id)
    out = job.brief()
    if spec:
        out["spec"] = jobs.spec_for_page(job)
    return out


@router.post("/render/jobs/{job_id}/progress")
def post_progress(job_id: str, body: dict[str, Any]) -> dict:
    job = _job(job_id)
    jobs.progress(job, body)
    return {"state": job.state, "cancel": job.cancel}


@router.post("/render/jobs/{job_id}/result")
async def post_result(job_id: str, request: Request, stats: str = "") -> dict:
    job = _job(job_id)
    size = request.headers.get("content-length")
    if size and size.isdigit() and int(size) > jobs.MAX_RESULT:
        raise HTTPException(413, "The image is larger than the limit.")
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > jobs.MAX_RESULT:
            raise HTTPException(413, "The image is larger than the limit.")
    try:
        info = json.loads(stats) if stats else {}
        path = jobs.store_result(job, bytes(data), info if isinstance(info, dict) else {})
    except (jobs.JobError, ValueError) as err:
        raise HTTPException(400, str(err))
    return {"path": path, **job.brief()}


@router.get("/render/jobs/{job_id}/result")
def get_result(job_id: str) -> Response:
    job = _job(job_id)
    if job.state != "done" or not job.result_path:
        raise HTTPException(404, "This job has no image yet.")
    try:
        with open(job.result_path, "rb") as fh:
            data = fh.read()
    except OSError:
        raise HTTPException(404, "The image file is gone.")
    return Response(content=data, media_type="image/png")


@router.post("/render/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    job = _job(job_id)
    jobs.cancel(job)
    return job.brief()
