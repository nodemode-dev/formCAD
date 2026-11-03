import threading
import time
from contextlib import contextmanager

from app.cmd import barred

LIMITS = {
    "triangles": (1_000_000, 200_000),
    "layers": (6000, 1500),
    "items": (64, 16),
    "orient_triangles": (500_000, 100_000),
    "gcode_bytes": (256 << 20, 64 << 20),
    "seconds": (900, 180),
}

_lock = threading.Lock()
ACTIVE: dict = {}


class AdditiveError(Exception):
    pass


class Cancelled(AdditiveError):
    pass


class Activity:
    def __init__(self, doc_id, command, budget):
        self.doc_id, self.command = doc_id, command
        self.phase = ""
        self.progress = 0.0
        self.started = time.time()
        self.deadline = self.started + budget
        self.stop = threading.Event()

    def view(self) -> dict:
        return {"command": self.command, "phase": self.phase, "progress": round(self.progress, 4), "started": self.started}

    def check(self) -> None:
        if self.stop.is_set():
            raise Cancelled("The job was cancelled.")
        if time.time() > self.deadline:
            raise AdditiveError("The job ran past its time budget and was stopped.")

    def step(self, phase: str, progress=None) -> None:
        self.check()
        self.phase = phase
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        publish(self, "progress")


def publish(act: Activity, state: str, message: str = "") -> None:
    from app.doc import events

    events.publish({"type": "additivejob", "id": act.doc_id, "command": act.command, "state": state, "phase": act.phase, "progress": round(act.progress, 4), "message": message})


def restricted(runner=None) -> bool:
    return bool(barred.caller(runner))


def cap(key: str, runner=None) -> int:
    window, locked = LIMITS[key]
    return locked if restricted(runner) else window


def limits_view() -> dict:
    return {"interactive": {k: v[0] for k, v in LIMITS.items()}, "restricted": {k: v[1] for k, v in LIMITS.items()}}


@contextmanager
def activity(doc_id: str, command: str, runner=None):
    act = Activity(doc_id, command, cap("seconds", runner))
    with _lock:
        if doc_id in ACTIVE:
            raise AdditiveError("Another additive job (%s) is still running on this document." % ACTIVE[doc_id].command)
        ACTIVE[doc_id] = act
    publish(act, "start")
    message = ""
    try:
        yield act
    except Exception as err:
        message = str(err)
        raise
    finally:
        with _lock:
            ACTIVE.pop(doc_id, None)
        act.progress = 1.0
        publish(act, "end", message)


def cancel(doc_id: str) -> bool:
    with _lock:
        act = ACTIVE.get(doc_id)
    if act is None:
        return False
    act.stop.set()
    return True


def running(doc_id: str):
    with _lock:
        act = ACTIVE.get(doc_id)
    return act.view() if act is not None else None


class Quiet:
    def check(self) -> None:
        return None

    def step(self, phase: str, progress=None) -> None:
        return None


QUIET = Quiet()
