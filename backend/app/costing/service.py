import csv
import html
import io
import os
import time

from app.core import outputs
from app.costing import checker, cost, dfm, scope, sustain
from app.costing import facts as F
from app.costing import finding as FD
from app.costing import profile as PR

LEAD = ("=", "+", "-", "@", "\t", "\r")
MAX_SECOND = 20.0


def gather(doc, mode: str = "auto") -> tuple:
    prof = PR.current(doc.drawing)
    out = []
    for t in scope.targets(doc, mode):
        d = t["drawing"]
        f = F.part_facts(d, prof, t["label"], t.get("props"))
        out.append({"target": t, "label": t["label"], "qty": t["qty"], "facts": f})
    return prof, out


def estimate(doc, opts: dict) -> dict:
    prof, rows = gather(doc, opts.get("scope") or "auto")
    res_rows = []
    for r in rows:
        c = cost.part_cost(r["facts"], prof, opts.get("process") or "", opts.get("batch"), opts.get("volume"))
        res_rows.append({"part": r["label"], "qty": r["qty"], "part_number": r["target"].get("part_number", ""), "cost": c, "cost_row": r})
    roll = cost.roll_up([{"cost": x["cost"], "qty": x["qty"]} for x in res_rows])
    return {
        "currency": prof["currency"],
        "placeholder": not prof["defined"],
        "note": PR.EXAMPLE if not prof["defined"] else "",
        "sources": PR.SOURCES,
        "batch": int(opts.get("batch") or prof["batch"]),
        "volume": int(opts.get("volume") or prof["volume"]),
        "rows": [{k: v for k, v in x.items() if k != "cost_row"} for x in res_rows],
        "total": roll["total"],
        "by_line": roll["by_line"],
        "parts": roll["parts"],
        "units": roll["units"],
        "warnings": list(dict.fromkeys(w for x in res_rows for w in x["cost"]["notes"])),
        "_rows": res_rows,
    }


def public(res: dict) -> dict:
    return {k: v for k, v in res.items() if not k.startswith("_")}


def dfm_run(doc, opts: dict) -> dict:
    prof, rows = gather(doc, opts.get("scope") or "auto")
    rules = dfm.current(doc.drawing)
    findings: list = []
    parts = []
    t0 = time.perf_counter()
    for r in rows:
        proc = opts.get("process") or F.process_of(r["facts"])
        if time.perf_counter() - t0 > MAX_SECOND:
            parts.append({"part": r["label"], "process": proc, "findings": [], "checked": [], "skipped": ["not checked: the %d second limit of one DFM call was reached; run it with scope part for the rest" % MAX_SECOND], "summary": FD.counts([])})
            continue
        if proc == "purchased":
            parts.append({"part": r["label"], "process": proc, "findings": [], "checked": [], "skipped": ["purchased part: no DFM rules"], "summary": FD.counts([])})
            continue
        res = dfm.run(r["target"], r["facts"], proc, rules)
        parts.append(res)
        findings += res["findings"]
    return {"parts": parts, "findings": findings, "summary": FD.counts(findings), "thresholds": {k: {"value": v["value"], "source": v["source"], "single_source": v["single"]} for k, v in rules.items()}}


def check_run(doc, opts: dict) -> dict:
    d = doc.drawing
    rules = checker.current(d)
    prof, rows = gather(doc, opts.get("scope") or "auto")
    findings: list = []
    asm = (opts.get("scope") or "auto") != "part" and (doc.kind == "assembly")
    names = []
    if asm:
        from app.assembly import walk

        names = [i.record["label"] for i in walk.instances(doc)]
    for r in rows:
        t = dict(r["target"])
        t["component_names"] = names
        t["purchased"] = F.process_of(r["facts"]) == "purchased"
        findings += checker.evaluate_part(t, r["facts"], rules, checker.geometry_measure)
    if asm:
        top = {"drawing": d, "label": doc.name, "qty": 1, "component_names": names}
        top_facts = {"props": F.P.get(d), "bodies": [], "warnings": [], "material": "", "mass": None, "bbox": None}
        asm_rules = [r for r in rules if r["kind"] in ("property_required", "property_matches", "units", "name_pattern") and (r["kind"] != "name_pattern" or r.get("target") in ("document", "component"))]
        findings += checker.evaluate_part(top, top_facts, asm_rules, checker.geometry_measure)
    return {"rules": len(rules), "enabled": sum(1 for r in rules if r.get("enabled", True)), "parts": [r["label"] for r in rows], "findings": findings, "summary": FD.counts(findings), "ok": not any(f["severity"] == "error" for f in findings)}


def sustain_run(doc, opts: dict) -> dict:
    est = estimate(doc, opts)
    table = sustain.current(doc.drawing)
    rows = [{"label": x["part"], "qty": x["qty"], "facts": x["cost_row"]["facts"], "cycle_s": x["cost"]["cycle_s"], "process": x["cost"]["process"]} for x in est["_rows"]]
    return sustain.estimate(rows, table)


def cell(v) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(LEAD) else s


def build_report(doc, opts: dict) -> dict:
    t0 = time.perf_counter()
    est = estimate(doc, opts)
    dres = dfm_run(doc, opts) if opts.get("dfm", True) else None
    cres = check_run(doc, opts)
    sres = sustain_run(doc, opts)
    return {"document": doc.name, "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "cost": public(est), "dfm": dres, "check": cres, "sustainability": sres, "seconds": round(time.perf_counter() - t0, 2)}


def to_csv(rep: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["section", "part", "qty", "item", "amount", "detail"])
    for r in rep["cost"]["rows"]:
        for ln in r["cost"]["lines"]:
            w.writerow(["cost", cell(r["part"]), r["qty"], cell(ln["label"]), "%.4f" % ln["amount"], cell(ln["basis"])])
        w.writerow(["cost_unit", cell(r["part"]), r["qty"], "unit cost", "%.4f" % r["cost"]["unit_cost"], r["cost"]["process"]])
    w.writerow(["cost_total", "", "", "total", "%.4f" % rep["cost"]["total"], cell(rep["cost"]["currency"]) + (" (example rates)" if rep["cost"]["placeholder"] else "")])
    for sec in ("dfm", "check"):
        data = rep.get(sec)
        for f in (data or {}).get("findings", []):
            w.writerow([sec, cell(f["part"]), "", cell(f["rule"]), f["severity"], cell(f["message"])])
    for r in rep["sustainability"]["rows"]:
        w.writerow(["sustainability", cell(r["part"]), r["qty"], cell(r["material"]), "" if r["kg_co2e"] is None else "%.4f" % r["kg_co2e"], "kg CO2e per unit"])
    w.writerow(["sustainability_total", "", "", "total", "%.4f" % rep["sustainability"]["total_kg_co2e"], "kg CO2e"])
    for c in rep["sustainability"]["caveats"]:
        w.writerow(["caveat", "", "", "", "", cell(c)])
    return buf.getvalue()


def to_html(rep: dict) -> str:
    e = html.escape
    parts = ["<!doctype html><meta charset=utf-8><title>%s</title><style>body{font:14px sans-serif;margin:2em}td,th{border:1px solid #888;padding:2px 8px;text-align:left}table{border-collapse:collapse;margin:1em 0}</style>" % e(rep["document"] + " report")]
    parts.append("<h1>Cost, checks and sustainability: %s</h1><p>%s</p>" % (e(rep["document"]), e(rep["created"])))
    c = rep["cost"]
    if c["placeholder"]:
        parts.append("<p><b>%s</b></p>" % e(c["note"]))
    parts.append("<h2>Cost</h2><table><tr><th>Part</th><th>Qty</th><th>Process</th><th>Unit</th><th>Line total</th></tr>")
    for r in c["rows"]:
        parts.append("<tr><td>%s</td><td>%d</td><td>%s</td><td>%.2f</td><td>%.2f</td></tr>" % (e(r["part"]), r["qty"], e(r["cost"]["process"]), r["cost"]["unit_cost"], r["cost"]["unit_cost"] * r["qty"]))
    parts.append("<tr><th colspan=4>Total (%s)</th><th>%.2f</th></tr></table>" % (e(c["currency"]), c["total"]))
    for sec, title in (("dfm", "Manufacturability findings"), ("check", "Design check findings")):
        data = rep.get(sec)
        if not data:
            continue
        parts.append("<h2>%s</h2><table><tr><th>Severity</th><th>Part</th><th>Rule</th><th>Message</th><th>Source</th></tr>" % title)
        for f in data["findings"]:
            parts.append("<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (e(f["severity"]), e(f["part"]), e(f["rule"]), e(f["message"]), e(f["source"])))
        parts.append("</table>")
    s = rep["sustainability"]
    parts.append("<h2>Sustainability</h2><p>Total %.3f kg CO2e (screening estimate)</p><ul>" % s["total_kg_co2e"])
    for cv in s["caveats"]:
        parts.append("<li>%s</li>" % e(cv))
    parts.append("</ul>")
    if s["missing"]:
        parts.append("<p>Not estimated: %s</p>" % e("; ".join(s["missing"])))
    if s["attribution"]:
        parts.append("<p>%s</p>" % e(s["attribution"]))
    return "".join(parts)


def write_report(doc, path: str, opts: dict) -> dict:
    if not os.path.isabs(os.path.expanduser(str(path or ""))):
        raise outputs.OutputRefused("Give the full path of the report file.")
    full = outputs.checked(path, (".json", ".csv", ".html"), ".json")
    rep = build_report(doc, opts)
    ext = full.rsplit(".", 1)[-1].lower()
    if ext == "csv":
        data = to_csv(rep)
    elif ext == "html":
        data = to_html(rep)
    else:
        import json

        data = json.dumps(rep, indent=1, default=str)
    if len(data) > 8_000_000:
        raise ValueError("The report is larger than 8 MB.")
    with open(full + ".part", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(data)
    os.replace(full + ".part", full)
    found = len(rep["check"]["findings"]) + (len(rep["dfm"]["findings"]) if rep["dfm"] else 0)
    return {"path": full, "bytes": len(data.encode("utf-8")), "total": rep["cost"]["total"], "findings": found}
