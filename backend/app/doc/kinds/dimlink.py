from app.doc import commit_hooks

PRIORITY = 80


def follow(doc, tx) -> None:
    changed = {k[1] for k in tx.before if k[0] == "e"}
    if not changed:
        return
    from app.dim import assoc

    assoc.follow(doc, changed)


commit_hooks.register(PRIORITY, follow)
