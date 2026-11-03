import copy
import csv
import html
import io
import math
import os
import re
from datetime import datetime, timezone

from app.assembly import props
from app.cmd import barred
from app.core.outputs import OutputRefused, checked
from app.drawann import ops as ann_ops
from app.param.units import mm_per_unit
from app.pmi import geo, store as pmi_store
from app.toolbox import library
from app.solid.work import SolidError

SCHEMA = 1
HEADER = "INSPECTION"
MAX_ITEMS = 2000
AGENT_ITEMS = 300
MAX_ACTUALS = 100
MAX_TEXT = 200
CLASSES = ("", "critical", "major", "minor", "key")
KINDS = ("dimension", "tolerance", "note")
BALLOON_TAG = "insp:"
TITLE = "First-article style inspection report"
LAYOUT_NOTE = "Layout is FormCAD's own: part accountability, product accountability and characteristic accountability sections. It is not a copy of any industry form and makes no conformance claim."
ID_RE = re.compile(r"^K(\d+)$")


class InspectError(ValueError):
    pass


def blank() -> dict:
    return {"schema": SCHEMA, "next": 1, "items": [], "settings": {"balloon_offset": 12.0}, "report": {"form1": {}, "form2": {"materials": [], "processes": [], "tests": []}}}


def header(d) -> dict:
    raw = d.header.get(HEADER)
    out = blank()
    if isinstance(raw, dict):
        for k, v in copy.deepcopy(raw).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict) and k in ("settings", "report"):
                out[k].update(v)
            else:
                out[k] = v
    if int(out.get("schema", 1)) > SCHEMA:
        raise InspectError("The inspection data was written by a newer FormCAD.")
    return out


def save(d, h: dict) -> None:
    d.set_header(HEADER, copy.deepcopy(h))


def text(v, what, limit=MAX_TEXT) -> str:
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", str(v if v is not None else "")).strip()
    if len(s) > limit:
        raise InspectError("%s holds at most %d characters." % (what, limit))
    return s


def number(v, what):
    if v in (None, ""):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise InspectError("%s must be a number." % what)
    if not math.isfinite(x) or abs(x) > 1e9:
        raise InspectError("%s is out of range." % what)
    return x


def key_of(item: dict) -> str:
    s = item.get("source") or {}
    return "%s:%s" % (s.get("type", "manual"), s.get("ref", item.get("id")))


def new_item(h: dict, base: dict) -> dict:
    n = h["next"]
    h["next"] = n + 1
    item = {"id": "K%d" % n, "n": 0, "source": {"type": "manual", "ref": ""}, "kind": "dimension", "label": "", "nominal": None, "plus": 0.0, "minus": 0.0, "lower": None, "upper": None, "unit": "mm", "char": "", "datums": [], "class": "", "qty": 1, "method": "", "view": "", "anchor": None, "balloon": None, "actuals": [], "note": "", "state": "ok"}
    item.update(base)
    return item


def bounds_of(item: dict) -> None:
    nom, plus, minus = item.get("nominal"), item.get("plus") or 0.0, item.get("minus") or 0.0
    if item["kind"] == "dimension" and nom is not None:
        item["lower"], item["upper"] = nom - abs(minus), nom + abs(plus)


def pmi_items(d) -> list:
    out = []
    s = mm_per_unit(d)
    for rec in pmi_store.items(d):
        if rec["type"] == "datum":
            continue
        row = geo.describe(d, rec)
        base = {"source": {"type": "pmi", "ref": rec["id"]}, "label": row.get("label", ""), "state": row.get("state", "ok")}
        if rec["type"] == "dimension":
            val = rec.get("value") if rec.get("value") is not None else row.get("measured")
            if rec["dtype"] == "angle":
                unit = "deg"
            else:
                unit = "mm"
                val = None if val is None else val * s
            base.update(kind="dimension", nominal=val, plus=abs(rec.get("plus", 0.0)) * (1.0 if unit == "deg" else s), minus=abs(rec.get("minus", 0.0)) * (1.0 if unit == "deg" else s), unit=unit)
        else:
            base.update(kind="tolerance", char=rec["char"], datums=list(rec.get("datums") or []), lower=0.0, upper=float(rec["tol"]) * s, unit="mm")
        out.append(base)
    return out


def drawing_items(d) -> list:
    out = []
    for space in list(d.spaces):
        if space.startswith("part:"):
            continue
        for e in d.entities(space):
            if getattr(e, "kind", "") != "dimension":
                continue
            ov = getattr(e, "overrides", {}) or {}
            angular = e.dim_type in ("angular", "angular3")
            unit = "deg" if angular else "mm"
            f = 1.0 if angular else mm_per_unit(d)
            nom = float(e.measurement) * f
            label = e.text_override if e.text_override and e.text_override.strip() and "<>" not in e.text_override else ("%.4g" % nom)
            plus = abs(float(ov.get("DIMTP", 0.0) or 0.0)) * f
            minus = abs(float(ov.get("DIMTM", 0.0) or 0.0)) * f
            out.append({"source": {"type": "dimension", "ref": str(e.handle)}, "kind": "dimension", "label": label, "nominal": nom, "plus": plus, "minus": minus, "unit": unit, "view": space, "anchor": [float(v) for v in (e.text_point or e.def_point)[:3]]})
    return out


def collect(d, caller: str = "") -> dict:
    h = header(d)
    limit = AGENT_ITEMS if caller else MAX_ITEMS
    found = pmi_items(d) + drawing_items(d)
    have = {key_of(i): i for i in h["items"]}
    added = updated = 0
    seen = set()
    for f in found:
        k = key_of(f)
        seen.add(k)
        cur = have.get(k)
        if cur is None:
            if len(h["items"]) >= limit:
                raise InspectError("At most %d characteristics here." % limit)
            item = new_item(h, f)
            item["n"] = 1 + max([i["n"] for i in h["items"]] or [0])
            bounds_of(item)
            if f["kind"] == "tolerance":
                item["lower"], item["upper"] = f["lower"], f["upper"]
            h["items"].append(item)
            added += 1
        else:
            for fld in ("label", "kind", "unit", "char", "datums", "state", "anchor", "view"):
                if f.get(fld) is not None and cur.get(fld) != f.get(fld):
                    cur[fld] = f[fld]
            if not cur.get("locked_values"):
                for fld in ("nominal", "plus", "minus"):
                    if f.get(fld) is not None and cur.get(fld) != f.get(fld):
                        cur[fld] = f[fld]
                        updated += 1
                if cur["kind"] == "tolerance":
                    cur["lower"], cur["upper"] = f["lower"], f["upper"]
                else:
                    bounds_of(cur)
    lost = 0
    for i in h["items"]:
        if i["source"]["type"] in ("pmi", "dimension") and key_of(i) not in seen:
            if i.get("state") != "lost":
                i["state"] = "lost"
            lost += 1
    save(d, h)
    return {"added": added, "updated": updated, "lost": lost, "count": len(h["items"])}


def listing(d) -> dict:
    h = header(d)
    items = sorted(h["items"], key=lambda i: i["n"])
    return {"items": items, "settings": h["settings"], "report": h["report"], "limits": {"items": MAX_ITEMS, "actuals": MAX_ACTUALS}}


def find(h: dict, ident) -> dict:
    s = str(ident or "").strip().upper()
    for i in h["items"]:
        if i["id"] == s or str(i["n"]) == s:
            return i
    raise InspectError("There is no characteristic %s." % ident)


def add_manual(d, args: dict, caller: str = "") -> dict:
    h = header(d)
    if len(h["items"]) >= (AGENT_ITEMS if caller else MAX_ITEMS):
        raise InspectError("The characteristic limit is reached.")
    kind = str(args.get("kind") or "dimension").lower()
    if kind not in KINDS:
        raise InspectError("The kind is %s." % ", ".join(KINDS))
    item = new_item(h, {"kind": kind, "label": text(args.get("label"), "The label"), "unit": text(args.get("unit") or "mm", "The unit", 12)})
    item["n"] = 1 + max([i["n"] for i in h["items"]] or [0])
    item["source"] = {"type": "manual", "ref": item["id"]}
    apply(item, args, True)
    h["items"].append(item)
    save(d, h)
    return copy.deepcopy(item)


def apply(item: dict, args: dict, creating=False) -> None:
    for fld in ("label", "method", "view", "note"):
        if fld in args:
            item[fld] = text(args[fld], fld.capitalize())
    if "class" in args:
        c = str(args["class"] or "").lower()
        if c not in CLASSES:
            raise InspectError("The class is %s." % ", ".join(c for c in CLASSES if c))
        item["class"] = c
    if "qty" in args:
        q = int(number(args["qty"], "The quantity") or 1)
        if not 1 <= q <= MAX_ACTUALS:
            raise InspectError("The quantity is 1 to %d." % MAX_ACTUALS)
        item["qty"] = q
    for fld in ("nominal", "plus", "minus", "lower", "upper"):
        if fld in args:
            v = number(args[fld], "The " + fld)
            item[fld] = abs(v) if fld in ("plus", "minus") and v is not None else v
            if not creating and item["source"]["type"] in ("pmi", "dimension"):
                item["locked_values"] = True
    if any(f in args for f in ("nominal", "plus", "minus")) and not any(f in args for f in ("lower", "upper")):
        bounds_of(item)
    if item["lower"] is not None and item["upper"] is not None and item["lower"] > item["upper"]:
        raise InspectError("The lower limit is above the upper limit.")
    if "actuals" in args:
        vals = args["actuals"]
        if not isinstance(vals, list) or len(vals) > MAX_ACTUALS:
            raise InspectError("actuals is a list of at most %d numbers." % MAX_ACTUALS)
        item["actuals"] = [number(v, "An actual value") for v in vals]


def edit(d, ident, args: dict) -> dict:
    h = header(d)
    item = find(h, ident)
    apply(item, args)
    save(d, h)
    return copy.deepcopy(item)


def remove(d, ident) -> dict:
    h = header(d)
    item = find(h, ident)
    h["items"].remove(item)
    drop_balloons(d, [item["balloon"]] if item.get("balloon") else [])
    save(d, h)
    return {"removed": item["id"]}


def renumber(d, order=None) -> dict:
    h = header(d)
    items = sorted(h["items"], key=lambda i: i["n"])
    if order:
        ids = [str(o).upper() for o in order]
        if sorted(ids) != sorted(i["id"] for i in items):
            raise InspectError("order must list every characteristic id once.")
        by = {i["id"]: i for i in items}
        items = [by[i] for i in ids]
    for n, item in enumerate(items, start=1):
        item["n"] = n
    save(d, h)
    return {"count": len(items), "order": [i["id"] for i in items]}


def drop_balloons(d, handles) -> int:
    n = 0
    for hd in handles:
        if hd and d.ents.get(int(hd)) is not None:
            d.erase_entity(int(hd))
            n += 1
    return n


def balloons(d) -> dict:
    h = header(d)
    off = float(h["settings"].get("balloon_offset", 12.0))
    stale = [e.handle for sp in list(d.spaces) for e in d.entities(sp) if getattr(e, "kind", "") == "balloon" and str(getattr(e, "part_key", "")).startswith(BALLOON_TAG)]
    removed = drop_balloons(d, stale)
    made = 0
    for item in sorted(h["items"], key=lambda i: i["n"]):
        item["balloon"] = None
        if item["source"]["type"] != "dimension" or item.get("state") == "lost" or not item.get("anchor"):
            continue
        tip = item["anchor"]
        e = ann_ops.new_balloon(d, {"point": [tip[0] + off, tip[1] + off], "text": str(item["n"]), "tip": [tip[0], tip[1]], "part_key": BALLOON_TAG + item["id"]})
        item["balloon"] = d.add_entity(e, item.get("view") or "model")
        made += 1
    save(d, h)
    return {"made": made, "removed": removed}


def model_balloons(d) -> list:
    h = header(d)
    by = {}
    drawn, _cut = geo.display(d)
    for it in drawn:
        by[it["id"]] = it
    out = []
    for item in sorted(h["items"], key=lambda i: i["n"]):
        if item["source"]["type"] != "pmi":
            continue
        row = by.get(item["source"]["ref"])
        if not row or row.get("state") != "ok":
            continue
        out.append({"id": item["id"], "n": item["n"], "text": str(item["n"]), "anchor": row.get("text_at") or row.get("anchor"), "pmi": item["source"]["ref"], "class": item["class"]})
    return out


def verdict(item: dict) -> dict:
    vals = [v for v in item.get("actuals") or [] if v is not None]
    lo, hi = item.get("lower"), item.get("upper")
    if not vals:
        return {"result": "pending", "measured": 0, "failed": 0}
    bad = [v for v in vals if (lo is not None and v < lo - 1e-9) or (hi is not None and v > hi + 1e-9)]
    done = len(vals) >= item.get("qty", 1)
    return {"result": "fail" if bad else ("pass" if done else "partial"), "measured": len(vals), "failed": len(bad)}


def requirement(item: dict) -> str:
    if item["kind"] == "tolerance":
        return "%s %s%s" % (item.get("char", ""), ("<= %.4g" % item["upper"]) if item.get("upper") is not None else "", (" | " + " ".join(item["datums"])) if item.get("datums") else "")
    if item.get("nominal") is None:
        return item.get("label", "")
    return "%.4g (+%.4g / -%.4g) %s" % (item["nominal"], item.get("plus") or 0.0, item.get("minus") or 0.0, item.get("unit", ""))


def set_form(d, args: dict) -> dict:
    h = header(d)
    rep = h["report"]
    if "form1" in args:
        f = args["form1"]
        if not isinstance(f, dict) or len(f) > 40:
            raise InspectError("form1 is an object of at most 40 fields.")
        rep["form1"] = {text(k, "A field name", 60): text(v, "A field value") for k, v in f.items()}
    if "form2" in args:
        f = args["form2"]
        if not isinstance(f, dict):
            raise InspectError("form2 is an object with materials, processes and tests.")
        for key in ("materials", "processes", "tests"):
            if key in f:
                rows = f[key]
                if not isinstance(rows, list) or len(rows) > 100:
                    raise InspectError("%s is a list of at most 100 rows." % key)
                rep["form2"][key] = [{text(k, "A field name", 60): text(v, "A field value") for k, v in r.items()} for r in rows if isinstance(r, dict)]
    save(d, h)
    return rep


def build_report(doc) -> dict:
    d = doc.drawing
    h = header(d)
    p = props.get(d)
    f1 = {"Part number": p.get("part_number", ""), "Part name": p.get("description", "") or doc.name, "Revision": p.get("revision", ""), "Document": doc.name, "Organisation": "", "Date": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "Signature": ""}
    f1.update(h["report"].get("form1") or {})
    rows = []
    for item in sorted(h["items"], key=lambda i: i["n"]):
        v = verdict(item)
        rows.append({"n": item["n"], "id": item["id"], "kind": item["kind"], "label": item["label"], "requirement": requirement(item), "lower": item["lower"], "upper": item["upper"], "unit": item["unit"], "class": item["class"], "qty": item["qty"], "method": item["method"], "view": item["view"], "actuals": item["actuals"], "result": v["result"], "measured": v["measured"], "failed": v["failed"], "state": item.get("state", "ok"), "note": item["note"]})
    counts = {k: sum(1 for r in rows if r["result"] == k) for k in ("pass", "fail", "partial", "pending")}
    return {"title": TITLE, "layout_note": LAYOUT_NOTE, "form1": f1, "form2": h["report"]["form2"], "rows": rows, "counts": counts, "total": len(rows), "overall": "fail" if counts["fail"] else ("pass" if rows and counts["pass"] == len(rows) else "open")}


def csv_cell(v) -> str:
    s = "" if v is None else (("%.6g" % v) if isinstance(v, float) else str(v))
    return ("'" + s) if s[:1] in ("=", "+", "-", "@", "\t", "\r") and not re.match(r"^-?\d+(\.\d+)?([eE][-+]?\d+)?$", s) else s


def csv_text(rep: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Number", "Characteristic", "Requirement", "Lower", "Upper", "Unit", "Class", "Quantity", "Method", "View", "Actual values", "Result"])
    for r in rep["rows"]:
        w.writerow([csv_cell(x) for x in (r["n"], r["label"], r["requirement"], r["lower"], r["upper"], r["unit"], r["class"], r["qty"], r["method"], r["view"], "; ".join("%.6g" % a for a in r["actuals"] if a is not None), r["result"])])
    return out.getvalue()


def html_text(rep: dict) -> str:
    e = html.escape

    def table(head, rows):
        return "<table><tr>%s</tr>%s</table>" % ("".join("<th>%s</th>" % e(h) for h in head), "".join("<tr>%s</tr>" % "".join("<td>%s</td>" % e(str(c)) for c in r) for r in rows))

    f1 = "".join("<tr><th>%s</th><td>%s</td></tr>" % (e(k), e(str(v))) for k, v in rep["form1"].items())
    f2 = ""
    for key, title in (("materials", "Materials"), ("processes", "Special processes"), ("tests", "Functional tests")):
        rows = rep["form2"].get(key) or []
        if rows:
            cols = sorted({k for r in rows for k in r})
            f2 += "<h3>%s</h3>%s" % (e(title), table(cols, [[r.get(c, "") for c in cols] for r in rows]))
    body = table(["No.", "Characteristic", "Requirement", "Class", "Qty", "Method", "Actual values", "Result"], [[r["n"], r["label"], r["requirement"], r["class"], r["qty"], r["method"], "; ".join("%.6g" % a for a in r["actuals"] if a is not None), r["result"]] for r in rep["rows"]])
    c = rep["counts"]
    css = "body{font:13px sans-serif;margin:24px;color:#111}table{border-collapse:collapse;margin:8px 0 16px}th,td{border:1px solid #888;padding:3px 8px;text-align:left}th{background:#eee}h1{font-size:20px}h2{font-size:16px;margin-top:24px}h3{font-size:14px}.n{color:#555}"
    return "<!doctype html><html><head><meta charset=\"utf-8\"><title>%s</title><style>%s</style></head><body><h1>%s</h1><p class=\"n\">%s</p><h2>1 Part accountability</h2><table>%s</table><h2>2 Product accountability</h2>%s<h2>3 Characteristic accountability</h2>%s<p>Characteristics: %d. Passed %d, failed %d, partly measured %d, pending %d. Overall: %s.</p></body></html>" % (e(rep["title"]), css, e(rep["title"]), e(rep["layout_note"]), f1, f2 or "<p>No entries.</p>", body, rep["total"], c["pass"], c["fail"], c["partial"], c["pending"], e(rep["overall"]))


def export(doc, path: str, kind: str = "") -> dict:
    if not os.path.isabs(os.path.expanduser(str(path or ""))):
        raise OutputRefused("Give the full path of the report file.")
    full = checked(str(path), (".html", ".csv"), ".html")
    ext = os.path.splitext(full)[1].lower()
    rep = build_report(doc)
    body = html_text(rep) if ext == ".html" else csv_text(rep)
    with open(full + ".part", "w", encoding="utf-8", newline="") as fh:
        fh.write(body)
    os.replace(full + ".part", full)
    return {"path": full, "bytes": len(body.encode("utf-8")), "rows": rep["total"], "format": ext[1:]}


def import_results(d, path: str, caller: str = "", runner=None) -> dict:
    full, raw = library.read_text(path, caller, runner)
    rows = library.parse_table(raw)
    head = [re.sub(r"[^a-z0-9]+", "", c.lower()) for c in rows[0]]
    num = next((i for i, c in enumerate(head) if c in ("number", "n", "no", "id", "item")), None)
    cols = [i for i, c in enumerate(head) if c.startswith("actual") or c.startswith("result") or c.startswith("measured")]
    if num is None or not cols:
        raise InspectError("The results table needs a Number column and one or more Actual columns.")
    if len(rows) - 1 > MAX_ITEMS:
        raise InspectError("The results table has too many rows.")
    h = header(d)
    set_n = 0
    problems = []
    for ln, r in enumerate(rows[1:], start=2):
        try:
            item = find(h, r[num] if num < len(r) else "")
            vals = [number(r[i].replace(",", "."), "An actual value") for i in cols if i < len(r) and r[i].strip()]
        except (InspectError, AttributeError) as err:
            if len(problems) < 30:
                problems.append("Row %d: %s" % (ln, err))
            continue
        if len(vals) > MAX_ACTUALS:
            problems.append("Row %d: too many values." % ln)
            continue
        item["actuals"] = vals
        set_n += 1
    save(d, h)
    return {"file": full, "updated": set_n, "problems": problems}


ERRORS = (InspectError, OutputRefused, library.LibraryError, SolidError, pmi_store.PmiError, ann_ops.AnnError)
