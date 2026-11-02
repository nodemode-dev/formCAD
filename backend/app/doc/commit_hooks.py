HOOKS: list = []


def register(priority: int, fn) -> None:
    HOOKS.append((priority, fn))
    HOOKS.sort(key=lambda item: item[0])


def run(doc, tx) -> None:
    for _priority, fn in list(HOOKS):
        try:
            fn(doc, tx)
        except Exception as err:
            runner = getattr(doc, "runner", None)
            if runner is not None:
                runner.log("A follow-up update was skipped: %s" % err)
