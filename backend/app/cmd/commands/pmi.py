import re

from app.cmd.context import CommandError
from app.cmd.registry import command, executes
from app.pmi import geo, store
from app.solid.work import SolidError

GROUP = "solids"
REF_TOKEN = re.compile(r"^([fe]?)(\d+)$", re.IGNORECASE)
DIM_WORDS = ["Distance", "Diameter", "Radius", "Thickness", "Angle"]
CHAR_WORDS = [c.replace("_", " ").title().replace(" ", "") for c in store.CHARS]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (store.PmiError, SolidError) as err:
        raise CommandError(str(err))


def parse_refs(value):
    if isinstance(value, list):
        out = []
        for r in value:
            if isinstance(r, dict):
                out.append({"kind": str(r.get("kind", "face")), "pid": r.get("pid")})
            else:
                out.extend(parse_refs(str(r)))
        return out
    out = []
    for tok in str(value or "").replace(",", " ").split():
        m = REF_TOKEN.match(tok)
        if not m:
            raise CommandError("A feature reads like f12 (face with persistent id 12) or e3 (edge); %s is not one." % tok)
        out.append({"kind": "edge" if m.group(1).lower() == "e" else "face", "pid": int(m.group(2))})
    return out


def body_handle(ctx, args):
    h = args.get("body")
    if h is None:
        raise CommandError("Give body, the handle of the solid.")
    return int(h)


def pick_body(ctx):
    sel = yield ctx.select("Select the solid", pick_one=True)
    if sel.kind != "selection" or not sel.value:
        return None
    return int(sel.value[0])


def ask_refs(ctx, message):
    t = yield ctx.text(message)
    if t.kind != "text":
        return None
    return parse_refs(t.value)


def say_item(ctx, rec):
    d = geo.describe(ctx.d, rec)
    ctx.say("%s added: %s." % (rec["id"], d["label"] or rec["type"]))


@command("pmidim", aliases=("addpmidim",), group=GROUP, label="PMI Dimension", description="Add a dimension to the faces or edges of a solid, saved with the part and written to STEP.", menu="Draw > Annotation > PMI Dimension")
def pmidim_cmd(ctx):
    body = yield from pick_body(ctx)
    if body is None:
        return
    k = yield ctx.keyword("Dimension type", DIM_WORDS, "Distance")
    if k.kind != "keyword":
        return
    dtype = str(k.value).lower()
    refs = yield from ask_refs(ctx, "Enter the first feature (like f12 or e3)")
    if refs is None:
        return
    refs2 = []
    if dtype in store.TWO_FEATURE or dtype == "thickness":
        refs2 = yield from ask_refs(ctx, "Enter the second feature")
        if refs2 is None:
            return
    v = yield ctx.number("Value, or press Enter to use the measured value", default=0.0)
    value = float(v.value) if v.kind == "number" and float(v.value) > 0 else None
    pm = yield ctx.number("Plus and minus tolerance", default=0.0)
    tol = float(pm.value) if pm.kind == "number" else 0.0
    rec = run(store.add, ctx.d, {"type": "dimension", "body": body, "dtype": dtype, "refs": refs, "refs2": refs2, "value": value, "plus": tol, "minus": tol})
    run(geo.kernel_measure, ctx.d, store.body_of(ctx.d, body), dtype, rec["refs"], rec["refs2"])
    say_item(ctx, rec)
    return {"id": rec["id"]}


@executes("pmidim")
def pmidim_exec(ctx, args):
    data = {"type": "dimension", "body": body_handle(ctx, args), "dtype": str(args.get("dtype", "distance")), "refs": parse_refs(args.get("refs")), "refs2": parse_refs(args.get("refs2")), "value": args.get("value"), "plus": args.get("plus", 0.0), "minus": args.get("minus", 0.0), "text": args.get("text", ""), "offset": args.get("offset")}
    rec = run(store.add, ctx.d, {k: v for k, v in data.items() if v is not None})
    m = run(geo.kernel_measure, ctx.d, store.body_of(ctx.d, rec["body"]), rec["dtype"], rec["refs"], rec["refs2"])
    return {"id": rec["id"], "measured": m["value"], "record": rec}


@command("pmitol", aliases=("addpmitol",), group=GROUP, label="PMI Tolerance", description="Add a geometric tolerance frame to a face or edge of a solid, saved with the part and written to STEP.", menu="Draw > Annotation > PMI Tolerance")
def pmitol_cmd(ctx):
    body = yield from pick_body(ctx)
    if body is None:
        return
    k = yield ctx.keyword("Characteristic", CHAR_WORDS, "Flatness")
    if k.kind != "keyword":
        return
    char = [c for c, w in zip(store.CHARS, CHAR_WORDS) if w.lower() == str(k.value).lower()][0]
    refs = yield from ask_refs(ctx, "Enter the toleranced feature (like f12)")
    if refs is None:
        return
    t = yield ctx.number("Tolerance zone width", positive=True)
    if t.kind != "number":
        return
    dt = yield ctx.text("Datum letters in order, like A B, or press Enter for none", "")
    letters = [x for x in str(dt.value or "").replace(",", " ").split()] if dt.kind == "text" else []
    rec = run(store.add, ctx.d, {"type": "tolerance", "body": body, "char": char, "refs": refs, "tol": float(t.value), "datums": letters})
    say_item(ctx, rec)
    return {"id": rec["id"]}


@executes("pmitol")
def pmitol_exec(ctx, args):
    data = {"type": "tolerance", "body": body_handle(ctx, args), "char": str(args.get("char", "")), "refs": parse_refs(args.get("refs")), "tol": args.get("tol"), "zone": args.get("zone", "none"), "modifier": args.get("modifier", ""), "datums": args.get("datums") or [], "text": args.get("text", ""), "offset": args.get("offset")}
    rec = run(store.add, ctx.d, {k: v for k, v in data.items() if v is not None})
    return {"id": rec["id"], "record": rec}


@command("pmidatum", aliases=("addpmidatum",), group=GROUP, label="PMI Datum", description="Mark a face or edge of a solid as a datum feature with a letter.", menu="Draw > Annotation > PMI Datum")
def pmidatum_cmd(ctx):
    body = yield from pick_body(ctx)
    if body is None:
        return
    refs = yield from ask_refs(ctx, "Enter the datum feature (like f12)")
    if refs is None:
        return
    taken = store.datum_letters(ctx.d, body)
    nxt = next((c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in taken), "A")
    t = yield ctx.text("Datum letter", nxt)
    if t.kind not in ("text", "enter"):
        return
    letter = str(t.value or nxt).strip().upper()
    rec = run(store.add, ctx.d, {"type": "datum", "body": body, "refs": refs[:1], "letter": letter})
    say_item(ctx, rec)
    return {"id": rec["id"]}


@executes("pmidatum")
def pmidatum_exec(ctx, args):
    data = {"type": "datum", "body": body_handle(ctx, args), "letter": str(args.get("letter", "")), "refs": parse_refs(args.get("refs")), "text": args.get("text", ""), "offset": args.get("offset")}
    rec = run(store.add, ctx.d, {k: v for k, v in data.items() if v is not None})
    return {"id": rec["id"], "record": rec}


@command("pmiedit", group=GROUP, label="Edit PMI", description="Change the value, tolerance, letter or note of a PMI item.", menu="Draw > Annotation > Edit PMI")
def pmiedit_cmd(ctx):
    t = yield ctx.text("Enter the PMI item id (like M3)")
    if t.kind != "text":
        return
    rec = run(store.need, ctx.d, t.value.strip())
    if rec["type"] == "dimension":
        v = yield ctx.number("New value, or 0 to use the measured value", default=rec["value"] or 0.0)
        if v.kind != "number":
            return
        out = run(store.edit, ctx.d, rec["id"], {"value": float(v.value) if float(v.value) > 0 else None})
    elif rec["type"] == "tolerance":
        v = yield ctx.number("New tolerance zone width", default=rec["tol"], positive=True)
        if v.kind != "number":
            return
        out = run(store.edit, ctx.d, rec["id"], {"tol": float(v.value)})
    else:
        v = yield ctx.text("New datum letter", rec["letter"])
        if v.kind not in ("text", "enter"):
            return
        out = run(store.edit, ctx.d, rec["id"], {"letter": str(v.value or rec["letter"])})
    ctx.say("%s updated." % out["id"])
    return {"id": out["id"]}


@executes("pmiedit")
def pmiedit_exec(ctx, args):
    if not args.get("id"):
        raise CommandError("Give id, like M3.")
    fields = {k: v for k, v in args.items() if k not in ("id",)}
    if "refs" in fields:
        fields["refs"] = parse_refs(fields["refs"])
    if "refs2" in fields:
        fields["refs2"] = parse_refs(fields["refs2"])
    out = run(store.edit, ctx.d, str(args["id"]), fields)
    return {"id": out["id"], "record": out}


@command("pmidelete", aliases=("delpmi",), group=GROUP, label="Delete PMI", description="Remove PMI items by id.", menu="Draw > Annotation > Delete PMI")
def pmidelete_cmd(ctx):
    t = yield ctx.text("Enter the PMI item ids, separated by spaces (like M1 M2)")
    if t.kind != "text":
        return
    gone = [run(store.remove, ctx.d, x)["id"] for x in str(t.value).replace(",", " ").split()]
    ctx.say("Removed %d item(s)." % len(gone))
    return {"removed": gone}


@executes("pmidelete")
def pmidelete_exec(ctx, args):
    ids = args.get("ids") if args.get("ids") is not None else args.get("id")
    ids = ids if isinstance(ids, list) else [ids]
    if not ids or ids == [None]:
        raise CommandError("Give id or ids.")
    return {"removed": [run(store.remove, ctx.d, str(x))["id"] for x in ids]}
