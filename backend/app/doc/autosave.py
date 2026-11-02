import os
import re
import threading
import time
from datetime import datetime, timezone

from app.doc import container

PATTERN = re.compile(r"^(?P<title>.+)_(?P<inst>\d{1,10}-[0-9a-f]{1,32})_(?P<uid>\d+)\.sv\$$")
LOCK_FRESH = 300.0
LOCK_REFRESH = 60.0
MAX_SCAN = 10000
TICK = 5.0


def sanitize_title(title: str) -> str:
    out = "".join(c if (c.isalnum() or c in " .-_()") else "-" for c in title)[:80].strip(" .")
    return out or "Drawing"


class AutoSaver:
    def __init__(self, folder_fn, docs_fn, savetime_fn):
        self.folder_fn = folder_fn
        self.docs_fn = docs_fn
        self.savetime_fn = savetime_fn
        self.instance = "%d-%x" % (os.getpid(), int(time.time() * 1000))
        self.thread = None
        self.stop_event = threading.Event()
        self.last_lock = 0.0

    def folder(self) -> str:
        path = str(self.folder_fn())
        os.makedirs(path, mode=0o700, exist_ok=True)
        return path

    def lock_path(self, instance: str = "") -> str:
        return os.path.join(self.folder(), (instance or self.instance) + ".lock")

    def start(self) -> None:
        if self.thread is not None and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.refresh_lock(True)
        self.thread = threading.Thread(target=self.loop, name="formcad-autosave", daemon=True)
        self.thread.start()

    def stop(self, clean: bool = True) -> None:
        self.stop_event.set()
        if clean:
            for doc in self.docs_fn():
                self.discard(doc)
            try:
                os.unlink(self.lock_path())
            except OSError:
                pass

    def refresh_lock(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self.last_lock < LOCK_REFRESH:
            return
        try:
            with open(self.lock_path(), "w") as fh:
                fh.write(str(os.getpid()))
            self.last_lock = now
        except OSError:
            pass

    def loop(self) -> None:
        while not self.stop_event.wait(TICK):
            try:
                self.refresh_lock()
                self.run_once()
            except Exception:
                pass

    def file_for(self, doc) -> str:
        number = getattr(doc, "number", 0)
        return os.path.join(self.folder(), "%s_%s_%d.sv$" % (sanitize_title(doc.name), self.instance, number))

    def due(self, doc, now: float) -> bool:
        minutes = self.savetime_fn()
        if minutes <= 0 or doc.state_id == doc.autosaved_state or not doc.dirty_since:
            return False
        return now - doc.dirty_since >= minutes * 60.0

    def run_once(self, now: float | None = None) -> int:
        now = now if now is not None else time.time()
        count = 0
        for doc in list(self.docs_fn()):
            if self.due(doc, now):
                if self.write(doc):
                    count += 1
        return count

    def save_now(self) -> int:
        count = 0
        for doc in list(self.docs_fn()):
            if doc.dirty and doc.state_id != doc.autosaved_state:
                if self.write(doc):
                    count += 1
        self.refresh_lock(True)
        return count

    def write(self, doc) -> bool:
        with doc.lock:
            if doc.in_tx():
                return False
            target = doc.autosave_file or self.file_for(doc)
            try:
                data = container.encode(doc.drawing, doc.name, doc.created, doc.kind, True)
                container.atomic_write(target, data, 0o600)
            except (container.ContainerError, OSError):
                doc.dirty_since = time.time()
                return False
            doc.autosave_file = target
            doc.autosaved_state = doc.state_id
            doc.dirty_since = 0.0
        return True

    def discard(self, doc) -> None:
        path = doc.autosave_file
        doc.autosave_file = ""
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass

    def instance_alive(self, instance: str) -> bool:
        if instance == self.instance:
            return True
        try:
            age = time.time() - os.stat(self.lock_path(instance)).st_mtime
        except OSError:
            return False
        return age <= LOCK_FRESH

    def listing(self) -> list:
        folder = self.folder()
        out = []
        adopted = {d.autosave_file for d in self.docs_fn() if d.autosave_file}
        try:
            with os.scandir(folder) as it:
                for i, entry in enumerate(it):
                    if i >= MAX_SCAN:
                        break
                    m = PATTERN.match(entry.name)
                    if not m or not entry.is_file(follow_symlinks=False):
                        continue
                    if os.path.join(folder, entry.name) in adopted:
                        continue
                    if self.instance_alive(m.group("inst")):
                        continue
                    st = entry.stat()
                    out.append({"file": entry.name, "title": m.group("title"), "instance": m.group("inst"), "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="seconds"), "size": st.st_size, "mtime": st.st_mtime})
        except OSError:
            return []
        out.sort(key=lambda x: x["mtime"])
        for x in out:
            del x["mtime"]
        return out

    def resolve(self, name: str):
        base = os.path.basename(name)
        if base != name or not PATTERN.match(base):
            return None
        if not any(x["file"] == base for x in self.listing()):
            return None
        return os.path.join(self.folder(), base)

    def remove_listed(self, name: str) -> bool:
        path = self.resolve(name)
        if path is None:
            return False
        try:
            os.unlink(path)
        except OSError:
            return False
        self.sweep_locks()
        return True

    def sweep_locks(self) -> None:
        folder = self.folder()
        live = set()
        try:
            names = os.listdir(folder)
        except OSError:
            return
        for n in names:
            m = PATTERN.match(n)
            if m:
                live.add(m.group("inst"))
        for n in names:
            if n.endswith(".lock"):
                inst = n[:-5]
                if inst != self.instance and inst not in live and not self.instance_alive(inst):
                    try:
                        os.unlink(os.path.join(folder, n))
                    except OSError:
                        pass
