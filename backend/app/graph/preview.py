import json
import math
import os
import struct
import tempfile
import threading
import zlib
from collections import OrderedDict

import numpy as np

from app.graph import docvalues, shapes
from app.graph.values import Arc3, Circle3, Line3, Point3, Polyline3, Shape
from app.services import kernel
from app.solid import scene as base

MAGIC = base.MAGIC
VERSION = base.VERSION
HEADER = base.HEADER
RECORD = base.RECORD
NO_COLOUR = base.NO_COLOUR
FLAG_VISIBLE = base.FLAG_VISIBLE
FLAG_MESHED = base.FLAG_MESHED
FLAG_CLOSED = base.FLAG_CLOSED
FLAG_SELECTED = 8
FLAG_GRAPH = 16
FLAG_POINT = 32
FLAG_CURVE = 64
MAX_ITEMS = 20000
CACHE_ITEMS = 6000
CACHE_BYTES = 400 * 1024 * 1024
SELECTED: dict = {}
CACHE: "OrderedDict" = OrderedDict()
SIZES: dict = {}
LOCK = threading.RLock()


def select(graph_id: str, node_ids) -> None:
    SELECTED[str(graph_id)] = set(str(n) for n in node_ids or [])


def selected_of(graph) -> set:
    got = set(SELECTED.get(str(graph.id), ()))
    view = graph.view if isinstance(graph.view, dict) else {}
    got |= set(str(n) for n in view.get("selected") or [])
    for nid, node in graph.nodes.items():
        if node.extra.get("selected"):
            got.add(nid)
    return got


def colour_word(colour) -> int:
    if colour is None:
        return NO_COLOUR
    return (colour.r << 16) | (colour.g << 8) | colour.b


def circle_points(c: Circle3, segments: int = 96) -> list:
    pts = [c.point_at(i / segments) for i in range(segments)]
    pts.append(pts[0])
    return [(p.x, p.y, p.z) for p in pts]


def arc_points(a: Arc3) -> list:
    n = max(8, int(math.ceil(abs(a.sweep) / (2 * math.pi) * 96)))
    return [(p.x, p.y, p.z) for p in (a.point_at(i / n) for i in range(n + 1))]


def light_lines(value) -> list:
    if isinstance(value, Line3):
        return [[(value.a.x, value.a.y, value.a.z), (value.b.x, value.b.y, value.b.z)]]
    if isinstance(value, Polyline3):
        pts = [(p.x, p.y, p.z) for p in value.points]
        if value.closed and len(pts) > 2:
            pts.append(pts[0])
        return [pts]
    if isinstance(value, Circle3):
        return [circle_points(value)]
    if isinstance(value, Arc3):
        return [arc_points(value)]
    return []


class Item:
    __slots__ = ("node", "port", "path", "index", "kind", "value", "name", "layer", "colour", "selected", "lines", "mesh", "point")

    def __init__(self, node, port, path, index, value, selected):
        att = docvalues.attributes_of(value)
        self.node, self.port, self.path, self.index = node, port, str(path), index
        self.value = docvalues.unwrap(value)
        self.name, self.layer, self.colour = att["name"], att["layer"], att["colour"]
        self.selected = selected
        self.kind = ""
        self.lines = []
        self.mesh = None
        self.point = None


def gather(graph, selected: set) -> list:
    items = []
    with graph.lock:
        for nid, node in graph.nodes.items():
            if not node.enabled or not node.preview or node.state != "computed":
                continue
            for port, tree in (node.outputs or {}).items():
                for path, row in tree.items():
                    for i, v in enumerate(row):
                        geo = docvalues.unwrap(v)
                        if isinstance(geo, (Point3, Line3, Polyline3, Circle3, Arc3, Shape)):
                            if isinstance(geo, Shape) and geo.kind == "docref":
                                continue
                            items.append(Item(nid, port, path, i, v, nid in selected))
                if len(items) >= MAX_ITEMS:
                    break
    return items[:MAX_ITEMS]


def fill(items: list, graph=None) -> list:
    pending = {}
    notes = []
    stale = False
    for it in items:
        v = it.value
        if isinstance(v, Point3):
            it.kind = "point"
            it.point = (v.x, v.y, v.z)
        elif isinstance(v, Shape):
            if shapes.serial_of(v.sid) != shapes.current_serial():
                if not stale:
                    notes.append("The kernel restarted; the graph is solving again.")
                stale = True
                continue
            it.kind = v.kind
            pending.setdefault((v.sid, v.kind), []).append(it)
        else:
            it.kind = "curve"
            it.lines = light_lines(v)
    misses = {}
    for key, its in pending.items():
        hit = CACHE.get(key)
        if hit is None:
            misses[key] = its
            continue
        CACHE.move_to_end(key)
        for it in its:
            it.lines, it.mesh = hit
    if misses:
        load_shapes(misses, notes)
    if stale and graph is not None:
        shapes.recover(graph)
    return notes


def remember(key, lines, mesh, size: int) -> None:
    with LOCK:
        CACHE[key] = (lines, mesh)
        SIZES[key] = size
        while len(CACHE) > CACHE_ITEMS or sum(SIZES.values()) > CACHE_BYTES:
            old, _v = CACHE.popitem(last=False)
            SIZES.pop(old, None)


def load_shapes(pending: dict, notes: list) -> None:
    jobs = []
    for (sid, kind), its in pending.items():
        jobs.append({"sid": shapes.unwrap(sid), "kind": "curve" if kind == "curve" else "mesh", "_key": (sid, kind)})
    with tempfile.TemporaryDirectory(prefix="fcgraph_") as tmp:
        try:
            res = kernel.call("graph_preview", {"dir": tmp, "items": [{k: v for k, v in j.items() if k != "_key"} for j in jobs]}, 60.0 + 0.05 * len(jobs))
        except Exception as err:
            notes.append(str(err) or "The kernel did not answer.")
            return
        for job, got in zip(jobs, res.get("results") or []):
            its = pending[job["_key"]]
            if "error" in got:
                notes.append(got["error"])
                continue
            if "polyline" in got:
                lines = [[tuple(q) for q in got["polyline"]]]
                for it in its:
                    it.lines = lines
                remember(job["_key"], lines, None, 24 * len(lines[0]))
                continue
            try:
                with open(got["path"], "rb") as fh:
                    data = fh.read()
                parsed = base.parse(data)
            except Exception as err:
                notes.append(str(err))
                continue
            for it in its:
                it.mesh = parsed
            remember(job["_key"], [], parsed, len(data))


def sections_for(it: Item, scale: float):
    if it.mesh is not None:
        m = it.mesh
        pos = (m["pos"] / np.float32(scale)).astype("<f4")
        epos = (m["epos"] / np.float32(scale)).astype("<f4")
        faces = m["faces"].copy()
        faces[:, 0] = np.arange(1, m["nf"] + 1, dtype="<u4")
        edges = m["edges"].copy()
        edges[:, 0] = np.arange(1, m["ne"] + 1, dtype="<u4")
        return {"pos": pos, "nor": m["nor"], "idx": m["idx"], "tri_face": m["tri_face"], "faces": faces, "edges": edges, "epos": epos, "snaps": np.zeros(0, dtype=base.SNAP)}, m["nv"], m["nt"], m["nf"], m["ne"], int(len(epos))
    flat, table = [], []
    first = 0
    for line in it.lines:
        pts = [tuple(c / scale for c in q) for q in line]
        table.append((len(table) + 1, first, len(pts), 8))
        flat.extend(pts)
        first += len(pts)
    if it.point is not None:
        flat = [tuple(c / scale for c in it.point)]
        table = [(1, 0, 1, 8)]
    epos = np.asarray(flat, dtype="<f4").reshape(-1, 3)
    edges = np.asarray(table, dtype="<u4").reshape(-1, 4)
    empty_u = np.zeros(0, dtype="<u4")
    empty_f = np.zeros((0, 3), dtype="<f4")
    return {"pos": empty_f, "nor": empty_f, "idx": empty_u, "tri_face": empty_u, "faces": np.zeros((0, 4), dtype="<u4"), "edges": edges, "epos": epos, "snaps": np.zeros(0, dtype=base.SNAP)}, 0, 0, 0, len(table), int(len(epos))


def pack(items: list, scale: float, rev: int, notes: list) -> bytes:
    body = bytearray()
    records, strings = [], []
    base_at = HEADER + len(items) * RECORD
    for i, it in enumerate(items):
        flags = FLAG_VISIBLE | FLAG_GRAPH | (FLAG_SELECTED if it.selected else 0)
        if it.kind == "brep":
            flags |= FLAG_CLOSED
        if it.kind == "point":
            flags |= FLAG_POINT
        if it.kind == "curve":
            flags |= FLAG_CURVE
        strings.append({"handle": i + 1, "name": it.name, "layer": it.layer, "source": "graph", "node": it.node, "port": it.port, "path": it.path, "index": it.index, "kind": it.kind, "selected": bool(it.selected)})
        if it.mesh is None and not it.lines and it.point is None:
            records.append(struct.pack("<32I", i + 1, 1, flags & ~FLAG_VISIBLE, colour_word(it.colour), *([0] * 20), i, *([0] * 7)))
            continue
        sec, nv, nt, nf, ne, npts = sections_for(it, scale)
        flags |= FLAG_MESHED
        offs = {}
        for name in ("pos", "nor", "idx", "tri_face", "faces", "edges", "epos", "snaps"):
            base.pad4(body)
            offs[name] = base_at + len(body)
            body.extend(np.ascontiguousarray(sec[name]).tobytes())
        pts = sec["pos"] if nv else sec["epos"]
        if len(pts):
            lo, hi = pts.min(axis=0), pts.max(axis=0)
            box = [float(c) for c in (*lo, *hi)]
        else:
            box = [0.0] * 6
        records.append(struct.pack("<18I6f8I", i + 1, 1, flags, colour_word(it.colour), nv, nt, nf, ne, npts, 0, offs["pos"], offs["nor"], offs["idx"], offs["tri_face"], offs["faces"], offs["edges"], offs["epos"], offs["snaps"], *box, i, 0, 0, 0, 0, 0, 0, 0))
    base.pad4(body)
    meta = json.dumps({"bodies": strings, "mm_per_unit": scale, "detail": 1.0, "rev": rev, "graph": True, "notes": notes[:20]}, separators=(",", ":")).encode("utf-8")
    meta += b" " * ((4 - len(meta) % 4) % 4)
    table = b"".join(records)
    strings_at = base_at + len(body)
    payload = table + bytes(body) + meta
    total = HEADER + len(payload)
    crc = zlib.crc32(payload) & 0xFFFFFFFF
    head = struct.pack("<13IfII", MAGIC, VERSION, HEADER, total, rev, len(items), 0, 0, HEADER, HEADER + len(table), strings_at, len(meta), crc, scale, 0, 0)
    return head + payload


def scene(doc, graph) -> bytes:
    from app.param.units import mm_per_unit

    d = doc.drawing if doc is not None else None
    scale = float(mm_per_unit(d)) if d is not None else 1.0
    items = gather(graph, selected_of(graph))
    notes = fill(items, graph)
    items = [it for it in items if it.mesh is not None or it.lines or it.point is not None]
    return pack(items, scale, int(graph.rev), notes)
