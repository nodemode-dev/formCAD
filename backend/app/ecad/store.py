import copy
import re

SCHEMA = 1
HEADER = "ECAD"
GRID = 1.27
ROOT = "S1"
MAX_SHEETS = 999
MAX_PARTS = 5000
MAX_ITEMS = 50000
MAX_ITEMS_AGENT = 5000
MAX_PINS = 2000
MAX_BATCH = 2000
MAX_BATCH_AGENT = 200
ITEM_KINDS = {"wire": "W", "bus": "B", "junction": "J", "no_connect": "X", "label": "L", "bus_entry": "E", "sheet_symbol": "H", "text": "T"}
ETYPES = ("input", "output", "bidirectional", "tri_state", "passive", "power_in", "power_out", "open_collector", "unconnected")
ERC_RULES = (
    "pin_conflict", "input_no_driver", "power_not_driven", "pin_not_connected", "duplicate_refdes", "unannotated", "single_label",
    "dangling_wire", "bus_member_mismatch", "missing_footprint", "unknown_footprint", "unknown_symbol", "single_node_net",
    "multiple_names", "sheet_pin_mismatch", "wire_end_on_wire", "missing_value",
)
ERC_DEFAULTS = {
    "pin_conflict": "error", "input_no_driver": "error", "power_not_driven": "error", "pin_not_connected": "error", "duplicate_refdes": "error",
    "unannotated": "error", "single_label": "warning", "dangling_wire": "warning", "bus_member_mismatch": "error", "missing_footprint": "warning",
    "unknown_footprint": "warning", "unknown_symbol": "error", "single_node_net": "warning", "multiple_names": "warning", "sheet_pin_mismatch": "error",
    "wire_end_on_wire": "warning", "missing_value": "ignore",
}
SEVERITIES = ("error", "warning", "ignore")


class EcadError(ValueError):
    pass


def blank() -> dict:
    return {
        "schema": SCHEMA, "name": "", "units": "mm", "root": ROOT, "next": {"part": 1, "sheet": 2, "W": 1, "B": 1, "J": 1, "X": 1, "L": 1, "E": 1, "H": 1, "T": 1},
        "settings": {"erc": dict(ERC_DEFAULTS)}, "sheets": {ROOT: new_sheet(ROOT, "Root")}, "parts": {}, "lib": {"symbols": {}, "footprints": {}},
    }


def new_sheet(sid: str, name: str) -> dict:
    return {"id": sid, "name": name, "title": name, "paper": "A4", "wires": [], "buses": [], "junctions": [], "no_connects": [], "labels": [], "bus_entries": [], "sheet_symbols": [], "texts": []}


def header(d) -> dict:
    raw = d.header.get(HEADER)
    base = blank()
    if isinstance(raw, dict):
        for k, v in copy.deepcopy(raw).items():
            base[k] = v
        base["next"] = {**blank()["next"], **base["next"]}
        base["settings"] = {"erc": {**ERC_DEFAULTS, **(base.get("settings") or {}).get("erc", {})}}
    return base


def is_ecad(d) -> bool:
    return isinstance(d.header.get(HEADER), dict)


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def ensure(d) -> dict:
    h = header(d)
    if not is_ecad(d):
        save(d, h)
    elif int(h.get("schema", 1)) > SCHEMA:
        raise EcadError("This design was written with schema %s by a newer FormCAD; this version reads schema %d." % (h.get("schema"), SCHEMA))
    return h


def natural(s: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def parts(d) -> list:
    return sorted(header(d)["parts"].values(), key=lambda p: int(p["id"][1:]))


def count_items(h: dict) -> int:
    n = 0
    for sh in h["sheets"].values():
        for key in ("wires", "buses", "junctions", "no_connects", "labels", "bus_entries", "sheet_symbols", "texts"):
            n += len(sh.get(key, []))
    return n


def next_id(h: dict, kind: str) -> str:
    code = ITEM_KINDS[kind]
    n = h["next"][code]
    h["next"][code] = n + 1
    return "%s%d" % (code, n)


def need_sheet(h: dict, sid: str) -> dict:
    sh = h["sheets"].get(sid)
    if sh is None:
        raise EcadError("There is no sheet %s." % sid)
    return sh


def need_part(h: dict, pid: str) -> dict:
    key = str(pid or "").strip()
    p = h["parts"].get(key)
    if p is None:
        for q in h["parts"].values():
            if q["refdes"] == key:
                return q
        raise EcadError("There is no part %s." % pid)
    return p


def pt(v, what="point") -> list:
    try:
        x, y = float(v[0]), float(v[1])
    except (TypeError, ValueError, IndexError, KeyError):
        raise EcadError("A %s is [x, y] in millimetres." % what)
    if abs(x) > 1e5 or abs(y) > 1e5 or x != x or y != y:
        raise EcadError("A %s is out of range." % what)
    return [round(x, 4), round(y, 4)]
