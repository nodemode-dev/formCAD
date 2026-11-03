import os

from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import COMMANDS, command, executes
from app.core import outputs
from app.doc import events
from app.graph import model, session, store

FAILURES = (store.StoreError, model.GraphError, ValueError, KeyError)
READ_EXT = (".graph", ".json")


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except FAILURES as err:
        raise CommandError(err.message if isinstance(err, model.GraphRefused) else str(err.args[0]) if isinstance(err, KeyError) and err.args else str(err))


def pick(ctx, name):
    recs = store.records(ctx.d)
    if not recs:
        raise CommandError("This document has no graph. Use GRAPH to make one.")
    key = str(name or "").strip()
    if not key:
        return recs[0]
    rec = store.get(ctx.d, key)
    if rec is None:
        raise CommandError("There is no graph %s." % key)
    return rec


def refused(ctx, name, args):
    msg = barred.args_refusal(ctx.runner, COMMANDS[name], args)
    if msg:
        raise CommandError(msg)


@command("graph", aliases=("grapheditor", "nodeeditor"), group="tools", label="Graph", description="Open the graph editor on a graph of this document. A graph is made when the document has none.", menu="Tools > Graph", repeatable=False)
def graph_cmd(ctx):
    out = graph_exec(ctx, {})
    ctx.say(out["message"])
    return out


@executes("graph")
def graph_exec(ctx, args):
    recs = store.records(ctx.d)
    key = str(args.get("graph") or args.get("name") or "").strip()
    if key and store.get(ctx.d, key) is not None:
        rec = store.get(ctx.d, key)
    elif recs and not args.get("new") and not key:
        rec = recs[0]
    else:
        rec = run(store.create, ctx.d, key)
    events.publish({"type": "graph", "reason": "open", "id": ctx.doc.id, "graph": rec["id"]})
    return {"id": rec["id"], "label": rec["label"], "message": "Graph %s is open." % rec["label"]}


@command("graphrun", aliases=("solvegraph",), group="tools", label="Run Graph", description="Solve a graph of this document and report the state of every node.", menu="Tools > Run Graph", undoable=False, repeatable=False)
def graphrun_cmd(ctx):
    out = graphrun_exec(ctx, {})
    ctx.say(out["message"])
    return out


@executes("graphrun")
def graphrun_exec(ctx, args):
    rec = pick(ctx, args.get("graph") or args.get("name"))
    sess = run(session.of, ctx.doc, rec["id"])
    sess.request(0, bool(args.get("all", True)))
    if not sess.wait(float(args.get("timeout") or 600.0)):
        raise CommandError("The graph did not finish solving in time.")
    st = sess.state(int(args.get("first") or 6))
    rep = st["report"] or {}
    bad = [nid for nid, n in st["nodes"].items() if n["state"] == "failed"]
    warn = [nid for nid, n in st["nodes"].items() if n["level"] == "warning"]
    return {"id": rec["id"], "ran": len(rep.get("ran", [])), "kept": len(rep.get("kept", [])), "failed": bad, "warnings": warn, "aborted": rep.get("aborted", False), "ms": rep.get("ms"), "digest": rep.get("digest", ""), "nodes": st["nodes"], "message": "Graph %s solved: %d node(s) ran, %d failed." % (rec["label"], len(rep.get("ran", [])), len(bad))}


@command("graphimport", group="tools", label="Import Graph", description="Read a graph file into this document as a new graph.", menu="Tools > Import Graph", repeatable=False)
def graphimport_cmd(ctx):
    r = yield ctx.text("Enter the graph file to import")
    if r.kind != "text" or not str(r.value).strip():
        return
    refused(ctx, "graphimport", {"path": str(r.value)})
    out = graphimport_exec(ctx, {"path": str(r.value)})
    ctx.say(out["message"])
    return out


@executes("graphimport")
def graphimport_exec(ctx, args):
    raw = str(args.get("path") or "").strip()
    if not raw:
        raise CommandError("Give path.")
    full = os.path.abspath(os.path.expanduser(raw))
    if os.path.splitext(full)[1].lower() not in READ_EXT:
        raise CommandError("A graph file ends in .graph.")
    rec = run(store.import_file, ctx.d, full, str(args.get("name") or ""))
    return {"id": rec["id"], "label": rec["label"], "nodes": len(rec["definition"].get("nodes") or []), "message": "Graph %s imported with %d node(s)." % (rec["label"], len(rec["definition"].get("nodes") or []))}


@command("graphexport", group="tools", label="Export Graph", description="Write a graph of this document to a graph file.", menu="Tools > Export Graph", undoable=False, repeatable=False)
def graphexport_cmd(ctx):
    r = yield ctx.text("Enter the graph file to write")
    if r.kind != "text" or not str(r.value).strip():
        return
    refused(ctx, "graphexport", {"path": str(r.value)})
    out = graphexport_exec(ctx, {"path": str(r.value)})
    ctx.say(out["message"])
    return out


@executes("graphexport")
def graphexport_exec(ctx, args):
    rec = pick(ctx, args.get("graph") or args.get("name"))
    try:
        path = outputs.checked(args.get("path"), (store.EXT,), store.EXT)
    except outputs.OutputRefused as err:
        raise CommandError(str(err))
    try:
        store.write_file(path, rec["definition"])
    except OSError as err:
        raise CommandError("The file could not be written: %s" % err)
    return {"id": rec["id"], "path": path, "message": "Graph %s written to %s." % (rec["label"], path)}
