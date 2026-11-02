from app.cmd import jig
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.doc import geom
from app.doc.entities import entity_from_dict


NEIGHBOURS = 64
LOCKED_MSG = "The object is on a locked layer."


def targets(ctx, args) -> list:
    if "handles" in args:
        raw = args["handles"]
    elif "handle" in args:
        raw = [args["handle"]]
    else:
        raw = ctx.runner.current_selection()
    out = []
    for h in raw:
        try:
            v = int(h)
        except (TypeError, ValueError):
            raise CommandError("Invalid handle.")
        if v not in out:
            out.append(v)
    return out


def _erase(ctx, handles):
    stash = []
    count = 0
    rows = ctx.editable(handles)
    for e in rows:
        lst = ctx.d.spaces.get(e.owner, [])
        idx = lst.index(e.handle) if e.handle in lst else -1
        below = list(reversed(lst[max(idx - NEIGHBOURS, 0) : idx])) if idx > 0 else []
        above = lst[idx + 1 : idx + 1 + NEIGHBOURS] if idx >= 0 else []
        stash.append({"data": e.to_dict(), "index": idx, "below": below, "above": above})
    for e in rows:
        ctx.d.erase_entity(e.handle)
        count += 1
    if stash:
        ctx.doc.last_erased = stash
    return count


@command("erase", aliases=("e", "delete"), group="modify", label="Erase", description="Delete selected objects (remembered for OOPS).", menu="Modify > Erase")
def erase(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    n = _erase(ctx, s.value)
    if n:
        ctx.say("%d erased." % n)
    else:
        ctx.say(LOCKED_MSG)


@executes("erase")
def erase_exec(ctx, args):
    if args.get("all"):
        handles = [e.handle for e in ctx.visible_entities()]
    else:
        handles = targets(ctx, args)
    return {"erased": _erase(ctx, handles)}


def _restore_one(ctx, row) -> bool:
    ent = entity_from_dict(row["data"])
    d = ctx.d
    if ent.handle in d.ents or ent.owner not in d.spaces or ent.handle >= d.next_handle:
        return False
    if d.layer(ent.layer) is None:
        return False
    if not d.restore_entity(ent):
        return False
    lst = d.spaces[ent.owner]
    lst.remove(ent.handle)
    for h in row["below"]:
        if h in d.ents and h in lst and h != ent.handle:
            lst.insert(lst.index(h) + 1, ent.handle)
            return True
    for h in row["above"]:
        if h in d.ents and h in lst and h != ent.handle:
            lst.insert(lst.index(h), ent.handle)
            return True
    lst.append(ent.handle)
    return True


def _oops(ctx) -> int:
    rows = sorted(ctx.doc.last_erased, key=lambda r: r["index"])
    return sum(1 for r in rows if _restore_one(ctx, r))


@command("oops", group="modify", label="Oops", description="Restore the objects removed by the last erase.", menu="")
def oops(ctx):
    n = _oops(ctx)
    ctx.say("%d object(s) restored." % n)
    yield from ()


@executes("oops")
def oops_exec(ctx, args):
    return {"restored": _oops(ctx)}


def _displace(ctx, handles, vec):
    moved = 0
    for e in ctx.editable(handles):
        ctx.d.modify(e.handle).move_by(vec)
        moved += 1
    return moved


def _vec(a, b):
    return [b[0] - a[0], b[1] - a[1], 0.0]


@command("move", aliases=("m",), group="modify", label="Move", description="Translate objects by base and second point or displacement.", menu="Modify > Move")
def move(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    b = yield ctx.point("Specify base point", ["Displacement"])
    if b.kind == "enter" or (b.kind == "keyword"):
        d = yield ctx.point("Specify displacement", default=[0.0, 0.0, 0.0], jig=lambda q: jig.moved_items(ctx.d, s.value, [q[0], q[1], 0.0]))
        if d.kind != "point":
            return
        vec = [d.value[0], d.value[1], 0.0]
    elif b.kind == "point":
        p = yield ctx.point("Specify second point or", base=b.value, default_text="use first point as displacement", jig=lambda q: jig.moved_items(ctx.d, s.value, _vec(b.value, q)))
        if p.kind == "point":
            vec = _vec(b.value, p.value)
        elif p.kind == "enter":
            vec = [b.value[0], b.value[1], 0.0]
        else:
            return
    else:
        return
    _displace(ctx, s.value, vec)


@executes("move")
def move_exec(ctx, args):
    handles = targets(ctx, args)
    if "delta" in args:
        vec = geom.as_pt(args["delta"])
    elif "from" in args and "to" in args:
        vec = _vec(geom.as_pt(args["from"]), geom.as_pt(args["to"]))
    else:
        raise CommandError("Give delta or from and to.")
    return {"moved": _displace(ctx, handles, vec)}


def _copies(ctx, handles, vec, count=1):
    made = []
    for k in range(1, count + 1):
        shift = [vec[0] * k, vec[1] * k, 0.0]
        for h in handles:
            e = ctx.d.get(h)
            if e is None:
                continue
            clone = e.copy_as_new()
            clone.move_by(shift)
            made.append(ctx.d.add_entity(clone, e.owner))
    return made


def _array_jig(ctx, handles, base, cursor, count, fit):
    v = _vec(base, cursor)
    if fit:
        v = [v[0] / (count - 1), v[1] / (count - 1), 0.0]
    out = []
    for k in range(1, min(count, 200)):
        out.extend(jig.moved_items(ctx.d, handles, [v[0] * k, v[1] * k, 0.0]))
    return out


@command("copy", aliases=("co", "cp"), group="modify", label="Copy", description="Copy objects repeatedly by displacement.", menu="Modify > Copy")
def copy(ctx):
    s = yield ctx.select("Select objects")
    if s.kind != "selection" or not s.value:
        return
    handles = list(s.value)
    b = yield ctx.point("Specify base point", ["Displacement"])
    if b.kind == "enter" or b.kind == "keyword":
        d = yield ctx.point("Specify displacement", default=[0.0, 0.0, 0.0], jig=lambda q: jig.moved_items(ctx.d, handles, [q[0], q[1], 0.0]))
        if d.kind != "point":
            return
        _copies(ctx, handles, [d.value[0], d.value[1], 0.0])
        return
    if b.kind != "point":
        return
    base = b.value
    batches = []
    while True:
        p = yield ctx.point("Specify second point", ["Array", "Exit", "Undo"], base=base, default="Exit", default_text="Exit", jig=lambda q: jig.moved_items(ctx.d, handles, _vec(base, q)))
        if p.kind == "enter" or (p.kind == "keyword" and p.value == "Exit"):
            return
        if p.kind == "keyword" and p.value == "Undo":
            if batches:
                for h in batches.pop():
                    ctx.d.erase_entity(h)
            else:
                ctx.say("Nothing to undo.")
            continue
        if p.kind == "keyword" and p.value == "Array":
            n = yield ctx.number("Enter number of items to array", default=2, integer=True, minimum=2, maximum=10000)
            if n.kind != "number":
                continue
            q = yield ctx.point("Specify second point", ["Fit"], base=base, jig=lambda c, cnt=n.value: _array_jig(ctx, handles, base, c, cnt, False))
            if q.kind == "keyword":
                q = yield ctx.point("Specify second point to fit array", base=base, jig=lambda c, cnt=n.value: _array_jig(ctx, handles, base, c, cnt, True))
                if q.kind != "point":
                    continue
                v = _vec(base, q.value)
                v = [v[0] / (n.value - 1), v[1] / (n.value - 1), 0.0]
            elif q.kind == "point":
                v = _vec(base, q.value)
            else:
                continue
            batches.append(_copies(ctx, handles, v, n.value - 1))
            continue
        if p.kind == "point":
            batches.append(_copies(ctx, handles, _vec(base, p.value)))
            continue
        return


@executes("copy")
def copy_exec(ctx, args):
    handles = targets(ctx, args)
    count = int(args.get("count", 1))
    if not 1 <= count <= 10000:
        raise CommandError("count must be 1 to 10000.")
    if "delta" in args:
        vec = geom.as_pt(args["delta"])
    elif "from" in args and "to" in args:
        vec = _vec(geom.as_pt(args["from"]), geom.as_pt(args["to"]))
    else:
        raise CommandError("Give delta or from and to.")
    return {"created": _copies(ctx, handles, vec, count)}


@command("select", group="modify", label="Select", description="Build a selection (window, crossing, handle, all).", menu="", undoable=False, repeatable=False)
def select(ctx):
    s = yield ctx.select("Select objects")
    if s.kind == "selection":
        ctx.doc.selection = list(s.value)
        ctx.doc.announce("selection")
        ctx.say("%d selected" % len(s.value))


@command("selectall", aliases=("ai_selall",), group="modify", label="Select All", description="Select every visible object of the editing space.", menu="Edit > Select All", undoable=False, repeatable=False)
def selectall(ctx):
    ctx.doc.selection = [e.handle for e in ctx.visible_entities()]
    ctx.doc.announce("selection")
    ctx.say("%d selected" % len(ctx.doc.selection))
    yield from ()
