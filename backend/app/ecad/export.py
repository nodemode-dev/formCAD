import csv
import io
import json

from app.core import outputs
from app.ecad.store import EcadError, natural


def netlist_text(nl: dict) -> str:
    lines = ["FORMCAD-NETLIST 1", "DESIGN %s" % (nl["design"] or "untitled")]
    for c in nl["components"]:
        lines.append("COMPONENT %s | %s | %s | %s%s" % (c["ref"], c["symbol"], c["value"] or "-", c["footprint"] or "-", " | DNP" if c["dnp"] else ""))
    for n in nl["nets"]:
        lines.append("NET %s : %s" % (n["name"], " ".join("%s.%s" % (x["ref"], x["pin"]) for x in n["nodes"])))
    return "\n".join(lines) + "\n"


def bom_rows(nl: dict) -> list:
    groups = {}
    for c in nl["components"]:
        if c["dnp"]:
            continue
        key = (c["value"], c["footprint"], c["symbol"], tuple(sorted(c["fields"].items())))
        groups.setdefault(key, []).append(c["ref"])
    rows = []
    for (value, fp, sym, fields), refs in groups.items():
        refs.sort(key=natural)
        rows.append({"refs": " ".join(refs), "qty": len(refs), "value": value, "footprint": fp, "symbol": sym, **{k: v for k, v in fields}})
    rows.sort(key=lambda r: natural(r["refs"].split(" ")[0]))
    return rows


def bom_csv(nl: dict) -> str:
    rows = bom_rows(nl)
    extra = sorted({k for r in rows for k in r if k not in ("refs", "qty", "value", "footprint", "symbol")})
    cols = ["refs", "qty", "value", "footprint", "symbol"] + extra
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()


def write(path: str, kind: str, nl: dict, fmt: str = "json") -> dict:
    try:
        if kind == "bom":
            full = outputs.checked(path, (".csv",), ".csv")
            data = bom_csv(nl)
        else:
            full = outputs.checked(path, (".json", ".net", ".txt"), ".json")
            ext = full.rsplit(".", 1)[-1]
            data = json.dumps(nl, indent=1) + "\n" if (fmt == "json" and ext == "json") else netlist_text(nl)
    except outputs.OutputRefused as err:
        raise EcadError(str(err))
    with open(full, "w", encoding="utf-8", newline="") as fh:
        fh.write(data)
    return {"path": full, "bytes": len(data.encode("utf-8")), "components": len(nl["components"]), "nets": len(nl["nets"])}
