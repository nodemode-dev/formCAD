from app.core import guard


class SchemError(ValueError):
    pass


WINDOW = {"devices": 5000, "wires": 20000, "sheets": 200, "rows": 50000, "entities": 100000, "pins": 500}
AGENT = {"devices": 800, "wires": 3000, "sheets": 30, "rows": 8000, "entities": 20000, "pins": 128}


def limited() -> bool:
    return guard.CALLER.get() in ("macro", "agent")


def get() -> dict:
    out = dict(AGENT if limited() else WINDOW)
    out["limited_caller"] = limited()
    return out


def need(count, key: str, what: str) -> None:
    cap = get()[key]
    if count > cap:
        raise SchemError("%s: %d is more than the limit of %d." % (what, count, cap))
