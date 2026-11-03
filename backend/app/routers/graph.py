import copy
import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.core import outputs
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.graph import edits, model, registry, session, store
from app.graph import tree as T

router = APIRouter(tags=["graph"])
LIVE: dict = {}
LIVE_WINDOW = 3.0


class CreateBody(BaseModel):
    name: str = ""
    definition: Optional[dict[str, Any]] = None


class PutBody(BaseModel):
    definition: dict[str, Any]
    label: Optional[str] = None
    live: bool = False
    delay: float = 0.0
    solve: bool = True


class OpsBody(BaseModel):
    ops: list[dict[str, Any]]
    live: bool = False
    delay: float = 0.0
    solve: bool = True


class SolveBody(BaseModel):
    all: bool = False
    wait: bool = True
    delay: float = 0.0
    timeout: float = 600.0


class FileBody(BaseModel):
    path: str
    name: str = ""
    solve: bool = True


class BakeBody(BaseModel):
    options: dict[str, Any] = {}
    nodes: Optional[list[str]] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, model.GraphRefused):
        raise HTTPException(409 if err.code in ("cycle", "selfloop", "newer") else 400, {"message": err.message, "code": err.code, "path": err.path})
    raise HTTPException(400, str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


FAILURES = (store.StoreError, model.GraphError, edits.EditError, KeyError, ValueError, T.TreeError, TypeError, OverflowError, RecursionError)


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                return doc, fn(doc)
        except FAILURES as err:
            _fail(err)
        except CommandFailed as err:
            raise HTTPException(409, str(err))


def _read(doc_id: str):
    return _doc(doc_id)


def _summary(rec: dict) -> dict:
    d = rec["definition"]
    return {"id": rec["id"], "label": rec["label"], "nodes": len(d.get("nodes") or []), "wires": len(d.get("wires") or []), "groups": len(d.get("groups") or []), "version": d.get("version"), "readonly": model.version_tuple(d.get("version"))[0] > model.version_tuple(model.VERSION)[0]}


def _full(doc, gid: str) -> dict:
    sess = session.of(doc, gid)
    rec = store.need(doc.drawing, gid)
    g = sess.graph
    return {"id": rec["id"], "label": rec["label"], "definition": copy.deepcopy(rec["definition"]), "readonly": g.readonly, "problems": list(g.problems), "rev": g.rev, "busy": sess.busy()}


def _merge_live(doc, gid: str, live: bool) -> None:
    key = (doc.id, gid)
    now = time.monotonic()
    steps = doc.undo.steps
    prev = LIVE.get(key)
    if steps:
        top = steps[-1]
        if prev is not None and len(steps) >= 2 and prev[0] is steps[-2] and now - prev[1] <= LIVE_WINDOW and top.label == prev[0].label:
            keep = steps[-2]
            for k, v in top.before.items():
                keep.before.setdefault(k, v)
            keep.state_after = top.state_after
            steps.pop()
            top = keep
        if live:
            LIVE[key] = (top, now)
        else:
            LIVE.pop(key, None)


def _after(doc, gid: str, solve: bool, delay: float, live: bool) -> dict:
    _merge_live(doc, gid, live)
    sess = session.of(doc, gid)
    expired = sess.sync()
    session.publish(sess, "definition", {"expired": expired, "live": live})
    if solve:
        sess.request(delay)
    return {"expired": expired, "busy": sess.busy()}


@router.get("/graph/catalogue")
def catalogue() -> dict:
    return {"revision": registry.revision(), "nodes": registry.catalogue()}


@router.get("/docs/{doc_id}/graphs")
def list_graphs(doc_id: str) -> dict:
    doc = _read(doc_id)
    with doc.lock:
        return {"graphs": [_summary(r) for r in store.records(doc.drawing)]}


@router.post("/docs/{doc_id}/graphs")
def create_graph(doc_id: str, body: CreateBody) -> dict:
    doc, rec = _edit(doc_id, "GRAPHNEW", lambda d: store.create(d.drawing, body.name, body.definition))
    try:
        out = _full(doc, rec["id"])
    except FAILURES as err:
        _fail(err)
    return out


@router.post("/docs/{doc_id}/graphs/import")
def import_graph(doc_id: str, body: FileBody) -> dict:
    doc, rec = _edit(doc_id, "GRAPHIMPORT", lambda d: store.import_file(d.drawing, body.path, body.name))
    out = _full(doc, rec["id"])
    if body.solve:
        session.of(doc, rec["id"]).request(0)
    return out


@router.get("/docs/{doc_id}/graphs/{gid}")
def get_graph(doc_id: str, gid: str) -> dict:
    doc = _read(doc_id)
    try:
        with doc.lock:
            return _full(doc, gid)
    except FAILURES as err:
        _fail(err)


@router.put("/docs/{doc_id}/graphs/{gid}")
def put_graph(doc_id: str, gid: str, body: PutBody) -> dict:
    doc, rec = _edit(doc_id, "GRAPHEDIT", lambda d: store.update(d.drawing, gid, body.definition, body.label))
    out = _after(doc, rec["id"], body.solve, body.delay, body.live)
    out["id"] = rec["id"]
    return out


@router.patch("/docs/{doc_id}/graphs/{gid}")
def patch_graph(doc_id: str, gid: str, body: OpsBody) -> dict:
    def run(d):
        rec = store.need(d.drawing, gid)
        g = model.Graph.from_definition(copy.deepcopy(rec["definition"]), rec["id"])
        if g.readonly:
            raise model.GraphRefused("This graph was written by a newer version of formCAD and cannot be changed here.", "newer")
        result = edits.apply(g, body.ops)
        store.update(d.drawing, gid, g.to_definition())
        return rec["id"], result

    doc, (rid, result) = _edit(doc_id, "GRAPHEDIT", run)
    out = _after(doc, rid, body.solve, body.delay, body.live)
    out["id"] = rid
    out["results"] = result
    return out


@router.delete("/docs/{doc_id}/graphs/{gid}")
def delete_graph(doc_id: str, gid: str) -> dict:
    def run(d):
        rec = store.need(d.drawing, gid)
        store.delete(d.drawing, gid)
        return rec["id"]

    doc, rid = _edit(doc_id, "GRAPHDELETE", run)
    with session.LOCK:
        gone = session.SESSIONS.pop((doc.id, rid), None)
    if gone is not None:
        gone.stop()
    return {"deleted": rid}


@router.post("/docs/{doc_id}/graphs/{gid}/solve")
def solve_graph(doc_id: str, gid: str, body: SolveBody) -> dict:
    doc = _read(doc_id)
    try:
        sess = session.of(doc, gid)
    except FAILURES as err:
        _fail(err)
    sess.request(body.delay, body.all)
    if body.wait:
        if not sess.wait(body.timeout):
            raise HTTPException(504, "The solve did not finish in time; it is still running.")
    out = sess.state()
    out["id"] = sess.gid
    return out


@router.post("/docs/{doc_id}/graphs/{gid}/cancel")
def cancel_graph(doc_id: str, gid: str) -> dict:
    doc = _read(doc_id)
    try:
        sess = session.of(doc, gid)
    except FAILURES as err:
        _fail(err)
    sess.cancel()
    sess.wait(30.0)
    return {"id": sess.gid, "busy": sess.busy()}


@router.get("/docs/{doc_id}/graphs/{gid}/state")
def graph_state(doc_id: str, gid: str, first: int = 6) -> dict:
    doc = _read(doc_id)
    try:
        sess = session.of(doc, gid)
    except FAILURES as err:
        _fail(err)
    return sess.state(max(0, min(first, 50)))


@router.get("/docs/{doc_id}/graphs/{gid}/tree/{node}/{port}")
def graph_tree(doc_id: str, gid: str, node: str, port: str, offset: int = 0, limit: int = 50) -> dict:
    doc = _read(doc_id)
    try:
        sess = session.of(doc, gid)
    except FAILURES as err:
        _fail(err)
    g = sess.graph
    with g.lock:
        n = g.nodes.get(node)
        if n is None:
            raise HTTPException(404, "There is no node %s." % node)
        p = n.port(port, "out")
        if p is None:
            raise HTTPException(404, "Node %s has no output %s." % (node, port))
        tree = n.outputs.get(p.name) or T.DataTree()
        branches = tree.items()
        offset = max(0, offset)
        limit = max(1, min(limit, 500))
        page = [{"path": str(path), "count": len(items), "items": [T.format_item(v) for v in items[:200]]} for path, items in branches[offset : offset + limit]]
        return {"node": node, "port": p.name, "state": n.state, "branches": tree.count, "items": tree.item_count, "offset": offset, "limit": limit, "page": page}


@router.get("/docs/{doc_id}/graphs/{gid}/preview")
def graph_preview(doc_id: str, gid: str) -> Response:
    doc = _read(doc_id)
    try:
        from app.graph import preview
    except ImportError:
        raise HTTPException(501, "The graph preview is not part of this build.")
    try:
        sess = session.of(doc, gid)
    except FAILURES as err:
        _fail(err)
    data = preview.scene(doc, sess.graph)
    return Response(content=data, media_type="application/octet-stream")


@router.post("/docs/{doc_id}/graphs/{gid}/bake")
def graph_bake(doc_id: str, gid: str, body: BakeBody) -> dict:
    doc = _read(doc_id)
    try:
        from app.graph import bake
    except ImportError:
        raise HTTPException(501, "Baking is not part of this build.")
    try:
        sess = session.of(doc, gid)
    except FAILURES as err:
        _fail(err)
    if sess.busy():
        sess.wait(600.0)
    sess.request(0)
    sess.wait(600.0)
    return _edit(doc_id, "GRAPHBAKE", lambda d: bake.bake(d, sess.graph, body.model_dump()))[1]


@router.post("/docs/{doc_id}/graphs/{gid}/import")
def replace_from_file(doc_id: str, gid: str, body: FileBody) -> dict:
    def run(d):
        data = store.read_file(body.path)
        return store.update(d.drawing, gid, data, body.name or None)

    doc, rec = _edit(doc_id, "GRAPHIMPORT", run)
    out = _after(doc, rec["id"], body.solve, 0.0, False)
    out["id"] = rec["id"]
    return out


@router.post("/docs/{doc_id}/graphs/{gid}/export")
def export_graph(doc_id: str, gid: str, body: FileBody) -> dict:
    doc = _read(doc_id)
    try:
        path = outputs.checked(body.path, (store.EXT,), store.EXT)
    except outputs.OutputRefused as err:
        raise HTTPException(400, str(err))
    with doc.lock:
        try:
            defn = store.export_definition(doc.drawing, gid)
            store.write_file(path, defn)
        except FAILURES as err:
            _fail(err)
        except OSError as err:
            raise HTTPException(400, "The file could not be written: %s" % err)
    return {"path": path, "bytes": len(store.dumps(defn))}
