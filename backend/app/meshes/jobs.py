import threading
import time
from contextlib import contextmanager

from app.cmd import barred
from app.cmd.context import CommandError
from app.meshes.core import MeshError

LIMITS = {
    "repair": (5_000_000, 500_000),
    "selfx": (200_000, 50_000),
    "reduce": (5_000_000, 500_000),
    "remesh": (40_000, 12_000),
    "boolean": (2_000_000, 300_000),
    "section": (5_000_000, 500_000),
    "tobrep": (50_000, 20_000),
}
BREP_INTERACTIVE = 5_000
SELFX_MAX_PAIRS = 100_000
SAMPLE_POINTS = 4_000_000

_lock = threading.Lock()
ACTIVE: dict = {}


class Cancelled(MeshError):
    pass


class Activity:
    def __init__(self, doc_id, command):
        self.doc_id = doc_id
        self.command = command
        self.phase = ""
        self.progress = 0.0
        self.started = time.time()
        self.stop = threading.Event()

    def view(self) -> dict:
        return {"command": self.command, "phase": self.phase, "progress": round(self.progress, 4), "started": self.started}

    def check(self) -> None:
        if self.stop.is_set():
            raise Cancelled("The mesh operation was cancelled.")

    def step(self, phase: str, progress=None) -> None:
        self.check()
        self.phase = phase
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        publish(self, "progress")


class Quiet:
    phase = ""
    progress = 0.0

    def check(self) -> None:
        return None

    def step(self, phase: str, progress=None) -> None:
        return None


QUIET = Quiet()


def publish(act: Activity, state: str, message: str = "") -> None:
    from app.doc import events

    events.publish({"type": "meshjob", "id": act.doc_id, "command": act.command, "state": state, "phase": act.phase, "progress": round(act.progress, 4), "message": message})


@contextmanager
def activity(ctx, command: str):
    doc_id = getattr(ctx.doc, "id", "")
    act = Activity(doc_id, command)
    with _lock:
        if doc_id in ACTIVE:
            raise CommandError("Another mesh operation (%s) is still running on this document." % ACTIVE[doc_id].command.upper())
        ACTIVE[doc_id] = act
    publish(act, "start")
    message = ""
    try:
        yield act
    except Cancelled as err:
        message = str(err)
        raise
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


def restricted(runner) -> bool:
    return bool(barred.caller(runner))


def cap(runner, key: str) -> int:
    window, locked = LIMITS[key]
    return locked if restricted(runner) else window


def need_room(runner, key: str, triangles: int, what: str) -> None:
    limit = cap(runner, key)
    if triangles > limit:
        who = " from a macro or an outside agent" if restricted(runner) else ""
        raise MeshError("%s is limited to %d triangles%s; this mesh has %d. Reduce it first." % (what, limit, who, triangles))


def limits_view() -> dict:
    names = list(LIMITS)
    return {
        "interactive": {k: LIMITS[k][0] for k in names},
        "restricted": {k: LIMITS[k][1] for k in names},
        "brep_interactive": BREP_INTERACTIVE,
        "selfx_pairs": SELFX_MAX_PAIRS,
    }
