from app.doc import commit_hooks, loops

PRIORITY = 90


def reactor_hatches(ent_dict_or_obj):
    raw = ent_dict_or_obj.get("reactors") if isinstance(ent_dict_or_obj, dict) else getattr(ent_dict_or_obj, "reactors", None)
    out = []
    for r in raw or ():
        if isinstance(r, dict) and "hatch" in r:
            out.append(int(r["hatch"]))
    return out


def source_handles(hatch):
    out = []
    for loop in hatch.loops:
        for s in loop.get("sources", ()):
            if s not in out:
                out.append(s)
    return out


def box_center(box):
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def source_shift(d, tx, sources):
    from app.doc.entities import entity_from_dict

    dx = dy = 0.0
    n = 0
    for s in sources:
        old = tx.before.get(("e", s))
        cur = d.ents.get(s)
        if not isinstance(old, dict) or cur is None:
            continue
        b0 = entity_from_dict(old).bounds()
        b1 = cur.bounds()
        if b0 is None or b1 is None:
            continue
        c0, c1 = box_center(b0), box_center(b1)
        dx += c1[0] - c0[0]
        dy += c1[1] - c0[1]
        n += 1
    return (dx / n, dy / n) if n else (0.0, 0.0)


def rebuilt(d, hatch, shift):
    out = []
    for loop in hatch.loops:
        src = loop.get("sources") or []
        if not src:
            out.append(loop)
            continue
        c = loops.centroid_of(loop["vertices"])
        res = loops.rebuild_loop(d, src, hatch.gap, (c[0] + shift[0], c[1] + shift[1]))
        if res is None:
            if loop.get("outer", True):
                return None
            continue
        verts, sources = res
        out.append(loops.make_loop(verts, sources, int(loop.get("depth", 0 if loop.get("outer", True) else 1))))
    return out


def same_shape(a, b):
    if len(a) != len(b):
        return False
    ka = sorted(loops.loop_key(l["vertices"]) for l in a)
    kb = sorted(loops.loop_key(l["vertices"]) for l in b)
    if [len(x) for x in ka] != [len(x) for x in kb]:
        return False
    for xa, xb in zip(ka, kb):
        for pa, pb in zip(xa, xb):
            if abs(pa[0] - pb[0]) > 1e-4 or abs(pa[1] - pb[1]) > 1e-4:
                return False
    return True


def say(doc, text):
    runner = getattr(doc, "runner", None)
    if runner is not None:
        runner.log(text)


def follow(doc, tx):
    d = doc.drawing
    changed = {k[1] for k in tx.before if k[0] == "e"}
    if not changed:
        return
    affected = set()
    for h in changed:
        cur = d.ents.get(h)
        if cur is not None:
            if cur.kind == "hatch" and cur.associative:
                affected.add(h)
            affected.update(reactor_hatches(cur))
        old = tx.before.get(("e", h))
        if isinstance(old, dict):
            affected.update(reactor_hatches(old))
    for hh in sorted(affected):
        hatch = d.ents.get(hh)
        if hatch is None or hatch.kind != "hatch" or not hatch.associative:
            continue
        fresh = hatch.extra.get("assoc_fresh")
        if fresh:
            d.modify(hh)
            hatch.extra.pop("assoc_fresh", None)
            continue
        sources = source_handles(hatch)
        if not sources:
            continue
        src_changed = [s for s in sources if s in changed]
        self_changed = hh in changed
        if not src_changed and not self_changed:
            continue
        shift = source_shift(d, tx, src_changed) if src_changed else (0.0, 0.0)
        new = rebuilt(d, hatch, shift)
        if new is None or not new:
            d.modify(hh)
            hatch.associative = False
            say(doc, "The hatch lost its boundary and keeps its shape; it is no longer associative.")
            continue
        if not src_changed:
            if not same_shape(new, hatch.loops):
                d.modify(hh)
                hatch.associative = False
                say(doc, "The hatch was changed on its own; it is no longer associative.")
            continue
        if same_shape(new, hatch.loops):
            continue
        d.modify(hh)
        hatch.loops = new


commit_hooks.register(PRIORITY, follow)
