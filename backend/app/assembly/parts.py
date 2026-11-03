import copy
import threading
from collections import OrderedDict

from app.assembly import props as P
from app.assembly import refs
from app.doc import container
from app.doc.model import SPACE_MODEL
from app.param.units import mm_per_unit
from app.solid import blobs, work

CACHE_LIMIT = 24
CACHE_TAG = "d1"
_lock = threading.RLock()
_loaded: OrderedDict = OrderedDict()


class PartLoadError(Exception):
    pass


class PartBody:
    def __init__(self, ent):
        self.ent = ent
        self.handle = ent.handle
        self.name = ent.name or "Body%d" % ent.handle
        self.blob = ent.blob
        self.rgb = list(ent.rgb or [])
        self.offset = [float(v) for v in (ent.offset or [0.0, 0.0, 0.0])]
        self.summary = dict(ent.summary or {})
        self.closed = bool(self.summary.get("closed"))
        self.material = ent.material or ""
        self.face_ids = list(ent.face_ids or [])
        self.edge_ids = list(ent.edge_ids or [])
        self.version = ent.version


class LoadedPart:
    source = "file"

    def __init__(self, path, sig, drawing, kind):
        self.path = path
        self.sig = sig
        self.drawing = drawing
        self.kind = kind
        self.mm_per_unit = mm_per_unit(drawing)
        self.bodies = []
        self.props = P.get(drawing)
        self.configs = []
        self.active_config = ""
        self.variants = {}
        self.scan()

    @property
    def is_assembly(self) -> bool:
        return self.kind == "assembly"

    def scan(self) -> None:
        d = self.drawing
        self.bodies = [PartBody(e) for e in d.ordered_entities() if e.kind == "solidbody" and e.owner == SPACE_MODEL and d.visible(e)]
        try:
            from app.bodies import configs as C

            self.configs = [r["name"] for r in C.configs(d)]
            self.active_config = C.active_name(d) if self.configs else ""
        except Exception:
            self.configs = []
            self.active_config = ""

    def mesh(self, body, detail: float):
        return work.mesh_for(self.drawing, body.ent, detail)

    def material_of(self, config: str = "") -> str:
        for b in self.bodies:
            if b.material:
                return b.material
        return ""


class CachedPart(LoadedPart):
    source = "cache"

    def __init__(self, host_drawing, rec):
        cache = rec.get("cache") or {}
        self.host = host_drawing
        self.path = ""
        self.sig = dict(rec.get("sig") or {})
        self.drawing = host_drawing
        self.kind = "part"
        self.mm_per_unit = float(cache.get("mmu") or mm_per_unit(host_drawing))
        self.props = dict(cache.get("props") or {})
        self.configs = list(cache.get("configs") or [])
        self.active_config = str(cache.get("active_config") or "")
        self.variants = {}
        self.bodies = []
        for i, b in enumerate(cache.get("bodies") or []):
            pb = PartBody.__new__(PartBody)
            pb.ent = None
            pb.handle = int(b.get("handle", i))
            pb.name = str(b.get("name") or "Body%d" % i)
            pb.blob = str(b.get("blob") or "")
            pb.rgb = list(b.get("rgb") or [])
            pb.offset = [float(v) for v in (b.get("offset") or [0.0, 0.0, 0.0])]
            pb.summary = {}
            pb.closed = bool(b.get("closed"))
            pb.material = str(b.get("material") or "")
            pb.face_ids = []
            pb.edge_ids = []
            pb.version = 0
            self.bodies.append(pb)

    def scan(self) -> None:
        return None

    def mesh(self, body, detail: float):
        return self.host.blobs.get(blobs.cache_path(body.blob, CACHE_TAG))


class EmbeddedPart(LoadedPart):
    source = "embedded"

    def __init__(self, host_drawing, rec):
        self.cid = rec["id"]
        self.space = (rec.get("embedded") or {}).get("space") or "part:%s" % rec["id"]
        self.path = ""
        self.sig = {}
        self.drawing = host_drawing
        self.kind = "part"
        self.mm_per_unit = mm_per_unit(host_drawing)
        self.props = dict(rec.get("props") or {})
        self.configs = []
        self.active_config = ""
        self.variants = {}
        self.bodies = []
        self.scan()

    def scan(self) -> None:
        d = self.drawing
        self.bodies = [PartBody(d.ents[h]) for h in d.spaces.get(self.space, []) if h in d.ents and d.ents[h].kind == "solidbody"]


def load(path: str) -> LoadedPart:
    real = refs.os.path.realpath(path)
    q = refs.quick_sig(real)
    if q is None:
        raise PartLoadError("The file is not there.")
    key = (real, q[0], q[1])
    with _lock:
        hit = _loaded.get(key)
        if hit is not None:
            _loaded.move_to_end(key)
            return hit
    try:
        d, man = container.load(real)
    except container.ContainerError as err:
        raise PartLoadError(err.message)
    kind = "assembly" if man.get("kind") == "assembly" else "part"
    lp = LoadedPart(real, refs.sig_of(real), d, kind)
    with _lock:
        for k in [k for k in _loaded if k[0] == real]:
            _loaded.pop(k, None)
        _loaded[key] = lp
        while len(_loaded) > CACHE_LIMIT:
            _loaded.popitem(last=False)
    return lp


def forget(path: str = "") -> None:
    with _lock:
        if not path:
            _loaded.clear()
            return
        real = refs.os.path.realpath(path)
        for k in [k for k in _loaded if k[0] == real]:
            _loaded.pop(k, None)


def cache_record(host_drawing, lp: LoadedPart, embed: bool = True, config: str = "") -> dict:
    out = {"bodies": [], "props": copy.deepcopy(lp.props), "configs": list(lp.configs), "active_config": lp.active_config, "mmu": lp.mm_per_unit, "taken": ""}
    if not embed:
        return out
    total = 0
    for b in lp.bodies:
        try:
            raw = lp.mesh(b, 1.0)
        except work.SolidError:
            raw = None
        if raw is not None:
            total += len(raw)
            if total > 64 * 1024 * 1024:
                break
            host_drawing.blobs[blobs.cache_path(b.blob, CACHE_TAG)] = raw
        out["bodies"].append({"handle": b.handle, "name": b.name, "blob": b.blob, "rgb": b.rgb, "offset": b.offset, "closed": b.closed, "material": b.material, "has_mesh": raw is not None})
    return out


def shapes(lp: LoadedPart, body) -> str:
    return work.worker_id(lp.drawing, body.ent)
