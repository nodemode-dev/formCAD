from app.core import guard


class PipeError(ValueError):
    pass


WINDOW = {"points": 2000, "runs": 500, "specs": 200, "taps": 200, "reducers": 100, "rows": 20000, "bodies": 400}
AGENT = {"points": 400, "runs": 100, "specs": 50, "taps": 40, "reducers": 20, "rows": 4000, "bodies": 60}


def limited() -> bool:
    return guard.CALLER.get() in ("macro", "agent")


def get() -> dict:
    out = dict(AGENT if limited() else WINDOW)
    out["limited_caller"] = limited()
    return out


def need(count, key: str, what: str) -> None:
    cap = get()[key]
    if count > cap:
        raise PipeError("%s: %d is more than the limit of %d." % (what, count, cap))
