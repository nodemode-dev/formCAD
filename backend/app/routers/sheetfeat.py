from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routers.part import _edit, _read
from app.sheetmetal import check, records, rule, tables

router = APIRouter(tags=["sheetmetal"])


class TableBody(BaseModel):
    name: str = ""
    mode: str
    axis: str = "angle"
    sets: list[dict[str, Any]]
    tolerance: float = 1e-6
    source: str = ""


class GaugeBody(BaseModel):
    name: str = ""
    material: str = ""
    source: str = ""
    entries: list[dict[str, Any]]


def show_rule(d):
    r = rule.rule_of_part(d)
    if r is None:
        return None
    out = dict(r)
    out["table"] = None if r.get("table") is None else {"id": r["table"].get("id"), "mode": r["table"]["mode"], "axis": r["table"]["axis"]}
    return out


def wrap(fn):
    try:
        return fn()
    except tables.TableError as err:
        raise HTTPException(400, str(err))


@router.get("/{doc_id}/sheetmetal")
def overview(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"rule": show_rule(doc.drawing), "features": records.features(doc.drawing), "bends": records.bends(doc.drawing)})


@router.get("/{doc_id}/sheetmetal/rule")
def get_rule(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"rule": show_rule(doc.drawing)})


@router.get("/{doc_id}/sheetmetal/bends")
def get_bends(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"bends": records.bends(doc.drawing)})


@router.get("/{doc_id}/sheetmetal/features")
def get_features(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"features": records.features(doc.drawing)})


@router.get("/{doc_id}/sheetmetal/verify")
def verify(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: check.verify(doc))


@router.get("/{doc_id}/sheetmetal/tables")
def list_tables(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"tables": tables.listing(doc.drawing), "gauges": tables.gauges(doc.drawing)})


@router.get("/{doc_id}/sheetmetal/tables/{table_id}")
def get_table(doc_id: str, table_id: str) -> dict:
    def run(doc):
        got = tables.get(doc.drawing, table_id)
        if got is None:
            raise HTTPException(404, "There is no bend table %s." % table_id)
        return got

    return _read(doc_id, run)


@router.put("/{doc_id}/sheetmetal/tables/{table_id}")
def put_table(doc_id: str, table_id: str, body: TableBody) -> dict:
    return _edit(doc_id, "SMTABLE", lambda doc: wrap(lambda: rule.save_table(doc, table_id, body.model_dump())))


@router.delete("/{doc_id}/sheetmetal/tables/{table_id}")
def delete_table(doc_id: str, table_id: str) -> dict:
    return _edit(doc_id, "SMTABLE", lambda doc: wrap(lambda: (rule.drop_table(doc, table_id), {"removed": table_id})[1]))


@router.put("/{doc_id}/sheetmetal/gauges/{gauge_id}")
def put_gauge(doc_id: str, gauge_id: str, body: GaugeBody) -> dict:
    return _edit(doc_id, "SMGAUGE", lambda doc: wrap(lambda: tables.put_gauge(doc.drawing, gauge_id, body.model_dump())))


@router.delete("/{doc_id}/sheetmetal/gauges/{gauge_id}")
def delete_gauge(doc_id: str, gauge_id: str) -> dict:
    return _edit(doc_id, "SMGAUGE", lambda doc: wrap(lambda: (tables.remove_gauge(doc.drawing, gauge_id), {"removed": gauge_id})[1]))
