import copy
import os

from app.doc import layouts as L
from app.output import plotstyle as P


def table_or_fail(d, name):
    t = P.find(d, name)
    if t is None:
        raise P.StyleError('Plot style table "%s" not found.' % name)
    return t


def apply(doc, action, args):
    d = doc.drawing
    a = str(action).strip().casefold()
    if a == "list":
        return {"tables": P.listing(d)}
    if a == "get":
        return P.describe(table_or_fail(d, args.get("name")))
    if a == "create":
        kind = str(args.get("kind", "named")).strip().casefold()
        name = str(args.get("name", "")).strip()
        if not name:
            raise P.StyleError("A plot style table needs a name.")
        if P.find(d, name) is not None and P.find(d, name).get("stored"):
            raise P.StyleError('A plot style table named "%s" already exists.' % name)
        t = P.new_table(kind, name, str(args.get("description", "")))
        P.store(doc, t)
        return P.describe(P.find(d, name))
    if a == "copy":
        src = table_or_fail(d, args.get("name"))
        new = str(args.get("to") or "%s-copy" % src["name"]).strip()
        t = copy.deepcopy(src)
        t["name"] = new
        t.pop("builtin", None)
        t.pop("file", None)
        P.store(doc, t)
        return P.describe(P.find(d, new))
    if a == "delete":
        t = table_or_fail(d, args.get("name"))
        if not t.get("stored"):
            raise P.StyleError("Only tables stored in the drawing can be deleted.")
        d.table_remove("plotstyles", t["name"])
        for rec in L.records(d):
            if str(rec.get("page_setup", {}).get("style_table", "")).casefold() == t["name"].casefold():
                L.set_page_setup(d, rec["name"], {"style_table": ""})
        return {"deleted": t["name"]}
    if a in ("setstyle", "addstyle", "removestyle", "describe"):
        rec = P.editable_copy(doc, args.get("table"))
        t = P.clean_table(rec)
        if a == "setstyle":
            P.edit_style(t, args.get("style"), args.get("fields") or {})
        elif a == "addstyle":
            P.add_style(t, args.get("style"), args.get("fields"))
        elif a == "removestyle":
            P.remove_style(t, args.get("style"))
        if "description" in args and a == "describe":
            t["description"] = str(args["description"])[:1024]
        P.store(doc, t)
        return P.describe(P.find(d, t["name"]))
    if a == "load":
        path = args.get("path")
        if path:
            full = os.path.abspath(os.path.expanduser(str(path)))
            try:
                if os.path.getsize(full) > P.MAX_FILE:
                    raise P.StyleError("The plot style file is larger than 4 MiB.")
                with open(full, "r", encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                raise P.StyleError('The plot style file "%s" could not be read.' % path)
            except UnicodeDecodeError:
                raise P.StyleError('The plot style file "%s" is not text.' % path)
        else:
            text = str(args.get("text", ""))
        t = P.parse_file(text)
        if args.get("name"):
            t["name"] = str(args["name"]).strip()
        P.store(doc, t)
        return P.describe(P.find(d, t["name"]))
    if a == "save":
        t = table_or_fail(d, args.get("name"))
        path = P.save_to_folder(t, args.get("path"))
        return {"path": path, "name": t["name"]}
    if a == "use":
        layout = str(args.get("layout", ""))
        name = args.get("name")
        none = str(name or "").strip().casefold() in P.NONE_NAMES
        if not none:
            table_or_fail(d, name)
        changes = {"style_table": "" if none else str(name)}
        if "display" in args:
            changes["display_styles"] = bool(args["display"])
        return {"layout": layout, "page_setup": L.set_page_setup(d, layout, changes)}
    raise P.StyleError("Unknown plot style action %s." % action)


MUTATING = ("create", "copy", "delete", "setstyle", "addstyle", "removestyle", "describe", "load", "use")
