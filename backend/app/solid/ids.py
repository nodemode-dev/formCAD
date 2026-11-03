MAX_LINEAGE = 200000


def next_pid(drawing) -> int:
    cur = getattr(drawing, "pid_next", 0)
    if not cur:
        top = 0
        for e in drawing.ents.values():
            if e.kind in ("solidbody", "meshbody"):
                top = max([top, *e.face_ids, *e.edge_ids] if (e.face_ids or e.edge_ids) else [top])
        cur = top + 1
    drawing.pid_next = cur + 1
    return cur


def mint(drawing, count: int) -> list:
    return [next_pid(drawing) for _ in range(count)]


def inherit_kind(drawing, count: int, parts: list, key: str, lineage: dict) -> list:
    out = [0] * count
    for old_ids, history in parts:
        rows = (history or {}).get(key) or {}
        for old_text in sorted(rows, key=lambda t: int(t)):
            old = int(old_text)
            if old >= len(old_ids):
                continue
            row = rows[old_text]
            for rank, new in enumerate(row.get("to") or []):
                if not 0 <= new < count or out[new]:
                    continue
                if rank == 0:
                    out[new] = old_ids[old]
                else:
                    out[new] = next_pid(drawing)
                    if len(lineage) < MAX_LINEAGE:
                        lineage[str(out[new])] = old_ids[old]
    for i, v in enumerate(out):
        if not v:
            out[i] = next_pid(drawing)
    return out


def inherit(drawing, nfaces: int, nedges: int, parts: list, lineage: dict | None = None):
    lin = dict(lineage or {})
    faces = inherit_kind(drawing, nfaces, [(f, h) for f, _e, h in parts], "faces", lin)
    edges = inherit_kind(drawing, nedges, [(e, h) for _f, e, h in parts], "edges", lin)
    return faces, edges, lin


def fresh(drawing, nfaces: int, nedges: int):
    return mint(drawing, nfaces), mint(drawing, nedges)
