import inspect
import json
import math
import re
from dataclasses import dataclass, replace

from app.cmd import jig, registry, snaps
from app.cmd.context import CommandCancel, CommandError, Context
from app.cmd.prompts import Env, Input, InputError, Prompt, format_prompt, match_keyword, parse_point, point_to_input, resolve
from app.doc import geom
from app.doc.document import CommandFailed

HISTORY_MAX = 5000
HISTORY_DROP = 1000
STATE_HISTORY = 200
MAX_FRAMES = 32
SEL_WORDS = ("All", "Last", "Previous", "Window", "Crossing", "BOX", "Add", "Remove", "Undo")
FILTER_AXES = {".x": "x", ".y": "y", ".z": "z", ".xy": "xy", ".xz": "xz", ".yz": "yz"}


class Frame:
    def __init__(self, kind: str, base=None, angle=None, label: str = ""):
        self.kind = kind
        self.pts: list = []
        self.base = base
        self.angle = angle
        self.label = label
        self.silent = False

    def prompt(self) -> Prompt:
        k = self.kind
        n = len(self.pts)
        if k == "from":
            return Prompt("Base point" if n == 0 else "<Offset>", ("point",))
        if k == "m2p":
            return Prompt("First point of mid" if n == 0 else "Second point of mid", ("point",))
        if k in FILTER_AXES:
            axes = FILTER_AXES[k]
            if n == 0:
                return Prompt(".%s of" % axes.upper(), ("point",))
            need = "".join(c for c in "xyz" if c not in axes).upper()
            return Prompt("(need %s)" % need, ("point",))
        if k == "tt":
            return Prompt("Specify temporary OTRACK point", ("point",))
        if k == "tk":
            return Prompt("First tracking point" if n == 0 else "Next point (Press ENTER to end tracking)", ("point",))
        return Prompt("Angle Override: %s" % self.label, ("point",), base=self.base)

    def accept(self, pt):
        k = self.kind
        self.pts.append(pt)
        if k == "from":
            if len(self.pts) == 2:
                b, o = self.pts
                return True, [b[0] + o[0], b[1] + o[1], 0.0]
            return False, None
        if k == "m2p":
            if len(self.pts) == 2:
                return True, geom.midpoint(self.pts[0], self.pts[1])
            return False, None
        if k in FILTER_AXES:
            if len(self.pts) == 2:
                a, b = self.pts
                axes = FILTER_AXES[k]
                return True, [a[0] if "x" in axes else b[0], a[1] if "y" in axes else b[1], 0.0]
            return False, None
        if k == "tt":
            return True, None
        if k == "tk":
            return False, None
        return True, pt

    def enter(self):
        if self.kind == "tk" and self.pts:
            return True, self.pts[-1]
        raise InputError("Point required.")


class SelState:
    def __init__(self, prompt: Prompt):
        self.prompt = prompt
        self.selected: list = []
        self.mode = "add"
        self.window = None
        self.steps: list = []
        self.single = False

    def message(self) -> str:
        if self.window:
            return "Specify first corner" if len(self.window[1]) == 0 else "Specify opposite corner"
        if self.mode == "remove":
            return "Remove objects"
        return self.prompt.message


@dataclass
class Deferred:
    mode: str
    handle: int
    near: list
    ref: list


class Run:
    def __init__(self, spec, transparent: bool = False):
        self.spec = spec
        self.gen = None
        self.started = False
        self.prompt = None
        self.frames: list = []
        self.sel = None
        self.transparent = transparent
        self.owns_tx = False
        self.ctx = None
        self.status = "run"


class CommandRunner:
    def __init__(self, doc):
        self.doc = doc
        self.history: list = []
        self.memory: dict = {}
        self.run = None
        self.outer = None
        self.last_cmd = None
        self._out: list = []
        self.cursor_angle = 0.0
        self.tracking = None
        self.error = ""
        self.result = None
        self.snap_override = None
        self.deferred = None

    def command_name(self) -> str:
        r = self.outer if (self.run and self.run.transparent and self.outer) else self.run
        return r.spec.name if r else ""

    def log(self, line: str) -> None:
        self.history.append(line)
        self._out.append(line)
        if len(self.history) > HISTORY_MAX:
            del self.history[:HISTORY_DROP]

    def env(self) -> Env:
        h = self.doc.drawing.header
        angle = self.cursor_angle
        if self.run and self.run.frames and self.run.frames[-1].angle is not None:
            angle = self.run.frames[-1].angle
        return Env(list(self.doc.lastpoint), int(h.get("AUNITS", 0)), float(h.get("ANGBASE", 0.0)), int(h.get("ANGDIR", 0)), int(h.get("LUNITS", 2)), int(h.get("LUPREC", 4)), int(h.get("AUPREC", 0)), angle, self.tracking)

    def current_prompt(self):
        run = self.run
        if run is None:
            return None
        if run.frames:
            return run.frames[-1].prompt()
        if run.sel is not None:
            corner = run.sel.window[1][0] if run.sel.window and run.sel.window[1] else None
            return Prompt(run.sel.message(), ("point",) if run.sel.window else ("select",), [], None, "", corner, select=not run.sel.window)
        if self.snap_override and run.prompt is not None and "point" in run.prompt.accepts:
            return replace(run.prompt, message=snaps.LABELS[self.snap_override] + " of", options=[], default=None, default_text="")
        return run.prompt

    def expect(self, p) -> str:
        if self.run is None or p is None:
            return "none"
        if p.select:
            return "selection"
        k = p.kind()
        if k == "entity":
            return "entity"
        if k == "text":
            return "text"
        if k == "keyword":
            return "keyword"
        if "point" in p.accepts:
            if "distance" in p.accepts and p.base is not None:
                return "distance"
            if "angle" in p.accepts and p.base is not None:
                return "angle"
            return "point"
        if "distance" in p.accepts:
            return "distance"
        if "angle" in p.accepts:
            return "angle"
        return "number"

    def base_point(self):
        p = self.current_prompt()
        base = p.base if p is not None and p.base is not None else self.tracking
        return [float(base[0]), float(base[1])] if base is not None else None

    def state(self) -> dict:
        run = self.run
        p = self.current_prompt()
        text = "Command:"
        options = []
        default = None
        kind = "idle"
        accepts = []
        base = None
        if run is not None and p is not None:
            text = format_prompt(p)
            options = [{"key": o, "label": o} for o in p.options]
            default = p.default
            kind = p.kind()
            accepts = list(p.accepts)
            base = p.base
            if run.sel is not None and not run.sel.window:
                options = [{"key": o, "label": o} for o in SEL_WORDS]
                text = format_prompt(Prompt(run.sel.message(), ("select",)))
        doc = self.doc
        out = {
            "active": run is not None,
            "command": self.command_name().upper(),
            "prompt": text,
            "options": options,
            "defaultValue": default,
            "kind": kind,
            "accepts": accepts,
            "expect": self.expect(p) if run is not None else "none",
            "base": self.base_point() if run is not None else None,
            "preview": self.has_preview(),
            "snapOverride": self.snap_override,
            "transparent": bool(run and run.transparent),
            "suspended": self.outer.spec.name.upper() if self.outer else None,
            "history": self.history[-STATE_HISTORY:],
            "historySize": len(self.history),
            "output": list(self._out),
            "error": self.error,
            "rev": doc.rev,
            "dirty": doc.dirty,
            "selection": list(doc.selection),
        }
        if self.result is not None:
            out["result"] = self.result
        return out

    def has_preview(self) -> bool:
        run = self.run
        if run is None:
            return False
        if run.sel is not None:
            return bool(run.sel.window and len(run.sel.window[1]) == 1)
        if run.frames or run.prompt is None:
            return False
        return run.prompt.jig is not None

    def preview(self, pt) -> dict:
        with self.doc.lock:
            try:
                cursor = self._clean(pt)
            except InputError:
                return {"items": []}
            return jig.build(self, cursor)

    def jig_prepare(self, cursor):
        pend = self.deferred
        ent = self.doc.drawing.get(pend.handle) if pend is not None else None
        if pend is None or ent is None:
            return lambda: None
        old = list(pend.ref)
        try:
            p = snaps.single(pend.mode, ent, cursor, pend.near)
            pend.ref[0], pend.ref[1] = p[0], p[1]
        except snaps.SnapError:
            pass

        def restore():
            pend.ref[0], pend.ref[1] = old[0], old[1]

        return restore

    def _clean(self, pt) -> list:
        try:
            vals = [float(v) for v in pt]
        except (TypeError, ValueError):
            raise InputError("Invalid point.")
        if len(vals) not in (2, 3) or not all(math.isfinite(v) for v in vals):
            raise InputError("Invalid point.")
        return [vals[0], vals[1], 0.0]

    def _ent(self, handle):
        try:
            return self.doc.drawing.get(int(handle)) if handle is not None else None
        except (TypeError, ValueError):
            return None

    def _visible_handles(self) -> set:
        d = self.doc.drawing
        return {e.handle for e in d.entities(self.doc.current_space) if d.visible(e)}

    def _aperture(self, snap) -> float:
        if snap and isinstance(snap.get("aperture"), (int, float)) and snap["aperture"] > 0:
            return float(snap["aperture"])
        return float(self.doc.view.get("height", 100.0)) * 0.02

    def _echo(self, p: Prompt, pt) -> None:
        self.log("%s %.10g,%.10g" % (format_prompt(p), pt[0], pt[1]))

    def submit_point(self, pt, snap=None) -> dict:
        self.begin_call()
        with self.doc.lock:
            try:
                self._canvas_point(self._clean(pt), snap if isinstance(snap, dict) else None)
            except (InputError, snaps.SnapError) as err:
                self._fail(str(err))
            self.doc.live_touch()
        return self.state()

    def submit_pick(self, pick) -> dict:
        self.begin_call()
        with self.doc.lock:
            try:
                self._canvas_pick(pick)
            except (InputError, snaps.SnapError) as err:
                self._fail(str(err))
            self.doc.live_touch()
        return self.state()

    def submit_selection(self, payload) -> dict:
        self.begin_call()
        with self.doc.lock:
            try:
                self._canvas_selection(payload)
            except InputError as err:
                self._fail(str(err))
            self.doc.live_touch()
        return self.state()

    def set_selection(self, handles, mode: str = "set") -> list:
        from app.sysvars import registry as sv

        doc = self.doc
        with doc.lock:
            vis = self._visible_handles()
            found = []
            for h in handles:
                if h in vis and h not in found:
                    found.append(h)
            if not sv.get_var(doc, "PICKFIRST"):
                found = []
                mode = "set"
            if mode == "add":
                found = list(doc.selection) + [h for h in found if h not in doc.selection]
            elif mode == "remove":
                found = [h for h in doc.selection if h not in found]
            doc.selection = [h for h in found if h in vis]
            doc.announce("selection")
            return list(doc.selection)

    def current_selection(self) -> list:
        with self.doc.lock:
            vis = self._visible_handles()
            self.doc.selection = [h for h in self.doc.selection if h in vis]
            return list(self.doc.selection)

    def _canvas_point(self, pt, snap) -> None:
        run = self.run
        if run is None:
            return
        if run.sel is not None:
            self._sel_point(run.sel, pt)
            return
        p = self.current_prompt()
        if "entity" in p.accepts and "point" not in p.accepts:
            raise InputError("Select an object.")
        if p.free_text or not any(a in p.accepts for a in ("point", "distance", "angle")):
            raise InputError("A point is not accepted here.")
        eff, defer = self._effective(pt, snap, self.base_point(), not run.frames)
        self._echo(p, eff)
        if run.frames:
            self._frame_point(eff)
        else:
            self._deliver_point(eff, defer)

    def _canvas_pick(self, pick) -> None:
        if not isinstance(pick, dict):
            raise InputError("Invalid pick.")
        pt = self._clean(pick.get("point") or [0.0, 0.0])
        ent = self._ent(pick.get("handle"))
        run = self.run
        if run is None:
            if ent is not None and ent.handle in self._visible_handles():
                from app.sysvars import registry as sv

                self.set_selection([ent.handle], "add" if sv.get_var(self.doc, "PICKADD") else "set")
            return
        if run.sel is not None:
            if run.sel.window is not None or ent is None:
                self._sel_point(run.sel, pt)
                return
            if ent.handle not in self._visible_handles():
                raise InputError("Nothing selected there.")
            self._apply_selection(run.sel, [ent.handle])
            if run.sel.prompt.pick_one and run.sel.selected:
                self._finish_selection()
            return
        p = self.current_prompt()
        if "entity" in p.accepts and "point" not in p.accepts and not run.frames:
            if ent is None or ent.handle not in self._visible_handles():
                raise InputError("No object found there.")
            self._echo(p, pt)
            self._deliver(Input("entity", {"handle": ent.handle, "point": [pt[0], pt[1]]}))
            return
        self._canvas_point(pt, {"handle": ent.handle} if ent is not None else None)

    def _canvas_selection(self, payload) -> None:
        if not isinstance(payload, dict):
            raise InputError("Invalid selection.")
        mode = payload.get("mode", "set")
        if mode not in ("set", "add", "remove"):
            raise InputError("Selection mode must be set, add or remove.")
        try:
            handles = [int(h) for h in payload.get("handles", [])]
        except (TypeError, ValueError):
            raise InputError("Invalid handle list.")
        run = self.run
        if run is None:
            self.set_selection(handles, mode)
            return
        sel = run.sel
        if sel is None or sel.window is not None:
            raise InputError("No object selection is requested now.")
        vis = self._visible_handles()
        found = []
        for h in handles:
            if h in vis and h not in found:
                found.append(h)
        if mode == "set":
            sel.steps.append(list(sel.selected))
            sel.selected = found
            self.log("%d found, %d total" % (len(found), len(found)) if found else "0 found")
        else:
            old = sel.mode
            sel.mode = "remove" if mode == "remove" else "add"
            self._apply_selection(sel, found)
            sel.mode = old
        if sel.prompt.pick_one and sel.selected:
            self._finish_selection()

    def _sel_point(self, sel: SelState, pt) -> None:
        if sel.window is None:
            sel.window = ("auto", [pt])
            return
        kind, pts = sel.window
        pts.append(pt)
        if len(pts) == 2:
            self._select_window(sel, kind, pts)
            sel.window = None

    def _effective(self, pt, snap, base, allow_defer):
        mode = str(snap["mode"]).lower() if snap and snap.get("mode") else None
        handle = snap.get("handle") if snap else None
        near = self._clean(snap["at"]) if snap and snap.get("at") else pt
        want = self.snap_override
        aperture = self._aperture(snap)
        ents = list(self.run.ctx.visible_entities())
        if want == "none":
            mode = None
        elif want and mode != want:
            label = snaps.LABELS[want]
            if want in snaps.DEFERRABLE:
                ent = self._ent(handle) or snaps.nearest_curve(ents, near, aperture)
                if ent is None:
                    raise snaps.SnapError("%s needs a curve there." % label)
                handle = ent.handle
            else:
                found = snaps.search(ents, want, near, aperture, self._ent(handle))
                if found is None:
                    raise snaps.SnapError("No %s snap point found there." % label.lower())
                pt = found[0]
                near = pt
                handle = found[1]
            mode = want
        if mode in snaps.DEFERRABLE:
            ent = self._ent(handle) or snaps.nearest_curve(ents, near, aperture)
            if ent is None:
                raise snaps.SnapError("%s needs a curve there." % snaps.LABELS[mode])
            if self.deferred is not None:
                base = None
            if base is not None:
                pt = snaps.single(mode, ent, base, near)
            elif allow_defer:
                self.snap_override = None
                return [near[0], near[1], 0.0], (mode, ent.handle, [near[0], near[1], 0.0])
            else:
                raise snaps.SnapError("%s needs a base point here." % snaps.LABELS[mode])
        elif mode in snaps.LABELS and mode != "none" and snap and snap.get("at"):
            pt = near
        self.snap_override = None
        return pt, None

    def _resolve_deferred(self, pt, defer) -> None:
        pend = self.deferred
        d = self.doc.drawing
        if pend is not None:
            ent1 = d.get(pend.handle)
            if ent1 is None:
                self.deferred = None
            elif defer is not None:
                ent2 = d.get(defer[1])
                p1, p2 = snaps.pair(pend.mode, ent1, pend.near, defer[0], ent2, defer[2])
                pend.ref[0], pend.ref[1] = p1[0], p1[1]
                pt[0], pt[1] = p2[0], p2[1]
                self.deferred = None
                return
            else:
                p1 = snaps.single(pend.mode, ent1, pt, pend.near)
                pend.ref[0], pend.ref[1] = p1[0], p1[1]
                self.deferred = None
                return
        if defer is not None:
            self.deferred = Deferred(defer[0], defer[1], list(defer[2]), pt)

    def begin_call(self) -> None:
        self._out = []
        self.error = ""
        self.result = None

    def submit(self, text: str) -> dict:
        self.begin_call()
        with self.doc.lock:
            self._submit(text.replace("\r", "").replace("\n", " "))
            self.doc.live_touch()
        return self.state()

    def _submit(self, text: str) -> None:
        if self.run is None:
            self._idle(text)
        else:
            self._active(text)

    def _tokens(self, text: str) -> list:
        return re.split(r"[ \t]", text)

    def _idle(self, text: str) -> None:
        line = text.lstrip(" \t")
        if line.strip() == "":
            if self.last_cmd:
                self._launch(self.last_cmd, [], False)
            return
        if "{" in line:
            word, _, rest = line.partition("{")
            word = word.strip()
            spec = registry.resolve(word)
            if spec is not None:
                try:
                    args = json.loads("{" + rest)
                except ValueError:
                    self._fail("Invalid parameters for %s." % word.upper())
                    return
                self._programmatic(spec, args if isinstance(args, dict) else {})
                return
        toks = self._tokens(line)
        word, rest = toks[0], toks[1:]
        if word.startswith("("):
            self._fail("The embedded language is not available yet.")
            return
        transparent = word.startswith("'")
        if transparent:
            word = word[1:]
        spec = registry.resolve(word)
        if spec is None:
            from app.sysvars import known

            bare = word.upper()
            if known(bare) and not word.startswith(("_", ".", "-")):
                self._launch("setvar", [bare] + rest, False)
                return
            self._fail("Unknown command: %s" % word.upper())
            return
        self._launch(spec.name, rest, transparent)

    def _fail(self, msg: str) -> None:
        self.error = msg
        self.log(msg)

    def _active(self, text: str) -> None:
        run = self.run
        p = self.current_prompt()
        if p is not None and p.free_text and not run.frames and run.sel is None:
            self._feed_text(text)
            return
        whole = text.strip()
        if p is not None and " " in whole and not run.frames and run.sel is None and any(o.lower() == whole.lower() for o in p.options):
            self._feed(whole)
            return
        toks = self._tokens(text.lstrip(" \t")) if text.strip() != "" else [""]
        for i, tok in enumerate(toks):
            if self.run is None:
                rest = " ".join(toks[i:]).strip()
                if rest:
                    self._idle(rest)
                return
            self._feed(tok)

    def _feed_text(self, text: str) -> None:
        run = self.run
        p = run.prompt
        self.log("%s %s" % (format_prompt(p), text))
        if text == "" and p.default is None:
            self._deliver(Input("enter"))
        elif text == "":
            self._deliver(Input("text", p.default, True))
        else:
            self._deliver(Input("text", text, text=text))

    def _launch(self, name: str, args: list, transparent: bool) -> None:
        spec = registry.COMMANDS[name]
        if self.run is not None and not transparent:
            self.cancel_run(quiet=True)
        if transparent:
            self._start_transparent(spec)
        else:
            self._start(spec)
        for i, tok in enumerate(args):
            if self.run is None:
                rest = " ".join(args[i:]).strip()
                if rest:
                    self._idle(rest)
                return
            self._feed(tok)

    def _start(self, spec) -> None:
        doc = self.doc
        run = Run(spec)
        run.ctx = Context(self, doc)
        self.log("Command: %s" % spec.name.upper())
        if spec.undoable:
            doc.begin(spec.name.upper())
            run.owns_tx = True
        self.run = run
        self.outer = None
        self.tracking = None
        self.deferred = None
        self.snap_override = None
        self._boot(run)

    def _start_transparent(self, spec) -> None:
        if not spec.transparent:
            self._fail("'%s cannot be used transparently." % spec.name.upper())
            return
        if self.run is None:
            self._start(spec)
            return
        if self.outer is not None or self.run.transparent:
            self._fail("A transparent command is already in progress.")
            return
        run = Run(spec, True)
        run.ctx = Context(self, self.doc)
        self.log(">>%s" % spec.name.upper())
        self.outer = self.run
        self.run = run
        self._boot(run)

    def _boot(self, run: Run) -> None:
        try:
            res = run.spec.fn(run.ctx)
        except Exception as err:
            self._crash(run, err)
            return
        if inspect.isgenerator(res):
            run.gen = res
            self._advance(None)
        else:
            self._finish(run, "done")

    def _advance(self, value) -> None:
        run = self.run
        while run is not None:
            try:
                if not run.started:
                    run.started = True
                    prompt = next(run.gen)
                else:
                    prompt = run.gen.send(value)
            except StopIteration:
                self._finish(run, "done")
                return
            except CommandCancel:
                self._finish(run, "cancel")
                return
            except CommandError as err:
                self._fail(str(err))
                self._finish(run, "error")
                return
            except Exception as err:
                self._crash(run, err)
                return
            run.frames = []
            if isinstance(prompt, Prompt) and prompt.select:
                pre = self._preselected(prompt)
                if pre is not None:
                    value = Input("selection", pre)
                    continue
                run.prompt = prompt
                run.sel = SelState(prompt)
                return
            run.sel = None
            run.prompt = prompt
            return

    def _preselected(self, prompt: Prompt):
        doc = self.doc
        if not prompt.preselect or not doc.selection:
            return None
        from app.sysvars import registry as sv

        if not sv.get_var(doc, "PICKFIRST"):
            return None
        valid = [h for h in doc.selection if h in doc.drawing.ents]
        if not valid:
            return None
        doc.prev_selection = list(valid)
        doc.selection = []
        self.log("%d found" % len(valid))
        return valid

    def _crash(self, run: Run, err: Exception) -> None:
        self._fail("Internal error in %s: %s" % (run.spec.name.upper(), err))
        self._finish(run, "crash")

    def _finish(self, run: Run, status: str) -> None:
        doc = self.doc
        if run.gen is not None:
            try:
                run.gen.close()
            except Exception:
                pass
        if run.transparent and self.outer is not None:
            self.run = self.outer
            self.outer = None
            self.log("Resuming %s command." % self.run.spec.name.upper())
            return
        step = None
        if run.owns_tx:
            if status == "crash":
                doc.rollback()
            else:
                try:
                    step = doc.commit(True)
                except CommandFailed as err:
                    self._fail(str(err))
        self.run = None
        self.outer = None
        self.tracking = None
        self.deferred = None
        self.snap_override = None
        if run.spec.repeatable:
            self.last_cmd = run.spec.name
        if step is not None:
            doc.selection = []
            doc.announce("edit")

    def cancel_run(self, quiet: bool = False) -> None:
        run = self.run
        if run is None:
            return
        if self.outer is not None:
            self.run = self.outer
            self.outer = None
            self.run.frames = []
            outer = self.run
            if not quiet:
                self.log("*Cancel*")
            self._finish(outer, "cancel")
            return
        if not quiet:
            self.log("*Cancel*")
        self._finish(run, "cancel")

    def cancel(self) -> dict:
        self.begin_call()
        with self.doc.lock:
            if self.run is None:
                self.doc.selection = []
            else:
                self.cancel_run()
        return self.state()

    def inline_undo(self) -> bool:
        run = self.run
        if run is None or run.frames or run.sel is not None or run.prompt is None:
            return False
        if not any(o.lower() == "undo" for o in run.prompt.options):
            return False
        self._feed("Undo")
        return True

    def run_command(self, name: str, args: dict | None = None) -> dict:
        self.begin_call()
        with self.doc.lock:
            spec = registry.resolve(name.lstrip("'"))
            if spec is None:
                self._fail("Unknown command: %s" % name.upper())
                return self.state()
            args = args or {}
            if self.run is not None:
                self.cancel_run(quiet=True)
            if "inputs" in args and isinstance(args["inputs"], list):
                self._launch(spec.name, [str(x) for x in args["inputs"]], False)
            else:
                self._programmatic(spec, args)
            self.doc.live_touch()
        return self.state()

    def _programmatic(self, spec, args: dict) -> None:
        if self.run is not None:
            self.cancel_run(quiet=True)
        if spec.execute is None:
            self._launch(spec.name, [], False)
            return
        doc = self.doc
        ctx = Context(self, doc)
        self.log("Command: %s" % spec.name.upper())
        try:
            if spec.undoable:
                doc.begin(spec.name.upper())
            try:
                self.result = spec.execute(ctx, args)
            except CommandError as err:
                self._fail(str(err))
            except Exception as err:
                if spec.undoable:
                    doc.rollback()
                self._fail("Internal error in %s: %s" % (spec.name.upper(), err))
                return
            if spec.undoable:
                step = doc.commit(True)
                if step is not None:
                    doc.selection = []
                    doc.announce("edit")
        except CommandFailed as err:
            self._fail(str(err))
        if spec.repeatable:
            self.last_cmd = spec.name

    def _feed(self, tok: str) -> None:
        run = self.run
        if len(tok) > 1 and tok.startswith("'"):
            word = tok[1:]
            spec = registry.resolve(word)
            if spec is None:
                self._fail("Unknown command: %s" % word.upper())
                return
            self._start_transparent(spec)
            return
        if run.frames:
            self._feed_frame(tok)
            return
        if run.sel is not None:
            self._feed_sel(tok)
            return
        p = run.prompt
        try:
            res = resolve(p, tok, self.env())
        except InputError as err:
            self.log("%s %s" % (format_prompt(p), tok))
            self._fail(str(err))
            return
        self.log("%s %s" % (format_prompt(p), tok))
        kind = res[0]
        if kind == "input":
            self._deliver(res[1])
        elif kind == "point":
            self._deliver_point(res[1])
        else:
            self._push_frame(res[1], res[2])

    def _deliver_point(self, pt: list, defer=None) -> None:
        run = self.run
        try:
            self._resolve_deferred(pt, defer)
            inp = point_to_input(run.prompt, pt, self.env())
        except (InputError, snaps.SnapError) as err:
            self._fail(str(err))
            return
        self._deliver(inp)

    def _frame_point(self, pt) -> None:
        frame = self.run.frames[-1]
        done, val = frame.accept(pt)
        if frame.kind == "tt" and done:
            self.tracking = pt
        self._frame_result(done, val)

    def _deliver(self, inp: Input) -> None:
        self.snap_override = None
        if inp.kind == "point":
            self.doc.lastpoint = [inp.value[0], inp.value[1], 0.0]
        self._advance(inp)

    def _push_frame(self, kind: str, text: str) -> None:
        run = self.run
        if kind.startswith("osnap:"):
            mode = snaps.mode_of(kind[6:])
            self.snap_override = mode
            if mode != "none":
                self.log("%s of" % snaps.LABELS[mode])
            return
        if len(run.frames) >= MAX_FRAMES:
            self._fail("Too many nested point modifiers.")
            return
        if kind == "angle":
            base = run.prompt.base or self.tracking
            if base is None:
                self._fail("Angle override needs a base point.")
                return
            env = self.env()
            try:
                from app.cmd import units

                a = units.parse_angle(text.strip().lstrip("<"), env.aunits)
            except ValueError as err:
                self._fail(str(err))
                return
            if a is None:
                self._fail("Invalid angle.")
                return
            ang = units.direction_from_angle(a, env.angbase, env.angdir)
            run.frames.append(Frame("angle", base, ang, text.strip().lstrip("<")))
            return
        run.frames.append(Frame(kind, run.prompt.base))

    def _feed_frame(self, tok: str) -> None:
        run = self.run
        frame = run.frames[-1]
        p = frame.prompt()
        env = self.env()
        self.log("%s %s" % (format_prompt(p), tok))
        try:
            res = resolve(p, tok, env)
        except InputError as err:
            self._fail(str(err))
            return
        kind = res[0]
        if kind == "input":
            if res[1].kind == "enter":
                try:
                    done, val = frame.enter()
                except InputError as err:
                    self._fail(str(err))
                    return
                self._frame_result(done, val)
            return
        if kind == "modifier":
            self._push_frame(res[1], res[2])
            return
        self._frame_point(res[1])

    def _frame_result(self, done: bool, val) -> None:
        run = self.run
        if not done:
            return
        run.frames.pop()
        if val is None:
            return
        if run.frames:
            parent = run.frames[-1]
            d2, v2 = parent.accept(val)
            self._frame_result(d2, v2)
            return
        self._deliver_point(val)

    def _feed_sel(self, tok: str) -> None:
        run = self.run
        sel = run.sel
        prompt = sel.prompt
        env = self.env()
        label = format_prompt(Prompt(sel.message(), ("select",)))
        self.log("%s %s" % (label, tok))
        t = tok.strip()
        if sel.window is not None:
            kind, pts = sel.window
            if t == "":
                sel.window = None
                return
            try:
                pt = parse_point(t, env)
            except InputError as err:
                self._fail(str(err))
                return
            if pt is None:
                self._fail("Invalid point.")
                return
            pts.append(pt)
            if len(pts) == 2:
                self._select_window(sel, kind, pts)
                sel.window = None
            return
        if t == "":
            self._finish_selection()
            return
        word = match_keyword(list(SEL_WORDS) + ["Single", "Multiple", "Auto", "Fence"], t)
        low = t.lower()
        if low in ("p", "previous"):
            word = "Previous"
        elif low in ("l", "last"):
            word = "Last"
        elif low in ("w", "window"):
            word = "Window"
        elif low in ("c", "crossing"):
            word = "Crossing"
        elif low == "all":
            word = "All"
        if t.startswith("#") or re.fullmatch(r"[hH][0-9a-fA-F]+(,[hH]?[0-9a-fA-F]+)*", t):
            self._select_handles(sel, t)
            if prompt.pick_one and sel.selected:
                self._finish_selection()
            return
        if word in ("Window", "Crossing", "BOX"):
            sel.window = ("crossing" if word == "Crossing" else "window", [])
            return
        if word == "Add":
            sel.mode = "add"
            return
        if word == "Remove":
            sel.mode = "remove"
            return
        if word == "Undo":
            if sel.steps:
                sel.selected = sel.steps.pop()
            return
        if word in ("All", "Last", "Previous"):
            cands = self._candidates()
            if word == "All":
                found = [e.handle for e in cands]
            elif word == "Last":
                found = [cands[-1].handle] if cands else []
            else:
                found = [h for h in self.doc.prev_selection if h in self.doc.drawing.ents]
            self._apply_selection(sel, found)
            if prompt.pick_one and sel.selected:
                self._finish_selection()
            return
        if word in ("Single", "Multiple", "Auto", "Fence"):
            return
        self._fail("Select objects with ALL, Last, Previous, Window, Crossing, #handle or a pick on the canvas.")

    def _candidates(self) -> list:
        return [e for e in self.run.ctx.visible_entities()]

    def _select_handles(self, sel: SelState, text: str) -> None:
        found = []
        d = self.doc.drawing
        vis = {e.handle for e in self._candidates()}
        for part in text.split(","):
            s = part.strip().lstrip("#").lstrip("hH")
            try:
                h = int(s, 16)
            except ValueError:
                continue
            if h in vis:
                found.append(h)
        self._apply_selection(sel, found)

    def _select_window(self, sel: SelState, kind: str, pts: list) -> None:
        if kind == "auto":
            kind = "window" if pts[1][0] >= pts[0][0] else "crossing"
        box = (min(pts[0][0], pts[1][0]), min(pts[0][1], pts[1][1]), max(pts[0][0], pts[1][0]), max(pts[0][1], pts[1][1]))
        found = []
        for e in self._candidates():
            b = e.bounds()
            if b is None:
                continue
            if kind == "window" and geom.box_inside(b, box):
                found.append(e.handle)
            elif kind == "crossing" and geom.boxes_overlap(b, box):
                found.append(e.handle)
        self._apply_selection(sel, found)

    def _apply_selection(self, sel: SelState, found: list) -> None:
        sel.steps.append(list(sel.selected))
        if sel.mode == "remove":
            sel.selected = [h for h in sel.selected if h not in found]
            n = len(found)
        else:
            n = len(found)
            for h in found:
                if h not in sel.selected:
                    sel.selected.append(h)
        self.log("%d found, %d total" % (n, len(sel.selected)) if n else "0 found")

    def _finish_selection(self) -> None:
        run = self.run
        sel = run.sel
        handles = list(sel.selected)
        if handles:
            self.doc.prev_selection = list(handles)
        run.sel = None
        self._advance(Input("selection", handles))
