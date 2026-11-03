import copy

from app.core.outputs import OutputRefused, checked
from app.harness import analyze, flat, sheet, store
from app.harness.store import HarnessError

ERRORS = (HarnessError, OutputRefused, store.rules.RuleError)
KINDS = ("wirelist", "fromto", "segments", "connectors")


def listing(doc) -> dict:
    h = store.header(doc.drawing)
    return {"settings": h["settings"], "nodes": list(h["nodes"].values()), "segments": list(h["segments"].values()), "wires": list(h["wires"].values()), "cables": list(h["cables"].values()), "flat": h["flat"], "sheet": h["sheet"], "limits": store.MAX}


def report(doc) -> dict:
    h = store.header(doc.drawing)
    return analyze.run(doc, h)


def do(doc, action: str, args: dict, caller: str = "") -> dict:
    d = doc.drawing
    h = store.header(d)
    out = {}
    if action == "addnode":
        out = store.add_node(h, args, caller)
    elif action == "addsegment":
        out = store.add_segment(h, args, caller)
    elif action == "addwire":
        out = store.add_wire(h, args, caller)
    elif action == "addcable":
        out = store.add_cable(h, args, caller)
    elif action == "edit":
        out = store.edit(h, args.get("kind"), args.get("id"), args.get("changes"), caller)
    elif action == "remove":
        out = {"removed": store.remove(h, args.get("kind"), args.get("id"))}
    elif action == "settings":
        out = store.set_settings(h, args.get("changes") or {k: v for k, v in args.items() if k != "action"})
    elif action in ("flatten", "formboard"):
        rep = analyze.run(doc, h)
        h["flat"] = flat.layout(h, rep, args.get("trunk"), args.get("angle"), args.get("clearance"))
        out = {"flat": h["flat"]}
        if action == "formboard":
            out["sheet"] = sheet.draw(d, h, rep)
    elif action == "rotate":
        members = flat.rotate_branch(h["flat"], str(args.get("node") or ""), store.vec(args.get("to"), "to", 2))
        out = {"moved": members}
    elif action == "sheet":
        out = sheet.draw(d, h, analyze.run(doc, h))
    elif action == "clearsheet":
        sheet.clear(d, h)
        out = {"cleared": True}
    else:
        raise HarnessError("action is addnode, addsegment, addwire, addcable, edit, remove, settings, flatten, rotate, sheet, formboard or clearsheet.")
    store.save(d, h)
    return copy.deepcopy(out)


def export_csv(doc, kind: str, path: str, sep: str = ",") -> dict:
    kind = str(kind or "wirelist").lower()
    if kind not in KINDS:
        raise HarnessError("kind is %s." % ", ".join(KINDS))
    if sep not in (",", ";", "\t"):
        raise HarnessError("sep is a comma, a semicolon or a tab.")
    rep = analyze.run(doc, store.header(doc.drawing))
    tab = sheet.tables(store.header(doc.drawing), rep)[kind]
    text = sheet.csv_text(tab, sep)
    full = checked(str(path), (".csv",), ".csv")
    with open(full, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return {"path": full, "bytes": len(text.encode("utf-8")), "rows": len(tab["rows"]), "kind": kind}
