import copy

from app.cmd import dim_support as DS
from app.cmd.context import CommandError
from app.cmd.draw_support import pick_entity
from app.cmd.registry import command, executes
from app.dim import vars as DV
from app.doc import tables as T
from app.sysvars import registry as sv

DESCRIPTIONS = {}


def _describe(name):
    if not DESCRIPTIONS:
        sv._ensure_loaded()
        for vd in sv.VARS:
            if vd.dim:
                DESCRIPTIONS[vd.name] = vd.desc
    return DESCRIPTIONS.get(name, "")


def style_names(ctx):
    return sorted(ctx.d.tables["dimstyles"].names(), key=lambda n: n.casefold())


def find_style(ctx, name):
    rec = ctx.d.table_get("dimstyles", str(name).strip())
    if rec is None:
        raise CommandError('Dimension style "%s" does not exist.' % name)
    return rec


def in_use(ctx, name):
    low = name.casefold()
    for e in ctx.d.ents.values():
        if e.kind == "dimension" and str(e.style).casefold() == low:
            return True
    return False


def list_lines(ctx):
    cur = DS.current_style(ctx)
    out = []
    for n in style_names(ctx):
        out.append("%s%s" % (n, "  (current)" if n.casefold() == cur.casefold() else ""))
    return out


def variable_lines(ctx, rec, other=None):
    out = []
    a = rec["vars"]
    for name in DV.NAMES:
        va = a.get(name)
        if other is None:
            out.append("%-12s %-12s %s" % (name, DV.format_value(va), _describe(name)))
        else:
            vb = other["vars"].get(name)
            if va != vb:
                out.append("%-12s %-12s %-12s %s" % (name, DV.format_value(va), DV.format_value(vb), _describe(name)))
    return out


def compare_lines(ctx, name_a, name_b):
    a, b = find_style(ctx, name_a), find_style(ctx, name_b)
    diff = variable_lines(ctx, a, b)
    head = 'Comparing "%s" and "%s"' % (a["name"], b["name"])
    if not diff:
        return [head, "The dimension styles are identical."]
    return [head] + ["%-12s %-12s %-12s" % ("Variable", a["name"], b["name"])] + diff


def save_style(ctx, name, vars_=None, source=None, annotative=None, description=None):
    nm = str(name).strip()
    if not nm or len(nm) > 255 or any(ch in nm for ch in '<>/\\":;?*|,=`'):
        raise CommandError("Invalid dimension style name.")
    base = source if source is not None else find_style(ctx, DS.current_style(ctx))
    cur = ctx.d.table_get("dimstyles", nm)
    rec = copy.deepcopy(cur) if cur is not None else T.new_dimstyle(nm)
    if cur is None or source is not None:
        rec["vars"] = copy.deepcopy(base["vars"])
    rec["name"] = cur["name"] if cur is not None else nm
    bad = []
    for k, v in (vars_ or {}).items():
        try:
            rec["vars"][DV.clean_name(k)] = DV.validate(ctx.doc, k, v)
        except KeyError:
            bad.append(k)
        except ValueError as err:
            raise CommandError(str(err))
    if bad:
        raise CommandError("Unknown dimension variable: %s." % ", ".join(str(b) for b in bad))
    if annotative is not None:
        rec["annotative"] = bool(annotative)
    if description is not None:
        rec["description"] = str(description)
    ctx.d.table_set("dimstyles", rec)
    return rec


def set_current(ctx, name):
    rec = find_style(ctx, name)
    sv.set_var(ctx.doc, "DIMSTYLE", rec["name"])
    return rec


def rename_style(ctx, old, new):
    rec = find_style(ctx, old)
    if rec["name"].casefold() == "standard":
        raise CommandError("Standard cannot be renamed.")
    new = str(new).strip()
    if not new:
        raise CommandError("Invalid dimension style name.")
    if ctx.d.table_get("dimstyles", new) is not None:
        raise CommandError('Dimension style "%s" already exists.' % new)
    was_current = rec["name"].casefold() == DS.current_style(ctx).casefold()
    old_name = rec["name"]
    ctx.d.table_remove("dimstyles", old_name)
    moved = copy.deepcopy(rec)
    moved["name"] = new
    ctx.d.table_set("dimstyles", moved)
    for e in list(ctx.d.ents.values()):
        if e.kind == "dimension" and str(e.style).casefold() == old_name.casefold():
            ctx.d.modify(e.handle).style = new
    if was_current:
        ctx.d.set_header("DIMSTYLE", new)
    return moved


def delete_style(ctx, name):
    rec = find_style(ctx, name)
    nm = rec["name"]
    if nm.casefold() == "standard":
        raise CommandError("Standard cannot be deleted.")
    if nm.casefold() == DS.current_style(ctx).casefold():
        raise CommandError("The current dimension style cannot be deleted.")
    if in_use(ctx, nm):
        raise CommandError("The dimension style is in use and cannot be deleted.")
    ctx.d.table_remove("dimstyles", nm)


def apply_to(ctx, handles):
    from app.cmd.commands.dim_edit import _update

    return _update(ctx, handles)


def _ask_style(ctx, msg, default=None):
    while True:
        r = yield ctx.word(msg, ["?"], default)
        if r.kind == "keyword" and r.value == "?":
            for line in list_lines(ctx):
                ctx.say(line)
            continue
        return r


def _run_menu(ctx):
    while True:
        mp = ctx.keyword("Enter a dimension style option", ["Save", "Restore", "STatus", "Variables", "Apply", "?", "Rename", "Delete", "Compare"], None)
        mp.hint = "bare"
        r = yield mp
        if r.kind != "keyword":
            return
        k = r.value
        if k == "Save":
            n = yield ctx.word("Enter name for new dimension style", ["?"])
            if n.kind == "keyword":
                for line in list_lines(ctx):
                    ctx.say(line)
                continue
            if n.kind != "text":
                return
            if ctx.d.table_get("dimstyles", n.value) is not None:
                y = yield ctx.yesno("That dimension style already exists. Replace it?", "No")
                if y.kind != "keyword" or y.value != "Yes":
                    return
            save_style(ctx, n.value)
            ctx.say('Dimension style "%s" saved.' % n.value)
            return
        if k == "Restore":
            pr = ctx.word("Enter dimension style name,", ["?"])
            pr.hint = "bare"
            pr.default_text = "select dimension"
            r2 = yield pr
            if r2.kind == "keyword":
                for line in list_lines(ctx):
                    ctx.say(line)
                continue
            if r2.kind == "enter":
                s = yield ctx.entity("Select dimension")
                ent = pick_entity(ctx, s.value) if s.kind == "entity" else None
                if ent is None or ent.kind != "dimension":
                    ctx.say("Object selected is not a dimension.")
                    return
                set_current(ctx, ent.style)
                return
            if r2.kind != "text":
                return
            set_current(ctx, r2.value)
            return
        if k == "STatus":
            for line in variable_lines(ctx, find_style(ctx, DS.current_style(ctx))):
                ctx.say(line)
            return
        if k == "Variables":
            r2 = yield from _ask_style(ctx, "Enter dimension style name or [?]")
            if r2.kind != "text":
                return
            rec = find_style(ctx, r2.value)
            r3 = yield ctx.word("Enter a dimension style to compare or <none>", ["?"])
            if r3.kind == "text":
                for line in compare_lines(ctx, rec["name"], r3.value):
                    ctx.say(line)
            else:
                for line in variable_lines(ctx, rec):
                    ctx.say(line)
            return
        if k == "Apply":
            s = yield ctx.select("Select objects")
            if s.kind == "selection" and s.value:
                ctx.say("%d dimension(s) updated." % apply_to(ctx, s.value))
            return
        if k == "?":
            for line in list_lines(ctx):
                ctx.say(line)
            return
        if k == "Compare":
            a = yield ctx.word("Enter first dimension style name")
            b = yield ctx.word("Enter second dimension style name")
            if a.kind == "text" and b.kind == "text":
                for line in compare_lines(ctx, a.value, b.value):
                    ctx.say(line)
            return
        if k == "Rename":
            a = yield ctx.word("Enter dimension style name to rename")
            b = yield ctx.word("Enter new dimension style name")
            if a.kind == "text" and b.kind == "text":
                rename_style(ctx, a.value, b.value)
            return
        if k == "Delete":
            a = yield ctx.word("Enter dimension style name to delete")
            if a.kind == "text":
                delete_style(ctx, a.value)
            return


@command("dimstyle", aliases=("d", "dst", "ddim"), group="annotate", label="Dimension Style", description="Save, restore, list, compare, apply, rename and delete dimension styles.", menu="Format > Dimension Style")
def dimstyle(ctx):
    yield from _run_menu(ctx)


@command("-dimstyle", group="annotate", label="Dimension Style (command line)", description="Command line dimension style options: Save, Restore, STatus, Variables, Apply, ?.", menu="")
def dimstyle_text(ctx):
    yield from _run_menu(ctx)


@command("dimstyle.dimension", group="annotate", label="Dimension Style", description="Same as DIMSTYLE, from the Dimension menu.", menu="Dimension > Dimension Style")
def dimstyle_dimension(ctx):
    yield from _run_menu(ctx)


@command("dimstyle.list", group="annotate", label="List Dimension Styles", description="List dimension styles.", menu="")
def dimstyle_list(ctx):
    for line in list_lines(ctx):
        ctx.say(line)
    yield from ()


@command("dimstyle.current", group="annotate", label="Set Current Dimension Style", description="Make a dimension style current.", menu="")
def dimstyle_current(ctx):
    r = yield from _ask_style(ctx, "Enter dimension style name or [?]", DS.current_style(ctx))
    if r.kind in ("text",):
        set_current(ctx, r.value)
    elif r.kind == "enter":
        pass


@command("dimstyle.rename", group="annotate", label="Rename Dimension Style", description="Rename a dimension style.", menu="")
def dimstyle_rename(ctx):
    a = yield ctx.word("Enter dimension style name to rename")
    b = yield ctx.word("Enter new dimension style name")
    if a.kind == "text" and b.kind == "text":
        rename_style(ctx, a.value, b.value)


@command("dimstyle.delete", group="annotate", label="Delete Dimension Style", description="Delete an unused dimension style.", menu="")
def dimstyle_delete(ctx):
    a = yield ctx.word("Enter dimension style name to delete")
    if a.kind == "text":
        delete_style(ctx, a.value)


@command("dimstyle.compare", group="annotate", label="Compare Dimension Styles", description="Compare two dimension styles variable by variable.", menu="")
def dimstyle_compare(ctx):
    a = yield ctx.word("Enter first dimension style name")
    b = yield ctx.word("Enter second dimension style name")
    if a.kind == "text" and b.kind == "text":
        for line in compare_lines(ctx, a.value, b.value):
            ctx.say(line)


@command("dimstyle.override", group="annotate", label="Dimension Style Override", description="Apply or clear per-dimension style overrides.", menu="")
def dimstyle_override(ctx):
    from app.cmd.commands.dim_edit import dimoverride

    yield from dimoverride(ctx)


def _style_entry(rec, current):
    return {"name": rec["name"], "current": rec["name"].casefold() == current.casefold(), "annotative": bool(rec.get("annotative")), "description": rec.get("description", ""), "vars": copy.deepcopy(rec["vars"])}


@executes("dimstyle", "-dimstyle", "dimstyle.dimension")
def dimstyle_exec(ctx, args):
    action = str(args.get("action", "list")).lower()
    cur = DS.current_style(ctx)
    if action == "list":
        return {"styles": [_style_entry(find_style(ctx, n), cur) for n in style_names(ctx)], "current": cur}
    if action in ("save", "create", "modify"):
        name = args.get("name")
        if not name:
            raise CommandError("Give a style name.")
        exists = ctx.d.table_get("dimstyles", name) is not None
        if action == "modify" and not exists:
            raise CommandError('Dimension style "%s" does not exist.' % name)
        if action == "create" and exists:
            raise CommandError('Dimension style "%s" already exists.' % name)
        source = find_style(ctx, args["from"]) if args.get("from") else None
        rec = save_style(ctx, name, args.get("vars"), source, args.get("annotative"), args.get("description"))
        if args.get("current"):
            set_current(ctx, rec["name"])
        return {"style": _style_entry(rec, DS.current_style(ctx))}
    if action in ("restore", "current"):
        rec = set_current(ctx, args["name"])
        return {"current": rec["name"]}
    if action in ("status", "variables"):
        rec = find_style(ctx, args.get("name") or cur)
        return {"name": rec["name"], "vars": copy.deepcopy(rec["vars"])}
    if action == "compare":
        a, b = find_style(ctx, args["a"]), find_style(ctx, args["b"])
        diff = {k: [a["vars"].get(k), b["vars"].get(k)] for k in DV.NAMES if a["vars"].get(k) != b["vars"].get(k)}
        return {"a": a["name"], "b": b["name"], "differences": diff}
    if action == "apply":
        return {"updated": apply_to(ctx, [int(h) for h in args.get("handles", [])])}
    if action == "rename":
        rec = rename_style(ctx, args["name"], args["new"])
        return {"style": _style_entry(rec, DS.current_style(ctx))}
    if action == "delete":
        delete_style(ctx, args["name"])
        return {"deleted": args["name"]}
    if action == "override":
        from app.cmd.commands.dim_edit import _set_overrides, _validate_all

        handles = [int(h) for h in args.get("handles", [])]
        values = _validate_all(ctx, args.get("vars", {}))
        return {"changed": _set_overrides(ctx, handles, values, bool(args.get("clear")))}
    raise CommandError("Action must be list, save, create, modify, restore, status, variables, compare, apply, rename, delete or override.")
