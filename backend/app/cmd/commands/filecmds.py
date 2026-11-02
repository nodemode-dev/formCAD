import os

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import audit as A
from app.doc import compare as C
from app.doc import recover as R
from app.doc import savecheck, templates
from app.doc.service import DocumentFault, service
from app.interchange import files
from app.interchange.errors import InterchangeError
from app.sysvars import registry as sv


def fault(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except DocumentFault as err:
        raise CommandError(err.message)


def pack_doc(doc) -> dict:
    return {"doc": doc.id, "name": doc.name, "untitled": not doc.path}


def new_drawing(ctx, template: str, name: str = ""):
    t = str(template or "").strip()
    if t == ".":
        t = ""
    doc = fault(service.new, name, t)
    ctx.say("New drawing %s." % doc.name)
    return pack_doc(doc)


def default_template() -> str:
    return str(sv.session_value("QNEWTEMPLATE") or "").strip()


@command("new", group="file", label="New", description="Start a new untitled drawing, from a template file or blank.", menu="File > New...", undoable=False, repeatable=False)
def new_cmd(ctx):
    default = default_template() or "."
    r = yield ctx.text("Enter template file name or . for none", default)
    if r.kind == "enter":
        new_drawing(ctx, default)
    elif r.kind == "text":
        new_drawing(ctx, str(r.value))


@executes("new")
def new_exec(ctx, args):
    t = args.get("template")
    return new_drawing(ctx, default_template() if t is None else str(t), str(args.get("name", "") or ""))


@command("qnew", group="file", label="Quick New", description="Start a new untitled drawing from the default template without asking.", menu="File > Quick New", undoable=False, repeatable=False)
def qnew_cmd(ctx):
    new_drawing(ctx, default_template())


@executes("qnew")
def qnew_exec(ctx, args):
    return new_drawing(ctx, default_template(), str(args.get("name", "") or ""))


def set_template(ctx, ref: str):
    r = str(ref or "").strip()
    if r in ("", "."):
        ctx.setvar("QNEWTEMPLATE", "")
        ctx.say("New drawings start blank.")
        return {"template": ""}
    if templates.lookup(r) is None:
        path = templates.file_for(r)
        if path is None:
            raise CommandError('Cannot find the template "%s".' % r)
        r = path
    ctx.setvar("QNEWTEMPLATE", r)
    ctx.say("New drawings start from %s." % r)
    return {"template": r}


@command("qnewtemplate", group="file", label="Default Template", description="Choose the template file NEW starts from.", menu="Tools > Options", undoable=False, repeatable=False)
def qnewtemplate_cmd(ctx):
    r = yield ctx.text("Enter template file name or . for none", default_template() or ".")
    if r.kind == "text":
        set_template(ctx, str(r.value))
    elif r.kind == "enter":
        set_template(ctx, default_template())


@executes("qnewtemplate")
def qnewtemplate_exec(ctx, args):
    return set_template(ctx, str(args.get("template", "")))


def target_doc(ctx, ref):
    if ref in (None, ""):
        return ctx.doc
    docs = list(service.docs.values())
    s = str(ref)
    if s.isdigit() and 1 <= int(s) <= len(docs):
        return docs[int(s) - 1]
    for d in docs:
        if d.id == s or d.name.casefold() == s.casefold():
            return d
    raise CommandError("no such drawing")


def save_before_close(doc):
    if not doc.path:
        raise CommandError("%s was not saved; it stays open." % doc.name)
    fault(service.save, doc)


def close_now(ctx, doc, save: bool = False, ifclean: bool = False) -> dict:
    if ifclean and doc.dirty:
        return {"closed": False, "dirty": True, "id": doc.id, "name": doc.name}
    if save:
        save_before_close(doc)
    service.close(doc, True)
    ctx.say("Closed %s." % doc.name)
    return {"closed": True, "id": doc.id, "name": doc.name, "active": service.active_id}


def close_later(ctx, doc, save=False) -> None:
    def go():
        if doc.id in service.docs:
            try:
                if save:
                    save_before_close(doc)
                service.close(doc, True)
            except (CommandError, DocumentFault):
                pass

    ctx.runner.later.append(go)


def ask_save(ctx, doc):
    r = yield ctx.keyword("Save changes to %s?" % doc.name, ["Yes", "No", "Cancel"], "Yes")
    if r.kind == "enter":
        return "Yes"
    return r.value if r.kind == "keyword" else "Cancel"


@command("close", group="file", label="Close", description="Close the current drawing, asking about unsaved changes.", menu="File > Close", undoable=False, repeatable=False)
def close_cmd(ctx):
    doc = ctx.doc
    save = False
    if doc.dirty:
        ans = yield from ask_save(ctx, doc)
        if ans == "Cancel":
            ctx.say("Close cancelled.")
            return
        if ans == "Yes":
            if not doc.path:
                ctx.say("%s was not saved; it stays open." % doc.name)
                return
            save = True
    close_later(ctx, doc, save)


@executes("close")
def close_exec(ctx, args):
    return close_now(ctx, target_doc(ctx, args.get("doc")), bool(args.get("save", False)), bool(args.get("ifclean", False)))


@command("closeall", group="file", label="Close All", description="Close every open drawing, asking about each one with unsaved changes.", menu="File > Close All", undoable=False, repeatable=False)
def closeall_cmd(ctx):
    plan = []
    for doc in list(service.docs.values()):
        save = False
        if doc.dirty:
            ans = yield from ask_save(ctx, doc)
            if ans == "Cancel":
                ctx.say("Close All stopped.")
                break
            if ans == "Yes":
                if not doc.path:
                    ctx.say("%s was not saved; it stays open." % doc.name)
                    continue
                save = True
        plan.append((doc, save))
    for doc, save in plan:
        close_later(ctx, doc, save)


@executes("closeall")
def closeall_exec(ctx, args):
    closed = []
    kept = []
    for doc in list(service.docs.values()):
        if args.get("ifclean") and doc.dirty:
            kept.append(doc.id)
            continue
        close_now(ctx, doc, bool(args.get("save", False)))
        closed.append(doc.id)
    return {"closed": closed, "kept": kept}


def do_save(ctx, path: str = "") -> dict:
    doc = ctx.doc
    target = (path or doc.path or "").strip()
    if not target:
        raise CommandError("drawing has no file name yet; use saveas {path}")
    if savecheck.guard(doc):
        raise CommandError(savecheck.guard(doc))
    res = savecheck.loss(doc, target)
    out = {"path": target}
    if res["dropped"]:
        out["dropped"] = res["dropped"]
        ctx.say("Not saved in the file: " + ", ".join("%d %s" % (n, k) for k, n in sorted(res["dropped"].items())))
    if os.path.splitext(target)[1].lower() in (".dxf", ".dwg"):
        fault(service.save_foreign, doc, target, getattr(doc, "save_version", ""), bool(getattr(doc, "save_binary", False)))
    else:
        fault(service.save, doc, path)
    out["path"] = doc.path
    ctx.say("Saved %s." % doc.path)
    return out


@command("save", aliases=("qsave",), group="file", label="Save", description="Save the drawing to its own file.", menu="File > Save", undoable=False, repeatable=False)
def save_cmd(ctx):
    doc = ctx.doc
    if not doc.path:
        raise CommandError("drawing has no file name yet; use saveas {path}")
    res = savecheck.loss(doc, doc.path)
    if res["dropped"] and not savecheck.agreed(doc, doc.path, res):
        names = ", ".join("%d %s" % (c["count"], c["name"]) for c in res["types"])
        if res["more"]:
            names += " and %d more types" % res["more"]
        ctx.say("Saving %s will remove content: %s" % (doc.name, names))
        ctx.say("DXF keeps them. Use Save As to keep them in the drawing.")
        r = yield ctx.keyword("Save anyway", ["Save As", "Cancel", "Save Anyway"], "Cancel")
        if r.kind != "keyword" or r.value != "Save Anyway":
            ctx.say("Save cancelled: %s was not changed." % doc.path)
            return
        savecheck.agree(doc, doc.path, res)
    do_save(ctx)


@executes("save")
def save_exec(ctx, args):
    return do_save(ctx, str(args.get("path", "") or ""))


def run_audit(ctx, fix: bool) -> dict:
    res = A.run(ctx.doc, fix)
    for ln in res["lines"]:
        ctx.say(ln)
    out = {k: res[k] for k in ("errors", "fixed", "issues", "lines")}
    if int(sv.get_var(ctx.doc, "AUDITCTL")) and ctx.doc.path:
        path = A.report_path(ctx.doc)
        from app.doc import container

        body = "Audit of drawing: %s\n%s\n" % (ctx.doc.path, "\n".join(res["lines"]))
        try:
            container.atomic_write(path, body.encode("utf-8"), 0o600)
            out["report"] = path
        except OSError:
            pass
    return out


@command("audit", group="file", label="Audit", description="Check the drawing for errors and optionally repair them.", menu="File > Drawing Utilities > Audit", undoable=True, repeatable=False)
def audit_cmd(ctx):
    r = yield ctx.yesno("Fix any errors detected?", "No")
    fix = r.kind == "keyword" and r.value == "Yes"
    run_audit(ctx, fix)


@executes("audit")
def audit_exec(ctx, args):
    return run_audit(ctx, bool(args.get("fix", False)))


def do_recover(ctx, path: str, copy: bool = False) -> dict:
    full = os.path.realpath(os.path.expanduser(str(path or "")))
    if not os.path.isfile(full):
        raise CommandError('Cannot find the file "%s".' % path)
    ext = os.path.splitext(full)[1].lower()
    from app.doc.document import Document

    if ext == ".fcad":
        try:
            drawing, manifest, notes = R.tolerant(full)
        except R.RecoverError as err:
            raise CommandError(str(err))
        kind = manifest.get("kind") if manifest.get("kind") in templates.KINDS else "drawing"
        doc = Document(drawing, os.path.splitext(os.path.basename(full))[0], "" if copy else full, kind, drawing.metric)
    else:
        try:
            drawing, report, _k = files.read_any(full, True)
        except InterchangeError as err:
            raise CommandError(str(err))
        notes = list(report.notes)
        doc = Document(drawing, os.path.splitext(os.path.basename(full))[0], "" if copy or ext not in (".dxf", ".dwg") else full, "drawing", drawing.metric)
    for n in notes:
        ctx.say(n)
    with service.lock:
        service._register(doc)
    res = A.run(doc, False)
    fixed = 0
    if res["errors"]:
        with doc.transaction("RECOVER"):
            res = A.run(doc, True)
        fixed = res["fixed"]
    if fixed or notes:
        doc.saved_state = -1
        doc.dirty_since = doc.dirty_since or 1.0
    for ln in res["lines"]:
        ctx.say(ln)
    ctx.say("Recovered %s." % doc.name)
    out = pack_doc(doc)
    out.update({"errors": res["errors"], "fixed": fixed, "notes": notes, "dirty": doc.dirty})
    return out


@command("recover", group="file", label="Recover", description="Open a damaged drawing as tolerantly as possible and repair it.", menu="File > Drawing Utilities > Recover...", undoable=False, repeatable=False)
def recover_cmd(ctx):
    r = yield ctx.text("Enter file name to recover")
    if r.kind == "text":
        do_recover(ctx, str(r.value).strip())


@executes("recover")
def recover_exec(ctx, args):
    return do_recover(ctx, str(args.get("path", "")), bool(args.get("copy", False)))


def recovery_action(ctx, action: str, name: str = "") -> dict:
    a = action.lower()
    if a == "list":
        items = service.recovery_list()
        for i in items:
            ctx.say("%s  %s  %d bytes" % (i["file"], i["modified"], i["size"]))
        if not items:
            ctx.say("No autosaved drawings are waiting.")
        return {"items": items}
    if a == "open":
        doc = fault(service.recovery_open, name)
        ctx.say("Opened %s as an unsaved copy." % doc.name)
        return pack_doc(doc)
    if a == "discard":
        ok = service.recovery_discard(name)
        if not ok:
            raise CommandError("That recovery file is not available.")
        ctx.say("Recovery file removed.")
        return {"discarded": name}
    raise CommandError("Recovery action is list, open or discard.")


@command("drawingrecovery", aliases=("recoverymanager",), group="file", label="Drawing Recovery Manager", description="List, open or discard drawings autosaved by an app that did not close normally.", menu="File > Drawing Utilities > Drawing Recovery Manager", undoable=False, repeatable=False)
def drawingrecovery_cmd(ctx):
    recovery_action(ctx, "list")
    items = service.recovery_list()
    if not items:
        return
    r = yield ctx.keyword("Recovery action", ["Open", "Discard", "Later"], "Later")
    if r.kind != "keyword" or r.value == "Later":
        return
    n = yield ctx.text("Enter the file name from the list", items[0]["file"])
    name = items[0]["file"] if n.kind == "enter" else (str(n.value).strip() if n.kind == "text" else "")
    if name:
        recovery_action(ctx, r.value, name)


@executes("drawingrecovery")
def drawingrecovery_exec(ctx, args):
    return recovery_action(ctx, str(args.get("action", "list")), str(args.get("file", "")))


def other_drawing(ctx, args):
    spec = str(args.get("other", "") or args.get("path", "")).strip()
    if args.get("data"):
        d, name = C.load_other("", str(args["data"]), str(args.get("name", "")))
        return (lambda: d), name, ""
    live = C.find_open(service, spec, ctx.doc)
    if live is not None:
        if live is ctx.doc:
            raise CommandError("A drawing cannot be compared with itself.")
        return (lambda: live.drawing), live.name, live.path
    if not spec:
        raise CommandError("Name the drawing to compare with.")
    full = os.path.realpath(os.path.expanduser(spec))
    if ctx.doc.path and os.path.realpath(ctx.doc.path) == full:
        raise CommandError("A drawing cannot be compared with itself.")
    return (lambda: C.read_file(spec)), os.path.splitext(os.path.basename(spec))[0], full


def guard_compare(fn, *a):
    try:
        return fn(*a)
    except C.CompareError as err:
        raise CommandError(str(err))


def say_result(ctx, st) -> None:
    c = st["counts"]
    ctx.say("Compared with %s: %d the same, %d only in this drawing, %d only in the other, %d changed." % (st["other"], c["same"], c["only_this"], c["only_other"], c["changed"]))
    if st["left_out"]:
        ctx.say("%d objects were left out because of the %d object limit." % (st["left_out"], C.MAX_OBJECTS))
    if not st["listed_all"]:
        ctx.say("At most %d differences of each kind are listed." % C.MAX_LISTED)
    ctx.say("%d change area%s." % (len(st["areas"]), "" if len(st["areas"]) == 1 else "s"))


def do_compare(ctx, args) -> dict:
    getter, name, path = guard_compare(other_drawing, ctx, args)
    st = C.compare(ctx.doc, getter(), name, path)
    st["_reload"] = getter
    ctx.doc.compare = st
    say_result(ctx, st)
    ctx.doc.announce("compare")
    return C.public(st)


@command("compare", group="file", label="Compare Drawings", description="Compare this drawing's current tab with another drawing.", menu="Tools > Compare", undoable=False, repeatable=False)
def compare_cmd(ctx):
    r = yield ctx.text("Enter the drawing to compare with (an open drawing's name or a file path)")
    if r.kind == "text":
        do_compare(ctx, {"other": str(r.value).strip()})


@executes("compare")
def compare_exec(ctx, args):
    return do_compare(ctx, args)


def state_of(ctx):
    st = getattr(ctx.doc, "compare", None)
    if st is None:
        raise CommandError("There is no comparison; run COMPARE first.")
    return st


def go_area(ctx, step: int) -> dict:
    st = state_of(ctx)
    n = len(st["areas"])
    if n == 0:
        ctx.say("The drawings do not differ.")
        return {"index": -1, "count": 0}
    st["index"] = (st["index"] + step) % n
    box = st["areas"][st["index"]]["box"]
    w = box[2] - box[0]
    h = box[3] - box[1]
    height = max(h, w / getattr(ctx.doc, "aspect", 1.6), 1e-6) * 1.5
    center = [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0]
    ctx.doc.set_view(center, height)
    ctx.doc.request_view("window", center=list(center), height=height)
    ctx.say("Change area %d of %d." % (st["index"] + 1, n))
    return {"index": st["index"], "count": n, "box": box}


@command("comparenext", group="file", label="Next Change", description="Zoom to the next change area of the comparison.", menu="Tools > Compare > Next Change", undoable=False, repeatable=False)
def comparenext_cmd(ctx):
    go_area(ctx, 1)


@executes("comparenext")
def comparenext_exec(ctx, args):
    return go_area(ctx, 1)


@command("compareprevious", group="file", label="Previous Change", description="Zoom to the previous change area of the comparison.", menu="Tools > Compare > Previous Change", undoable=False, repeatable=False)
def compareprevious_cmd(ctx):
    go_area(ctx, -1)


@executes("compareprevious")
def compareprevious_exec(ctx, args):
    return go_area(ctx, -1)


def do_close_compare(ctx) -> dict:
    had = getattr(ctx.doc, "compare", None) is not None
    ctx.doc.compare = None
    ctx.say("Comparison closed." if had else "There is no comparison.")
    if had:
        ctx.doc.announce("compare")
    return {"closed": had}


@command("compareclose", group="file", label="Close Comparison", description="Discard the comparison result.", menu="Tools > Compare > Close", undoable=False, repeatable=False)
def compareclose_cmd(ctx):
    do_close_compare(ctx)


@executes("compareclose")
def compareclose_exec(ctx, args):
    return do_close_compare(ctx)


def do_export(ctx) -> dict:
    st = state_of(ctx)
    fresh = C.compare(ctx.doc, st["_reload"](), st["other"], st["other_path"])
    fresh["_reload"] = st["_reload"]
    ctx.doc.compare = fresh
    new = C.export(ctx.doc, fresh, service, fresh["_drawing"])
    ctx.say("The comparison was exported to the new drawing %s." % new.name)
    out = pack_doc(new)
    out["counts"] = fresh["counts"]
    out["objects"] = len(new.drawing.ents)
    return out


@command("compareexport", aliases=("comparexport",), group="file", label="Export Comparison", description="Put the differences in a new drawing, coloured by side.", menu="Tools > Compare > Export", undoable=False, repeatable=False)
def comparexport_cmd(ctx):
    do_export(ctx)


@executes("compareexport")
def comparexport_exec(ctx, args):
    return do_export(ctx)
