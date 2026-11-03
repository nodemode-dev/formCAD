import array
import io
import zipfile
import zlib
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from app.core import guard
from app.meshes.core import Mesh, MeshError

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL_NS = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}
MAX_PARTS = 64
MAX_OBJECTS = 20000
MAX_DEPTH = 24
MAX_RATIO = 200
MAX_ENTRIES = 4096
MAX_RESOURCE_ITEMS = 200000
WINDOW_LIMITS = {"archive": 256 << 20, "member": 64 << 20, "vertices": 4_000_000, "triangles": 4_000_000, "instances": 4_000_000, "bodies": MAX_OBJECTS, "who": ""}
AGENT_LIMITS = {"archive": 32 << 20, "member": 16 << 20, "vertices": 500_000, "triangles": 1_000_000, "instances": 1_000_000, "bodies": 500, "who": " for a macro or agent"}


def limits():
    return AGENT_LIMITS if guard.CALLER.get() else WINDOW_LIMITS


class CappedStream:
    def __init__(self, src, cap, what, check_doctype=False):
        self.src, self.cap, self.what, self.read_bytes, self.check_doctype = src, cap, what, 0, check_doctype

    def read(self, n=-1):
        data = self.src.read(65536 if n is None or n < 0 else min(n, 65536))
        if self.check_doctype and data:
            self.check_doctype = False
            low = data.lower()
            if b"<!doctype" in low or b"<!entity" in low:
                raise MeshError("The 3MF model uses an XML declaration that is refused for safety.")
        self.read_bytes += len(data)
        if self.read_bytes > self.cap:
            raise MeshError("The 3MF %s expands beyond %d MB; it is refused." % (self.what, self.cap >> 20))
        return data


def hex_color(rgb):
    return "#%02X%02X%02X" % tuple(max(0, min(255, round(float(x) * 255.0))) for x in rgb)


def write_3mf(parts: list, unit: str = "millimeter", title: str = "FormCAD") -> bytes:
    if unit not in UNIT_MM:
        raise MeshError("The 3MF unit is micron, millimeter, centimeter, inch, foot or meter.")
    palette = []
    for p in parts:
        rgb = p.get("rgb")
        key = hex_color(rgb) if rgb else None
        p["_key"] = key
        if key and key not in palette:
            palette.append(key)
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write('<model unit="%s" xml:lang="en-US" xmlns="%s" xmlns:m="%s">\n' % (unit, CORE_NS, MATERIAL_NS))
    out.write('<metadata name="Title">%s</metadata>\n<metadata name="Application">FormCAD</metadata>\n<resources>\n' % escape(title))
    pid = 1
    if palette:
        out.write('<basematerials id="1">\n')
        for i, key in enumerate(palette):
            out.write('<base name="Colour %d" displaycolor="%sFF"/>\n' % (i + 1, key))
        out.write("</basematerials>\n")
        pid = 2
    ids = []
    scale = 1.0 / UNIT_MM[unit]
    for p in parts:
        m = p["mesh"]
        if not len(m.t):
            continue
        attrs = 'id="%d" type="model" name=%s' % (pid, quoteattr(str(p.get("name") or "Body")[:120]))
        if p["_key"]:
            attrs += ' pid="1" pindex="%d"' % palette.index(p["_key"])
        out.write("<object %s><mesh><vertices>\n" % attrs)
        v = m.v * scale
        out.write("".join('<vertex x="%.12g" y="%.12g" z="%.12g"/>\n' % (a, b, c) for a, b, c in v))
        out.write("</vertices><triangles>\n")
        out.write("".join('<triangle v1="%d" v2="%d" v3="%d"/>\n' % (a, b, c) for a, b, c in m.t))
        out.write("</triangles></mesh></object>\n")
        ids.append(pid)
        pid += 1
    if not ids:
        raise MeshError("There are no triangles to write.")
    out.write("</resources>\n<build>\n")
    out.write("".join('<item objectid="%d"/>\n' % i for i in ids))
    out.write("</build>\n</model>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="%s"/></Relationships>' % MODEL_REL)
        zf.writestr("3D/3dmodel.model", out.getvalue())
    return buf.getvalue()


def local(tag):
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def parse_xml(data: bytes):
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data[:65536].lower():
        raise MeshError("The 3MF model uses an XML declaration that is refused for safety.")
    try:
        return ET.fromstring(data)
    except ET.ParseError as err:
        raise MeshError("The 3MF model is not valid XML (%s)." % err)


def matrix_of(text):
    if not text:
        return np.eye(4)
    try:
        v = [float(x) for x in text.split()]
    except ValueError:
        raise MeshError("A 3MF transform holds a value that is not a number.")
    if len(v) != 12:
        raise MeshError("A 3MF transform holds twelve numbers.")
    m = np.eye(4)
    m[:3, :3] = np.array(v[:9]).reshape(3, 3).T
    m[:3, 3] = v[9:12]
    return m


def parse_color(text):
    t = str(text or "").strip().lstrip("#")
    if len(t) in (6, 8):
        try:
            return [round(int(t[i:i + 2], 16) / 255.0, 4) for i in (0, 2, 4)]
        except ValueError:
            return None
    return None


def member_bytes(zf, info, cap):
    if info.file_size > cap:
        raise MeshError("A 3MF part is larger than %d MB; it is refused." % max(1, cap >> 20))
    stream = CappedStream(zf.open(info), cap, "part")
    chunks = []
    while True:
        d = stream.read()
        if not d:
            break
        chunks.append(d)
    return b"".join(chunks)


def parse_model(stream, lim, warns):
    root_attrs = None
    stack = []
    materials, objects, build_items = {}, {}, []
    group = None
    cur = None
    seen = {"resources": False, "build": False}
    nverts = ntris = nitems = 0
    try:
        for event, el in ET.iterparse(stream, events=("start", "end")):
            tag = local(el.tag)
            if event == "start":
                stack.append(el)
                if root_attrs is None:
                    root_attrs = dict(el.attrib)
                elif tag == "object":
                    if len(objects) >= MAX_OBJECTS:
                        raise MeshError("The 3MF file holds more than %d objects." % MAX_OBJECTS)
                    cur = {"name": el.get("name") or "", "type": el.get("type") or "model", "pid": el.get("pid"), "pindex": el.get("pindex"), "v": array.array("d"), "t": array.array("q"), "props": set(), "mesh": None, "components": []}
                elif tag in ("basematerials", "colorgroup"):
                    group = []
                continue
            stack.pop()
            parent = stack[-1] if stack else None
            if tag == "vertex" and cur is not None:
                nverts += 1
                if nverts > lim["vertices"]:
                    raise MeshError("The 3MF file holds more than %d vertices%s." % (lim["vertices"], lim["who"]))
                try:
                    cur["v"].extend((float(el.get("x")), float(el.get("y")), float(el.get("z"))))
                except (TypeError, ValueError):
                    raise MeshError("A 3MF vertex holds a value that is not a number.")
            elif tag == "triangle" and cur is not None:
                ntris += 1
                if ntris > lim["triangles"]:
                    raise MeshError("The 3MF file holds more than %d triangles%s." % (lim["triangles"], lim["who"]))
                try:
                    cur["t"].extend((int(el.get("v1")), int(el.get("v2")), int(el.get("v3"))))
                except (TypeError, ValueError, OverflowError):
                    raise MeshError("A 3MF triangle holds an index that is not a number.")
                if len(cur["props"]) < 1024:
                    cur["props"].add((el.get("pid"), el.get("p1")))
            elif tag in ("base", "color") and group is not None:
                nitems += 1
                if nitems > MAX_RESOURCE_ITEMS:
                    raise MeshError("The 3MF file holds more than %d colours." % MAX_RESOURCE_ITEMS)
                group.append(parse_color(el.get("displaycolor") if tag == "base" else el.get("color")))
            elif tag in ("basematerials", "colorgroup") and group is not None:
                materials[el.get("id")] = group
                group = None
            elif tag == "component" and cur is not None:
                nitems += 1
                if nitems > MAX_RESOURCE_ITEMS:
                    raise MeshError("The 3MF file holds more than %d components." % MAX_RESOURCE_ITEMS)
                if any(k.endswith("}path") for k in el.attrib):
                    warns.append("A component refers to another model part (production extension); it is skipped.")
                else:
                    cur["components"].append((el.get("objectid"), matrix_of(el.get("transform"))))
            elif tag == "item" and parent is not None and local(parent.tag) == "build":
                nitems += 1
                if nitems > MAX_RESOURCE_ITEMS:
                    raise MeshError("The 3MF file builds more than %d items." % MAX_RESOURCE_ITEMS)
                build_items.append((el.get("objectid"), matrix_of(el.get("transform"))))
            elif tag == "object" and cur is not None:
                v = np.frombuffer(cur["v"], dtype=np.float64).reshape(-1, 3) if len(cur["v"]) else None
                t = np.frombuffer(cur["t"], dtype=np.int64).reshape(-1, 3) if len(cur["t"]) else None
                if v is not None and t is not None:
                    if not np.isfinite(v).all():
                        raise MeshError("A 3MF vertex holds a value that is not finite.")
                    if t.min() < 0 or t.max() >= len(v):
                        raise MeshError("A 3MF triangle refers to a vertex that does not exist.")
                    cur["mesh"] = (v, t, cur["props"])
                cur["nv"] = len(v) if cur["mesh"] else 0
                cur["nt"] = len(t) if cur["mesh"] else 0
                del cur["v"], cur["t"], cur["props"]
                objects[el.get("id")] = cur
                cur = None
            elif tag in ("resources", "build"):
                seen[tag] = True
            if parent is not None:
                el.clear()
                parent.remove(el)
    except ET.ParseError as err:
        raise MeshError("The 3MF model is not valid XML (%s)." % err)
    if root_attrs is None:
        raise MeshError("The 3MF model is empty.")
    return root_attrs, materials, objects, build_items, seen


def read_3mf(data: bytes) -> tuple:
    lim = limits()
    if len(data) > lim["archive"]:
        raise MeshError("The 3MF file is larger than the %d MB limit%s." % (lim["archive"] >> 20, lim["who"]))
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, EOFError):
        raise MeshError("The file is not a valid 3MF archive.")
    infos = {i.filename: i for i in zf.infolist()}
    if len(zf.infolist()) > MAX_ENTRIES:
        raise MeshError("The 3MF archive is larger than the limits allow.")
    try:
        path = None
        if "_rels/.rels" in infos:
            rels = parse_xml(member_bytes(zf, infos["_rels/.rels"], 1 << 20))
            for r in rels:
                if r.get("Type") == MODEL_REL:
                    path = (r.get("Target") or "").lstrip("/")
                    break
        if not path or path not in infos:
            cands = [n for n in infos if n.lower().endswith(".model")]
            if not cands:
                raise MeshError("The 3MF archive holds no model part.")
            path = cands[0]
        info = infos[path]
        if info.file_size > lim["member"]:
            raise MeshError("The 3MF model part is %d MB when unpacked; the limit is %d MB%s." % (info.file_size >> 20, lim["member"] >> 20, lim["who"]))
        if info.file_size > (1 << 20) and info.compress_size > 0 and info.file_size / info.compress_size > MAX_RATIO:
            raise MeshError("The 3MF model part is compressed %d to 1, which is how an archive bomb looks; it is refused." % (info.file_size // info.compress_size))
        warns = []
        stream = CappedStream(zf.open(info), lim["member"], "model part", True)
        root_attrs, materials, objects, build_items, seen = parse_model(stream, lim, warns)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error):
        raise MeshError("The 3MF archive cannot be unpacked (damaged, encrypted or an unsupported compression).")
    unit = root_attrs.get("unit") or "millimeter"
    if unit not in UNIT_MM:
        raise MeshError('The 3MF unit "%s" is not one of the unit names of the specification.' % unit)
    scale = UNIT_MM[unit]
    notes = []
    required = root_attrs.get("requiredextensions")
    if required:
        warns.append("The file requires extensions this reader does not implement (%s); only the core geometry is read." % required)
    if not seen["resources"] or not seen["build"]:
        raise MeshError("The 3MF model has no resources or no build section.")

    memo = {}

    def weigh(oid, depth, trail):
        if depth > MAX_DEPTH or oid in trail:
            raise MeshError("The 3MF components nest too deeply or loop.")
        if oid in memo:
            return memo[oid]
        obj = objects.get(oid)
        if obj is None:
            raise MeshError("A 3MF item refers to the object %s, which does not exist." % oid)
        tri, vert, bod = obj["nt"], obj["nv"], 1 if obj["mesh"] is not None else 0
        for cid, _cm in obj["components"]:
            a, b, c = weigh(cid, depth + 1, trail | {oid})
            tri, vert, bod = tri + a, vert + b, bod + c
        memo[oid] = (tri, vert, bod)
        return memo[oid]

    total_t = total_v = total_b = 0
    for oid, _m in build_items:
        a, b, c = weigh(oid, 0, frozenset())
        total_t, total_v, total_b = total_t + a, total_v + b, total_b + c
        if total_t > lim["instances"] or total_v > lim["instances"]:
            raise MeshError("The 3MF components build more than %d triangles once every instance is counted%s." % (lim["instances"], lim["who"]))
        if total_b > lim["bodies"]:
            raise MeshError("The 3MF file builds more than %d bodies%s." % (lim["bodies"], lim["who"]))

    def colour_of(obj, tprops):
        pid, pidx = obj["pid"], obj["pindex"]
        if pid in materials and pidx is not None:
            try:
                return materials[pid][int(pidx)]
            except (ValueError, IndexError):
                return None
        used = {(a, b) for a, b in tprops if a is not None and b is not None}
        cols = []
        for a, b in used:
            try:
                c = materials[a][int(b)]
            except (KeyError, ValueError, IndexError):
                continue
            if c and c not in cols:
                cols.append(c)
        if len(cols) == 1:
            return cols[0]
        if len(cols) > 1:
            notes.append("Object \"%s\" uses %d colours; the first is used for the whole body." % (obj["name"], len(cols)))
            return cols[0]
        return None

    def flatten(oid, mat, depth, trail):
        if depth > MAX_DEPTH or oid in trail:
            raise MeshError("The 3MF components nest too deeply or loop.")
        obj = objects.get(oid)
        if obj is None:
            raise MeshError("A 3MF item refers to the object %s, which does not exist." % oid)
        found = []
        if obj["mesh"] is not None:
            v, t, tp = obj["mesh"]
            w = (np.c_[v, np.ones(len(v))] @ mat.T)[:, :3]
            tt = t.copy()
            if np.linalg.det(mat[:3, :3]) < 0:
                tt = tt[:, ::-1]
            found.append({"name": obj["name"], "mesh": Mesh(w * scale, tt), "rgb": colour_of(obj, tp), "type": obj["type"]})
        for cid, cm in obj["components"]:
            found.extend(flatten(cid, mat @ cm, depth + 1, trail | {oid}))
        return found

    parts = []
    for oid, item_matrix in build_items:
        parts.extend(flatten(oid, item_matrix, 0, frozenset()))
    if not parts:
        raise MeshError("The 3MF file builds no geometry.")
    for p in parts:
        if p["type"] not in ("model", "solidsupport"):
            notes.append("Object \"%s\" is of type %s (not a printed body)." % (p["name"], p["type"]))
    return parts, {"unit": unit, "unit_mm": scale, "notes": notes, "warnings": warns, "path": path, "build_items": len(parts)}
