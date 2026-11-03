import threading
from contextlib import contextmanager
from types import SimpleNamespace

from app.cmd.context import CommandError
from app.meshes import jobs
from app.part.registry import PartError

CANCEL_POLL = 0.2


@contextmanager
def running(doc, command: str, error=PartError):
    try:
        with jobs.activity(SimpleNamespace(doc=doc), command) as act:
            yield act
    except jobs.Cancelled:
        raise error("The %s was cancelled." % ("wall thickness map" if command == "plasticwall" else "plastic check"))
    except CommandError as err:
        raise error(str(err))


def interruptible(act, fn, *args):
    box: dict = {}

    def go() -> None:
        try:
            box["value"] = fn(*args)
        except BaseException as err:
            box["error"] = err

    worker = threading.Thread(target=go, name="plastic-job", daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(CANCEL_POLL)
        act.check()
    if "error" in box:
        raise box["error"]
    return box["value"]
