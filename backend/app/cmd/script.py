import os
import re
import threading
import time

from app.cmd import lisphook, registry, snaps
from app.cmd.prompts import InputError, parse_point
from app.doc import curveops, geom

MAX_BYTES = 4_000_000
MAX_LINES = 200_000
PUMP_LINES = 20_000
MAX_TOTAL_LINES = 2_000_000
MAX_DELAY_MS = 600_000
REPEAT_GAP = 0.05
NESTED = "a script is already running; nested scripts are not supported"
PROGRAMMATIC = re.compile(r"^\s*[A-Za-z_.'-][\w.-]*\s*\{")


class ScriptError(Exception):
    pass


class ScriptRun:
    def __init__(self, name: str, lines: list, repeat: bool = False, times: int | None = None):
        self.name = name
        self.lines = lines
        self.index = 0
        self.repeat = repeat
        self.times = times
        self.iteration = 0
        self.state = "running"
        self.wait_until = 0.0
        self.executing = False
        self.timer = None
        self.total = 0
        self.note = ""
        self.caller = ""
        self.files = ()

    def info(self) -> dict:
        return {"name": self.name, "line": min(self.index, len(self.lines)), "lines": len(self.lines), "state": self.state, "repeat": self.repeat, "iteration": self.iteration + 1, "note": self.note}


def read_file(path: str) -> tuple:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw:
        raise ScriptError("A script file name is required.")
    if os.path.splitext(raw)[1] == "":
        raw += ".scr"
    if os.path.splitext(raw)[1].lower() != ".scr":
        raise ScriptError("Script files end in .scr.")
    full = os.path.realpath(raw)
    if not os.path.isfile(full):
        raise ScriptError('Cannot find the script file "%s".' % path)
    if os.path.getsize(full) > MAX_BYTES:
        raise ScriptError("The script file is too large (limit %d KB)." % (MAX_BYTES // 1000))
    try:
        with open(full, "rb") as fh:
            data = fh.read(MAX_BYTES + 1)
    except OSError as err:
        raise ScriptError("Cannot read the script file: %s" % err)
    return os.path.basename(full), split_lines(data.decode("utf-8-sig", errors="replace"))


def split_lines(text: str) -> list:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if len(lines) > MAX_LINES:
        raise ScriptError("The script has too many lines (limit %d)." % MAX_LINES)
    return lines


def start(runner, name: str, lines: list, repeat: bool = False, times: int | None = None) -> ScriptRun:
    if runner.script is not None:
        raise ScriptError(NESTED)
    sc = ScriptRun(name, lines, repeat, times)
    from app.core import guard

    sc.caller = guard.CALLER.get()
    sc.files = guard.FILES.get()
    runner.script = sc
    runner.log("Running script %s." % name)
    return sc


def stop(runner, quiet: bool = False) -> None:
    sc = runner.script
    if sc is None:
        return
    if sc.timer is not None:
        sc.timer.cancel()
    runner.script = None
    if not quiet:
        runner.log("Script %s stopped at line %d." % (sc.name, min(sc.index, len(sc.lines))))


def pause(runner, why: str = "") -> bool:
    sc = runner.script
    if sc is None or sc.state == "paused":
        return False
    if sc.timer is not None:
        sc.timer.cancel()
        sc.timer = None
    sc.state = "paused"
    sc.note = why
    runner.log("Script %s paused at line %d. Type RESUME to continue." % (sc.name, min(sc.index, len(sc.lines))))
    return True


def resume(runner) -> bool:
    sc = runner.script
    if sc is None or sc.state != "paused":
        return False
    sc.state = "running"
    sc.note = ""
    sc.wait_until = 0.0
    runner.log("Resuming script %s." % sc.name)
    return True


def delay(runner, ms: int) -> bool:
    sc = runner.script
    if sc is None:
        return False
    sc.wait_until = time.monotonic() + max(0, min(int(ms), MAX_DELAY_MS)) / 1000.0
    return True


def on_cancel(runner) -> bool:
    sc = runner.script
    if sc is None or sc.executing:
        return False
    if sc.state == "paused":
        stop(runner)
        return True
    return pause(runner, "cancelled")


def _arm(runner, sc: ScriptRun, seconds: float) -> None:
    if sc.timer is not None:
        sc.timer.cancel()
    doc = runner.doc

    def fire():
        with doc.lock:
            if runner.script is not sc:
                return
            sc.timer = None
            runner.begin_call()
            drain(runner)
            doc.live_touch()
            doc.announce("script")

    sc.timer = threading.Timer(max(0.0, seconds), fire)
    sc.timer.daemon = True
    sc.timer.start()


def run_later(runner) -> None:
    while runner.later and runner.run is None:
        runner.later.pop(0)()


def drain(runner) -> None:
    sc = runner.script
    if sc is None or sc.state != "running" or sc.executing:
        return
    now = time.monotonic()
    if sc.wait_until > now:
        if sc.timer is None:
            _arm(runner, sc, sc.wait_until - now)
        return
    sc.wait_until = 0.0
    sc.executing = True
    steps = 0
    try:
        while runner.script is sc and sc.state == "running":
            if sc.wait_until > time.monotonic():
                _arm(runner, sc, sc.wait_until - time.monotonic())
                return
            if sc.index >= len(sc.lines):
                if not _wrap(runner, sc):
                    return
                continue
            if steps >= PUMP_LINES:
                _arm(runner, sc, 0.0)
                return
            if sc.total >= MAX_TOTAL_LINES:
                runner.log("Script %s stopped: too many lines run." % sc.name)
                runner.script = None
                return
            steps += 1
            sc.total += 1
            line_no = sc.index + 1
            line = sc.lines[sc.index]
            sc.index += 1
            runner.error = ""
            step(runner, line)
            if runner.error and runner.script is sc:
                sc.state = "paused"
                sc.note = runner.error
                runner.log("Script %s stopped at line %d. Type RESUME to continue with the next line." % (sc.name, line_no))
                return
    finally:
        sc.executing = False


def _wrap(runner, sc: ScriptRun) -> bool:
    if sc.repeat:
        sc.iteration += 1
        sc.index = 0
        if sc.times is not None and sc.iteration >= sc.times:
            runner.script = None
            runner.log("Script %s finished." % sc.name)
            return False
        if sc.times is None:
            _arm(runner, sc, REPEAT_GAP)
            return False
        return True
    runner.script = None
    runner.log("Script %s finished." % sc.name)
    return False


def step(runner, raw: str) -> None:
    line = raw.rstrip("\r\n")
    plain = line.strip()
    if plain.startswith(";"):
        return
    if plain == "":
        if runner.run is not None:
            runner._submit("")
        return
    if plain == "^C":
        if runner.run is not None:
            runner.cancel_run()
        return
    if plain.startswith("@"):
        directive(runner, plain)
        return
    p = runner.current_prompt() if runner.run is not None else None
    free = p is not None and p.free_text and not runner.run.frames and runner.run.sel is None
    if free:
        runner._submit(line.rstrip(" \t\r"))
        return
    enter = line.rstrip("\t\r").endswith(" ")
    text = line.rstrip(" \t\r") + (" " if enter else "")
    if plain.startswith(("(", "!")) and not (runner.run is not None and plain.startswith("!")):
        lisphook.lisp_line(runner, text)
        return
    if runner.run is not None and PROGRAMMATIC.match(line):
        word = line.split("{", 1)[0].strip()
        if registry.resolve(word.lstrip("'")) is not None:
            runner.cancel_run(quiet=True)
    runner._submit(text)


def directive(runner, plain: str) -> None:
    head, _, rest = plain[1:].partition(" ")
    head = head.lower()
    rest = rest.strip()
    env = runner.env()
    try:
        if head == "pick":
            parts = rest.split()
            pt = parse_point(parts[0], env) if parts else None
            if pt is None:
                raise InputError("@pick needs a point.")
            ent = nearest(runner, pt)
            pick = {"point": [pt[0], pt[1]], "shift": "shift" in [x.lower() for x in parts[1:]]}
            if ent is not None:
                pick["handle"] = ent.handle
            runner._canvas_pick(pick)
        elif head == "box":
            parts = rest.split()
            if len(parts) != 2:
                raise InputError("@box needs two corner points.")
            a, b = parse_point(parts[0], env), parse_point(parts[1], env)
            if a is None or b is None:
                raise InputError("@box needs two corner points.")
            handles = area_handles(runner, a, b)
            runner._canvas_selection({"mode": "add" if runner.run is not None else "set", "handles": handles, "box": [a[0], a[1], b[0], b[1]]})
        elif head == "handles":
            hs = [int(x.strip().lstrip("#").lstrip("hH"), 16) for x in rest.split(",") if x.strip()]
            runner._canvas_selection({"mode": "add" if runner.run is not None else "set", "handles": hs})
        else:
            raise InputError("Unknown script directive @%s." % head)
    except (InputError, snaps.SnapError, ValueError) as err:
        runner._fail(str(err))


def visible(runner) -> list:
    d = runner.doc.drawing
    return [e for e in d.entities(runner.doc.current_space) if d.visible(e)]


def nearest(runner, pt):
    ents = visible(runner)
    aperture = float(runner.doc.view.get("height", 100.0)) * 0.02
    hit = snaps.nearest_curve(ents, [pt[0], pt[1], 0.0], aperture)
    if hit is not None:
        return hit
    for e in reversed(ents):
        b = e.bounds()
        if b is not None and b[0] <= pt[0] <= b[2] and b[1] <= pt[1] <= b[3]:
            return e
    return None


def area_handles(runner, a, b) -> list:
    kind = "window" if b[0] >= a[0] else "crossing"
    box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))
    rect = [[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]
    found = []
    for e in visible(runner):
        bb = e.bounds()
        if kind == "window":
            if bb is not None and geom.box_inside(bb, box):
                found.append(e.handle)
        elif bb is None:
            if e.kind in ("xline", "ray") and curveops.hit_by_polygon(e, rect, "cross"):
                found.append(e.handle)
        elif geom.boxes_overlap(bb, box):
            if geom.box_inside(bb, box) or curveops.hit_by_polygon(e, rect, "cross"):
                found.append(e.handle)
    return found
