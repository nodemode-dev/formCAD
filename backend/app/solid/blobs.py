import hashlib
import re

PART_DIR = "parts/"
CACHE_DIR = "cache/"
MAX_BLOB = 256 * 1024 * 1024
MAX_BLOBS_TOTAL = 4096
MESH_DIR = "meshes/"
SIM_DIR = "sim/"
NAME = re.compile(r"^(parts/[0-9a-f]{24}\.brep|cache/[0-9a-f]{24}-[0-9a-z.]{1,12}\.mesh|meshes/[0-9a-f]{24}\.fmesh|sim/[0-9a-f]{24}\.npz)$")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:24]


def part_path(blob: str) -> str:
    return "%s%s.brep" % (PART_DIR, blob)


def cache_path(blob: str, tag: str) -> str:
    return "%s%s-%s.mesh" % (CACHE_DIR, blob, tag)


def put_part(drawing, data: bytes) -> str:
    if len(data) > MAX_BLOB:
        raise ValueError("The shape is larger than the 256 MB limit.")
    blob = digest(data)
    drawing.blobs.setdefault(part_path(blob), data)
    return blob


def get_part(drawing, blob: str) -> bytes:
    data = drawing.blobs.get(part_path(blob))
    if data is None:
        raise KeyError("The stored shape %s is missing from the file." % blob)
    return data


def bodies(drawing):
    return [e for e in drawing.ents.values() if e.kind in ("solidbody", "meshbody")]


def kept_copies(drawing) -> set:
    tbl = drawing.tables.get("components")
    if tbl is None:
        return set()
    return {str(b.get("blob")) for r in tbl.values() for b in ((r.get("cache") or {}).get("bodies") or []) if b.get("blob")}


def cage_bases(drawing) -> set:
    out = set()
    for e in drawing.ents.values():
        if e.kind == "solidbody":
            rec = (e.source or {}).get("cage")
            if isinstance(rec, dict) and rec.get("blob"):
                out.add(str(rec["blob"]))
    return out


def container_entries(drawing) -> list:
    if not drawing.blobs:
        return []
    live = {e.blob for e in bodies(drawing)} | kept_copies(drawing) | cage_bases(drawing)
    from app.sim import records as sim_records

    live |= sim_records.blobs_in_use(drawing)
    out = []
    for path, data in drawing.blobs.items():
        if path.startswith(PART_DIR):
            blob = path[len(PART_DIR):-len(".brep")]
        elif path.startswith(MESH_DIR):
            blob = path[len(MESH_DIR):-len(".fmesh")]
        elif path.startswith(SIM_DIR):
            blob = path[len(SIM_DIR):-len(".npz")]
        else:
            blob = path[len(CACHE_DIR):].split("-", 1)[0]
        if blob in live:
            out.append((path, data))
    return out


def read_entries(zf, limit_total: int = 1024 * 1024 * 1024) -> dict:
    out = {}
    total = 0
    for info in zf.infolist():
        name = info.filename
        if name.endswith("/") or not NAME.match(name):
            continue
        if info.file_size > MAX_BLOB or len(out) >= MAX_BLOBS_TOTAL:
            continue
        total += info.file_size
        if total > limit_total:
            break
        out[name] = zf.read(info)
    return out
