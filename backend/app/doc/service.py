import atexit
import json
import os
import threading
import time

from app.doc import container, events
from app.doc.autosave import AutoSaver
from app.doc.document import Document
from app.doc.model import Drawing
from app.sysvars import registry as sv

EXT = ".fcad"
MAX_RECENT = 30


class DocError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def _data_dir():
    from app.core import config

    return config.data_dir()


def _autosave_dir():
    raw = str(sv.session_value("SAVEFILEPATH") or "").strip()
    if raw:
        return os.path.expanduser(raw)
    from app.core import config

    return config.autosave_dir()


class Service:
    def __init__(self):
        self.docs: dict = {}
        self.lock = threading.RLock()
        self.active_id = ""
        self.counter = 0
        self.number = 0
        self.epoch = 0
        self.saver = AutoSaver(_autosave_dir, lambda: list(self.docs.values()), lambda: int(sv.session_value("SAVETIME")))
        self._started = False

    def start(self) -> None:
        with self.lock:
            if self._started:
                return
            self._started = True
        self.saver.start()
        atexit.register(self.stop)

    def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self.saver.stop(True)

    def get(self, doc_id: str) -> Document:
        doc = self.docs.get(doc_id)
        if doc is None:
            raise DocError("No such document.", 404)
        self.active_id = doc_id
        return doc

    def active(self):
        return self.docs.get(self.active_id)

    def summaries(self) -> list:
        return [d.summary() for d in self.docs.values()]

    def _register(self, doc: Document) -> Document:
        self.start()
        self.number += 1
        doc.number = self.number
        self.docs[doc.id] = doc
        self.active_id = doc.id
        self.epoch += 1
        events.publish({"type": "docs", "reason": "open", "id": doc.id, "epoch": self.epoch})
        return doc

    def new(self, name: str = "", template: str = "") -> Document:
        tpl = (template or "").lower()
        if tpl in ("metric", "iso"):
            metric = True
        elif tpl in ("imperial", "inch"):
            metric = False
        else:
            metric = bool(sv.session_value("MEASUREINIT"))
        with self.lock:
            self.counter += 1
            title = name.strip() or "Drawing%d" % self.counter
            doc = Document(Drawing(metric), title, "", "drawing", metric)
            return self._register(doc)

    def open(self, path: str) -> Document:
        if not path:
            raise DocError("A path is required.")
        full = os.path.realpath(os.path.expanduser(path))
        with self.lock:
            for d in self.docs.values():
                if d.path and os.path.realpath(d.path) == full:
                    self.active_id = d.id
                    return d
            try:
                drawing, manifest = container.load(full)
            except container.ContainerError as err:
                raise DocError(err.message)
            name = os.path.splitext(os.path.basename(full))[0]
            doc = Document(drawing, name, full, "drawing", drawing.metric)
            doc.created = str(manifest.get("created") or doc.created)
            self._register(doc)
        self.add_recent(full)
        return doc

    def save(self, doc: Document, path: str = "") -> Document:
        target = (path or doc.path or "").strip()
        if not target:
            raise DocError("The drawing has no file name yet; give a path.")
        if os.path.splitext(target)[1] == "":
            target += EXT
        with doc.lock:
            if doc.in_tx():
                raise DocError("A command is still recording; finish it before saving.", 409)
            doc.undo.end_group()
            try:
                dest = container.save(target, doc.drawing, doc.name, doc.created, bool(sv.session_value("ISAVEBAK")))
            except container.ContainerError as err:
                raise DocError(err.message)
            doc.mark_saved(dest)
            doc.name = os.path.splitext(os.path.basename(dest))[0]
            self.saver.discard(doc)
        self.add_recent(dest)
        events.publish({"type": "docs", "reason": "save", "id": doc.id})
        doc.announce("save")
        return doc

    def close(self, doc: Document, force: bool = False) -> bool:
        with self.lock:
            if doc.dirty and not force:
                return False
            runner = doc.runner
            if runner is not None and runner.run is not None:
                with doc.lock:
                    runner.cancel_run(quiet=True)
            self.saver.discard(doc)
            self.docs.pop(doc.id, None)
            if self.active_id == doc.id:
                self.active_id = next(reversed(self.docs), "") if self.docs else ""
            self.epoch += 1
        events.publish({"type": "docs", "reason": "close", "id": doc.id, "epoch": self.epoch})
        return True

    def recent_path(self):
        return _data_dir() / "recent.json"

    def recent(self) -> list:
        try:
            items = json.loads(self.recent_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [i for i in items if isinstance(i, str)]

    def add_recent(self, path: str) -> None:
        items = [p for p in self.recent() if p != path]
        items.insert(0, path)
        try:
            container.atomic_write(str(self.recent_path()), json.dumps(items[:MAX_RECENT]).encode("utf-8"), 0o600)
        except (OSError, ValueError):
            pass

    def recovery_list(self) -> list:
        return self.saver.listing()

    def recovery_open(self, name: str) -> Document:
        path = self.saver.resolve(name)
        if path is None:
            raise DocError("That recovery file is not available.", 404)
        try:
            drawing, manifest = container.load(path)
        except container.ContainerError as err:
            raise DocError(err.message)
        with self.lock:
            title = str(manifest.get("title") or "Recovered")
            doc = Document(drawing, title, "", "drawing", drawing.metric)
            doc.created = str(manifest.get("created") or doc.created)
            doc.saved_state = -1
            doc.dirty_since = time.time()
            self._register(doc)
            doc.autosave_file = path
            doc.autosaved_state = doc.state_id
        return doc

    def recovery_discard(self, name: str) -> bool:
        return self.saver.remove_listed(name)


service = Service()
