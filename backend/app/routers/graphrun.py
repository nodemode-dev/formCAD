from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.doc.service import DocumentFault, service
from app.graph import optimize, runner
from app.graph import plugins as graph_plugins

router = APIRouter(tags=["graph-run"])
STATUS = {"usage": 400, "schema": 400, "missing": 422, "timeout": 408, "cancelled": 409, "errors": 422}


class RunBody(BaseModel):
    graph: Optional[dict[str, Any]] = None
    graph_path: str = ""
    inputs: dict[str, Any] = {}
    seed: Optional[int] = None
    timeout_s: float = runner.DEFAULT_TIMEOUT
    document: str = ""
    doc_path: str = ""
    bake_path: str = ""
    strict: bool = False


class IoBody(BaseModel):
    graph: Optional[dict[str, Any]] = None
    graph_path: str = ""


class OptimizeBody(BaseModel):
    genes: list[str]
    fitness_node: str
    fitness_port: str = ""
    direction: str = "minimise"
    method: str = "evolution"
    population: Optional[int] = None
    generations: Optional[int] = None
    budget: Optional[int] = None
    seed: int = 0
    time_limit: float = 0.0
    stagnation: int = 0
    commit: bool = True


def fail(err) -> None:
    if isinstance(err, runner.RunError):
        detail = {"message": err.message, "code": err.code}
        detail.update({k: v for k, v in err.extra.items() if k == "missing"})
        raise HTTPException(STATUS.get(err.code, 400), detail)
    raise HTTPException(400, str(err))


def definition_of(body) -> dict:
    if body.graph is not None:
        return body.graph
    if body.graph_path:
        return runner.read_graph_file(body.graph_path)
    raise runner.RunError("Give graph (a definition) or graph_path (a .graph file).", "usage")


@router.post("/graph/run")
def run_graph(body: RunBody) -> dict:
    if not runner.acquire():
        raise HTTPException(429, "Too many graph runs are going. Try again shortly.")
    try:
        graph_plugins.load_trusted()
        defn = definition_of(body)
        if not body.document:
            return run_inline(defn, dict(body.inputs), body)
        if body.doc_path or body.bake_path:
            raise runner.RunError("Give document (an open document, read only) or doc_path and bake_path, not both.", "usage")
        doc = doc_of(body.document)
        return runner.run(defn, dict(body.inputs), doc.drawing, body.seed, body.timeout_s, None, body.strict)
    except runner.RunError as err:
        fail(err)
    finally:
        runner.release()


def run_inline(defn: dict, inputs: dict, body: RunBody) -> dict:
    return runner.run_request(defn, inputs, body.doc_path, body.bake_path, body.seed, body.timeout_s, None, body.strict)


@router.post("/graph/io")
def graph_io(body: IoBody) -> dict:
    try:
        graph_plugins.load_trusted()
        return runner.describe(runner.load_graph(definition_of(body)))
    except runner.RunError as err:
        fail(err)


@router.get("/graph/libraries")
def libraries() -> dict:
    return {"libraries": graph_plugins.listing()}


def doc_of(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


@router.post("/docs/{doc_id}/graphs/{gid}/optimize")
def start_optimize(doc_id: str, gid: str, body: OptimizeBody) -> dict:
    doc = doc_of(doc_id)
    spec = body.model_dump()
    try:
        job = optimize.start(doc, gid, spec, body.commit)
    except (optimize.OptimizeError, ValueError, KeyError) as err:
        raise HTTPException(400, str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))
    return job.view()


@router.get("/docs/{doc_id}/graphs/{gid}/optimize")
def list_optimize(doc_id: str, gid: str) -> dict:
    doc = doc_of(doc_id)
    return {"jobs": optimize.listing(doc.id, gid)}


@router.get("/docs/{doc_id}/graphs/{gid}/optimize/{job_id}")
def get_optimize(doc_id: str, gid: str, job_id: str) -> dict:
    doc = doc_of(doc_id)
    job = optimize.get(job_id)
    if job is None or job.doc_id != doc.id:
        raise HTTPException(404, "No such optimizer run.")
    return job.view()


@router.post("/docs/{doc_id}/graphs/{gid}/optimize/{job_id}/cancel")
def cancel_optimize(doc_id: str, gid: str, job_id: str) -> dict:
    doc = doc_of(doc_id)
    job = optimize.get(job_id)
    if job is None or job.doc_id != doc.id:
        raise HTTPException(404, "No such optimizer run.")
    optimize.cancel(job_id)
    return job.view()
