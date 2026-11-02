from app.calc import engine, units


def _resolve_pick(doc, item, mode):
    if isinstance(item, dict):
        pt = item.get("point")
        handle = item.get("handle")
    else:
        pt, handle = item, None
    if not isinstance(pt, (list, tuple)) or len(pt) < 2:
        raise engine.CalcError("a pick needs a point")
    pt = [float(pt[0]), float(pt[1]), 0.0]
    if doc is None or handle is None or mode is None:
        return pt
    ent = doc.drawing.get(int(handle))
    if ent is None:
        raise engine.CalcError("no such object for the pick")
    from app.cmd import snaps

    aperture = float(item.get("aperture") or doc.view.get("height", 100.0) * 0.02) if isinstance(item, dict) else doc.view.get("height", 100.0) * 0.02
    if mode in ("per", "tan"):
        return pt
    found = snaps.search([ent], mode, pt, max(aperture, 1e-9) * 50.0, ent)
    if found is None:
        raise engine.CalcError("no %s point found on that object" % mode)
    return [found[0][0], found[0][1], 0.0]


def handle(body: dict, doc=None) -> dict:
    try:
        if body.get("units") is not None:
            kind = body["units"] if isinstance(body["units"], str) and body["units"] not in ("", "all") else None
            return {"ok": True, "units": units.listing(kind)}
        if body.get("convert") is not None:
            c = body["convert"]
            v = units.convert(float(c["value"]), c["from"], c["to"], c.get("type"))
            return {"ok": True, "kind": "number", "value": v, "text": engine.format_value(v)}
        if body.get("pick") is not None:
            p = body["pick"]
            out = engine.pick_helper(p.get("mode"), [x["point"] if isinstance(x, dict) else x for x in p.get("points", [])])
            out["ok"] = True
            return out
        expression = body.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return {"ok": False, "error": "CAL: empty expression"}
        picks = list(body.get("picks") or [])
        it = iter(picks)

        def picker(mode):
            try:
                item = next(it)
            except StopIteration:
                raise engine.NeedsPick(mode or "cur")
            return _resolve_pick(doc, item, mode)

        out = engine.run(expression, body.get("variables"), picker)
        out["ok"] = True
        return out
    except engine.NeedsPick as err:
        return {"ok": False, "error": "CAL: %s" % err, "needsPick": err.mode}
    except (engine.CalcError, units.UnitError, KeyError, TypeError, ValueError) as err:
        return {"ok": False, "error": "CAL: %s" % err}
