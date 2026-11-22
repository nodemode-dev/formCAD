import threading
import weakref

from app.assembly import parts, refs, store
from app.param.units import mm_per_unit
from app.solid import blobs, work

CHANGED = "It was opened in full instead of lightweight because its file changed after the display copy in this assembly was stored."
_lock = threading.RLock()
_resolved: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def enabled(d) -> bool:
    return bool(store.header(d).get("lightweight", True))


def resolved(d) -> set:
    with _lock:
        got = _resolved.get(d)
        if got is None:
            got = set()
            _resolved[d] = got
        return got


def mark(d, key: str) -> None:
    with _lock:
        resolved(d).add(key)


def usable(host_d, rec: dict, conf: str) -> bool:
    cache = rec.get("cache") or {}
    bodies = cache.get("bodies") or []
    if rec.get("type") != "part" or not bodies or not cache.get("complete", True):
        return False
    if str(conf or "") != str(rec.get("config") or ""):
        return False
    return all(b.get("has_mesh") and blobs.cache_path(str(b.get("blob") or ""), parts.CACHE_TAG) in host_d.blobs for b in bodies)


def matches(real: str, recorded: dict) -> bool:
    if not recorded or not (recorded.get("size") or recorded.get("mtime")):
        return False
    q = refs.quick_sig(real)
    if q is None:
        return False
    if q == (int(recorded.get("size") or 0), int(recorded.get("mtime") or 0)):
        return True
    if not recorded.get("sha256") or q[0] != int(recorded.get("size") or 0):
        return False
    return refs.same_sig(recorded, refs.sig_of(real))


class LightPart(parts.LoadedPart):
    source = "light"

    def __init__(self, host_d, rec: dict, real: str, top, key: str):
        cache = rec.get("cache") or {}
        self.host = host_d
        self.top = top
        self.key = key
        self.label = str(rec.get("label") or key)
        self.path = real
        self.sig = dict(rec.get("sig") or {})
        self.kind = "part"
        self.mm_per_unit = float(cache.get("mmu") or mm_per_unit(host_d))
        self.props = dict(cache.get("props") or {})
        self.configs = list(cache.get("configs") or [])
        self.active_config = str(cache.get("active_config") or "")
        self.variants = {}
        self.bodies = parts.cached_bodies(cache)
        self._full = None

    @property
    def drawing(self):
        return self.full().drawing

    def scan(self) -> None:
        return None

    def full(self) -> parts.LoadedPart:
        if self._full is not None:
            return self._full
        try:
            lp = parts.load(self.path)
        except parts.PartLoadError as err:
            raise work.SolidError("%s could not be loaded in full: %s" % (self.label, err))
        if not refs.same_sig(self.sig, lp.sig):
            raise work.SolidError("The file of %s changed after this assembly was opened; reload the component, then try again." % self.label)
        self._full = lp
        mark(self.top, self.key)
        return lp

    def full_body(self, body):
        lp = self.full()
        for b in lp.bodies:
            if b.blob == body.blob and b.handle == body.handle:
                return lp, b
        for b in lp.bodies:
            if b.blob == body.blob:
                return lp, b
        raise work.SolidError("%s has no body %s in its file; reload the component." % (self.label, body.name))

    def mesh(self, body, detail: float):
        if work.detail_tag(detail) == parts.CACHE_TAG:
            got = self.host.blobs.get(blobs.cache_path(body.blob, parts.CACHE_TAG))
            if got is not None:
                return got
        lp, b = self.full_body(body)
        return lp.mesh(b, detail)

    def shape(self, body) -> str:
        lp, b = self.full_body(body)
        return work.worker_id(lp.drawing, b.ent)


def _targets(doc, cids) -> list:
    from app.assembly import walk

    want = None if cids is None else {str(c) for c in cids}
    out = []
    for inst in walk.instances(doc):
        top = inst.key.split("/", 1)[0].split("#", 1)[0]
        if want is not None and top not in want:
            continue
        out.append(inst)
    return out


def resolve(doc, cids=None) -> dict:
    done, failed = [], []
    for inst in _targets(doc, cids):
        lp = inst.part
        if lp is None or lp.source != "light":
            continue
        try:
            for b in lp.bodies:
                lp.shape(b)
            done.append(inst.key)
        except work.SolidError as err:
            failed.append({"key": inst.key, "message": str(err)})
    return {"resolved": sorted(set(done)), "failed": failed, "lightweight": count(doc)}


def lighten(doc, cids=None) -> dict:
    d = doc.drawing
    with _lock:
        keys = resolved(d)
        if cids is None:
            gone = sorted(keys)
            keys.clear()
        else:
            want = {str(c) for c in cids}
            gone = sorted(k for k in keys if k.split("/", 1)[0].split("#", 1)[0] in want)
            keys.difference_update(gone)
    return {"lightweight": gone, "count": count(doc)}


def count(doc) -> int:
    from app.assembly import walk

    return sum(1 for i in walk.instances(doc) if i.status.get("lightweight"))
