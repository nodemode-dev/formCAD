from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.cmd import aliasfile, macro
from app.doc import compare as C
from app.doc import queries as Q
from app.doc import savecheck, templates
from app.doc.service import DocumentFault, service

router = APIRouter(tags=["filetools"])


class Free(BaseModel):
    model_config = {"extra": "allow"}


class AliasBody(BaseModel):
    alias: Optional[str] = None
    command: Optional[str] = None
    path: Optional[str] = None
    aliases: Optional[dict[str, str]] = None


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _run(doc_id: str, name: str, args: dict | None = None, quiet_errors: bool = False) -> dict:
    doc = _doc(doc_id)
    state = doc.get_runner().run_command(name, args or {})
    if state.get("error") and not quiet_errors:
        raise HTTPException(400, state["error"])
    return {"result": state.get("result"), "state": state}


def _alias(fn, *a):
    try:
        return fn(*a)
    except aliasfile.AliasError as err:
        raise HTTPException(400, str(err))


@router.get("/aliases")
def aliases_list() -> dict:
    return aliasfile.listing()


@router.get("/aliases/suggest")
def aliases_suggest(text: str = "") -> dict:
    return {"items": aliasfile.suggest(text)}


@router.put("/aliases")
def aliases_replace(body: AliasBody) -> dict:
    return _alias(aliasfile.replace_all, body.aliases or {})


@router.post("/aliases/set")
def aliases_set(body: AliasBody) -> dict:
    return _alias(aliasfile.set_one, body.alias or "", body.command or "")


@router.post("/aliases/remove")
def aliases_remove(body: AliasBody) -> dict:
    return _alias(aliasfile.remove_one, body.alias or "")


@router.post("/aliases/load")
def aliases_load(body: AliasBody) -> dict:
    return _alias(aliasfile.load, body.path or "")


@router.post("/aliases/reinit")
def aliases_reinit() -> dict:
    return _alias(aliasfile.reinit)


@router.post("/aliases/clear")
def aliases_clear() -> dict:
    return aliasfile.clear()


@router.post("/aliases/save")
def aliases_save(body: AliasBody) -> dict:
    return {"path": _alias(aliasfile.save, body.path or "")}


@router.get("/templates")
def templates_list() -> dict:
    return {"items": templates.listing(), "default": _default_template()}


def _default_template() -> str:
    from app.sysvars import registry as sv

    return str(sv.session_value("QNEWTEMPLATE") or "")


@router.get("/macros")
def macros_list() -> dict:
    return {"items": macro.listing()}


@router.get("/docs/{doc_id}/macro")
def macro_status(doc_id: str) -> dict:
    rn = _doc(doc_id).get_runner()
    rec = macro.current(rn)
    return {"recording": rn.recorder is not None, "name": rec.name if rec else "", "steps": len(rec.events) if rec else 0, "lines": [e["line"] for e in rec.events][:2000] if rec else []}


@router.post("/docs/{doc_id}/macro/start")
def macro_start(doc_id: str, body: Optional[Free] = None) -> dict:
    return _run(doc_id, "macrorecord", {"name": (body.model_extra or {}).get("name", "") if body else ""})


@router.post("/docs/{doc_id}/macro/stop")
def macro_stop(doc_id: str) -> dict:
    return _run(doc_id, "macrostop")


@router.post("/docs/{doc_id}/macro/play")
def macro_play(doc_id: str, body: Optional[Free] = None) -> dict:
    return _run(doc_id, "macroplay", {"path": (body.model_extra or {}).get("path", "") if body else ""})


@router.post("/docs/{doc_id}/macro/save")
def macro_save(doc_id: str, body: Free) -> dict:
    return _run(doc_id, "macrosave", dict(body.model_extra or {}))


@router.post("/docs/{doc_id}/script")
def script_run(doc_id: str, body: Free) -> dict:
    a = dict(body.model_extra or {})
    return _run(doc_id, "rscript" if a.pop("repeat", False) else "script", a)


@router.get("/docs/{doc_id}/script")
def script_status(doc_id: str) -> dict:
    rn = _doc(doc_id).get_runner()
    return {"script": rn.script.info() if rn.script else None}


@router.post("/docs/{doc_id}/script/resume")
def script_resume(doc_id: str) -> dict:
    return _run(doc_id, "resume")


@router.post("/docs/{doc_id}/script/stop")
def script_stop(doc_id: str) -> dict:
    from app.cmd import script

    rn = _doc(doc_id).get_runner()
    with rn.doc.lock:
        script.stop(rn)
    return {"script": None}


@router.get("/docs/{doc_id}/inspect")
def inspect(doc_id: str, limit: int = Q.DEFAULT_LIMIT) -> dict:
    return _run(doc_id, "inspectdrawing", {"limit": limit})["result"]


def _query(doc_id: str, name: str, body) -> dict:
    return _run(doc_id, name, dict(body.model_extra or {}) if body else {})["result"]


@router.post("/docs/{doc_id}/query/entities")
def query_entities(doc_id: str, body: Optional[Free] = None) -> dict:
    return _query(doc_id, "queryentities", body)


@router.post("/docs/{doc_id}/query/texts")
def query_texts(doc_id: str, body: Optional[Free] = None) -> dict:
    return _query(doc_id, "querytexts", body)


@router.post("/docs/{doc_id}/analyze/shapes")
def analyze_shapes(doc_id: str, body: Optional[Free] = None) -> dict:
    return _query(doc_id, "analyzeshapes", body)


@router.post("/docs/{doc_id}/analyze/loops")
def analyze_loops(doc_id: str, body: Optional[Free] = None) -> dict:
    return _query(doc_id, "impliedloops", body)


@router.post("/docs/{doc_id}/analyze/usage")
def analyze_usage(doc_id: str, body: Optional[Free] = None) -> dict:
    return _query(doc_id, "analyzeusage", body)


@router.post("/docs/{doc_id}/count")
def count(doc_id: str, body: Optional[Free] = None) -> dict:
    return _query(doc_id, "count", body)


@router.post("/docs/{doc_id}/audit")
def audit(doc_id: str, body: Optional[Free] = None) -> dict:
    return _run(doc_id, "audit", dict(body.model_extra or {}) if body else {})


@router.post("/recover")
def recover(body: Free) -> dict:
    docs = list(service.docs.values())
    host = docs[-1] if docs else service.new("Recovery")
    return _run(host.id, "recover", dict(body.model_extra or {}))


@router.get("/docs/{doc_id}/save-check")
def save_check(doc_id: str, path: str = "") -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        res = savecheck.loss(doc, path)
        res["blocked"] = savecheck.guard(doc)
        res["agreed"] = savecheck.agreed(doc, path, res) if res["dropped"] else True
        res["dirty"] = doc.dirty
        res["name"] = doc.name
        res["path"] = path or doc.path
        return res


@router.post("/docs/{doc_id}/save-check/agree")
def save_agree(doc_id: str, body: Optional[Free] = None) -> dict:
    doc = _doc(doc_id)
    path = (body.model_extra or {}).get("path", "") if body else ""
    with doc.lock:
        res = savecheck.loss(doc, path)
        savecheck.agree(doc, path, res)
        return {"agreed": True}


@router.get("/docs/{doc_id}/compare")
def compare_state(doc_id: str) -> dict:
    doc = _doc(doc_id)
    with doc.lock:
        return C.public(getattr(doc, "compare", None))


@router.post("/docs/{doc_id}/compare")
def compare_run(doc_id: str, body: Free) -> dict:
    return _run(doc_id, "compare", dict(body.model_extra or {}))["result"]


@router.post("/docs/{doc_id}/compare/next")
def compare_next(doc_id: str) -> dict:
    return _run(doc_id, "comparenext")["result"]


@router.post("/docs/{doc_id}/compare/previous")
def compare_previous(doc_id: str) -> dict:
    return _run(doc_id, "compareprevious")["result"]


@router.post("/docs/{doc_id}/compare/export")
def compare_export(doc_id: str) -> dict:
    return _run(doc_id, "compareexport")["result"]


@router.delete("/docs/{doc_id}/compare")
def compare_close(doc_id: str) -> dict:
    return _run(doc_id, "compareclose")["result"]


@router.post("/docs/{doc_id}/close-ask")
def close_ask(doc_id: str) -> dict:
    doc = _doc(doc_id)
    return {"dirty": doc.dirty, "name": doc.name, "path": doc.path, "untitled": not doc.path}


@router.post("/docs/{doc_id}/close-command")
def close_command(doc_id: str, body: Optional[Free] = None) -> dict:
    return _run(doc_id, "close", dict(body.model_extra or {}) if body else {})["result"]


@router.get("/recovery/pending")
def recovery_pending() -> dict:
    items = service.recovery_list()
    return {"items": items, "count": len(items)}
