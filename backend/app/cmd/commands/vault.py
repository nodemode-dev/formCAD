import json

from app.cmd import barred
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.vault import commit, history, maint, mergeops, notes, pdm, refsops, registry, session, views
from app.vault.base import VaultError

GROUP = "vault"
CANCEL = object()
ACTIONS_BRANCH = ["List", "Create", "Delete", "Rename"]
ACTIONS_MERGE = ["Status", "Start", "Resolve", "Complete", "Abort"]
ACTIONS_LOCK = ["Status", "Lock", "Unlock", "Break"]
ACTIONS_COMMENT = ["List", "Add", "Reply", "Resolve", "Reopen", "Delete"]
STATE_WORDS = ["Wip", "Review", "Released", "Obsolete"]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except VaultError as err:
        raise CommandError(err.message)


def agent_of(ctx) -> bool:
    return bool(barred.caller(ctx.runner))


def vault_of(args):
    return run(registry.get, str(args.get("vault") or ""))


def bound(ctx) -> dict:
    return run(session.status_of, ctx.doc.id)


def doc_id(ctx, args) -> str:
    given = str(args.get("doc") or "").strip()
    if given:
        return given
    b = bound(ctx)
    if b["bound"]:
        return b["doc"]["id"]
    raise CommandError("Give doc (the vault document id), or check this drawing in first.")


def ask(ctx, message, default=""):
    t = yield ctx.text(message, default or None)
    if t.kind == "text":
        return str(t.value).strip()
    if t.kind == "enter":
        return default
    return CANCEL


def pick(ctx, message, words, default):
    k = yield ctx.keyword(message, words, default)
    if k.kind != "keyword":
        return CANCEL
    return str(k.value).lower()


def short(h: str) -> str:
    return h[:12]


def say_version(ctx, v: dict) -> None:
    flags = ", ".join(x for x in (["rev " + v["revision"]] if v["revision"] else []) + [v["state"]] + v["branches"] + v["tags"])
    ctx.say("%s  %s  %s  %s (%s)" % (short(v["id"]), v["author"], v["message"], flags, "identical" if v["identical"] else "rebuilt"))


def active_binding_path(ctx, args, agent: bool) -> str:
    path = str(args.get("path") or "").strip()
    if path:
        return path
    if not ctx.doc.path:
        raise CommandError("Save the drawing to a file first, or give path.")
    if agent:
        why = barred.path_refusal(ctx.doc.path, ctx.runner)
        if why:
            raise CommandError(why)
    return ctx.doc.path


def do_create(ctx, args):
    rec = run(registry.create, str(args.get("name") or ""), str(args.get("folder") or ""), bool(args.get("attach", False)))
    return {"vault": rec, "message": "Vault %s ready in %s." % (rec["id"], rec["folder"])}


def do_checkin(ctx, args):
    agent = agent_of(ctx)
    v = vault_of(args)
    path = active_binding_path(ctx, args, agent)
    if not args.get("path") and ctx.doc.path:
        run(session.save_doc, ctx.doc)
    res = run(commit.checkin, v, path=path, doc=str(args.get("doc") or ""), name=str(args.get("name") or ""), branch=str(args.get("branch") or ""), message=str(args.get("message") or ""), who=str(args.get("author") or ""), keep_lock=bool(args.get("keep_lock", False)), auto_merge=bool(args.get("auto_merge", True)), base=str(args.get("base") or ""), agent=agent)
    ver = res["version"]
    msg = {"ok": "Checked in %s as %s on %s.", "merged": "Checked in %s and merged into %s (%s).", "diverged": "Checked in %s on %s; the branch moved, so a merge needs your choices (%s)."}[res["status"]]
    if res["status"] == "ok":
        msg = msg % (res["doc"], short(ver["id"]), res["branch"])
    elif res["status"] == "merged":
        msg = msg % (res["doc"], res["target"], short(res["merged"]["id"]))
    else:
        msg = msg % (res["doc"], res["branch"], "%d conflict(s)" % res["merge"]["unresolved"])
    res["message"] = msg
    return res


def do_checkout(ctx, args):
    agent = agent_of(ctx)
    v = vault_of(args)
    did = doc_id(ctx, args)
    path = str(args.get("path") or "").strip()
    if not path:
        raise CommandError("Give the file name to write.")
    res = run(commit.checkout, v, did, path, str(args.get("version") or args.get("branch") or ""), bool(args.get("edit", True)), bool(args.get("lock", True)), str(args.get("author") or ""), bool(args.get("overwrite", False)), agent)
    if args.get("open") and not agent:
        run(session.open_result, res)
    res["message"] = "%s written to %s%s." % (short(res["version"]), res["path"], " for editing" if res["edit"] else " read only")
    return res


def do_undo(ctx, args):
    agent = agent_of(ctx)
    v = vault_of(args)
    res = run(commit.undo_checkout, v, active_binding_path(ctx, args, agent), bool(args.get("restore", False)), str(args.get("author") or ""))
    res["message"] = "Checkout of %s undone." % res["doc"]
    return res


def do_log(ctx, args):
    v = vault_of(args)
    did = doc_id(ctx, args)

    def go():
        with v.read() as c:
            start = history.resolve_ref(c, did, str(args["branch"])) if args.get("branch") else None
            return history.log(c, did, start, int(args.get("limit") or 30))

    items = run(go)
    for x in items:
        say_version(ctx, x)
    return {"versions": items, "message": "%d version(s)." % len(items)}


def do_branch(ctx, args):
    v = vault_of(args)
    did = doc_id(ctx, args)
    action = str(args.get("action") or "list").lower()
    if action == "list":
        out = run(refsops.listing, v, did)
        for b in out["branches"]:
            ctx.say("%s  %s  %s" % (b["name"], short(b["head"]), b["state"]))
        out["message"] = "%d branch(es), %d tag(s)." % (len(out["branches"]), len(out["tags"]))
        return out
    name = str(args.get("name") or "")
    if action == "create":
        out = run(refsops.create, v, did, name, str(args.get("from") or ""), str(args.get("author") or ""))
        out["message"] = "Branch %s starts at %s." % (name, short(out["head"]))
        return out
    if action == "delete":
        out = run(refsops.delete, v, did, name, bool(args.get("force", False)))
        out["message"] = "Branch %s deleted." % name
        return out
    if action == "rename":
        out = run(refsops.rename, v, did, name, str(args.get("to") or ""))
        out["message"] = "Branch renamed to %s." % out["name"]
        return out
    raise CommandError("action is list, create, delete or rename.")


def do_tag(ctx, args):
    out = run(refsops.tag, vault_of(args), doc_id(ctx, args), str(args.get("name") or ""), str(args.get("version") or ""))
    out["message"] = "Tag %s set." % out["name"]
    return out


def do_diff(ctx, args):
    v = vault_of(args)
    did = doc_id(ctx, args)

    def full(text):
        with v.read() as c:
            return history.resolve_ref(c, did, str(text or "")).hex()

    out = run(lambda: views.diff(v, full(args.get("a")), full(args.get("b")), int(args.get("limit") or 200)))
    s = out["summary"]
    for it in out["items"][:40]:
        ctx.say("%s %s%s" % (it["change"], it["entity"], "  " + ", ".join("%s: %s -> %s" % (f["path"], f["a"], f["b"]) for f in it["fields"][:3]) if it["fields"] else ""))
    out["message"] = "%d added, %d removed, %d changed, %d reordered." % (s["added"], s["removed"], s["changed"], s["reordered"])
    return out


def merge_say(ctx, m):
    for c in m["conflicts"]:
        ctx.say("%s  %s  %s  %s  ours=%s theirs=%s  choice=%s" % (c["id"], c["kind"], c["entity"], c["path"], json.dumps(c["ours"])[:40], json.dumps(c["theirs"])[:40], c["choice"] or "-"))


def parse_choices(text) -> dict:
    out = {}
    if isinstance(text, dict):
        return text
    for tok in str(text or "").replace(",", " ").split():
        if "=" not in tok:
            raise CommandError("Write each choice as id=ours, id=theirs, id=base, id=keep_both, id=accept or id=restore.")
        k, _, val = tok.partition("=")
        out[k.strip()] = val.strip()
    return out


def do_merge(ctx, args):
    v = vault_of(args)
    did = doc_id(ctx, args)
    action = str(args.get("action") or "status").lower()
    if action == "start":
        m = run(mergeops.start, v, did, str(args.get("source") or ""), str(args.get("branch") or ""), str(args.get("author") or ""))
    elif action == "status":
        m = run(mergeops.state, v, did)
    elif action == "resolve":
        m = run(mergeops.resolve, v, did, parse_choices(args.get("choices")))
    elif action == "abort":
        out = run(mergeops.abort, v, did)
        out["message"] = "Merge abandoned."
        return out
    elif action == "complete":
        out = run(mergeops.complete, v, did, str(args.get("message") or ""), str(args.get("author") or ""))
        out["message"] = "Merged as %s." % short(out["version"]["id"])
        return out
    else:
        raise CommandError("action is status, start, resolve, complete or abort.")
    merge_say(ctx, m)
    m["message"] = "Merge is %s: %d conflict(s), %d without a choice." % (m["status"], len(m["conflicts"]), m["unresolved"])
    return m


def do_lock(ctx, args):
    v = vault_of(args)
    did = doc_id(ctx, args)
    action = str(args.get("action") or "status").lower()
    if action == "status":
        lk = run(refsops.doc_lock, v, did)
        return {"lock": lk, "message": "Not locked." if lk is None else "Locked by %s on %s." % (lk["owner"], lk["machine"])}
    if action == "lock":
        lk = run(refsops.lock, v, did, str(args.get("author") or ""), str(args.get("note") or ""))
        return {"lock": lk, "message": "Locked."}
    if action == "unlock":
        out = run(refsops.unlock, v, did, str(args.get("author") or ""))
        out["message"] = "Unlocked."
        return out
    if action == "break":
        out = run(refsops.break_lock, v, did, str(args.get("author") or ""), str(args.get("note") or ""))
        out["message"] = "Lock of %s broken%s." % (out["owner"], "; their work is on " + out["kept"] if out["kept"] else "")
        return out
    raise CommandError("action is status, lock, unlock or break.")


def do_state(ctx, args):
    v = vault_of(args)
    ver = str(args.get("version") or "")
    if not ver:
        did = doc_id(ctx, args)
        ver = run(views.doc, v, did)["head"]
    out = run(pdm.set_state, v, ver, str(args.get("state") or ""), str(args.get("revision") or ""), str(args.get("note") or ""), bool(args.get("cascade", False)), str(args.get("author") or ""))
    out["message"] = "%s is now %s%s." % (short(out["id"]), out["state"], " revision " + out["revision"] if out["revision"] else "")
    return out


def do_revise(ctx, args):
    out = run(pdm.revise, vault_of(args), doc_id(ctx, args), str(args.get("branch") or ""), str(args.get("author") or ""))
    out["message"] = "New working version %s." % short(out["id"])
    return out


def do_whereused(ctx, args):
    out = run(pdm.whereused, vault_of(args), doc_id(ctx, args), str(args.get("version") or ""), str(args.get("scope") or "heads"))
    for u in out["used_by"]:
        ctx.say("%s  %s  %s  as %s (%s)" % (u["from_name"], u["short"], u["state"], u["comp"], u["mode"]))
    out["message"] = "Used by %d assembly version(s)." % len(out["used_by"])
    return out


def do_comment(ctx, args):
    v = vault_of(args)
    did = doc_id(ctx, args)
    action = str(args.get("action") or "list").lower()
    if action == "list":
        items = run(notes.listing, v, did, str(args.get("version") or ""), str(args.get("status") or ""))
        for c in items:
            ctx.say("#%d %s %s [%s] %s%s" % (c["id"], c["author"], c["entity"], c["status"], c["body"][:80], "" if c["attached"] is not False else " (orphaned)"))
        return {"comments": items, "message": "%d comment(s)." % len(items)}
    if action in ("add", "reply"):
        ver = str(args.get("version") or "")
        if not ver:
            ver = run(views.doc, v, did)["head"]
        out = run(notes.add, v, did, ver, str(args.get("entity") or ""), str(args.get("body") or ""), args.get("anchor"), args.get("parent") if action == "reply" else None, str(args.get("markup_svg") or ""), args.get("camera"), str(args.get("author") or ""))
        out["message"] = "Comment %d added." % out["id"]
        return out
    cid = int(args.get("id") or 0)
    if action in ("resolve", "reopen"):
        out = run(notes.update, v, cid, "resolved" if action == "resolve" else "open", "", str(args.get("author") or ""))
        out["message"] = "Comment %d is %s." % (cid, out["status"])
        return out
    if action == "delete":
        out = run(notes.delete, v, cid, str(args.get("author") or ""))
        out["message"] = "Comment deleted."
        return out
    raise CommandError("action is list, add, reply, resolve, reopen or delete.")


def do_pin(ctx, args):
    from app.assembly import store as A

    v = vault_of(args)
    did = str(args.get("doc") or "").strip()
    if not did:
        raise CommandError("Give doc, the vault document to pin to.")
    cid = A.find_component(ctx.d, str(args.get("comp") or ""))["id"]
    ver = str(args.get("version") or "")
    follow = str(args.get("follow") or "head")
    if follow not in ("head", "released"):
        raise CommandError("follow is head or released.")

    def go():
        with v.read() as c:
            history.doc_row(c, did)
            return bytes(history.version_row(c, ver, did)["hash"]).hex() if ver else ""

    full = run(go)
    live = ctx.d.modify_record(A.COMPONENTS, cid)
    ref = dict(live.get("ref") or {})
    ref["vault"] = {"id": registry.vault_id_of(v), "doc": did, "version": full, "follow": follow}
    live["ref"] = ref
    return {"comp": cid, "vault": ref["vault"], "message": "%s follows %s %s." % (cid, did, short(full) if full else follow)}


def do_verify(ctx, args):
    out = run(maint.verify, vault_of(args), str(args.get("doc") or ""), str(args.get("version") or ""), bool(args.get("deep", False)))
    out["message"] = "%d version(s) checked, %d reopen byte-identical, %d problem(s)." % (out["versions"], out["identical"], len(out["bad"]))
    return out


def do_gc(ctx, args):
    out = run(maint.gc, vault_of(args), bool(args.get("dry_run", True)), int(args.get("grace_days", 30)))
    out["message"] = "%s %d version(s), %d object(s), %d bytes." % ("Would drop" if out["dry_run"] else "Dropped", out["versions_dropped"], out["objects_dropped"], out["bytes_freed"])
    return out


@command("vaultcreate", aliases=("vcr",), group=GROUP, label="New Vault", description="Create a vault in the data folder or in a folder you choose, or attach one that already exists.", menu="File > Vault > New Vault", undoable=False, repeatable=False)
def vaultcreate(ctx):
    name = yield from ask(ctx, "Enter the vault name")
    if name is CANCEL or not name:
        return
    folder = yield from ask(ctx, "Enter the vault folder, or press Enter to keep it in the data folder")
    if folder is CANCEL:
        return
    out = do_create(ctx, {"name": name, "folder": folder})
    ctx.say(out["message"])
    return out


@executes("vaultcreate")
def vaultcreate_exec(ctx, args):
    return do_create(ctx, args)


@command("vaultcheckin", aliases=("vci",), group=GROUP, label="Check In", description="Save this drawing and store it in the vault as a new version.", menu="File > Vault > Check In", undoable=False, repeatable=False)
def vaultcheckin(ctx):
    msg = yield from ask(ctx, "Enter a message for this version", "Check-in")
    if msg is CANCEL:
        return
    out = do_checkin(ctx, {"message": msg})
    ctx.say(out["message"])
    return {"version": out["version"]["id"], "doc": out["doc"]}


@executes("vaultcheckin")
def vaultcheckin_exec(ctx, args):
    return do_checkin(ctx, args)


@command("vaultcheckout", aliases=("vco",), group=GROUP, label="Check Out", description="Write a version from the vault to a file, for editing with a lock or for reading.", menu="File > Vault > Check Out", undoable=False, repeatable=False)
def vaultcheckout(ctx):
    did = yield from ask(ctx, "Enter the vault document id", bound(ctx)["doc"]["id"] if bound(ctx)["bound"] else "")
    if did is CANCEL or not did:
        return
    path = yield from ask(ctx, "Enter the file name to write")
    if path is CANCEL or not path:
        return
    e = yield ctx.yesno("Check out for editing", "Yes")
    if e.kind != "keyword":
        return
    out = do_checkout(ctx, {"doc": did, "path": path, "edit": e.value == "Yes", "open": True})
    ctx.say(out["message"])
    return {"path": out["path"]}


@executes("vaultcheckout")
def vaultcheckout_exec(ctx, args):
    return do_checkout(ctx, args)


@command("vaultundo", aliases=("vun",), group=GROUP, label="Undo Check Out", description="Give up a checkout: release the lock and forget the binding of this drawing's file.", menu="File > Vault > Undo Check Out", undoable=False, repeatable=False)
def vaultundo(ctx):
    r = yield ctx.yesno("Rewrite the file from the checked-out version", "No")
    if r.kind != "keyword":
        return
    out = do_undo(ctx, {"restore": r.value == "Yes"})
    ctx.say(out["message"])
    return out


@executes("vaultundo")
def vaultundo_exec(ctx, args):
    return do_undo(ctx, args)


@command("vaultlog", aliases=("vlg",), group=GROUP, label="Vault History", description="List the versions of this drawing's vault document.", menu="File > Vault > History", undoable=False)
def vaultlog(ctx):
    return do_log(ctx, {})


@executes("vaultlog")
def vaultlog_exec(ctx, args):
    return do_log(ctx, args)


@command("vaultbranch", aliases=("vbr",), group=GROUP, label="Vault Branch", description="List, create, delete or rename branches of a vault document.", menu="File > Vault > Branches", undoable=False, repeatable=False)
def vaultbranch(ctx):
    a = yield from pick(ctx, "Branch [%s]" % "/".join(ACTIONS_BRANCH), ACTIONS_BRANCH, "List")
    if a is CANCEL:
        return
    args = {"action": a}
    if a != "list":
        name = yield from ask(ctx, "Enter the branch name")
        if name is CANCEL or not name:
            return
        args["name"] = name
    if a == "rename":
        to = yield from ask(ctx, "Enter the new name")
        if to is CANCEL or not to:
            return
        args["to"] = to
    out = do_branch(ctx, args)
    ctx.say(out["message"])
    return out


@executes("vaultbranch")
def vaultbranch_exec(ctx, args):
    return do_branch(ctx, args)


@command("vaulttag", aliases=("vtg",), group=GROUP, label="Vault Tag", description="Name a version of a vault document; tags do not move.", menu="", undoable=False, repeatable=False)
def vaulttag(ctx):
    name = yield from ask(ctx, "Enter the tag name")
    if name is CANCEL or not name:
        return
    ver = yield from ask(ctx, "Enter the branch or version to tag", "main")
    if ver is CANCEL:
        return
    out = do_tag(ctx, {"name": name, "version": ver})
    ctx.say(out["message"])
    return out


@executes("vaulttag")
def vaulttag_exec(ctx, args):
    return do_tag(ctx, args)


@command("vaultdiff", aliases=("vdf",), group=GROUP, label="Compare Versions", description="List the entities that differ between two versions of a vault document.", menu="", undoable=False, repeatable=False)
def vaultdiff(ctx):
    a = yield from ask(ctx, "Enter the first version")
    if a is CANCEL or not a:
        return
    b = yield from ask(ctx, "Enter the second version")
    if b is CANCEL or not b:
        return
    out = do_diff(ctx, {"a": a, "b": b})
    ctx.say(out["message"])
    return out["summary"]


@executes("vaultdiff")
def vaultdiff_exec(ctx, args):
    return do_diff(ctx, args)


@command("vaultmerge", aliases=("vmg",), group=GROUP, label="Merge", description="Merge a branch or version into a branch with a conflict report; the merge is made when every conflict has a choice.", menu="File > Vault > Merge", undoable=False, repeatable=False)
def vaultmerge(ctx):
    a = yield from pick(ctx, "Merge [%s]" % "/".join(ACTIONS_MERGE), ACTIONS_MERGE, "Status")
    if a is CANCEL:
        return
    args = {"action": a}
    if a == "start":
        src = yield from ask(ctx, "Enter the branch or version to merge in")
        if src is CANCEL or not src:
            return
        args["source"] = src
    if a == "resolve":
        text = yield from ask(ctx, "Enter the choices as id=ours or id=theirs, separated by spaces")
        if text is CANCEL or not text:
            return
        args["choices"] = text
    if a == "complete":
        msg = yield from ask(ctx, "Enter a message for the merge, or press Enter for the default")
        if msg is CANCEL:
            return
        args["message"] = msg
    out = do_merge(ctx, args)
    ctx.say(out["message"])
    return {"status": out.get("status")}


@executes("vaultmerge")
def vaultmerge_exec(ctx, args):
    return do_merge(ctx, args)


@command("vaultlock", aliases=("vlk",), group=GROUP, label="Lock", description="Show, take, release or break the lock on a vault document.", menu="", undoable=False, repeatable=False)
def vaultlock(ctx):
    a = yield from pick(ctx, "Lock [%s]" % "/".join(ACTIONS_LOCK), ACTIONS_LOCK, "Status")
    if a is CANCEL:
        return
    out = do_lock(ctx, {"action": a})
    ctx.say(out["message"])
    return out


@executes("vaultlock")
def vaultlock_exec(ctx, args):
    return do_lock(ctx, args)


@command("vaultstate", aliases=("vst",), group=GROUP, label="Set Lifecycle State", description="Move a version through work in progress, in review, released and obsolete; releasing gives it a revision.", menu="File > Vault > Lifecycle", undoable=False, repeatable=False)
def vaultstate(ctx):
    s = yield from pick(ctx, "State [%s]" % "/".join(STATE_WORDS), STATE_WORDS, "Review")
    if s is CANCEL:
        return
    out = do_state(ctx, {"state": s})
    ctx.say(out["message"])
    return {"state": out["state"], "revision": out["revision"]}


@executes("vaultstate")
def vaultstate_exec(ctx, args):
    return do_state(ctx, args)


@command("vaultrevise", aliases=("vrv",), group=GROUP, label="Revise", description="Start a new working version after a released one.", menu="File > Vault > Revise", undoable=False, repeatable=False)
def vaultrevise(ctx):
    out = do_revise(ctx, {})
    ctx.say(out["message"])
    return {"version": out["id"]}


@executes("vaultrevise")
def vaultrevise_exec(ctx, args):
    return do_revise(ctx, args)


@command("vaultwhereused", aliases=("vwu",), group=GROUP, label="Where Used", description="List the assemblies that use this vault document.", menu="File > Vault > Where Used", undoable=False)
def vaultwhereused(ctx):
    out = do_whereused(ctx, {})
    ctx.say(out["message"])
    return {"used_by": len(out["used_by"])}


@executes("vaultwhereused")
def vaultwhereused_exec(ctx, args):
    return do_whereused(ctx, args)


@command("vaultcomment", aliases=("vcm",), group=GROUP, label="Vault Comment", description="List, add, reply to, resolve, reopen or delete comments anchored to entities of a vault document.", menu="File > Vault > Comments", undoable=False, repeatable=False)
def vaultcomment(ctx):
    a = yield from pick(ctx, "Comment [%s]" % "/".join(ACTIONS_COMMENT), ACTIONS_COMMENT, "List")
    if a is CANCEL:
        return
    args = {"action": a}
    if a == "add":
        ent = yield from ask(ctx, "Enter the entity id, like entity:257 or table:features:F2, or press Enter for the whole drawing")
        if ent is CANCEL:
            return
        args["entity"] = ent
    if a in ("add", "reply"):
        body = yield from ask(ctx, "Enter the comment")
        if body is CANCEL or not body:
            return
        args["body"] = body
    if a in ("reply", "resolve", "reopen", "delete"):
        n = yield ctx.number("Comment number", integer=True, positive=True)
        if n.kind != "int" and n.kind != "number":
            return
        args["id" if a != "reply" else "parent"] = int(n.value)
    out = do_comment(ctx, args)
    ctx.say(out["message"])
    return {"ok": True}


@executes("vaultcomment")
def vaultcomment_exec(ctx, args):
    return do_comment(ctx, args)


@command("vaultpin", aliases=("vpn",), group=GROUP, label="Pin Component to Vault", description="Make a component follow a vault document: a fixed version, the latest version or the latest release.", menu="Assembly > Pin to Vault")
def vaultpin(ctx):
    comp = yield from ask(ctx, "Enter the component id or label")
    if comp is CANCEL or not comp:
        return
    did = yield from ask(ctx, "Enter the vault document id")
    if did is CANCEL or not did:
        return
    ver = yield from ask(ctx, "Enter a version to pin to, or press Enter to follow the branch")
    if ver is CANCEL:
        return
    out = do_pin(ctx, {"comp": comp, "doc": did, "version": ver})
    ctx.say(out["message"])
    return {"comp": out["comp"]}


@executes("vaultpin")
def vaultpin_exec(ctx, args):
    return do_pin(ctx, args)


@command("vaultverify", aliases=("vvf",), group=GROUP, label="Verify Vault", description="Rebuild versions from the stored objects and compare them with what was checked in.", menu="", undoable=False, repeatable=False)
def vaultverify(ctx):
    out = do_verify(ctx, {})
    ctx.say(out["message"])
    return {"bad": len(out["bad"])}


@executes("vaultverify")
def vaultverify_exec(ctx, args):
    return do_verify(ctx, args)


@command("vaultgc", group=GROUP, label="Clean Vault", description="Drop versions no branch, tag, release, checkout, comment or recent work reaches, and the objects only they used.", menu="", undoable=False, repeatable=False)
def vaultgc(ctx):
    r = yield ctx.yesno("Delete now (No only reports what would go)", "No")
    if r.kind != "keyword":
        return
    out = do_gc(ctx, {"dry_run": r.value != "Yes"})
    ctx.say(out["message"])
    return {"dropped": out["versions_dropped"]}


@executes("vaultgc")
def vaultgc_exec(ctx, args):
    return do_gc(ctx, args)
