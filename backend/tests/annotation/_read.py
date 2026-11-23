import re
import xml.etree.ElementTree as ET
import zlib

from tests.support.dxf import Dxf

MM_PER_PT = 25.4 / 72.0


def dimension_texts(doc, tmp_path, name="dims") -> dict:
    path = tmp_path / ("%s.dxf" % name)
    doc.post("/interchange/export", {"path": str(path), "format": "dxf"})
    dxf = Dxf.read(path)
    owner = {}
    texts: dict = {}
    current = None
    for rec in dxf.sections.get("BLOCKS", []):
        if rec.kind == "BLOCK":
            current = rec.text(2)
        elif rec.kind in ("TEXT", "MTEXT") and current:
            texts.setdefault(current, []).append(rec.text(1))
    for dim in dxf.entities("DIMENSION"):
        owner[round(dim.number(42), 9)] = texts.get(dim.text(2), [])
    return {"by_block": texts, "dimensions": [(round(d.number(42), 9), texts.get(d.text(2), [])) for d in dxf.entities("DIMENSION")], "by_value": owner}


def only_dimension_text(doc, tmp_path, name="dims") -> list:
    found = dimension_texts(doc, tmp_path, name)["dimensions"]
    assert len(found) == 1, found
    return found[0][1]


def plot(engine, doc, kind, request) -> tuple:
    job = doc.post("/plot", {"kind": kind, "request": request})
    assert job["state"] == "done", job
    res = engine.raw("GET", "/api/plot/jobs/%s/result" % job["id"])
    assert res.status_code == 200
    return job, res.content


SVG_NS = "{http://www.w3.org/2000/svg}"


def svg_root(data: bytes):
    return ET.fromstring(data)


def svg_mm(value: str) -> float:
    assert value.endswith("mm"), value
    return float(value[:-2])


def svg_segments(data: bytes) -> list:
    root = svg_root(data)
    height = float(root.get("viewBox").split()[3])
    out = []
    for path in root.iter(SVG_NS + "path"):
        if path.get("fill") not in (None, "none"):
            continue
        d = path.get("d") or ""
        pen = None
        for op, x, y in re.findall(r"([ML])\s*(-?[\d.]+)[ ,](-?[\d.]+)", d):
            pt = (float(x), height - float(y))
            if op == "L" and pen is not None:
                out.append((pen, pt))
            pen = pt
    return out


def pdf_objects(data: bytes) -> list:
    return re.findall(rb"(\d+) 0 obj\s*(.*?)endobj", data, re.S)


def pdf_media_boxes(data: bytes) -> list:
    boxes = []
    for _num, body in pdf_objects(data):
        if re.search(rb"/Type\s*/Page\b", body):
            m = re.search(rb"/MediaBox\s*\[\s*([-\d.\s]+)\]", body)
            boxes.append([float(v) for v in m.group(1).split()])
    return boxes


def pdf_streams(data: bytes) -> list:
    out = []
    for m in re.finditer(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", data, re.S):
        head, raw = m.group(1), m.group(2)
        out.append(zlib.decompress(raw) if b"FlateDecode" in head else raw)
    return out


def pdf_segments(data: bytes) -> list:
    segs = []
    for stream in pdf_streams(data):
        tokens = stream.split()
        stack = []
        ctm = [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
        saved = []
        pen = None
        for tok in tokens:
            try:
                stack.append(float(tok))
                continue
            except ValueError:
                pass
            op = tok.decode("latin-1")
            if op == "q":
                saved.append(list(ctm))
            elif op == "Q" and saved:
                ctm = saved.pop()
            elif op == "cm" and len(stack) >= 6:
                a, b, c, d, e, f = stack[-6:]
                A, B, C, D, E, F = ctm
                ctm = [a * A + b * C, a * B + b * D, c * A + d * C, c * B + d * D, e * A + f * C + E, e * B + f * D + F]
            elif op in ("m", "l") and len(stack) >= 2:
                x, y = stack[-2:]
                pt = (ctm[0] * x + ctm[2] * y + ctm[4], ctm[1] * x + ctm[3] * y + ctm[5])
                if op == "l" and pen is not None:
                    segs.append((pen, pt))
                pen = pt
            stack = []
    return segs


def longest(segments) -> float:
    return max(((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5 for a, b in segments)


def ink_box_mm(pdf_bytes: bytes, dpi: float = 600.0, threshold: int = 128):
    import numpy as np
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(pdf_bytes)
    try:
        page = pdf[0]
        bitmap = page.render(scale=dpi / 72.0, grayscale=True)
        img = np.asarray(bitmap.to_numpy())
        if img.ndim == 3:
            img = img[..., 0]
        ys, xs = np.nonzero(img < threshold)
        px = 25.4 / dpi
        h = img.shape[0]
        return (xs.min() * px, (h - 1 - ys.max()) * px, (xs.max() + 1) * px, (h - ys.min()) * px)
    finally:
        pdf.close()
