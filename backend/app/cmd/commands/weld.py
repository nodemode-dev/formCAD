import copy

from app.cmd import barred
from app.cmd.commands.part import brief, find_feature, run
from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.param import units as U
from app.part import store, tree
from app.weld import cutlist, joints, shapes

AGENT_MEMBER_CAP = 40
FRAME_PARAMS = ("members", "corner", "junctions", "tolerance", "gussets", "end_caps", "density")
FAILURES = (cutlist.CutError, shapes.ShapeError)


def guard(fn):
    def call(*a, **kw):
        try:
            return fn(*a, **kw)
        except FAILURES as err:
            raise CommandError(str(err))

    return call


def caller_cap(ctx, count):
    if barred.caller(getattr(ctx, "runner", None)) and count > AGENT_MEMBER_CAP:
        raise CommandError("A macro or an agent may place at most %d members at once; use the window for larger frames." % AGENT_MEMBER_CAP)


def frame_ids(doc):
    recs = store.records(doc.drawing)
    order = store.tree(doc.drawing)["order"]
    return [f for f in order if f in recs and recs[f]["type"] == "weld_frame"]


def need_frame(ctx, args):
    if args.get("frame") not in (None, ""):
        fid = find_feature(ctx.doc, args["frame"])
        if store.get(ctx.doc.drawing, fid)["type"] != "weld_frame":
            raise CommandError("%s is not a weld frame." % fid)
        return fid
    ids = frame_ids(ctx.doc)
    if not ids:
        raise CommandError("There is no weld frame; run WELDFRAME first.")
    return ids[-1]


def resolve_profile(ctx, spec, ids):
    if isinstance(spec, dict) or spec in (None, ""):
        return spec
    if isinstance(spec, str) and spec.split(" ")[0] in shapes.SHAPES:
        return parse_inline(spec)
    fid = find_feature(ctx.doc, spec)
    if store.get(ctx.doc.drawing, fid)["type"] != "sketch":
        raise CommandError("%s is not a sketch." % spec)
    if fid not in ids:
        ids.append(fid)
    return fid


def parse_inline(text):
    parts = str(text).replace(",", " ").split()
    names = [n for n, _ in shapes.SHAPES[parts[0]]]
    try:
        nums = [float(x) for x in parts[1:]]
    except ValueError:
        raise CommandError("Give the sizes of %s as numbers: %s." % (parts[0], " ".join(names)))
    if len(nums) > len(names) or len(nums) < len([n for n, lab in shapes.SHAPES[parts[0]] if "optional" not in lab]):
        raise CommandError("%s takes the sizes %s." % (parts[0], " ".join(names)))
    out = {"shape": parts[0]}
    out.update(dict(zip(names, nums)))
    return out


def clean_members(ctx, raw, ids, default_profile=None):
    out = []
    for i, m in enumerate(raw):
        if not isinstance(m, dict):
            raise CommandError("Member %d is not an object." % (i + 1))
        q = dict(m)
        q["profile"] = resolve_profile(ctx, q.get("profile", default_profile), ids)
        out.append(q)
    return out


def build_members(ctx, args, ids):
    if args.get("members"):
        return clean_members(ctx, args["members"], ids, args.get("profile"))
    lines = args.get("lines")
    if not lines:
        raise CommandError("Give members, or lines with a profile.")
    members = []
    for i, ln in enumerate(lines):
        if not isinstance(ln, (list, tuple)) or len(ln) != 2:
            raise CommandError("A line is a pair of points.")
        members.append({"a": list(ln[0]), "b": list(ln[1])})
    return clean_members(ctx, members, ids, args.get("profile"))


def edit_frame(ctx, fid, mutate, new_profiles=()):
    rec = store.get(ctx.doc.drawing, fid)
    params = copy.deepcopy(rec.get("params") or {})
    mutate(params)
    refs = None
    have = [r.get("id") for r in (rec.get("refs") or {}).get("profiles") or [] if isinstance(r, dict)]
    want = list(have) + [p for p in new_profiles if p not in have]
    if want != have:
        refs = {"profiles": want}
    out = run(tree.edit_feature, ctx.doc, fid, None, {k: params[k] for k in params}, refs)
    ctx.say(brief(out)["message"])
    return brief(out)


@command("weldframe", group="solids", label="Weld Frame", description="Build a frame of structural members along lines from a profile, with corner treatments.", menu="Draw > Weldments > Frame")
def weldframe(ctx):
    prof = yield ctx.text("Profile: a sketch name or a shape with sizes, for example rect_tube 40 40 3", None)
    if prof.kind != "text":
        return
    a = yield ctx.text("First member start x y z", None)
    if a.kind != "text":
        return
    b = yield ctx.text("First member end x y z", None)
    if b.kind != "text":
        return

    def pt(raw):
        try:
            v = [float(x) for x in str(raw.value).replace(",", " ").split()]
        except ValueError:
            raise CommandError("Give three numbers.")
        if len(v) != 3:
            raise CommandError("Give three numbers.")
        return v

    weldframe_exec(ctx, {"lines": [[pt(a), pt(b)]], "profile": prof.value})


@executes("weldframe")
@guard
def weldframe_exec(ctx, args):
    ids = []
    members = build_members(ctx, args, ids)
    caller_cap(ctx, len(members))
    params = {k: args[k] for k in FRAME_PARAMS if k in args and k != "members"}
    params["members"] = members
    refs = {"profiles": ids} if ids else {}
    out = run(tree.add_feature, ctx.doc, "weld_frame", params, refs, args.get("label"), args.get("after"), False)
    ctx.say(brief(out)["message"])
    return brief(out)


@command("weldmember", group="solids", label="Weld Member", description="Add, change or remove a member of a weld frame.", menu="Draw > Weldments > Member")
def weldmember(ctx):
    mid = yield ctx.text("Member id to remove, or Enter to add", "")
    if mid.kind != "text":
        return
    if str(mid.value).strip():
        weldmember_exec(ctx, {"action": "remove", "id": str(mid.value).strip()})
        return
    ctx.say("Give the member with the programmatic form: a, b, profile.")


@executes("weldmember")
@guard
def weldmember_exec(ctx, args):
    fid = need_frame(ctx, args)
    action = str(args.get("action") or "add")
    ids = []
    spec = {k: v for k, v in args.items() if k in ("id", "a", "b", "profile", "rotation", "locate", "group", "label", "start_trim", "end_trim")}
    if "profile" in spec:
        spec["profile"] = resolve_profile(ctx, spec["profile"], ids)
    if action not in ("add", "edit", "remove"):
        raise CommandError("The action is add, edit or remove.")

    def change(p):
        mem = list(p.get("members") or [])
        pos = next((i for i, m in enumerate(mem) if str(m.get("id")) == str(spec.get("id"))), None)
        if action == "add":
            if pos is not None:
                raise CommandError("Member %s already exists." % spec.get("id"))
            if "a" not in spec or "b" not in spec:
                raise CommandError("A member needs a and b.")
            caller_cap(ctx, len(mem) + 1)
            if not spec.get("id"):
                n = 1
                used = {str(m.get("id")) for m in mem}
                while "M%d" % n in used:
                    n += 1
                spec["id"] = "M%d" % n
            mem.append(spec)
        elif pos is None:
            raise CommandError("There is no member %s." % spec.get("id"))
        elif action == "remove":
            del mem[pos]
            if not mem:
                raise CommandError("A frame needs at least one member; delete the feature instead.")
        else:
            mem[pos] = {**mem[pos], **spec}
        p["members"] = mem

    return edit_frame(ctx, fid, change, ids)


@command("weldjoint", group="solids", label="Weld Joint", description="Set the corner treatment and trim priority at one junction of a weld frame.", menu="Draw > Weldments > Joint")
def weldjoint(ctx):
    at = yield ctx.text("Junction position x y z", None)
    if at.kind != "text":
        return
    word = yield ctx.keyword("Treatment [Miter/Butt/Cope/None]", ["Miter", "Butt", "Cope", "None"], "Butt")
    kind = str(word.value).lower() if word.kind == "keyword" else "butt"
    try:
        pos = [float(x) for x in str(at.value).replace(",", " ").split()]
    except ValueError:
        raise CommandError("Give three numbers.")
    weldjoint_exec(ctx, {"at": pos, "treatment": kind})


@executes("weldjoint")
@guard
def weldjoint_exec(ctx, args):
    fid = need_frame(ctx, args)
    at = args.get("at")
    if not isinstance(at, (list, tuple)) or len(at) != 3:
        raise CommandError("Give the junction position at: [x, y, z].")
    if args.get("treatment") not in (None,) + joints.TREATMENTS:
        raise CommandError("The treatment is one of %s." % ", ".join(joints.TREATMENTS))
    spec = {"at": [float(c) for c in at]}
    for k in ("treatment", "order"):
        if args.get(k) is not None:
            spec[k] = args[k]

    def change(p):
        js = [j for j in (p.get("junctions") or []) if not same_point(j.get("at"), spec["at"])]
        if not args.get("clear"):
            js.append(spec)
        p["junctions"] = js

    return edit_frame(ctx, fid, change)


def same_point(a, b):
    try:
        return all(abs(float(x) - float(y)) < 1e-6 for x, y in zip(a, b))
    except (TypeError, ValueError):
        return False


@command("weldgusset", group="solids", label="Weld Gusset", description="Add a triangular gusset between two members that meet.", menu="Draw > Weldments > Gusset")
def weldgusset(ctx):
    raw = yield ctx.text("Two member ids, for example X1 L1", None)
    if raw.kind != "text":
        return
    pair = str(raw.value).replace(",", " ").split()
    if len(pair) != 2:
        raise CommandError("Give exactly two member ids.")
    leg = yield ctx.number("Gusset leg length", positive=True)
    if leg.kind != "number":
        return
    t = yield ctx.number("Gusset thickness", positive=True)
    if t.kind != "number":
        return
    weldgusset_exec(ctx, {"members": pair, "leg": leg.value, "thickness": t.value})


@executes("weldgusset")
@guard
def weldgusset_exec(ctx, args):
    fid = need_frame(ctx, args)

    def change(p):
        gs = list(p.get("gussets") or [])
        if args.get("action") == "remove":
            idx = int(args.get("index", -1))
            if not 0 <= idx < len(gs):
                raise CommandError("There is no gusset %s." % args.get("index"))
            del gs[idx]
        else:
            if not isinstance(args.get("members"), list) or len(args["members"]) != 2:
                raise CommandError("Give members: [idA, idB].")
            if len(gs) >= 200:
                raise CommandError("A frame holds at most 200 gussets.")
            gs.append({k: args[k] for k in ("members", "leg", "thickness", "side", "label") if k in args})
        p["gussets"] = gs

    return edit_frame(ctx, fid, change)


@command("weldendcap", group="solids", label="Weld End Cap", description="Add a plate that closes the end of a member.", menu="Draw > Weldments > End Cap")
def weldendcap(ctx):
    mid = yield ctx.text("Member id", None)
    if mid.kind != "text":
        return
    end = yield ctx.keyword("End [Start/End]", ["Start", "End"], "End")
    t = yield ctx.number("Cap thickness", positive=True)
    if t.kind != "number":
        return
    weldendcap_exec(ctx, {"member": str(mid.value).strip(), "end": str(end.value).lower() if end.kind == "keyword" else "end", "thickness": t.value})


@executes("weldendcap")
@guard
def weldendcap_exec(ctx, args):
    fid = need_frame(ctx, args)

    def change(p):
        cs = list(p.get("end_caps") or [])
        if args.get("action") == "remove":
            idx = int(args.get("index", -1))
            if not 0 <= idx < len(cs):
                raise CommandError("There is no end cap %s." % args.get("index"))
            del cs[idx]
        else:
            if args.get("member") in (None, "") or args.get("thickness") is None:
                raise CommandError("Give member and thickness.")
            if len(cs) >= 400:
                raise CommandError("A frame holds at most 400 end caps.")
            cs.append({k: args[k] for k in ("member", "end", "thickness", "shape", "offset", "label") if k in args})
        p["end_caps"] = cs

    return edit_frame(ctx, fid, change)


@command("weldcutlist", group="inquiry", label="Weld Cut List", description="List the members of the weld frames with length and both cut angles.", menu="Tools > Inquiry > Weld Cut List", undoable=False, repeatable=False)
def weldcutlist(ctx):
    weldcutlist_exec(ctx, {})
    yield from ()


@executes("weldcutlist")
@guard
def weldcutlist_exec(ctx, args):
    res = cutlist.build(ctx.d, args.get("tolerance"))
    for r in res["rows"]:
        ctx.say("%d. %d x %s, length %s, angles %s and %s%s" % (r["item"], r["qty"], r["profile"], cutlist.fmt(r["length"] / U.mm_per_unit(ctx.d)), cutlist.fmt(r["angle1"]), cutlist.fmt(r["angle2"]), (", " + r["description"]) if r["description"] else ""))
    return res


def table_fill(ctx, t, res, cols, title):
    from app.doc import tableops as O

    header = [cutlist.TITLES[c] for c in cols]
    body = cutlist.cells(ctx.d, res["rows"], cols)
    rows = []
    if t.title:
        rows.append([title])
    if t.header:
        rows.append(header)
    rows.extend(body or [[""] * len(cols)])
    try:
        O.fill_from_rows(ctx.d, t, rows, 0)
    except O.TableError as err:
        raise CommandError(str(err))
    if t.title and t.cols() > 1:
        t.cells[0][0]["span"] = [1, t.cols()]
    th = getattr(t, "text_height", None) or 2.5
    for c in range(t.cols()):
        width = max([len(str(r[c])) if c < len(r) else 0 for r in rows[int(t.title):]] + [4])
        t.col_widths[c] = max(t.col_widths[c], width * th * 0.7 + 2.0)
    O.ensure_heights(ctx.d, t)


def pick_cols(args):
    cols = list(args.get("columns") or cutlist.COLUMNS)
    for c in cols:
        if c not in cutlist.TITLES:
            raise CommandError("Unknown column %s; use %s." % (c, ", ".join(cutlist.TITLES)))
    return cols


@command("weldcuttable", group="annotation", label="Weld Cut List Table", description="Place a cut list table of the weld frames in the drawing.", menu="")
def weldcuttable(ctx):
    p = yield ctx.point("Specify the cut list table insertion point")
    if p.kind != "point":
        return
    weldcuttable_exec(ctx, {"point": [p.value[0], p.value[1]]})


@executes("weldcuttable")
@guard
def weldcuttable_exec(ctx, args):
    from app.cmd.commands.tables import make_table

    res = cutlist.build(ctx.d, args.get("tolerance"))
    if not res["rows"]:
        raise CommandError("There is no weld frame to list; build one first.")
    cols = pick_cols(args)
    title = str(args.get("title", "CUT LIST"))[:80]
    at = list(args.get("point", [0.0, 0.0]))
    t = make_table(ctx, len(cols), max(len(res["rows"]), 1), at, args.get("style"))
    table_fill(ctx, t, res, cols, title)
    t.extra = {"weldcut": {"tolerance": res["tolerance"], "columns": cols, "title": title}}
    h = ctx.add(t)
    return {"created": h, "rows": len(res["rows"]), "items": [r["item"] for r in res["rows"]]}


@command("weldcutupdate", group="annotation", label="Update Weld Cut List Tables", description="Rebuild the cut list tables from the current weld frames.", menu="", repeatable=False)
def weldcutupdate(ctx):
    out = weldcutupdate_exec(ctx, {})
    ctx.say("%d cut list table(s) updated." % out["updated"])
    yield from ()


@executes("weldcutupdate")
@guard
def weldcutupdate_exec(ctx, args):
    want = {int(h) for h in args["handles"]} if args.get("handles") else None
    n = 0
    for e in list(ctx.d.ents.values()):
        if e.kind != "table" or "weldcut" not in (e.extra or {}) or (want is not None and e.handle not in want) or ctx.locked(e):
            continue
        meta = e.extra["weldcut"]
        res = cutlist.build(ctx.d, meta.get("tolerance"))
        t = ctx.d.modify(e.handle)
        table_fill(ctx, t, res, meta["columns"], meta["title"])
        n += 1
    return {"updated": n}
