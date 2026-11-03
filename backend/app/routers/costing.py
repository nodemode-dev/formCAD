from typing import Any, Optional

from fastapi import APIRouter, HTTPException

from app.additive.jobs import AdditiveError
from app.core.outputs import OutputRefused
from app.costing import checker, dfm, service, sustain
from app.costing import profile as PR
from app.doc.document import CommandFailed
from app.routers.part import _doc
from app.solid.work import SolidError

router = APIRouter(tags=["costing"])
USER_ERRORS = (ValueError, KeyError, OutputRefused, AdditiveError)


def run(doc_id: str, fn, label: str = ""):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            if label:
                if doc.get_runner().run is not None:
                    raise HTTPException(409, "A command is running; finish it first.")
                with doc.transaction(label):
                    return fn(doc)
            return fn(doc)
        except SolidError as err:
            raise HTTPException(503, str(err))
        except CommandFailed as err:
            raise HTTPException(409, str(err))
        except USER_ERRORS as err:
            raise HTTPException(400, str(err))


def opts(scope: str, process: str, batch: Optional[int], volume: Optional[int]) -> dict:
    return {"scope": scope, "process": process, "batch": batch, "volume": volume}


@router.get("/{doc_id}/costing/profile")
def get_profile(doc_id: str) -> dict:
    return run(doc_id, lambda doc: {"profile": PR.current(doc.drawing), "sources": PR.SOURCES})


@router.put("/{doc_id}/costing/profile")
def put_profile(doc_id: str, body: dict[str, Any]) -> dict:
    return run(doc_id, lambda doc: {"profile": PR.put(doc.drawing, body)}, "COSTING")


@router.delete("/{doc_id}/costing/profile")
def delete_profile(doc_id: str) -> dict:
    def go(doc):
        PR.reset(doc.drawing)
        return {"profile": PR.current(doc.drawing)}

    return run(doc_id, go, "COSTING")


@router.get("/{doc_id}/costing/estimate")
def get_estimate(doc_id: str, scope: str = "auto", process: str = "", batch: Optional[int] = None, volume: Optional[int] = None) -> dict:
    return run(doc_id, lambda doc: service.public(service.estimate(doc, opts(scope, process, batch, volume))))


@router.get("/{doc_id}/costing/dfm")
def get_dfm(doc_id: str, scope: str = "auto", process: str = "") -> dict:
    return run(doc_id, lambda doc: service.dfm_run(doc, opts(scope, process, None, None)))


@router.get("/{doc_id}/costing/dfm/rules")
def get_dfm_rules(doc_id: str) -> dict:
    return run(doc_id, lambda doc: {"rules": dfm.current(doc.drawing)})


@router.put("/{doc_id}/costing/dfm/rules")
def put_dfm_rules(doc_id: str, body: dict[str, Any]) -> dict:
    return run(doc_id, lambda doc: {"rules": dfm.put(doc.drawing, body)}, "DFMRULE")


@router.get("/{doc_id}/costing/rules")
def get_rules(doc_id: str) -> dict:
    return run(doc_id, lambda doc: {"rules": checker.current(doc.drawing), "kinds": {k: v["text"] for k, v in checker.KINDS.items()}})


@router.put("/{doc_id}/costing/rules")
def put_rules(doc_id: str, body: dict[str, Any]) -> dict:
    return run(doc_id, lambda doc: {"rules": checker.put(doc.drawing, body.get("rules"))}, "DESIGNRULES")


@router.get("/{doc_id}/costing/check")
def get_check(doc_id: str, scope: str = "auto") -> dict:
    return run(doc_id, lambda doc: service.check_run(doc, {"scope": scope}))


@router.get("/{doc_id}/costing/emissions")
def get_emissions(doc_id: str) -> dict:
    return run(doc_id, lambda doc: {"table": sustain.current(doc.drawing), "caveats": sustain.CAVEATS, "attribution": sustain.ATTRIBUTION})


@router.put("/{doc_id}/costing/emissions")
def put_emissions(doc_id: str, body: dict[str, Any]) -> dict:
    return run(doc_id, lambda doc: {"table": sustain.put(doc.drawing, body)}, "EMISSIONS")


@router.put("/{doc_id}/costing/emissions/import")
def import_emissions(doc_id: str, body: dict[str, Any]) -> dict:
    def go(doc):
        rows = sustain.read_csv(body.get("path"))
        cur = sustain.current(doc.drawing)
        cur["factors"].update(rows)
        return {"table": sustain.put(doc.drawing, {"factors": cur["factors"]}), "imported": len(rows)}

    return run(doc_id, go, "EMISSIONS")


@router.get("/{doc_id}/costing/sustainability")
def get_sustainability(doc_id: str, scope: str = "auto", process: str = "") -> dict:
    return run(doc_id, lambda doc: service.sustain_run(doc, opts(scope, process, None, None)))


@router.post("/{doc_id}/costing/export")
def export_report(doc_id: str, body: dict[str, Any]) -> dict:
    o = {"scope": body.get("scope") or "auto", "process": body.get("process") or "", "batch": body.get("batch"), "volume": body.get("volume"), "dfm": body.get("dfm", True)}
    return run(doc_id, lambda doc: service.write_report(doc, body.get("path"), o))
