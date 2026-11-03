from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import guard
from app.doc.document import CommandFailed
from app.doc.service import DocumentFault, service
from app.ecad import erc, export, footprints, library, netlist, schematic, store, symbols
from app.ecad.store import EcadError

router = APIRouter(tags=["ecad"])

FAILURES = (EcadError, ValueError, KeyError, CommandFailed)


class OpBody(BaseModel):
    model_config = {"extra": "allow"}


class BatchBody(BaseModel):
    ops: list[dict[str, Any]]


class SymbolBody(BaseModel):
    model_config = {"extra": "allow"}


class SymbolGenBody(BaseModel):
    kind: str = "ic"
    id: str
    name: str = ""
    pins: Any = None
    split: Optional[int] = None
    rows: int = 1
    cols: int = 2
    prefix: str = "U"
    footprint: str = ""
    save: bool = True


class FootprintGenBody(BaseModel):
    family: str
    params: dict[str, Any] = {}
    id: str = ""
    save: bool = False


class FootprintBody(BaseModel):
    model_config = {"extra": "allow"}


class ExportBody(BaseModel):
    path: str
    format: str = "json"


class ErcBody(BaseModel):
    rules: dict[str, str]


def _doc(doc_id: str):
    try:
        return service.get(doc_id)
    except DocumentFault as err:
        raise HTTPException(err.status, err.message)


def _fail(err):
    if isinstance(err, CommandFailed):
        raise HTTPException(409, str(err))
    if isinstance(err, KeyError):
        raise HTTPException(400, str(err.args[0]) if err.args else "Not found.")
    raise HTTPException(400, str(err))


def _edit(doc_id: str, label: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        if doc.get_runner().run is not None:
            raise HTTPException(409, "A command is running; finish it first.")
        try:
            with doc.transaction(label):
                h = store.ensure(doc.drawing)
                result = fn(h)
                store.save(doc.drawing, h)
        except FAILURES as err:
            _fail(err)
        return {"rev": doc.rev, "result": result}


def _read(doc_id: str, fn):
    doc = _doc(doc_id)
    with doc.lock:
        try:
            return fn(store.header(doc.drawing), doc)
        except FAILURES as err:
            _fail(err)


def _summary(h: dict, doc) -> dict:
    return {
        "rev": doc.rev, "kind": doc.kind, "schema": h["schema"], "name": h["name"], "units": h["units"], "root": h["root"],
        "sheets": [{"id": s["id"], "name": s["name"], "title": s["title"], "paper": s["paper"], "parts": sum(1 for p in h["parts"].values() for pl in p["placements"] if pl["sheet"] == s["id"]), "wires": len(s["wires"]), "labels": len(s["labels"]), "sheet_symbols": len(s["sheet_symbols"])} for s in h["sheets"].values()],
        "parts": sorted(h["parts"].values(), key=lambda p: int(p["id"][1:])), "settings": h["settings"], "items": store.count_items(h),
    }


def _limit() -> int:
    return store.MAX_BATCH_AGENT if guard.CALLER.get() else store.MAX_BATCH


@router.get("/{doc_id}/ecad")
def listing(doc_id: str) -> dict:
    return _read(doc_id, _summary)


@router.get("/{doc_id}/ecad/schema")
def schema(doc_id: str) -> dict:
    _doc(doc_id)
    return {"schema": store.SCHEMA, "header": store.HEADER, "pcb_header": "ECAD_PCB", "etypes": list(store.ETYPES), "erc_rules": list(store.ERC_RULES), "erc_defaults": store.ERC_DEFAULTS, "ops": sorted(schematic.OPS), "footprint_families": list(footprints.FAMILIES), "footprint_defaults": footprints.DEFAULTS, "limits": {"parts": store.MAX_PARTS, "items": store.MAX_ITEMS, "batch": store.MAX_BATCH, "batch_agent": store.MAX_BATCH_AGENT, "sheets": store.MAX_SHEETS}}


@router.post("/{doc_id}/ecad/init")
def init(doc_id: str, body: OpBody = OpBody()) -> dict:
    extra = body.model_extra or {}
    return _edit(doc_id, "ECADINIT", lambda h: schematic.set_design(h, {"name": extra.get("name", h["name"])}))


@router.post("/{doc_id}/ecad/batch")
def batch(doc_id: str, body: BatchBody) -> dict:
    if len(body.ops) > _limit():
        raise HTTPException(400, "A batch has at most %d operations for this caller." % _limit())

    def run(h):
        if guard.CALLER.get() and store.count_items(h) + len(body.ops) > store.MAX_ITEMS_AGENT:
            raise EcadError("This caller may build designs of at most %d drawn items." % store.MAX_ITEMS_AGENT)
        out = []
        for i, op in enumerate(body.ops):
            try:
                out.append(schematic.apply(h, op))
            except EcadError as err:
                raise EcadError("Operation %d (%s): %s" % (i + 1, op.get("op"), err))
        return out

    return _edit(doc_id, "ECADBATCH", run)


@router.post("/{doc_id}/ecad/ops")
def one_op(doc_id: str, body: OpBody) -> dict:
    op = dict(body.model_extra or {})

    def run(h):
        if guard.CALLER.get() and store.count_items(h) + 1 > store.MAX_ITEMS_AGENT:
            raise EcadError("This caller may build designs of at most %d drawn items." % store.MAX_ITEMS_AGENT)
        return schematic.apply(h, op)

    return _edit(doc_id, "ECAD " + str(op.get("op", "")).upper(), run)


@router.get("/{doc_id}/ecad/sheets/{sid}/scene")
def scene(doc_id: str, sid: str) -> dict:
    return _read(doc_id, lambda h, doc: {"rev": doc.rev, **schematic.scene(h, sid)})


@router.get("/{doc_id}/ecad/parts/{pid}/pins")
def part_pins(doc_id: str, pid: str) -> dict:
    def run(h, doc):
        part = store.need_part(h, pid)
        return {"part": part["id"], "refdes": part["refdes"], "placements": [{**pl, "pins": [{"number": p["number"], "name": p["name"], "etype": p["etype"], "pos": p["abs"], "orient": p["abs_orient"], "hidden": p["hidden"]} for p in schematic.pins_of(h, part, pl)]} for pl in part["placements"]]}

    return _read(doc_id, run)


@router.get("/{doc_id}/ecad/netlist")
def get_netlist(doc_id: str) -> dict:
    return _read(doc_id, lambda h, doc: netlist.analyse(h)["netlist"])


@router.get("/{doc_id}/ecad/erc")
def get_erc(doc_id: str) -> dict:
    return _read(doc_id, lambda h, doc: erc.run(h))


@router.post("/{doc_id}/ecad/erc/settings")
def erc_settings(doc_id: str, body: ErcBody) -> dict:
    return _edit(doc_id, "ECADERC", lambda h: schematic.set_erc(h, {"rules": body.rules}))


@router.post("/{doc_id}/ecad/export/netlist")
def export_netlist(doc_id: str, body: ExportBody) -> dict:
    return _read(doc_id, lambda h, doc: export.write(body.path, "netlist", netlist.analyse(h)["netlist"], body.format))


@router.post("/{doc_id}/ecad/export/bom")
def export_bom(doc_id: str, body: ExportBody) -> dict:
    return _read(doc_id, lambda h, doc: export.write(body.path, "bom", netlist.analyse(h)["netlist"]))


@router.get("/{doc_id}/ecad/library/symbols")
def list_symbols(doc_id: str, q: str = "") -> dict:
    return _read(doc_id, lambda h, doc: {"symbols": library.list_symbols(doc.drawing, q)})


@router.get("/{doc_id}/ecad/library/symbols/{sid:path}")
def get_symbol(doc_id: str, sid: str) -> dict:
    def run(h, doc):
        s = library.sym_in(h, sid)
        if s is None:
            raise EcadError("There is no symbol %s." % sid)
        return s

    return _read(doc_id, run)


@router.post("/{doc_id}/ecad/library/symbols")
def save_symbol(doc_id: str, body: SymbolBody) -> dict:
    sym = dict(body.model_extra or {})
    return _edit(doc_id, "ECADSYMBOL", lambda h: library.save_symbol(h, sym))


@router.post("/{doc_id}/ecad/library/symbols/generate")
def generate_symbol(doc_id: str, body: SymbolGenBody) -> dict:
    def run(h):
        if body.kind == "connector":
            sym = symbols.connector(body.rows, body.cols, body.id)
        elif body.kind == "power":
            sym = symbols.power_symbol(body.name or body.id, body.id)
        elif body.kind == "ic":
            pins = symbols.parse_pins(body.pins)
            if not pins:
                raise EcadError("An IC symbol needs pins, for example '1:VCC:power_in;2:OUT:output'.")
            sym = symbols.generic_ic(body.id, body.name or body.id, pins, body.prefix, body.footprint, split=body.split)
        else:
            raise EcadError("Generate kind is ic, connector or power.")
        sym["name"] = body.name or sym["name"]
        if body.footprint:
            sym["default_footprint"] = body.footprint
        return library.save_symbol(h, sym) if body.save else sym

    return _edit(doc_id, "ECADSYMBOL", run) if body.save else _read(doc_id, lambda h, doc: {"result": run(h)})


@router.delete("/{doc_id}/ecad/library/symbols/{sid:path}")
def delete_symbol(doc_id: str, sid: str) -> dict:
    return _edit(doc_id, "ECADSYMBOL", lambda h: library.delete_symbol(h, sid))


@router.get("/{doc_id}/ecad/library/footprints")
def list_footprints(doc_id: str, q: str = "") -> dict:
    return _read(doc_id, lambda h, doc: {"footprints": library.list_footprints(doc.drawing, q), "families": footprints.DEFAULTS})


@router.get("/{doc_id}/ecad/library/footprints/{fid:path}")
def get_footprint(doc_id: str, fid: str) -> dict:
    def run(h, doc):
        fp = library.fp_in(h, fid)
        if fp is None:
            raise EcadError("There is no footprint %s." % fid)
        return fp

    return _read(doc_id, run)


@router.post("/{doc_id}/ecad/library/footprints/generate")
def generate_footprint(doc_id: str, body: FootprintGenBody) -> dict:
    try:
        fp = footprints.generate(body.family, body.params)
    except FAILURES as err:
        _fail(err)
    if body.id:
        fp["id"] = fp["name"] = body.id
    if not body.save:
        _doc(doc_id)
        return {"result": fp}
    return _edit(doc_id, "ECADFOOTPRINT", lambda h: library.save_footprint(h, fp))


@router.post("/{doc_id}/ecad/library/footprints")
def save_footprint(doc_id: str, body: FootprintBody) -> dict:
    fp = dict(body.model_extra or {})
    return _edit(doc_id, "ECADFOOTPRINT", lambda h: library.save_footprint(h, fp))


@router.delete("/{doc_id}/ecad/library/footprints/{fid:path}")
def delete_footprint(doc_id: str, fid: str) -> dict:
    return _edit(doc_id, "ECADFOOTPRINT", lambda h: library.delete_footprint(h, fid))
