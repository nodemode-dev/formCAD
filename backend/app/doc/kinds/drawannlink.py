from app.doc import commit_hooks

PRIORITY = 81
LINK_FIELDS = {
    "gdtframe": (("leader_link", "leader0"),),
    "datumsym": (("tip_link", "tip"),),
    "balloon": (("tip_link", "tip"),),
    "finishmark": (("tip_link", "position"),),
    "centermark": (("link", "center"), ("a_link", "a"), ("b_link", "b")),
}


def _set(ent, slot, p):
    v = [float(p[0]), float(p[1]), 0.0]
    if slot == "leader0":
        if ent.leader:
            ent.leader = [v] + [list(q) for q in ent.leader[1:]]
        return
    setattr(ent, slot, v)


def _cur(ent, slot):
    if slot == "leader0":
        return ent.leader[0] if ent.leader else None
    return getattr(ent, slot)


def follow(doc, tx) -> None:
    changed = {k[1] for k in tx.before if k[0] == "e"}
    if not changed:
        return
    from app.drawann import viewsrc

    if not viewsrc.view_kinds():
        return
    d = doc.drawing
    views = {h for h in changed if viewsrc.is_view(d.ents.get(h))}
    if not views:
        return
    tol = d.tolerances["absolute"] * 10.0
    for ent in list(d.ents.values()):
        fields = LINK_FIELDS.get(ent.kind)
        if not fields:
            continue
        for name, slot in fields:
            link = getattr(ent, name)
            if not link or link.get("h") not in views:
                continue
            if d.layer_locked(ent.layer):
                continue
            p = viewsrc.point(d, link)
            cur = _cur(ent, slot)
            if p is None:
                m = d.modify(ent.handle)
                setattr(m, name, {})
                continue
            if cur is not None and abs(cur[0] - p[0]) <= 1e-9 and abs(cur[1] - p[1]) <= 1e-9:
                if ent.kind != "centermark":
                    continue
            m = d.modify(ent.handle)
            _set(m, slot, p)
            if ent.kind == "centermark" and name == "link":
                ed = viewsrc.edge(d, d.ents[link["h"]], link["e"])
                if ed is not None and "r" in ed:
                    m.radius = float(ed["r"])
    from app.drawann import viewops, settings

    st = settings.get(d)
    for vh in views:
        old = [e for e in d.ents.values() if e.kind == "hatch" and e.extra.get("section_view") == vh]
        if not old:
            continue
        fresh = viewops.section_hatches(d, d.ents[vh], st)
        for e, f in zip(old, fresh):
            m = d.modify(e.handle)
            m.loops, m.pattern_angle = f.loops, f.pattern_angle
            m.extra = {**m.extra, "component": f.extra.get("component", "")}
        for e in old[len(fresh):]:
            d.erase_entity(e.handle)
        for f in fresh[len(old):]:
            f.layer, f.color = old[0].layer, old[0].color
            d.add_entity(f, old[0].owner)


commit_hooks.register(PRIORITY, follow)
