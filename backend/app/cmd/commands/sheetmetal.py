from app.cmd.commands.part import add_from, brief, run, sketch_ref
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.part import registry, tree
from app.sheetmetal import check, records, rule, tables

FAILURES = (tables.TableError,)
HEM_WORDS = ["Closed", "Open", "Teardrop", "Rolled"]


def ref_list(items):
    out = []
    for it in items if isinstance(items, (list, tuple)) else [items]:
        if isinstance(it, bool) or it is None:
            continue
        if isinstance(it, int):
            out.append({"pid": it})
        elif isinstance(it, str):
            out.append({"key": it})
        elif isinstance(it, dict):
            out.append(it)
    return out


def sheet_feature(ctx, args, type_name):
    ft = registry.get(type_name)
    params = dict(args.get("params") or {})
    refs = dict(args.get("refs") or {})
    for p in ft.params:
        if p.name in args and p.name not in params:
            params[p.name] = args[p.name]
    for slot in ft.refs:
        if slot.name in refs or slot.name not in args:
            continue
        if slot.kind in ("sketch", "feature"):
            refs.update(sketch_ref(ctx.doc, args[slot.name]))
        else:
            refs[slot.name] = ref_list(args[slot.name]) if slot.multi else ref_list(args[slot.name])[0]
    clean = dict(args, params=params, refs=refs)
    return add_from(ctx, clean, type_name, refs)


def ask_ids(ctx, label):
    raw = yield ctx.text(label, None)
    if raw.kind != "text":
        return None
    out = []
    for tok in str(raw.value).replace(",", " ").split():
        try:
            out.append(int(tok))
        except ValueError:
            raise CommandError("%s is not a persistent id; give numbers separated by spaces." % tok)
    return out or None


@command("smbaseflange", group="solids", label="Base Flange", description="Make the first sheet metal feature from a sketch: a closed shape gives a plate, an open path a bent section.", menu="Draw > Sheet Metal > Base Flange")
def smbaseflange(ctx):
    sk = yield ctx.text("Sketch name", None)
    if sk.kind != "text":
        return
    t = yield ctx.number("Sheet thickness", positive=True)
    if t.kind != "number":
        return
    sheet_feature(ctx, {"sketch": sk.value, "thickness": t.value}, "base_flange")


@executes("smbaseflange")
def smbaseflange_exec(ctx, args):
    return sheet_feature(ctx, args, "base_flange")


@command("smedgeflange", group="solids", label="Edge Flange", description="Fold a flange from one or more straight edges of the sheet.", menu="Draw > Sheet Metal > Edge Flange")
def smedgeflange(ctx):
    ids = yield from ask_ids(ctx, "Persistent ids of the edges")
    if not ids:
        return
    h = yield ctx.number("Flange length", positive=True)
    if h.kind != "number":
        return
    sheet_feature(ctx, {"edges": ids, "length": h.value}, "edge_flange")


@executes("smedgeflange")
def smedgeflange_exec(ctx, args):
    return sheet_feature(ctx, args, "edge_flange")


@command("smmiterflange", group="solids", label="Miter Flange", description="Fold a flange along a chain of connected edges with mitered corners.", menu="Draw > Sheet Metal > Miter Flange")
def smmiterflange(ctx):
    ids = yield from ask_ids(ctx, "Persistent ids of the edges in order")
    if not ids:
        return
    h = yield ctx.number("Flange length", positive=True)
    if h.kind != "number":
        return
    sheet_feature(ctx, {"edges": ids, "length": h.value}, "miter_flange")


@executes("smmiterflange")
def smmiterflange_exec(ctx, args):
    return sheet_feature(ctx, args, "miter_flange")


@command("smhem", group="solids", label="Hem", description="Fold an edge back on itself: closed, open, teardrop or rolled.", menu="Draw > Sheet Metal > Hem")
def smhem(ctx):
    ids = yield from ask_ids(ctx, "Persistent ids of the edges")
    if not ids:
        return
    kind = yield ctx.keyword("Hem type [Closed/Open/Teardrop/Rolled]", HEM_WORDS, "Closed")
    word = (kind.value if kind.kind == "keyword" else "Closed").lower()
    sheet_feature(ctx, {"edges": ids, "hem": word}, "hem")


@executes("smhem")
def smhem_exec(ctx, args):
    return sheet_feature(ctx, args, "hem")


@command("smjog", group="solids", label="Jog", description="Offset the sheet across a sketched line with two opposite bends.", menu="Draw > Sheet Metal > Jog")
def smjog(ctx):
    sk = yield ctx.text("Sketch name with the jog line", None)
    if sk.kind != "text":
        return
    ids = yield from ask_ids(ctx, "Persistent id of the face")
    if not ids:
        return
    off = yield ctx.number("Jog offset", positive=True)
    if off.kind != "number":
        return
    sheet_feature(ctx, {"sketch": sk.value, "face": ids[0], "offset": off.value}, "jog")


@executes("smjog")
def smjog_exec(ctx, args):
    return sheet_feature(ctx, args, "jog")


@command("smsketchbend", group="solids", label="Sketched Bend", description="Bend the flat sheet along a sketched line.", menu="Draw > Sheet Metal > Sketched Bend")
def smsketchbend(ctx):
    sk = yield ctx.text("Sketch name with the bend line", None)
    if sk.kind != "text":
        return
    ids = yield from ask_ids(ctx, "Persistent id of the face")
    if not ids:
        return
    sheet_feature(ctx, {"sketch": sk.value, "face": ids[0]}, "sketched_bend")


@executes("smsketchbend")
def smsketchbend_exec(ctx, args):
    return sheet_feature(ctx, args, "sketched_bend")


@command("smbendrelief", group="solids", label="Bend Relief", description="Cut relief notches at the ends of bends.", menu="Draw > Sheet Metal > Bend Relief")
def smbendrelief(ctx):
    raw = yield ctx.text("Bend ids, for example F3.1 F4.2", None)
    if raw.kind != "text":
        return
    sheet_feature(ctx, {"bends": str(raw.value).replace(",", " ").split()}, "bend_relief")


@executes("smbendrelief")
def smbendrelief_exec(ctx, args):
    bends = args.get("bends")
    if isinstance(bends, str):
        args = dict(args, bends=bends.replace(",", " ").split())
    return sheet_feature(ctx, args, "bend_relief")


@command("smcornerrelief", group="solids", label="Corner Relief", description="Cut a relief where two bends meet in a corner.", menu="Draw > Sheet Metal > Corner Relief")
def smcornerrelief(ctx):
    raw = yield ctx.text("Two bend ids that meet, for example F3.1 F4.1", None)
    if raw.kind != "text":
        return
    pair = str(raw.value).replace(",", " ").split()
    if len(pair) != 2:
        raise CommandError("Give exactly two bend ids.")
    sheet_feature(ctx, {"corners": [pair]}, "corner_relief")


@executes("smcornerrelief")
def smcornerrelief_exec(ctx, args):
    return sheet_feature(ctx, args, "corner_relief")


@command("smconvert", group="solids", label="Convert to Sheet Metal", description="Treat the body as constant thickness sheet and record its bends from a fixed face.", menu="Draw > Sheet Metal > Convert to Sheet Metal")
def smconvert(ctx):
    ids = yield from ask_ids(ctx, "Persistent id of the fixed face")
    if not ids:
        return
    sheet_feature(ctx, {"face": ids[0]}, "convert_sheet")


@executes("smconvert")
def smconvert_exec(ctx, args):
    return sheet_feature(ctx, args, "convert_sheet")


def rule_summary(doc):
    r = rule.rule_of_part(doc.drawing)
    if r is None:
        return None
    return {k: v for k, v in r.items() if k != "table"}


@command("smrule", group="solids", label="Sheet Metal Rule", description="Show the sheet metal rule of the part, or change one value of it.", menu="Tools > Sheet Metal > Rule")
def smrule(ctx):
    r = rule_summary(ctx.doc)
    if r is None:
        ctx.say("The part has no sheet metal rule yet; add a base flange first.")
        return
    ctx.say("Thickness %.4g mm, inside radius %.4g mm, method %s, K-factor %.4g." % (r["thickness_mm"], r["inner_radius_mm"], r["bend_method"], r["k_factor"]))
    key = yield ctx.text("Value to change (blank to keep the rule)", "")
    if key.kind != "text" or not str(key.value).strip():
        return
    val = yield ctx.number("New value")
    if val.kind != "number":
        return
    edit_rule(ctx, {str(key.value).strip(): val.value})


def edit_rule(ctx, values):
    root = rule.root_record(ctx.doc.drawing)
    if root is None:
        raise CommandError("The part has no sheet metal rule yet; add a base flange first.")
    ft = registry.get(root["type"])
    bad = [k for k in values if ft.param(k) is None or k in ("side", "depth", "depth_mode", "flip_depth")]
    if bad:
        raise CommandError("%s is not a rule value." % ", ".join(bad))
    out = run(tree.edit_feature, ctx.doc, root["id"], None, values)
    ctx.say(brief(out)["message"])
    return brief(out)


@executes("smrule")
def smrule_exec(ctx, args):
    values = dict(args.get("params") or {})
    for p in rule.RULE_PARAMS:
        if p.name in args and p.name not in values:
            values[p.name] = args[p.name]
    if not values:
        return {"rule": rule_summary(ctx.doc), "tables": tables.listing(ctx.doc.drawing)}
    return edit_rule(ctx, values)


@command("smtable", group="solids", label="Bend Tables", description="List the bend tables available to the part.", menu="Tools > Sheet Metal > Bend Tables", undoable=False)
def smtable(ctx):
    rows = tables.listing(ctx.doc.drawing)
    for t in rows:
        ctx.say("%s  %s  %s by %s  %s" % (t["id"], t["name"], t["mode"], t["axis"], t["origin"]))
    if not rows:
        ctx.say("There are no bend tables.")


@executes("smtable")
def smtable_exec(ctx, args):
    action = str(args.get("action") or "list").lower()
    d = ctx.doc.drawing
    try:
        if action == "list":
            return {"tables": tables.listing(d), "gauges": tables.gauges(d)}
        if action == "get":
            got = tables.get(d, args.get("id"))
            if got is None:
                raise CommandError("There is no bend table %s." % args.get("id"))
            return got
        if action in ("set", "add", "edit"):
            body = args.get("table") or {k: args[k] for k in ("name", "mode", "axis", "sets", "tolerance", "source") if k in args}
            return rule.save_table(ctx.doc, args.get("id"), body)
        if action == "delete":
            rule.drop_table(ctx.doc, args.get("id"))
            return {"message": "Bend table deleted."}
    except FAILURES as err:
        raise CommandError(str(err))
    raise CommandError("The action is list, get, set or delete.")


@command("smcheck", group="solids", label="Check Sheet Metal", description="Measure the thickness and the bend radii of the sheet body.", menu="Tools > Sheet Metal > Check", undoable=False)
def smcheck(ctx):
    out = run(check.verify, ctx.doc)
    ctx.say("Thickness deviation %.2e mm, %d bends, radii %s." % (out["max_deviation"], out["bends"], ", ".join("%.4g" % r for r in out["radii_mm"])))


@executes("smcheck")
def smcheck_exec(ctx, args):
    return run(check.verify, ctx.doc)


@command("smbends", group="solids", label="Bend List", description="List the recorded bends of the sheet metal part.", menu="Tools > Sheet Metal > Bend List", undoable=False)
def smbends(ctx):
    rows = records.bends(ctx.doc.drawing)
    for b in rows:
        ctx.say("%s  %s  %.1f deg  R%.4g  %s  BA %.4f" % (b["id"], b["type"], b["angle"] * 57.29577951308232, b["radius"], b["direction"], b["ba"]))
    if not rows:
        ctx.say("The part has no recorded bends.")


@executes("smbends")
def smbends_exec(ctx, args):
    return {"bends": records.bends(ctx.doc.drawing), "features": records.features(ctx.doc.drawing)}
