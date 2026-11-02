import copy
import itertools
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

from app.doc import commit_hooks, events, geom
from app.doc.model import Drawing
from app.doc.undo import Step, Tx, UndoManager

MAX_VIEW_HISTORY = 50
LARGE = 1e300


class CommandFailed(Exception):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Document:
    def __init__(self, drawing: Drawing | None = None, name: str = "Drawing1", path: str = "", kind: str = "drawing", metric: bool = True):
        self.id = uuid.uuid4().hex[:12]
        self.drawing = drawing or Drawing(metric)
        self.name = name
        self.path = path
        self.kind = kind
        self.created = now_iso()
        self.modified = self.created
        self.rev = 0
        self.undo = UndoManager()
        self.lock = threading.RLock()
        self._tx = None
        self._tx_depth = 0
        self._states = itertools.count(1)
        self.state_id = next(self._states)
        self.saved_state = self.state_id
        self.autosaved_state = self.state_id
        self.dirty_since = 0.0
        self.autosave_file = ""
        self.ent_rev: dict = {}
        self.removed_rev: dict = {}
        self.table_rev: dict = {}
        self.space_rev: dict = {}
        self.header_rev = 0
        self.selection: list = []
        self.prev_selection: list = []
        self.last_erased: list = []
        self.lastpoint = [0.0, 0.0, 0.0]
        self.view = {"center": [210.0, 148.5] if self.drawing.metric else [6.0, 4.5], "height": 297.0 if self.drawing.metric else 9.0}
        self.view_history: list = []
        self.view_requests: list = []
        self.tab = "model"
        self.active_vp = 0
        self.vp_max = 0
        self.tab_hint = 0
        self.space_views: dict = {}
        self.runner = None
        self.number = 0
        self.aspect = 1.6

    @property
    def current_space(self) -> str:
        from app.doc import layouts

        return layouts.effective_space(self)

    @current_space.setter
    def current_space(self, value: str) -> None:
        self.tab = value
        self.active_vp = 0
        self.vp_max = 0

    @property
    def dirty(self) -> bool:
        return self.state_id != self.saved_state

    def get_runner(self):
        if self.runner is None:
            from app.cmd.runner import CommandRunner

            self.runner = CommandRunner(self)
        return self.runner

    def begin(self, label: str) -> Tx:
        if self._tx is not None:
            self._tx_depth += 1
            return self._tx
        self._tx = Tx(label)
        self._tx_depth = 1
        self.drawing.recorder = self._tx
        return self._tx

    def in_tx(self) -> bool:
        return self._tx is not None

    def rollback(self) -> None:
        tx = self._tx
        if tx is None:
            return
        self._tx_depth -= 1
        if self._tx_depth > 0:
            return
        self._tx = None
        self.drawing.recorder = None
        for key, val in list(tx.before.items()):
            self.drawing.apply_key(key, val)
        if tx.live:
            self.rev += 1
            self._touch(tx.before.keys(), self.rev)
            self.announce("rollback")

    def live_touch(self) -> bool:
        tx = self._tx
        if tx is None or not tx.before:
            return False
        tx.live = True
        self.rev += 1
        self._touch(tx.before.keys(), self.rev)
        self.announce("live")
        return True

    def commit(self, undoable: bool = True) -> Step | None:
        tx = self._tx
        if tx is None:
            return None
        self._tx_depth -= 1
        if self._tx_depth > 0:
            return None
        if tx.before:
            commit_hooks.run(self, tx)
        self._tx = None
        self.drawing.recorder = None
        if not tx.before:
            return None
        bad = self._check_changed(tx.before)
        if bad:
            for key, val in list(tx.before.items()):
                self.drawing.apply_key(key, val)
            raise CommandFailed(bad)
        self.rev += 1
        self._touch(tx.before.keys(), self.rev)
        before_state = self.state_id
        self.state_id = next(self._states)
        self.modified = now_iso()
        if not self.dirty_since:
            self.dirty_since = time.time()
        step = Step(tx.label, tx.before, before_state, self.state_id)
        if undoable:
            self.undo.record(step)
        return step

    def _check_changed(self, before: dict) -> str:
        for key in before:
            if key[0] != "e":
                continue
            ent = self.drawing.ents.get(key[1])
            if ent is None:
                continue
            if not geom.finite_tree(ent.to_dict()):
                return "The result has non-finite numbers."
            box = ent.bounds()
            if box and any(abs(v) > LARGE for v in box):
                return "The result is too large."
        return ""

    @contextmanager
    def transaction(self, label: str, undoable: bool = True):
        self.begin(label)
        try:
            yield self._tx
        except BaseException:
            self.rollback()
            raise
        else:
            step = self.commit(undoable)
            if step is not None:
                self.announce("edit")

    def _touch(self, keys, rev: int) -> None:
        d = self.drawing
        for key in keys:
            kind = key[0]
            if kind == "e":
                h = key[1]
                if h in d.ents:
                    self.ent_rev[h] = rev
                    self.removed_rev.pop(h, None)
                else:
                    self.removed_rev[h] = rev
                    self.ent_rev.pop(h, None)
            elif kind == "t":
                self.table_rev[key[1]] = rev
            elif kind == "s":
                self.space_rev[key[1]] = rev
            elif kind == "h":
                self.header_rev = rev

    def _swap(self, step: Step) -> None:
        d = self.drawing
        for key, val in list(step.before.items()):
            cur = d.read_key(key)
            d.apply_key(key, val)
            step.before[key] = cur
        self.rev += 1
        self._touch(step.before.keys(), self.rev)
        self.state_id = step.state_before
        step.state_before, step.state_after = step.state_after, step.state_before
        self.selection = []
        from app.doc import editstate

        editstate.reconcile(self)
        self.modified = now_iso()
        if self.dirty and not self.dirty_since:
            self.dirty_since = time.time()

    def do_undo(self, n: int = 1) -> list:
        if self._tx is not None:
            raise CommandFailed("A command is still recording.")
        steps = self.undo.pop_undo(n)
        for s in steps:
            self._swap(s)
        if steps:
            self.announce("undo")
        return [s.label for s in steps]

    def do_redo(self, n: int = 1) -> list:
        if self._tx is not None:
            raise CommandFailed("A command is still recording.")
        steps = self.undo.pop_redo(n)
        for s in steps:
            self._swap(s)
        if steps:
            self.announce("redo")
        return [s.label for s in steps]

    def announce(self, reason: str) -> None:
        events.publish({"type": "doc", "id": self.id, "rev": self.rev, "reason": reason, "dirty": self.dirty})

    def bump(self, reason: str = "view") -> int:
        self.rev += 1
        self.announce(reason)
        return self.rev

    def request_view(self, mode: str, **params) -> dict:
        req = {"mode": mode, **params, "rev": self.rev + 1}
        self.view_requests.append(req)
        del self.view_requests[:-20]
        self.rev += 1
        events.publish({"type": "doc", "id": self.id, "rev": self.rev, "reason": "view", "view": req})
        return req

    def set_view(self, center, height: float) -> None:
        self.view_history.append(dict(self.view))
        del self.view_history[:-MAX_VIEW_HISTORY]
        self.view = {"center": [center[0], center[1]], "height": height}

    def mark_saved(self, path: str | None = None) -> None:
        self.undo.end_group()
        self.saved_state = self.state_id
        self.autosaved_state = self.state_id
        self.dirty_since = 0.0
        if path:
            self.path = path
        self.modified = now_iso()

    def snapshot(self, since: int = 0) -> dict:
        d = self.drawing
        ents = []
        removed = []
        if since <= 0:
            ents = [e.to_dict() for e in d.ordered_entities()]
        else:
            for h, r in self.ent_rev.items():
                if r > since and h in d.ents:
                    ents.append(d.ents[h].to_dict())
            removed = [h for h, r in self.removed_rev.items() if r > since and h not in d.ents]
        order = {s: list(hs) for s, hs in d.spaces.items() if since <= 0 or self.space_rev.get(s, 0) > since}
        box = d.extents()
        return {
            "rev": self.rev,
            "full": since <= 0,
            "entities": ents,
            "removed": removed,
            "order": order,
            "tables": {n: t.to_list() for n, t in d.tables.items() if n not in ("plotstyles",)},
            "header": copy.deepcopy(d.header),
            "view": copy.deepcopy(self.view),
            "extents": list(box) if box else None,
            "selection": list(self.selection),
        }

    def summary(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "modified": self.modified,
            "created": self.created,
            "rev": self.rev,
            "kind": self.kind,
            "dirty": self.dirty,
            "untitled": not self.path,
            "entities": len(self.drawing.ents),
            "metric": self.drawing.metric,
            "space": self.current_space,
            "tab": self.tab,
            "viewport": self.active_vp,
            "maximized": self.vp_max,
        }
