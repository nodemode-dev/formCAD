import re

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import groups as G


def _sel_prompt(ctx, msg, options=(), single=False, pick_one=False):
    p = ctx.select(msg, pick_one=pick_one)
    p.options = list(options)
    if single:
        p.hint = "nogroup"
    return p


def _carry(ctx) -> list:
    return list(getattr(ctx.runner, "sel_carry", []) or [])


def _new(chosen, more):
    for h in more:
        if h not in chosen:
            chosen.append(h)


def _plural(n: int) -> str:
    return "object" if n == 1 else "objects"


def _list_groups(ctx, pattern="*"):
    found = G.match(ctx.d, pattern)
    if not found:
        ctx.say("No matching groups found.")
        return []
    for g in found:
        flags = []
        flags.append("selectable" if g.get("selectable", True) else "not selectable")
        if g.get("unnamed"):
            flags.append("unnamed")
        ctx.say("%s%s (%s): %d %s" % (g["name"], " - " + g["description"] if g["description"] else "", ", ".join(flags), len(g["members"]), _plural(len(g["members"]))))
    return found


def _ask_name(ctx, msg="Enter a group name", allow_unnamed=True):
    while True:
        r = yield ctx.word(msg, ["?"])
        if r.kind == "keyword":
            _list_groups(ctx)
            continue
        if r.kind == "enter":
            if allow_unnamed:
                return ""
            return None
        if r.kind != "text":
            return None
        name = r.value.strip()
        if not G.valid_name(name):
            ctx.say("%s is not a valid group name." % name)
            continue
        if G.find(ctx.d, name) is not None:
            ctx.say("A group named %s already exists." % name)
            continue
        return name


def _announce_created(ctx, rec) -> None:
    n = len(rec["members"])
    if rec["unnamed"]:
        ctx.say("Unnamed group %s created with %d %s." % (rec["name"], n, _plural(n)))
    else:
        ctx.say('Group "%s" created with %d %s.' % (rec["name"], n, _plural(n)))


def _create(ctx, handles, name, desc, selectable=True):
    members = [h for h in handles if h in ctx.d.ents]
    if not members:
        raise CommandError("No objects to group.")
    try:
        rec = G.create(ctx.d, members, name or None, desc, selectable)
    except ValueError as err:
        raise CommandError(str(err))
    _announce_created(ctx, rec)
    return rec


@command("group", aliases=("g",), group="tools", label="Group", description="Create a named or unnamed group.", menu="Tools > Group")
def group(ctx):
    name = ""
    desc = ""
    chosen = []
    while True:
        r = yield _sel_prompt(ctx, "Select objects or [Name/Description]", ["Name", "Description"])
        if r.kind == "selection":
            _new(chosen, r.value)
            break
        if r.kind != "keyword":
            break
        _new(chosen, _carry(ctx))
        if r.value == "Name":
            n = yield from _ask_name(ctx)
            if n is not None:
                name = n
        else:
            t = yield ctx.text("Enter group description")
            if t.kind == "text":
                desc = t.value
    if not chosen:
        return
    _create(ctx, chosen, name, desc)


@executes("group")
def group_exec(ctx, args):
    handles = args.get("handles")
    if handles is None:
        handles = list(ctx.doc.selection)
    handles = [int(h) for h in handles]
    if not handles:
        raise CommandError("No objects to group.")
    rec = _create(ctx, handles, args.get("name"), args.get("description", ""), args.get("selectable", True))
    return {"name": rec["name"], "members": list(rec["members"]), "unnamed": rec["unnamed"]}


def _dissolve(ctx, rec) -> None:
    G.remove(ctx.d, rec["name"])
    ctx.say("Group %s ungrouped." % rec["name"])


@command("ungroup", group="tools", label="Ungroup", description="Dissolve groups; the objects stay.", menu="Tools > Ungroup")
def ungroup(ctx):
    pre = bool(ctx.doc.selection) and bool(ctx.var("PICKFIRST"))
    while True:
        r = yield _sel_prompt(ctx, "Select group or [Name]", ["Name"], True, True)
        if r.kind == "keyword":
            name = yield from _existing(ctx)
            if name is not None:
                _dissolve(ctx, G.find(ctx.d, name))
            return
        if r.kind != "selection" or not r.value:
            return
        hit = []
        for h in r.value:
            gl = G.groups_of(ctx.d, h)
            for g in (gl if pre else gl[-1:]):
                if g["name"] not in [x["name"] for x in hit]:
                    hit.append(g)
        if not hit:
            ctx.say("The object is not a member of any group.")
            return
        for g in hit:
            _dissolve(ctx, g)
        return


@executes("ungroup")
def ungroup_exec(ctx, args):
    names = args.get("name", args.get("names"))
    hit = []
    if names is not None:
        if isinstance(names, str):
            names = [n.strip() for n in names.split(",") if n.strip()]
        for n in names:
            rec = G.find(ctx.d, n)
            if rec is None:
                raise CommandError("No group named %s." % n)
            hit.append(rec)
    else:
        handles = [int(h) for h in args.get("handles", list(ctx.doc.selection))]
        if not handles:
            raise CommandError("0 found")
        for h in handles:
            for g in G.groups_of(ctx.d, h):
                if g["name"] not in [x["name"] for x in hit]:
                    hit.append(g)
        if not hit:
            raise CommandError("The object is not a member of any group.")
    out = []
    for rec in hit:
        out.append(rec["name"])
        _dissolve(ctx, rec)
    return {"ungrouped": out}


def _rename(ctx, rec, new):
    if not G.valid_name(new):
        raise CommandError("%s is not a valid group name." % new)
    if G.find(ctx.d, new) is not None and new.casefold() != rec["name"].casefold():
        raise CommandError("A group named %s already exists." % new)
    old = rec["name"]
    fresh = dict(rec)
    fresh["members"] = list(rec["members"])
    fresh["name"] = new
    fresh["unnamed"] = False
    G.remove(ctx.d, old)
    ctx.d.table_set(G.TABLE, fresh)
    ctx.say("Group %s renamed to %s." % (old, new))
    return fresh


def _add_members(ctx, name, handles) -> int:
    rec = ctx.d.modify_record(G.TABLE, name)
    n = 0
    for h in handles:
        if h in ctx.d.ents and h not in rec["members"]:
            rec["members"].append(h)
            n += 1
    ctx.say("%d %s added to group %s." % (n, _plural(n), name))
    return n


def _remove_members(ctx, name, handles) -> bool:
    rec = ctx.d.modify_record(G.TABLE, name)
    left = [h for h in rec["members"] if h not in handles]
    n = len(rec["members"]) - len(left)
    ctx.say("%d %s removed from group %s." % (n, _plural(n), name))
    if not left:
        G.remove(ctx.d, name)
        ctx.say("Group %s has no objects left and was deleted." % name)
        return True
    rec["members"] = left
    return False


def _pick_group(ctx):
    while True:
        r = yield _sel_prompt(ctx, "Select group or [Name]", ["Name"], True, True)
        if r.kind == "keyword":
            name = yield from _existing(ctx)
            return name
        if r.kind != "selection" or not r.value:
            return None
        for h in r.value:
            gl = G.groups_of(ctx.d, h)
            if gl:
                return gl[-1]["name"]
        ctx.say("The object is not a member of any group.")
        return None


@command("groupedit", group="tools", label="Group Edit", description="Add or remove group members, or rename a group.", menu="")
def groupedit(ctx):
    name = yield from _pick_group(ctx)
    if name is None:
        return
    while True:
        r = yield ctx.keyword("Enter an option", ["Add objects", "Remove objects", "REName"])
        if r.kind != "keyword":
            return
        if r.value == "Add objects":
            s = yield _sel_prompt(ctx, "Select objects to add to the group", (), True)
            if s.kind == "selection" and s.value:
                _add_members(ctx, name, s.value)
        elif r.value == "Remove objects":
            s = yield _sel_prompt(ctx, "Select objects to remove from the group", (), True)
            if s.kind == "selection" and s.value:
                if _remove_members(ctx, name, s.value):
                    return
        else:
            while True:
                t = yield ctx.word("Enter a new name for the group")
                if t.kind != "text":
                    break
                new = t.value.strip()
                if not G.valid_name(new):
                    ctx.say("%s is not a valid group name." % new)
                    continue
                if G.find(ctx.d, new) is not None and new.casefold() != name.casefold():
                    ctx.say("A group named %s already exists." % new)
                    continue
                name = _rename(ctx, G.find(ctx.d, name), new)["name"]
                break


@executes("groupedit")
def groupedit_exec(ctx, args):
    name = args.get("name")
    rec = G.find(ctx.d, name)
    if rec is None:
        raise CommandError("No group named %s." % name)
    name = rec["name"]
    out = {"name": name}
    if args.get("add"):
        out["added"] = _add_members(ctx, name, [int(h) for h in args["add"]])
    if args.get("remove"):
        if _remove_members(ctx, name, [int(h) for h in args["remove"]]):
            out["deleted"] = True
            return out
    if args.get("rename"):
        out["name"] = _rename(ctx, G.find(ctx.d, name), str(args["rename"]))["name"]
    return out


@command("groups.list", group="tools", label="List Groups", description="List every group with its members.", menu="", undoable=False)
def groups_list(ctx):
    found = G.all_groups(ctx.d)
    if not found:
        ctx.say("No groups.")
    _list_groups(ctx, "*")
    yield from ()


@executes("groups.list")
def groups_list_exec(ctx, args):
    return {"groups": [G.summary(g) for g in G.all_groups(ctx.d)]}


DASH_OPTS = ["?", "Order", "Add", "Remove", "Explode", "REName", "Selectable", "Create"]


def _existing(ctx, msg="Enter group name"):
    while True:
        r = yield ctx.word(msg)
        if r.kind != "text":
            return None
        rec = G.find(ctx.d, r.value.strip())
        if rec is None:
            ctx.say("No group named %s." % r.value.strip())
            continue
        return rec["name"]


def _reorder(ctx, name, start, dest, count):
    rec = ctx.d.modify_record(G.TABLE, name)
    mem = list(rec["members"])
    n = len(mem)
    if not (0 <= start < n):
        raise CommandError("Position must be 0 to %d." % (n - 1))
    if not (0 <= dest < n):
        raise CommandError("Position must be 0 to %d." % (n - 1))
    count = max(1, min(count, n - start))
    block = mem[start : start + count]
    rest = mem[:start] + mem[start + count :]
    dest = min(dest, len(rest))
    rec["members"] = rest[:dest] + block + rest[dest:]
    ctx.say("Group reordered.")


@command("-group", aliases=("-g",), group="tools", label="Group Options", description="Command-line group editor.", menu="")
def group_dash(ctx):
    r = yield ctx.keyword("Enter a group option", DASH_OPTS, "Create")
    if r.kind != "keyword":
        return
    k = r.value
    if k == "?":
        t = yield ctx.word("Enter group name(s) to list", default="*")
        if t.kind in ("text", "enter") or t.kind == "keyword":
            _list_groups(ctx, t.value if t.kind == "text" else "*")
        return
    if k == "Create":
        yield from _dash_create(ctx)
        return
    if k == "REName":
        old = yield from _existing(ctx, "Enter old group name")
        if old is None:
            return
        while True:
            t = yield ctx.word("Enter new group name")
            if t.kind != "text":
                return
            new = t.value.strip()
            if not G.valid_name(new):
                ctx.say("%s is not a valid group name." % new)
                continue
            if G.find(ctx.d, new) is not None and new.casefold() != old.casefold():
                ctx.say("A group named %s already exists." % new)
                continue
            _rename(ctx, G.find(ctx.d, old), new)
            return
    name = yield from _existing(ctx)
    if name is None:
        return
    if k == "Explode":
        _dissolve(ctx, G.find(ctx.d, name))
    elif k in ("Add", "Remove"):
        s = yield _sel_prompt(ctx, "Select objects to %s the group" % ("add to" if k == "Add" else "remove from"), (), True)
        if s.kind == "selection" and s.value:
            if k == "Add":
                _add_members(ctx, name, s.value)
            else:
                _remove_members(ctx, name, s.value)
    elif k == "Selectable":
        y = yield ctx.yesno("Group selectable?", "Yes" if G.find(ctx.d, name).get("selectable", True) else "No")
        if y.kind == "keyword":
            ctx.d.modify_record(G.TABLE, name)["selectable"] = y.value == "Yes"
            ctx.say("Group %s is %s." % (name, "selectable" if y.value == "Yes" else "not selectable"))
    elif k == "Order":
        n = len(G.find(ctx.d, name)["members"])
        a = yield ctx.number("Enter the position of the first object to move (0-%d)" % (n - 1), integer=True, minimum=0, maximum=n - 1)
        if a.kind != "number":
            return
        b = yield ctx.number("Enter the position to move it to (0-%d)" % (n - 1), integer=True, minimum=0, maximum=n - 1)
        if b.kind != "number":
            return
        c = yield ctx.number("Number of objects to move", default=1, integer=True, minimum=1)
        _reorder(ctx, name, a.value, b.value, c.value if c.kind == "number" else 1)


def _dash_create(ctx):
    name = yield from _ask_name(ctx, "Enter a group name or [?]")
    if name is None:
        return
    d = yield ctx.text("Enter group description")
    desc = d.value if d.kind == "text" else ""
    s = yield _sel_prompt(ctx, "Select objects for group")
    if s.kind == "selection" and s.value:
        _create(ctx, s.value, name, desc)


def _flag(v, default=True):
    return default if v is None else bool(v)


@executes("-group")
def group_dash_exec(ctx, args):
    opt = str(args.get("option", "create")).lower()
    if opt in ("?", "list"):
        return {"groups": [G.summary(g) for g in G.match(ctx.d, args.get("name", "*"))]}
    if opt == "create":
        handles = [int(h) for h in args.get("handles", list(ctx.doc.selection))]
        rec = _create(ctx, handles, args.get("name"), args.get("description", ""), _flag(args.get("selectable")))
        return {"name": rec["name"], "members": list(rec["members"])}
    if opt == "rename":
        rec = G.find(ctx.d, args.get("name"))
        if rec is None:
            raise CommandError("No group named %s." % args.get("name"))
        return {"name": _rename(ctx, rec, str(args.get("new_name")))["name"]}
    rec = G.find(ctx.d, args.get("name"))
    if rec is None:
        raise CommandError("No group named %s." % args.get("name"))
    name = rec["name"]
    if opt == "explode":
        _dissolve(ctx, rec)
        return {"ungrouped": [name]}
    if opt in ("add", "remove"):
        handles = [int(h) for h in args.get("handles", [])]
        if opt == "add":
            return {"added": _add_members(ctx, name, handles)}
        return {"deleted": _remove_members(ctx, name, handles)}
    if opt == "selectable":
        val = _flag(args.get("selectable"), not rec.get("selectable", True))
        ctx.d.modify_record(G.TABLE, name)["selectable"] = val
        return {"selectable": val}
    if opt == "order":
        _reorder(ctx, name, int(args.get("from", 0)), int(args.get("to", 0)), int(args.get("count", 1)))
        return {"members": list(G.find(ctx.d, name)["members"])}
    raise CommandError("Unknown group option.")


@command("pickstyle", group="tools", label="Group Selection", description="Group and associative hatch selection style (0 to 3).", menu="", transparent=True, undoable=False, repeatable=False)
def pickstyle(ctx):
    cur = int(ctx.var("PICKSTYLE"))
    while True:
        r = yield ctx.word("Enter new value for PICKSTYLE", default=str(cur))
        if r.kind not in ("text", "number"):
            return
        text = str(r.value).strip()
        if not re.fullmatch(r"[0-3]", text):
            ctx.say("Requires an integer between 0 and 3.")
            continue
        ctx.setvar("PICKSTYLE", int(text))
        return


@executes("pickstyle")
def pickstyle_exec(ctx, args):
    v = args.get("value")
    if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v <= 3:
        raise CommandError("Requires an integer between 0 and 3.")
    ctx.setvar("PICKSTYLE", v)
    return {"value": v}
