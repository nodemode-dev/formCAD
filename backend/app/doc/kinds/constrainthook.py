import copy

from app.doc import commit_hooks

PRIORITY = 60


def say(doc, text: str) -> None:
    runner = getattr(doc, "runner", None)
    if runner is not None:
        runner.log(text)


def follow(doc, tx) -> None:
    if getattr(tx, "constraint_done", False):
        return
    from app.param import store as S

    d = doc.drawing
    keys = [k for k in list(tx.before) if k[0] == "e"]
    if not keys:
        return
    changed = {k[1] for k in keys}
    new = {h for h in changed if d.get(h) is not None and tx.before[("e", h)] is None}
    if S.has_constraints(d):
        edited = {h for h in changed if d.get(h) is not None and tx.before[("e", h)] is not None}
        gone = {h for h in changed if d.get(h) is None}
        if gone:
            drop_dangling(doc, d, gone)
        if edited:
            resolve(doc, d, tx, edited)
    cfg = S.settings(d)
    infer_on = False
    try:
        from app.sysvars import registry as sv

        infer_on = bool(sv.get_var(doc, "CONSTRAINTINFER"))
    except Exception:
        infer_on = bool(cfg.get("infer"))
    if infer_on and new:
        from app.param import infer

        count = infer.infer_new(d, sorted(new))
        if count:
            say(doc, "%d constraint(s) inferred." % count)


def drop_dangling(doc, d, gone) -> None:
    from app.param import adapt, sketch
    from app.param import expr as X
    from app.param import store as S
    from app.param import units as U

    removed = 0
    marked = 0
    for r in S.constraints(d):
        if not (gone & set(adapt.handles_of(r))):
            continue
        if r.get("sketch"):
            if not r.get("dangling"):
                q = copy.deepcopy(r)
                q["dangling"] = True
                S.put_con(d, q)
                marked += 1
            continue
        if r.get("label"):
            for dep in S.dim_records(d):
                if dep["id"] != r["id"] and dep.get("expr") and (r["label"].casefold(), None) in {(n, None) for n, _s in X.references(dep["expr"])}:
                    q = copy.deepcopy(dep)
                    q["expr"] = X.rename(dep["expr"], r["label"], "(" + U.format_value(float(r.get("value") or 0.0)) + ")")
                    S.put_con(d, q)
            for p in S.user_params(d):
                if p.get("expr") and (r["label"].casefold(), None) in {(n, None) for n, _s in X.references(p["expr"])}:
                    q = dict(p)
                    q["expr"] = X.rename(p["expr"], r["label"], "(" + U.format_value(float(r.get("value") or 0.0)) + ")")
                    S.put_param(d, q)
        S.drop_con(d, r["id"])
        removed += 1
    sketch.prune(d)
    if removed:
        say(doc, "%d constraint(s) removed with their objects." % removed)
    if marked:
        say(doc, "%d sketch constraint(s) lost their objects and are marked dangling." % marked)


def resolve(doc, d, tx, edited) -> None:
    from app.param import adapt, ops
    from app.param import store as S

    recs = [r for r in S.constraints(d) if not r.get("dangling")]
    hit = {h for r in recs for h in adapt.handles_of(r)} & edited
    if not hit:
        return
    saved = {}
    for r in recs:
        if r["kind"] == "fix" and set(adapt.handles_of(r)) & hit and r.get("ctx") and fix_moved(d, tx, r):
            key = ("t", S.CONS, S.con_key(r["id"]))
            saved[key] = copy.deepcopy(r)
            q = copy.deepcopy(r)
            q["ctx"] = {}
            S.put_con(d, q)
    try:
        net = adapt.load(d, seeds=sorted(hit))
        from app.doc.entities import entity_from_dict

        for h in hit:
            net.hold_changed(h, entity_from_dict(tx.before[("e", h)]), 1e8)
        rep = net.sk.solve(analyse=False)
    except S.ParamError as err:
        undo_fix(d, saved)
        say(doc, "Constraints could not be satisfied: %s" % err)
        return
    if not rep.ok:
        undo_fix(d, saved)
        for h in hit & set(net.bind):
            d.apply_key(("e", h), tx.before[("e", h)])
        say(doc, "Constraints could not be satisfied: %s. The edit was not applied." % (rep.message.split(": ", 1)[-1] if rep.message else "they conflict"))
        return
    for cid, c in net.sk.cons.items():
        r = net.recs.get(cid)
        if r is not None and r["kind"] == "fix" and ("t", S.CONS, S.con_key(cid)) in saved:
            q = copy.deepcopy(S.get_con(d, cid))
            q["ctx"] = copy.deepcopy(c.ctx)
            S.put_con(d, q)
    moved = net.write_back()
    ops.touch(d, net.bind.keys())
    ops.refresh_driven(d, net)
    others = [h for h in moved if h not in hit]
    if others:
        say(doc, "%d constrained object(s) followed the edit." % len(others))


def fix_moved(d, tx, rec) -> bool:
    from app.doc.entities import entity_from_dict
    from app.param import adapt, marks

    for h, part in rec["refs"]:
        old = tx.before.get(("e", int(h)))
        new = d.get(int(h))
        if old is None or new is None:
            continue
        old = entity_from_dict(old)
        if part == "whole" or marks.point_of(new, part) is None:
            if adapt.params_of(old) != adapt.params_of(new):
                return True
            continue
        a, b = marks.point_of(old, part), marks.point_of(new, part)
        if a is None or b is None or abs(a[0] - b[0]) > 1e-12 or abs(a[1] - b[1]) > 1e-12:
            return True
    return False


def undo_fix(d, saved) -> None:
    from app.param import store as S

    for key, rec in saved.items():
        S.put_con(d, rec)


commit_hooks.register(PRIORITY, follow)
