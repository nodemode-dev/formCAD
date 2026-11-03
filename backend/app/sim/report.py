import html
import io
import math
import time

import numpy as np

from app.core import outputs
from app.doc import container
from app.output import pdfwrite
from app.output.sheet import Sheet, Style
from app.sim import display, records, study
from app.sim.fem import SimError
from app.text import stroke

MAX_TRIANGLES = 40000
FORMATS = {"html": ".html", "pdf": ".pdf"}


def mesh_display(doc, sid: str) -> dict:
    d = doc.drawing
    row = records.need(d, sid, "study")
    if not row.get("mesh_blob"):
        raise SimError("Study %s has not been meshed yet." % sid)
    model = study.build_model(study.get_blob(d, row["mesh_blob"]))
    nodes = model.nodes_mm
    used, idx = display.surface(nodes, model.tris)
    return {"study": sid, "positions": nodes[used].reshape(-1).tolist(), "indices": idx.reshape(-1).tolist(), "face_ids": [int(v) for v in model.tri_face], "groups": model.meta.get("groups", {}), "nodes": int(len(nodes)), "elements": int(len(model.tets)), "curved": bool(model.curved), "bbox": model.meta.get("bbox"), "info": row.get("mesh_info")}


def rgb_of(rec: dict, t: float) -> tuple:
    stops = rec["stops"]
    t = min(1.0, max(0.0, t))
    for a, b in zip(stops, stops[1:]):
        if t <= b[0] or b is stops[-1]:
            span = max(b[0] - a[0], 1e-12)
            u = min(1.0, max(0.0, (t - a[0]) / span))
            ca = [int(a[1][i : i + 2], 16) for i in (1, 3, 5)]
            cb = [int(b[1][i : i + 2], 16) for i in (1, 3, 5)]
            return tuple(int(round(ca[k] + (cb[k] - ca[k]) * u)) for k in range(3))
    return tuple(int(stops[-1][1][i : i + 2], 16) for i in (1, 3, 5))


def project(points: np.ndarray, azimuth=-35.0, elevation=25.0) -> tuple:
    a, e = math.radians(azimuth), math.radians(elevation)
    rz = np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(e), -math.sin(e)], [0, math.sin(e), math.cos(e)]])
    q = points @ rz.T @ rx.T
    return q[:, 0], q[:, 2], q[:, 1]


def contour_polygons(payload: dict, deformed=True) -> tuple:
    pos = np.array(payload["deformed"] if deformed and payload.get("deformed") else payload["positions"], dtype=float).reshape(-1, 3)
    tri = np.array(payload["indices"], dtype=np.int64).reshape(-1, 3)
    vals = np.array(payload["values"], dtype=float)
    if len(tri) > MAX_TRIANGLES:
        tri = tri[:: int(math.ceil(len(tri) / MAX_TRIANGLES))]
    x, y, depth = project(pos)
    lo, hi = payload["min"], payload["max"]
    span = hi - lo if hi > lo else 1.0
    order = np.argsort(-depth[tri].mean(axis=1))
    polys = []
    for t in tri[order]:
        v = vals[t].mean()
        polys.append(([(float(x[i]), float(y[i])) for i in t], rgb_of(payload["ramp"], (v - lo) / span)))
    return polys, (float(x.min()), float(y.min()), float(x.max()), float(y.max()))


def fmt(v, digits=4):
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return "%.*g" % (digits, v)
    return str(v)


def facts(doc, sid: str) -> dict:
    d = doc.drawing
    srow = records.need(d, sid, "study")
    res = records.get(d, srow["result"], "result") if srow.get("result") else None
    if res is None:
        raise SimError("Study %s has no result to report." % sid)
    mat = records.get(d, srow["material"], "material") if srow.get("material") else None
    return {
        "study": srow,
        "result": res,
        "material": mat,
        "loads": [records.get(d, i, "load") for i in srow.get("loads") or []],
        "fixtures": [records.get(d, i, "fixture") for i in srow.get("fixtures") or []],
        "contacts": [records.get(d, i, "contact") for i in srow.get("contacts") or []],
    }


def key_rows(res: dict) -> list:
    s = res["summary"]
    rows = []
    mapping = (
        ("max_displacement_m", "Maximum displacement", "mm", 1e3),
        ("max_von_mises_pa", "Maximum von Mises stress", "MPa", 1e-6),
        ("max_principal_pa", "Maximum principal stress", "MPa", 1e-6),
        ("min_principal_pa", "Minimum principal stress", "MPa", 1e-6),
        ("safety_factor", "Safety factor against yield", "", 1.0),
        ("min_temperature_k", "Minimum temperature", "K", 1.0),
        ("max_temperature_k", "Maximum temperature", "K", 1.0),
        ("max_flux_w_m2", "Maximum heat flux", "W/m2", 1.0),
        ("critical_load_n", "Critical load", "N", 1.0),
        ("mass_kg", "Mass", "kg", 1.0),
        ("equilibrium_error_n", "Equilibrium error", "N", 1.0),
    )
    for key, label, unit, k in mapping:
        if key in s and s[key] is not None:
            rows.append((label, fmt(s[key] * k), unit))
    if "frequencies_hz" in s:
        for i, f in enumerate(s["frequencies_hz"]):
            rows.append(("Mode %d frequency" % (i + 1), fmt(f, 6), "Hz"))
    if "load_factors" in s:
        for i, f in enumerate(s["load_factors"]):
            rows.append(("Buckling load factor %d" % (i + 1), fmt(f, 6), ""))
    for key, val in (s.get("heat_flow_w") or {}).items():
        rows.append(("Heat flow through fixture %s" % key, fmt(val), "W"))
    for key, val in (s.get("reactions_n") or {}).items():
        rows.append(("Reaction force at fixture %s" % key, ", ".join(fmt(v) for v in val), "N"))
    cnt = s.get("counts") or {}
    if cnt:
        rows.append(("Mesh", "%s nodes, %s elements, %s unknowns" % (cnt.get("nodes"), cnt.get("elements"), cnt.get("dofs")), ""))
    sol = s.get("solver") or {}
    if sol:
        rows.append(("Solver", "%s%s" % (sol.get("method", ""), (", residual %s" % fmt(sol["residual"], 3)) if "residual" in sol else ""), ""))
    return rows


def source_of(mat: dict, key: str):
    for x in mat.get("sources", []):
        if x.get("field") == key:
            return x
    return next((x for x in mat.get("sources", []) if x.get("field") == "all"), None)


def describe_load(r: dict) -> str:
    parts = [r["type"].replace("_", " ")]
    for key in ("value", "direction", "vector", "h", "t_inf"):
        if key in r:
            parts.append("%s %s" % (key, r[key]))
    return ", ".join(str(p) for p in parts)


def build_html(f: dict, payload: dict, title: str) -> str:
    esc = html.escape
    polys, box = contour_polygons(payload)
    w, h = box[2] - box[0], box[3] - box[1]
    pad = 0.04 * max(w, h, 1e-9)
    svg = []
    for pts, rgb in polys:
        svg.append('<polygon points="%s" fill="rgb(%d,%d,%d)" stroke="rgb(%d,%d,%d)" stroke-width="%.4f"/>' % (" ".join("%.3f,%.3f" % (p[0], -p[1]) for p in pts), *rgb, *rgb, pad * 0.05))
    view = "%.3f %.3f %.3f %.3f" % (box[0] - pad, -box[3] - pad, w + 2 * pad, h + 2 * pad)
    stops = payload["ramp"]["stops"]
    bar = "linear-gradient(to right, %s)" % ", ".join("%s %d%%" % (c, round(t * 100)) for t, c in stops)
    s, res, mat = f["study"], f["result"], f["material"]
    rows = "".join("<tr><th>%s</th><td>%s %s</td></tr>" % (esc(a), esc(b), esc(c)) for a, b, c in key_rows(res))
    mrows = ""
    if mat:
        for k in records.MATERIAL_FIELDS:
            if mat.get(k) is not None:
                src = source_of(mat, k)
                mrows += "<tr><th>%s</th><td>%s</td><td>%s</td></tr>" % (k, fmt(mat[k]), esc(("%s, %s %s" % (src["org"], src["title"], src["url"])).strip() if src else "no source recorded"))
    lrows = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(r["id"]), esc(describe_load(r))) for r in f["loads"] if r)
    xrows = "".join("<tr><th>%s</th><td>%s</td></tr>" % (esc(r["id"]), esc(r["type"] + (", axis %s" % r["axis"] if "axis" in r else ""))) for r in f["fixtures"] if r)
    unit = payload["display_unit"]
    k = payload["display_factor"]
    css = "body{font-family:Inter,Arial,sans-serif;max-width:900px;margin:24px auto;color:#1a1a1a}h1{font-size:22px}h2{font-size:16px;margin-top:24px}table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ddd;padding:4px 8px;text-align:left;font-size:13px}th{width:34%;font-weight:600}.bar{height:14px;border:1px solid #888}.scale{display:flex;justify-content:space-between;font-size:12px}svg{width:100%;height:auto;background:#fff;border:1px solid #ddd}.note{font-size:12px;color:#555}"
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>%s</title><style>%s</style></head><body><h1>%s</h1>"
        "<p class=\"note\">Study %s (%s), result %s, created %s. Generated %s.</p>"
        "<h2>Results</h2><table>%s</table>"
        "<h2>%s (%s)</h2><svg viewBox=\"%s\" xmlns=\"http://www.w3.org/2000/svg\">%s</svg><div class=\"bar\" style=\"background:%s\"></div><div class=\"scale\"><span>%s %s</span><span>%s %s</span></div>"
        "<p class=\"note\">Deformed shape drawn at %s times the real displacement. Contours are element averages drawn per surface triangle; maxima in the table come from the quadrature points.</p>"
        "<h2>Material</h2><table>%s</table>"
        "<h2>Loads</h2><table>%s</table><h2>Fixtures</h2><table>%s</table></body></html>"
    ) % (esc(title), css, esc(title), esc(s["id"]), esc(s["type"]), esc(res["id"]), esc(res.get("created", "")), esc(time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())), rows, esc(payload["label"]), esc(unit), view, "".join(svg), bar, fmt(payload["min"] * k), esc(unit), fmt(payload["max"] * k), esc(unit), fmt(payload["scale"]), mrows or "<tr><td>No material</td></tr>", lrows or "<tr><td>None</td></tr>", xrows or "<tr><td>None</td></tr>")


class Page:
    def __init__(self, width=210.0, height=297.0):
        self.sheet = Sheet("Report", width, height, [10, 10, width - 10, height - 10])
        self.layer = self.sheet.layer("Report")
        self.font = stroke.default()
        self.y = height - 18.0
        self.width = width
        self.black = Style((20, 20, 20), 1.0, 0.18, 1, 1, None, self.layer)

    def text(self, s: str, x: float, y: float, h: float = 3.2, style=None) -> float:
        st = style or self.black
        cx = x
        for ch in s:
            g = self.font.glyph(ch) or (self.font.glyph("?") if ch != " " else None)
            if g is None:
                cx += h * 0.6
                continue
            for pts in g.strokes or []:
                self.sheet.stroke([(cx + p[0] * h, y + p[1] * h) for p in pts], False, st)
            cx += g.adv * h
        return cx

    def line(self, s: str, h: float = 3.2, indent: float = 12.0, gap: float = 1.9) -> None:
        self.text(s, indent, self.y, h)
        self.y -= h + gap


def build_pdf(f: dict, payload: dict, title: str) -> bytes:
    res, s, mat = f["result"], f["study"], f["material"]
    page = Page()
    page.line(title, 6.0, gap=3.0)
    page.line("Study %s (%s), result %s, %s" % (s["id"], s["type"], res["id"], res.get("created", "")), 3.0, gap=3.0)
    for label, value, unit in key_rows(res)[:26]:
        page.line("%s: %s %s" % (label, value, unit), 3.2)
    page.y -= 3.0
    polys, box = contour_polygons(payload)
    w, h = max(box[2] - box[0], 1e-9), max(box[3] - box[1], 1e-9)
    area = (186.0, min(page.y - 40.0, 110.0))
    k = min(area[0] / w, area[1] / h)
    ox = 12.0 + (area[0] - w * k) / 2.0
    top = page.y
    oy = top - h * k - 2.0
    for pts, rgb in polys:
        st = Style(rgb, 1.0, 0.05, 1, 1, None, page.layer)
        ring = [(ox + (p[0] - box[0]) * k, oy + (p[1] - box[1]) * k) for p in pts]
        page.sheet.fill([ring], st, False)
        page.sheet.stroke(ring, True, st)
    page.y = oy - 8.0
    unit, kf = payload["display_unit"], payload["display_factor"]
    page.line("%s (%s): from %s to %s" % (payload["label"], unit, fmt(payload["min"] * kf), fmt(payload["max"] * kf)), 3.2)
    for i in range(60):
        t = i / 59.0
        x0 = 12.0 + t * 120.0
        st = Style(rgb_of(payload["ramp"], t), 1.0, 0.05, 1, 1, None, page.layer)
        page.sheet.fill([[(x0, page.y - 4), (x0 + 2.1, page.y - 4), (x0 + 2.1, page.y), (x0, page.y)]], st, False)
    page.y -= 10.0
    if mat:
        page.line("Material %s" % (mat.get("label") or mat["id"]), 3.4)
        for key in records.MATERIAL_FIELDS:
            if mat.get(key) is not None:
                src = source_of(mat, key)
                page.line("%s %s   %s" % (key, fmt(mat[key]), ("(%s)" % src["org"]) if src else "(no source recorded)"), 2.8, gap=1.4)
    return pdfwrite.render([page.sheet], title=title)


def write(doc, sid: str, path: str, fmt_name: str = "html", title: str | None = None) -> dict:
    kind = str(fmt_name or "html").lower()
    if kind not in FORMATS:
        raise SimError("A report is written as html or pdf.")
    f = facts(doc, sid)
    payload = display.show(doc, sid)
    name = title or "Simulation report, study %s" % f["study"]["id"]
    dest = outputs.checked(path, tuple(FORMATS.values()), FORMATS[kind])
    if not dest.lower().endswith(FORMATS[kind]):
        raise SimError("The file name must end in %s for a %s report." % (FORMATS[kind], kind))
    data = build_html(f, payload, name).encode("utf-8") if kind == "html" else build_pdf(f, payload, name)
    container.atomic_write(dest, data)
    return {"path": dest, "format": kind, "bytes": len(data), "study": sid}
