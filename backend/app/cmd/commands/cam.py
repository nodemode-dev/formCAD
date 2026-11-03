from app.cam import export, gen, post, registry, store, tools
from app.cam.limits import CamError, Cancelled
from app.cmd.context import CommandError
from app.cmd.registry import command, executes

FAILURES = (CamError, Cancelled, ValueError, KeyError, TypeError)


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def split_ids(text):
    return [t for t in str(text).replace(",", " ").split() if t]


def generate_inline(doc, ids):
    results = {}
    for oid in ids:
        try:
            st = gen.generate_one(doc, oid)
            results[oid] = {"status": st["status"], "message": st["message"], "summary": {k: v for k, v in st["summary"].items() if k != "meta"}, "warnings": st["warnings"]}
        except CamError as err:
            results[oid] = {"status": "failed", "message": str(err)}
    return results


@command("camsetup", group="solids", label="Manufacture Setup", description="Add a manufacturing setup: the stock and the work coordinate system the operations cut in.", menu="Manufacture > Setup")
def camsetup(ctx):
    t = yield ctx.text("Name of the setup", "Top")
    if t.kind != "text":
        return
    rec = run(store.add_setup, ctx.d, {"label": t.value.strip() or "Top"})
    ctx.say("Setup %s added: stock grown from the model, work origin at the top corner of the stock." % rec["id"])
    return {"id": rec["id"]}


@executes("camsetup")
def camsetup_exec(ctx, args):
    if args.get("setup"):
        rec = run(store.update_setup, ctx.d, str(args["setup"]), {k: v for k, v in args.items() if k != "setup"})
    else:
        rec = run(store.add_setup, ctx.d, args)
    return {"id": rec["id"], "setup": rec}


@command("camtool", group="solids", label="Manufacture Tool", description="Bring a tool from the tool library into this document.", menu="Manufacture > Tool")
def camtool(ctx):
    rows = run(tools.load_all)
    if not rows:
        ctx.say("The tool library is empty. Add tools in the Manufacture panel first.")
        return
    ctx.say("Library tools: %s" % ", ".join("%s (T%d)" % (r["name"], r["number"]) for r in rows[:20]))
    t = yield ctx.number("Tool number to bring in", integer=True, positive=True)
    if t.kind != "number":
        return
    match = [r for r in rows if r["number"] == int(t.value)]
    if not match:
        raise CommandError("There is no library tool with number %d." % int(t.value))
    row = run(store.import_tool, ctx.d, {"library_id": match[0]["id"]})
    ctx.say("Tool %s added." % row["id"])


@executes("camtool")
def camtool_exec(ctx, args):
    if args.get("remove"):
        run(store.delete_tool, ctx.d, args["remove"])
        return {"removed": int(args["remove"])}
    row = run(store.import_tool, ctx.d, args)
    return {"id": row["id"], "tool": row}


@command("camop", group="solids", label="Manufacture Operation", description="Add a machining operation (face, pocket, contour, adaptive clearing, drill, rest) to a setup.", menu="Manufacture > Operation")
def camop(ctx):
    kinds = [t["kind"] for t in registry.listing()]
    k = yield ctx.keyword("Operation [%s]" % "/".join(kinds), kinds, kinds[0])
    if k.kind != "keyword":
        return
    s = yield ctx.text("Setup id", "S1")
    if s.kind != "text":
        return
    n = yield ctx.number("Tool number", integer=True, positive=True)
    if n.kind != "number":
        return
    rec = run(store.add_op, ctx.d, {"type": k.value, "setup": s.value.strip(), "tool": int(n.value)})
    ctx.say("%s added. Set its geometry, heights and feeds, then generate it." % rec["id"])
    return {"id": rec["id"]}


@executes("camop")
def camop_exec(ctx, args):
    if args.get("op"):
        rec = run(store.update_op, ctx.d, str(args["op"]), {k: v for k, v in args.items() if k != "op"})
    else:
        rec = run(store.add_op, ctx.d, args)
    return {"id": rec["id"], "op": rec}


@command("camdelete", group="solids", label="Delete Manufacture Item", description="Delete an operation or a setup.", menu="Manufacture > Delete")
def camdelete(ctx):
    t = yield ctx.text("Operation or setup id (like O1 or S1)")
    if t.kind != "text":
        return
    ident = t.value.strip()
    if ident.upper().startswith("S"):
        out = run(store.delete_setup, ctx.d, ident)
        ctx.say("Removed setup and %d operation(s)." % len(out))
    else:
        run(store.delete_op, ctx.d, ident)
        ctx.say("Removed %s." % ident)


@executes("camdelete")
def camdelete_exec(ctx, args):
    if args.get("setup"):
        out = run(store.delete_setup, ctx.d, str(args["setup"]))
        for oid in out:
            gen.drop_cache(ctx.doc.id, oid)
        return {"removed": out}
    run(store.delete_op, ctx.d, str(args.get("op") or ""))
    gen.drop_cache(ctx.doc.id, str(args.get("op")))
    return {"removed": [str(args.get("op"))]}


@command("camgenerate", group="solids", label="Generate Toolpaths", description="Generate the toolpaths of operations again from the current model.", menu="Manufacture > Generate")
def camgenerate(ctx):
    t = yield ctx.text("Operation ids to generate (blank for all)", "")
    if t.kind != "text":
        return
    ids = run(gen_ids, ctx.doc, None, split_ids(t.value))
    res = generate_inline(ctx.doc, ids)
    for oid, r in res.items():
        ctx.say("%s: %s%s" % (oid, r["status"], " (%s)" % r["message"] if r.get("message") else ""))


def gen_ids(doc, setup, ops):
    from app.cam import jobs

    return jobs.ops_for(doc, setup, ops)


@executes("camgenerate")
def camgenerate_exec(ctx, args):
    ids = run(gen_ids, ctx.doc, args.get("setup"), [str(o) for o in args.get("ops") or []])
    return {"results": generate_inline(ctx.doc, ids)}


@command("camtime", group="solids", label="Machining Time", description="Estimate the machining time of the operations, simply and with acceleration.", menu="Manufacture > Time", undoable=False)
def camtime(ctx):
    rep = run(export.time_report, ctx.doc, None, None)
    for r in rep["ops"]:
        ctx.say("%s %s: %.1f s (simple %.1f s)" % (r["op"], r["label"], r["trapezoid_s"], r["simple_s"]))
    ctx.say("Total %.1f s with acceleration, %.1f s simple." % (rep["total"]["trapezoid_s"], rep["total"]["simple_s"]))


@executes("camtime")
def camtime_exec(ctx, args):
    return run(export.time_report, ctx.doc, args.get("setup"), [str(o) for o in args.get("ops") or []] or None)


@command("camexport", group="solids", label="Export G-code File", description="Write the toolpaths to a numerical control program file through a post.", menu="Manufacture > Export G-code", undoable=False)
def camexport(ctx):
    posts = [p["id"] for p in post.list_posts()]
    k = yield ctx.keyword("Post [%s]" % "/".join(posts), posts, posts[0] if posts else None)
    if k.kind != "keyword":
        return
    f = yield ctx.text("Enter the name of the G-code file to write")
    if f.kind != "text":
        return
    res = run(export.write_file, ctx.doc, f.value.strip(), k.value)
    ctx.say("Wrote %d lines to %s." % (res["lines"], res["path"]))
    for w in res["warnings"]:
        ctx.say(w)


@executes("camexport")
def camexport_exec(ctx, args):
    if not args.get("out"):
        raise CommandError("Give out, the file to write.")
    res = run(export.write_file, ctx.doc, str(args["out"]), str(args.get("post") or "linuxcnc"), args.get("setup"), [str(o) for o in args.get("ops") or []] or None, args.get("options"))
    return res
