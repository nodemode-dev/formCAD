import io
import uuid
import zipfile
from xml.sax.saxutils import escape, quoteattr

from app.additive import placement, slicing
from app.meshes.threemf import CORE_NS, MODEL_REL

PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NAMESPACE = uuid.UUID("5b1f0c0e-6d3a-4a53-9e1f-0b4c8a1f3d21")


def write_plate(parts: list, items: list, bed, title: str, plate_id: str) -> bytes:
    by_handle = {p.handle: p for p in parts}
    out = io.StringIO()
    out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    out.write('<model unit="millimeter" xml:lang="en-US" xmlns="%s" xmlns:p="%s">\n' % (CORE_NS, PROD_NS))
    out.write('<metadata name="Title">%s</metadata>\n<metadata name="Application">FormCAD</metadata>\n' % escape(title))
    out.write('<metadata name="PlateSize">%g x %g mm</metadata>\n<metadata name="Plate">%s</metadata>\n<resources>\n' % (bed[0], bed[1], escape(plate_id)))
    ids = {}
    for p in parts:
        if p.handle in ids or not len(p.t):
            continue
        oid = len(ids) + 1
        ids[p.handle] = oid
        wv, wt = slicing.weld(p.v, p.t)
        p = type(p)(p.handle, p.name, p.version, wv, wt)
        out.write('<object id="%d" type="model" name=%s p:UUID="%s"><mesh><vertices>\n' % (oid, quoteattr(str(p.name)[:120]), uuid.uuid5(NAMESPACE, "%s/%d" % (plate_id, p.handle))))
        out.write("".join('<vertex x="%.9g" y="%.9g" z="%.9g"/>\n' % (a, b, c) for a, b, c in p.v))
        out.write("</vertices><triangles>\n")
        out.write("".join('<triangle v1="%d" v2="%d" v3="%d"/>\n' % (a, b, c) for a, b, c in p.t))
        out.write("</triangles></mesh></object>\n")
    out.write('</resources>\n<build p:UUID="%s">\n' % uuid.uuid5(NAMESPACE, plate_id))
    for k, it in enumerate(items):
        p = by_handle.get(int(it["body"]))
        if p is None or p.handle not in ids:
            continue
        _v, m = placement.transform(p.v, it)
        nums = list(m[:3, :3].T.reshape(-1)) + list(m[:3, 3])
        out.write('<item objectid="%d" transform="%s" partnumber=%s p:UUID="%s"/>\n' % (ids[p.handle], " ".join("%.9g" % x for x in nums), quoteattr("%s-%d" % (str(p.name)[:60], k + 1)), uuid.uuid5(NAMESPACE, "%s/item/%d" % (plate_id, k))))
    out.write("</build>\n</model>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?>\n<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        zf.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?>\n<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="%s"/></Relationships>' % MODEL_REL)
        zf.writestr("3D/3dmodel.model", out.getvalue())
    return buf.getvalue()
