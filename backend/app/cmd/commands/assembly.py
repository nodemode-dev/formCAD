import os

from app.assembly import api, bom, cfg, light, model, parts, patterns, store, walk
from app.assembly import props as P
from app.assembly.store import AssemblyError
from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.solid.work import SolidError

FAILURES = (AssemblyError, P.PropError, SolidError, ValueError, KeyError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def comp_id(ctx, ident) -> str:
    return run(store.find_component, ctx.d, ident)["id"]


def folders_of(args) -> list:
    raw = args.get("folder")
    if raw is None:
        return []
    return [str(v) for v in (raw if isinstance(raw, list) else [raw]) if str(v).strip()]


def spec_of(args) -> object:
    for key in ("matrix", "frame"):
        if args.get(key) is not None:
            return {key: args[key]}
    spec = {}
    if args.get("translate") is not None:
        spec["translate"] = args["translate"]
    elif args.get("position") is not None:
        spec["translate"] = args["position"]
    if args.get("rotate") is not None:
        spec["rotate"] = args["rotate"]
    return spec or None


def point3(value):
    v = list(value)
    return [float(v[0]), float(v[1]), float(v[2]) if len(v) > 2 else 0.0]


def refused(ctx, name, args):
    msg = barred.args_refusal(ctx.runner, COMMANDS[name], args)
    if msg:
        raise CommandError(msg)


def say_status(ctx, rec, st):
    note = " (copy kept in this assembly)" if st["stale"] else ""
    ctx.say("%s %s: %s%s" % (rec["id"], rec["label"], st["status"], note))


@command("asminsert", aliases=("insertcomp", "addcomp"), group="solids", label="Insert Component", description="Add a part or assembly file to the assembly.", menu="Assembly > Insert Component")
def asminsert(ctx):
    t = yield ctx.text("Enter the part or assembly file to insert")
    if t.kind != "text":
        return
    refused(ctx, "asminsert", {"path": str(t.value)})
    pt = yield ctx.point("Specify the location of the component origin", default=[0.0, 0.0, 0.0])
    if pt.kind not in ("point", "text", "enter"):
        return
    where = point3(pt.value) if pt.kind == "point" else [0.0, 0.0, 0.0]
    rec = run(model.insert, ctx.doc, str(t.value), None, {"translate": where})
    ctx.say("Inserted %s as %s." % (rec["label"], rec["id"]))
    return {"id": rec["id"]}


@executes("asminsert")
def asminsert_exec(ctx, args):
    if not args.get("path"):
        raise CommandError("Give path.")
    rec = run(model.insert, ctx.doc, str(args["path"]), args.get("label"), spec_of(args), str(args.get("config") or ""), bool(args.get("relative", True)), args.get("fixed"), bool(args.get("visible", True)))
    return {"id": rec["id"], "label": rec["label"], "type": rec["type"], "message": "Inserted %s as %s." % (rec["label"], rec["id"])}


@command("asmremove", aliases=("delcomp",), group="solids", label="Remove Component", description="Remove a component and the patterns built on it.", menu="Assembly > Remove Component")
def asmremove(ctx):
    t = yield ctx.text("Enter the component name or id")
    if t.kind != "text":
        return
    out = run(model.remove, ctx.doc, comp_id(ctx, t.value))
    ctx.say("Removed %s." % out["component"])


@executes("asmremove")
def asmremove_exec(ctx, args):
    return run(model.remove, ctx.doc, comp_id(ctx, args.get("component")))


@command("asmmove", aliases=("movecomp",), group="solids", label="Move Component", description="Move or turn a component by a vector.", menu="Assembly > Move Component")
def asmmove(ctx):
    t = yield ctx.text("Enter the component name or id")
    if t.kind != "text":
        return
    cid = comp_id(ctx, t.value)
    pt = yield ctx.point("Specify the move vector", default=[0.0, 0.0, 0.0])
    if pt.kind != "point":
        return
    run(model.set_transform, ctx.doc, cid, {"translate": point3(pt.value)}, True)
    ctx.say("Moved %s." % cid)


@executes("asmmove")
def asmmove_exec(ctx, args):
    spec = spec_of(args)
    if spec is None:
        raise CommandError("Give matrix, frame, translate or rotate.")
    return run(model.set_transform, ctx.doc, comp_id(ctx, args.get("component")), spec, bool(args.get("relative", False)), bool(args.get("force", False)))


@command("asmflags", aliases=("asmsuppress", "suppresscomp"), group="solids", label="Component State", description="Suppress, hide or fix a component.", menu="Assembly > Component State")
def asmflags(ctx):
    t = yield ctx.text("Enter the component name or id")
    if t.kind != "text":
        return
    cid = comp_id(ctx, t.value)
    k = yield ctx.keyword("State [Suppress/Resolve/Hide/Show/Fix/Float]", ["Suppress", "Resolve", "Hide", "Show", "Fix", "Float"], "Suppress")
    word = (k.value if k.kind == "keyword" else "").lower()
    table = {"suppress": {"suppressed": True}, "resolve": {"suppressed": False}, "hide": {"visible": False}, "show": {"visible": True}, "fix": {"fixed": True}, "float": {"fixed": False}}
    if word not in table:
        return
    run(model.set_flags, ctx.doc, cid, **table[word])
    ctx.say("%s: %s." % (cid, word))


@executes("asmflags")
def asmflags_exec(ctx, args):
    cid = comp_id(ctx, args.get("component"))
    out = {}
    if args.get("label") is not None:
        out["label"] = run(model.rename, ctx.doc, cid, str(args["label"]))["label"]
    if any(args.get(k) is not None for k in ("visible", "suppressed", "fixed")):
        out.update(run(model.set_flags, ctx.doc, cid, args.get("visible"), args.get("suppressed"), args.get("fixed")))
    if args.get("config") is not None:
        out["config"] = run(model.set_config, ctx.doc, cid, str(args["config"]))["config"]
    if args.get("props") is not None or args.get("remove_props"):
        out["props"] = run(model.set_props, ctx.doc, cid, args.get("props") or {}, args.get("remove_props") or ())
    if args.get("note") is not None:
        run(model.set_note, ctx.doc, cid, args["note"])
    out.setdefault("id", cid)
    return out


@command("asmreload", aliases=("reloadcomp",), group="solids", label="Reload Component", description="Take the current version of a component file into the assembly.", menu="Assembly > Reload Component")
def asmreload(ctx):
    t = yield ctx.text("Enter the component name or id (or ALL)")
    if t.kind != "text":
        return
    names = [r["id"] for r in store.components(ctx.d) if r["type"] != "embedded"] if t.value.strip().lower() == "all" else [comp_id(ctx, t.value)]
    for cid in names:
        out = run(model.reload, ctx.doc, cid)
        ctx.say("%s: %s" % (cid, "new version taken" if out["changed"] else "already current"))


@executes("asmreload")
def asmreload_exec(ctx, args):
    ident = args.get("component")
    if str(ident or "").lower() == "all":
        results = []
        for r in store.components(ctx.d):
            if r["type"] == "embedded":
                continue
            try:
                results.append(model.reload(ctx.doc, r["id"], folders_of(args), bool(args.get("deep", False)), bool(args.get("relative", True))))
            except AssemblyError as err:
                results.append({"id": r["id"], "error": str(err)})
        return {"results": results}
    return run(model.reload, ctx.doc, comp_id(ctx, ident), folders_of(args), bool(args.get("deep", False)), bool(args.get("relative", True)))


@command("asmreplace", aliases=("replacecomp",), group="solids", label="Replace Component", description="Point a component at a different file.", menu="Assembly > Replace Component")
def asmreplace(ctx):
    t = yield ctx.text("Enter the component name or id")
    if t.kind != "text":
        return
    cid = comp_id(ctx, t.value)
    f = yield ctx.text("Enter the replacement file")
    if f.kind != "text":
        return
    refused(ctx, "asmreplace", {"path": str(f.value)})
    run(model.replace, ctx.doc, cid, str(f.value))
    ctx.say("%s now uses %s." % (cid, os.path.basename(str(f.value))))


@executes("asmreplace")
def asmreplace_exec(ctx, args):
    if not args.get("path"):
        raise CommandError("Give path.")
    return run(model.replace, ctx.doc, comp_id(ctx, args.get("component")), str(args["path"]), bool(args.get("relative", True)))


@command("asmfind", aliases=("findcomp",), group="solids", label="Find Component File", description="Search for the file of a component and show the places looked in.", menu="Assembly > Find File")
def asmfind(ctx):
    t = yield ctx.text("Enter the component name or id")
    if t.kind != "text":
        return
    out = run(model.find, ctx.doc, comp_id(ctx, t.value))
    for step in out["log"]:
        ctx.say("%-15s %-5s %s" % (step["step"], "found" if step["found"] else "no", step["path"]))
    ctx.say("Found %s." % out["resolved"] if out["found"] else "Not found.")


@executes("asmfind")
def asmfind_exec(ctx, args):
    return run(model.find, ctx.doc, comp_id(ctx, args.get("component")), folders_of(args), bool(args.get("deep", False)), bool(args.get("relink", True)), bool(args.get("relative", True)))


@command("asmrebase", group="solids", label="Make Paths Relative", description="Rewrite stored file paths relative to the assembly folder.", menu="Assembly > Make Paths Relative")
def asmrebase(ctx):
    out = run(model.rebase, ctx.doc)
    ctx.say("%d path(s) rewritten, %d missing." % (len(out["changed"]), len(out["missing"])))


@executes("asmrebase")
def asmrebase_exec(ctx, args):
    return run(model.rebase, ctx.doc, bool(args.get("relative", True)))


@command("asmembed", group="solids", label="Embed Part", description="Turn solid bodies drawn in this assembly into an embedded component.", menu="Assembly > Embed Part")
def asmembed(ctx):
    s = yield ctx.select("Select solid bodies to embed")
    if s.kind != "selection":
        return
    found = [int(h) for h in s.value if ctx.d.get(int(h)) is not None and ctx.d.get(int(h)).kind == "solidbody"]
    rec = run(model.embed, ctx.doc, found)
    ctx.say("Embedded %s as %s." % (rec["label"], rec["id"]))


@executes("asmembed")
def asmembed_exec(ctx, args):
    rec = run(model.embed, ctx.doc, args.get("handles") or [], args.get("label"), args.get("fixed"))
    return {"id": rec["id"], "label": rec["label"]}


@command("asmpattern", group="solids", label="Component Pattern", description="Repeat a component in a line, around an axis, or on the sites of a part feature.", menu="Assembly > Component Pattern")
def asmpattern(ctx):
    k = yield ctx.keyword("Pattern [Linear/Circular/Feature/List/Delete]", ["Linear", "Circular", "Feature", "List", "Delete"], "Linear")
    word = (k.value if k.kind == "keyword" else "").lower()
    if word == "list":
        for p in store.patterns(ctx.d):
            ctx.say("%s %s of %s, %d copies" % (p["id"], p["kind"], p["seed"], patterns.count_of(p)))
        return
    if word == "delete":
        t = yield ctx.text("Enter the pattern id")
        if t.kind == "text":
            run(model.delete_pattern, ctx.doc, t.value.strip())
        return
    if word not in ("linear", "circular", "feature"):
        return
    t = yield ctx.text("Enter the seed component name or id")
    if t.kind != "text":
        return
    seed = comp_id(ctx, t.value)
    if word == "linear":
        n = yield ctx.number("Number of copies in all", default=3, integer=True, positive=True)
        dist = yield ctx.distance("Spacing", default=10.0, positive=True)
        if n.kind != "number" or dist.kind != "number":
            return
        params = {"dir1": [1, 0, 0], "spacing1": dist.value, "count1": int(n.value)}
    elif word == "circular":
        n = yield ctx.number("Number of copies in all", default=4, integer=True, positive=True)
        if n.kind != "number":
            return
        params = {"count": int(n.value)}
    else:
        tt = yield ctx.text("Enter the part component that holds the feature")
        ff = yield ctx.text("Enter the feature id or name")
        if tt.kind != "text" or ff.kind != "text":
            return
        params = {"target": tt.value.strip(), "feature": ff.value.strip()}
    rec = run(model.add_pattern, ctx.doc, word, seed, params)
    ctx.say("%s: %d copies." % (rec["id"], patterns.count_of(rec)))


@executes("asmpattern")
def asmpattern_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    if action == "list":
        return api.patterns_view(ctx.doc)
    if action in ("linear", "circular", "feature"):
        rec = run(model.add_pattern, ctx.doc, action, str(args.get("seed") or ""), args.get("params") or {}, str(args.get("label") or ""))
        return {"id": rec["id"], "count": patterns.count_of(rec), "pattern": rec}
    if action == "edit":
        rec = run(model.edit_pattern, ctx.doc, str(args.get("id") or ""), args.get("params"), args.get("label"), args.get("skip"), args.get("suppressed"))
        return {"id": rec["id"], "count": patterns.count_of(rec), "pattern": rec}
    if action == "delete":
        return run(model.delete_pattern, ctx.doc, str(args.get("id") or ""))
    raise CommandError("action is list, linear, circular, feature, edit or delete.")


@command("asmconfig", group="solids", label="Assembly Configurations", description="List, make or switch assembly configurations (suppression, visibility, component configuration).", menu="Assembly > Configurations")
def asmconfig(ctx):
    k = yield ctx.keyword("Configuration [List/Activate/Delete]", ["List", "Activate", "Delete"], "List")
    word = (k.value if k.kind == "keyword" else "").lower()
    if word == "list":
        info = cfg.listing(ctx.d)
        for r in info["configs"]:
            ctx.say("%s%s" % (r["name"], " (active)" if r["name"] == info["active"] else ""))
        return
    t = yield ctx.text("Enter the configuration name")
    if t.kind != "text":
        return
    if word == "activate":
        run(cfg.activate, ctx.d, t.value)
    elif word == "delete":
        run(cfg.delete, ctx.d, t.value)


@executes("asmconfig")
def asmconfig_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    d = ctx.d
    if action == "list":
        return cfg.listing(d)
    name = str(args.get("name") or "")
    if action == "create":
        return run(cfg.create, d, name, args.get("description", ""), args.get("suppress"), args.get("visible"), args.get("component_config"), args.get("patterns"), args.get("copy_from"))
    if action == "edit":
        return run(cfg.update, d, name, args.get("description"), args.get("suppress"), args.get("visible"), args.get("component_config"), args.get("patterns"), args.get("new_name"))
    if action == "delete":
        return run(cfg.delete, d, name)
    if action == "activate":
        return run(cfg.activate, d, name)
    raise CommandError("action is list, create, edit, delete or activate.")


@command("asmbom", aliases=("bomlist",), group="solids", label="Bill of Materials", description="Show the bill of materials, export it as CSV, assign or renumber find numbers.", menu="Assembly > Bill of Materials")
def asmbom(ctx):
    k = yield ctx.keyword("BOM [Show/Export/Renumber]", ["Show", "Export", "Renumber"], "Show")
    word = (k.value if k.kind == "keyword" else "").lower()
    if word == "renumber":
        run(bom.renumber, ctx.doc)
        ctx.say("Find numbers renumbered.")
        return
    if word == "export":
        t = yield ctx.text("Enter the BOM file name")
        if t.kind != "text":
            return
        refused(ctx, "asmbom", {"path": str(t.value)})
        out = run(bom.export_csv, ctx.doc, str(t.value))
        ctx.say("Wrote %d row(s) to %s." % (out["rows"], out["path"]))
        return
    if word != "show":
        return
    info = run(bom.build, ctx.doc)
    for r in info["rows"]:
        ctx.say("%3s %s%-18s %-24s %4d  %s" % (r["find"], "  " * r["level"], r["part_number"], r["description"], r["qty"], r["material"]))
    for w in info["warnings"]:
        ctx.say("Note: " + w)


@executes("asmbom")
def asmbom_exec(ctx, args):
    action = str(args.get("action") or "show").lower()
    if action == "show":
        return run(bom.build, ctx.doc, str(args.get("mode") or "indented"), bool(args.get("include_suppressed", False)))
    if action == "renumber":
        return run(bom.renumber, ctx.doc)
    if action == "assign":
        return run(bom.assign, ctx.doc)
    if action == "export":
        if not args.get("path"):
            raise CommandError("Give path.")
        return run(bom.export_csv, ctx.doc, str(args["path"]), str(args.get("mode") or "indented"), args.get("columns"), bool(args.get("include_suppressed", False)))
    raise CommandError("action is show, export, renumber or assign.")


@command("asmsearch", group="settings", label="Component Search Folders", description="Set the folders and the order used to find component files.", menu="Assembly > Search Folders", undoable=True)
def asmsearch(ctx):
    h = store.header(ctx.d)
    ctx.say("Order: %s" % ", ".join(h["search_order"]))
    for f in h["search_folders"]:
        ctx.say("Folder: %s" % f)


@executes("asmsearch")
def asmsearch_exec(ctx, args):
    action = str(args.get("action") or "show").lower()
    if action == "show":
        h = store.header(ctx.d)
        return {"search_folders": h["search_folders"], "search_order": h["search_order"], "embed_cache": h["embed_cache"], "lightweight": bool(h.get("lightweight", True))}
    if action != "set":
        raise CommandError("action is show or set.")
    return run(model.settings, ctx.doc, args.get("folders"), args.get("order"), args.get("embed_cache"), args.get("lightweight"))


def _which(ctx, ident):
    if ident is None or str(ident).strip().lower() in ("", "all"):
        return None
    items = ident if isinstance(ident, list) else [ident]
    return [comp_id(ctx, v) for v in items]


@command("asmresolve", group="solids", label="Resolve Components", description="Load lightweight components in full so their solids can be measured, mated, checked or exported.", menu="Assembly > Resolve Components", undoable=False)
def asmresolve(ctx):
    t = yield ctx.text("Enter the component name or id (or ALL)", "ALL")
    if t.kind != "text":
        return
    out = run(light.resolve, ctx.doc, _which(ctx, t.value))
    ctx.say("%d resolved, %d still lightweight." % (len(out["resolved"]), out["lightweight"]))
    for f in out["failed"]:
        ctx.say("%s: %s" % (f["key"], f["message"]))


@executes("asmresolve")
def asmresolve_exec(ctx, args):
    return run(light.resolve, ctx.doc, _which(ctx, args.get("component")))


@command("asmlightweight", group="solids", label="Make Components Lightweight", description="Show components from the display copy kept in the assembly again, without their full solids.", menu="Assembly > Make Lightweight", undoable=False)
def asmlightweight(ctx):
    t = yield ctx.text("Enter the component name or id (or ALL)", "ALL")
    if t.kind != "text":
        return
    out = run(light.lighten, ctx.doc, _which(ctx, t.value))
    ctx.say("%d lightweight." % out["count"])


@executes("asmlightweight")
def asmlightweight_exec(ctx, args):
    return run(light.lighten, ctx.doc, _which(ctx, args.get("component")))


@command("partprops", aliases=("partprop",), group="solids", label="Document Properties", description="Show or set part number, description, material and revision of this document.", menu="File > Document Properties")
def partprops(ctx):
    for k, v in P.get(ctx.d).items():
        ctx.say("%s: %s" % (k, v))


@executes("partprops")
def partprops_exec(ctx, args):
    action = str(args.get("action") or "show").lower()
    if action == "show":
        return {"properties": P.get(ctx.d)}
    if action != "set":
        raise CommandError("action is show or set.")
    return {"properties": run(P.put, ctx.d, args.get("values") or {}, args.get("remove") or ())}


@command("asmrefresh", group="solids", label="Refresh Component Status", description="Check every component file again.", menu="Assembly > Refresh", undoable=False)
def asmrefresh(ctx):
    parts.forget()
    for cid, st in walk.top_statuses(ctx.doc).items():
        say_status(ctx, store.get(ctx.d, cid), st)


@executes("asmrefresh")
def asmrefresh_exec(ctx, args):
    parts.forget()
    return {"status": {cid: api.brief_status(st, False) for cid, st in walk.top_statuses(ctx.doc).items()}}
