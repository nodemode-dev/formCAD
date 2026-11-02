from app.doc import layerops as LO

STATE_OPTS = ["?", "Save", "Restore", "Edit", "Rename", "Delete", "Import", "Export"]
EDIT_OPTS = ["Add", "Remove", "Description", "Update", "Current", "eXit"]


def say_error(ctx, err) -> None:
    ctx.say(str(err))


def names_in(ctx, spec: str) -> list:
    out = LO.match_names(ctx.d, spec)
    if not out:
        ctx.say('Cannot find layer "%s".' % spec.strip())
    return out


def list_states(ctx, spec: str) -> None:
    pats = [s.strip() for s in spec.split(",") if s.strip()] or ["*"]
    rows = [r for r in LO.state_list(ctx.d) if any(LO.name_matches(p, r["name"], False) for p in pats)]
    if not rows:
        ctx.say("No matching layer states found.")
        return
    for r in rows:
        ctx.say("%s - %d layers%s" % (r["name"], r["layers"], (" - " + r["description"]) if r["description"] else ""))


def edit_loop(ctx, name: str):
    d = ctx.d
    while True:
        r = yield ctx.keyword('Enter an option for layer state "%s"' % name, EDIT_OPTS)
        if r.kind != "keyword" or r.value == "eXit":
            return
        k = r.value
        try:
            if k == "Description":
                t = yield ctx.text("Enter layer state description")
                if t.kind == "text":
                    LO.edit_state(d, name, description=t.value)
            elif k == "Update":
                LO.edit_state(d, name, update=True)
                ctx.say('Layer state "%s" updated from the drawing.' % name)
            elif k in ("Add", "Remove", "Current"):
                n = yield ctx.text("Enter name list of layer(s) to %s" % k.lower() if k != "Current" else "Enter layer name to make current in the state")
                if n.kind != "text":
                    continue
                if k == "Current":
                    LO.edit_state(d, name, current=n.value.strip())
                    continue
                found = names_in(ctx, n.value) if k == "Add" else [x.strip() for x in n.value.split(",") if x.strip()]
                if k == "Add":
                    LO.edit_state(d, name, add=found)
                else:
                    LO.edit_state(d, name, remove=found)
        except LO.LayerError as err:
            say_error(ctx, err)


def state_loop(ctx):
    d = ctx.d
    while True:
        r = yield ctx.keyword("Enter layer state option", STATE_OPTS)
        if r.kind != "keyword":
            return
        k = r.value
        try:
            if k == "?":
                n = yield ctx.text("Enter layer state name(s) to list", "*")
                if n.kind == "text":
                    list_states(ctx, n.value)
            elif k == "Save":
                n = yield ctx.text("Enter name for new layer state")
                if n.kind != "text":
                    continue
                name = n.value.strip()
                over = False
                if d.tables["layerstates"].get(name) is not None and LO.state_valid_name(name):
                    y = yield ctx.yesno('Layer state "%s" already exists. Replace it?' % name, "No")
                    if y.kind != "keyword" or y.value != "Yes":
                        continue
                    over = True
                desc = yield ctx.text("Enter layer state description", "")
                text = desc.value if desc.kind == "text" and desc.value else ""
                LO.save_state(d, name, text, overwrite=over)
                ctx.say('Layer state "%s" saved.' % name)
            elif k == "Restore":
                n = yield ctx.text("Enter name of layer state to restore")
                if n.kind != "text":
                    continue
                LO.push_prev(ctx.doc)
                res = LO.restore_state(d, n.value.strip())
                for note in res["notes"]:
                    ctx.say(note)
                ctx.say('Layer state "%s" restored.' % res["name"])
            elif k == "Edit":
                n = yield ctx.text("Enter name of layer state to edit")
                if n.kind != "text":
                    continue
                st = LO.state_get(d, n.value.strip())
                yield from edit_loop(ctx, st["name"])
            elif k == "Rename":
                o = yield ctx.text("Enter old layer state name")
                if o.kind != "text":
                    continue
                st = LO.state_get(d, o.value.strip())
                n = yield ctx.text("Enter new layer state name")
                if n.kind != "text":
                    continue
                LO.edit_state(d, st["name"], rename=n.value.strip())
                ctx.say('Layer state "%s" renamed to "%s".' % (st["name"], n.value.strip()))
            elif k == "Delete":
                n = yield ctx.text("Enter name(s) of layer state(s) to delete")
                if n.kind != "text":
                    continue
                gone = LO.delete_states(d, n.value)
                ctx.say("%d layer state(s) deleted." % len(gone))
            elif k == "Import":
                f = yield ctx.text("Enter file name to import layer states from")
                if f.kind != "text":
                    continue
                res = LO.import_states(d, path=f.value.strip())
                for s in res["skipped"]:
                    ctx.say('Layer state "%s" already exists and was not imported.' % s)
                ctx.say("%d layer state(s) imported." % len(res["imported"]))
            elif k == "Export":
                n = yield ctx.text("Enter name(s) of layer state(s) to export", "*")
                if n.kind != "text":
                    continue
                pats = [s.strip() for s in n.value.split(",") if s.strip()]
                chosen = [r["name"] for r in LO.state_list(d) if any(LO.name_matches(p, r["name"], False) for p in pats)]
                if not chosen:
                    ctx.say("No matching layer states found.")
                    continue
                f = yield ctx.text("Enter file name to export layer states to")
                if f.kind != "text":
                    continue
                res = LO.export_states(d, chosen, f.value.strip())
                ctx.say("%d layer state(s) exported to %s." % (res["count"], res["path"]))
        except LO.LayerError as err:
            say_error(ctx, err)
