import io
import re
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from app.meshes.core import Mesh, MeshError

CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
MATERIAL_NS = "http://schemas.microsoft.com/3dmanufacturing/material/2015/02"
MODEL_REL = "http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"
UNIT_MM = {"micron": 0.001, "millimeter": 1.0, "centimeter": 10.0, "inch": 25.4, "foot": 304.8, "meter": 1000.0}
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_PARTS = 64
MAX_OBJECTS = 20000
MAX_TRIANGLES = 20_000_000
MAX_DEPTH = 24


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


def read_3mf(data: bytes) -> tuple:
    if len(data) > MAX_ARCHIVE:
        raise MeshError("The file is larger than the 512 MB limit.")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise MeshError("The file is not a valid 3MF archive.")
    infos = zf.infolist()
    if len(infos) > 4096 or sum(i.file_size for i in infos) > MAX_ARCHIVE or any(i.file_size > MAX_ARCHIVE // 2 for i in infos):
        raise MeshError("The 3MF archive is larger than the limits allow.")
    path = None
    if "_rels/.rels" in zf.namelist():
        rels = parse_xml(zf.read("_rels/.rels"))
        for r in rels:
            if r.get("Type") == MODEL_REL:
                path = (r.get("Target") or "").lstrip("/")
                break
    if not path or path not in zf.namelist():
        cands = [n for n in zf.namelist() if n.lower().endswith(".model")]
        if not cands:
            raise MeshError("The 3MF archive holds no model part.")
        path = cands[0]
    root = parse_xml(zf.read(path))
    unit = root.get("unit") or "millimeter"
    if unit not in UNIT_MM:
        raise MeshError('The 3MF unit "%s" is not one of the unit names of the specification.' % unit)
    scale = UNIT_MM[unit]
    notes, warns = [], []
    ns = root.tag.split("}")[0] + "}" if "}" in root.tag else ""
    required = root.get("requiredextensions")
    if required:
        warns.append("The file requires extensions this reader does not implement (%s); only the core geometry is read." % required)
    resources = None
    build = None
    for ch in root:
        if local(ch.tag) == "resources":
            resources = ch
        elif local(ch.tag) == "build":
            build = ch
    if resources is None or build is None:
        raise MeshError("The 3MF model has no resources or no build section.")
    materials = {}
    for res in resources:
        t = local(res.tag)
        if t == "basematerials":
            materials[res.get("id")] = [parse_color(b.get("displaycolor")) for b in res if local(b.tag) == "base"]
        elif t == "colorgroup":
            materials[res.get("id")] = [parse_color(c.get("color")) for c in res if local(c.tag) == "color"]
    objects = {}
    count = 0
    for res in resources:
        if local(res.tag) != "object":
            continue
        count += 1
        if count > MAX_OBJECTS:
            raise MeshError("The 3MF file holds more than %d objects." % MAX_OBJECTS)
        obj = {"name": res.get("name") or "", "type": res.get("type") or "model", "pid": res.get("pid"), "pindex": res.get("pindex"), "mesh": None, "components": []}
        for ch in res:
            t = local(ch.tag)
            if t == "mesh":
                verts, tris, tprops = [], [], []
                for sub in ch:
                    if local(sub.tag) == "vertices":
                        try:
                            verts = [(float(v.get("x")), float(v.get("y")), float(v.get("z"))) for v in sub]
                        except (TypeError, ValueError):
                            raise MeshError("A 3MF vertex holds a value that is not a number.")
                    elif local(sub.tag) == "triangles":
                        try:
                            for tr in sub:
                                tris.append((int(tr.get("v1")), int(tr.get("v2")), int(tr.get("v3"))))
                                tprops.append((tr.get("pid"), tr.get("p1")))
                        except (TypeError, ValueError):
                            raise MeshError("A 3MF triangle holds an index that is not a number.")
                if len(tris) > MAX_TRIANGLES:
                    raise MeshError("The 3MF file holds more than %d triangles." % MAX_TRIANGLES)
                if verts and tris:
                    obj["mesh"] = (np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int64), tprops)
            elif t == "components":
                for c in ch:
                    if local(c.tag) == "component":
                        if any(k.endswith("}path") for k in c.attrib):
                            warns.append("A component refers to another model part (production extension); it is skipped.")
                            continue
                        obj["components"].append((c.get("objectid"), matrix_of(c.get("transform"))))
        objects[res.get("id")] = obj

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
            if t.min() < 0 or t.max() >= len(v):
                raise MeshError("A 3MF triangle refers to a vertex that does not exist.")
            w = (np.c_[v, np.ones(len(v))] @ mat.T)[:, :3]
            tt = t.copy()
            if np.linalg.det(mat[:3, :3]) < 0:
                tt = tt[:, ::-1]
            found.append({"name": obj["name"], "mesh": Mesh(w * scale, tt), "rgb": colour_of(obj, tp), "type": obj["type"]})
        for cid, cm in obj["components"]:
            found.extend(flatten(cid, mat @ cm, depth + 1, trail | {oid}))
        return found

    parts = []
    for item in build:
        if local(item.tag) != "item":
            continue
        parts.extend(flatten(item.get("objectid"), matrix_of(item.get("transform")), 0, frozenset()))
        if len(parts) > MAX_OBJECTS:
            raise MeshError("The 3MF file builds more than %d bodies." % MAX_OBJECTS)
    if not parts:
        raise MeshError("The 3MF file builds no geometry.")
    for p in parts:
        if p["type"] not in ("model", "solidsupport"):
            notes.append("Object \"%s\" is of type %s (not a printed body)." % (p["name"], p["type"]))
    return parts, {"unit": unit, "unit_mm": scale, "notes": notes, "warnings": warns, "path": path, "build_items": len(parts)}
