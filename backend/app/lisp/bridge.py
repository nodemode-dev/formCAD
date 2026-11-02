import math

from app.cmd import prompts
from app.cmd.prompts import Input, InputError
from app.lisp.types import Cons, EName, LispError, PickSet, point_of

PAUSE = "\\"


class Tap:
    def __init__(self, inner):
        self.inner = inner
        self.sends = 0
        self.done = False
        self.closed = False

    def send(self, value):
        self.sends += 1
        try:
            return self.inner.send(value)
        except BaseException:
            self.done = True
            raise

    def __next__(self):
        return self.send(None)

    def close(self):
        self.closed = True
        try:
            self.inner.close()
        except Exception:
            pass


def real_text(v: float) -> str:
    if not math.isfinite(v):
        raise LispError("bad argument type: command argument")
    return repr(float(v))


def point_text(pt) -> str:
    vals = [real_text(v) for v in pt]
    if len(vals) > 2 and float(pt[2]) == 0.0:
        vals = vals[:2]
    return ",".join(vals)


def feed_text(runner, s: str) -> None:
    runner._submit(s.replace("\r", "").replace("\n", " "))


def pick_point(runner, ent):
    pts = ent.snap_points()
    if pts:
        p = pts[0]
        return [float(p[0]), float(p[1])]
    box = ent.bounds()
    if box:
        return [(box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0]
    return [0.0, 0.0]


def pick_entity(runner, handle: int, pt=None) -> None:
    ent = runner.doc.drawing.get(handle)
    if ent is None:
        runner._fail("Invalid object.")
        return
    where = pt if pt is not None else pick_point(runner, ent)
    try:
        runner._canvas_pick({"handle": handle, "point": [where[0], where[1]]})
    except InputError as err:
        runner._fail(str(err))


def pick_set(runner, handles) -> None:
    try:
        runner._canvas_selection({"handles": list(handles), "mode": "add"})
    except InputError as err:
        runner._fail(str(err))


def run_command(L, args: list):
    ctx = L.ctx
    runner = ctx.runner
    if not args:
        if runner.run is not None:
            runner.cancel_run(quiet=True)
        return None
    for a in args:
        if a is None:
            continue
        t = type(a)
        if t is str:
            if a == PAUSE:
                if runner.run is None:
                    continue
                if not ctx.pause():
                    return None
                continue
            feed_text(runner, a)
        elif t is int:
            feed_text(runner, str(a))
        elif t is float:
            feed_text(runner, real_text(a))
        elif t is EName:
            pick_entity(runner, a.handle)
        elif t is PickSet:
            pick_set(runner, a.handles)
        elif t is Cons:
            pt = point_of(a)
            if pt is not None:
                feed_text(runner, point_text(pt))
            elif type(a.a) is EName:
                where = point_of(a.d.a) if type(a.d) is Cons else None
                pick_entity(runner, a.a.handle, where)
            else:
                raise LispError("bad argument type: command argument")
        else:
            raise LispError("bad argument type: command argument")
        L.tick()
    return None


def tap_current(runner):
    run = runner.run
    if run is None or run.gen is None:
        return None
    if not isinstance(run.gen, Tap):
        run.gen = Tap(run.gen)
    return run.gen


def canned_input(runner, prompt, ans):
    env = runner.env()
    t = type(ans)
    if t is bool or ans is None:
        return None
    if prompt.select:
        if isinstance(ans, (list, tuple)):
            hs = [int(x["handle"]) if isinstance(x, dict) else int(x) for x in ans]
            return Input("selection", hs)
        if isinstance(ans, str) and ans.strip() == "":
            return Input("enter")
        return None
    if t is EName:
        return Input("entity", {"handle": ans.handle, "point": [0.0, 0.0]})
    if isinstance(ans, dict) and "handle" in ans:
        return Input("entity", {"handle": int(ans["handle"]), "point": list(ans.get("point") or [0.0, 0.0])})
    if t is int or t is float:
        text = str(ans) if t is int else repr(float(ans))
    elif isinstance(ans, (list, tuple)) and 2 <= len(ans) <= 3 and all(isinstance(v, (int, float)) for v in ans):
        pt = [float(v) for v in ans]
        return Input("point", pt + [0.0] * (3 - len(pt)))
    elif t is str:
        text = ans
    else:
        return None
    try:
        res = prompts.resolve(prompt, text, env)
    except InputError as err:
        raise
    if res[0] == "input":
        return res[1]
    if res[0] == "point":
        return Input("point", res[1])
    return None
