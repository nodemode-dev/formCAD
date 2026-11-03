import math

from app.doc.entities import Hatch
from app.doc.kinds.drawann import Balloon, CenterMark
from app.drawann import viewsrc


def view_box(d, view):
    xs, ys = [], []
    for ed in viewsrc.edges(d, view):
        if ed["type"] == "line":
            for p in ed["p"]:
                xs.append(p[0])
                ys.append(p[1])
        else:
            c, r = ed["c"], float(ed["r"])
            xs += [c[0] - r, c[0] + r]
            ys += [c[1] - r, c[1] + r]
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]


def centermarks(d, view, st, arcs=False):
    out = []
    seen = set()
    edges = viewsrc.edges(d, view)
    for ed in edges:
        if ed.get("style", "visible") not in ("visible", "silhouette", "sharp"):
            continue
        if ed["type"] == "circle" or (arcs and ed["type"] == "arc"):
            if ed["type"] == "arc":
                sweep = (float(ed["a1"]) - float(ed["a0"])) % (2 * math.pi)
                if sweep < math.pi - 1e-9:
                    continue
            key = (round(ed["c"][0], 6), round(ed["c"][1], 6), round(float(ed["r"]), 6))
            if key in seen:
                continue
            seen.add(key)
            e = CenterMark(center=[float(ed["c"][0]), float(ed["c"][1]), 0.0], radius=float(ed["r"]), mode="circle", link={"h": view.handle, "e": ed["id"], "t": "center"}, view=view.handle, edge=ed["id"])
            out.append(e)
    axes = []
    prov = viewsrc.provider_for(view)
    if hasattr(prov, "axes"):
        axes = list(prov.axes(d, view))
    else:
        axes = silhouette_axes(edges)
    for ax in axes:
        out.append(CenterMark(mode="axis", a=[ax["a"][0], ax["a"][1], 0.0], b=[ax["b"][0], ax["b"][1], 0.0], center=[(ax["a"][0] + ax["b"][0]) / 2.0, (ax["a"][1] + ax["b"][1]) / 2.0, 0.0], a_link=ax.get("a_link", {}), b_link=ax.get("b_link", {}), view=view.handle, edge=ax.get("edge", "")))
    return out


def silhouette_axes(edges):
    sil = [e for e in edges if e["type"] == "line" and e.get("style") == "silhouette"]
    used = set()
    out = []
    for i, e1 in enumerate(sil):
        if i in used:
            continue
        a1, b1 = e1["p"]
        d1 = (b1[0] - a1[0], b1[1] - a1[1])
        L1 = math.hypot(*d1)
        if L1 < 1e-9:
            continue
        u = (d1[0] / L1, d1[1] / L1)
        for j in range(i + 1, len(sil)):
            if j in used:
                continue
            a2, b2 = sil[j]["p"]
            L2 = math.hypot(b2[0] - a2[0], b2[1] - a2[1])
            if abs(L1 - L2) > 1e-6 * max(L1, 1.0):
                continue
            cross = abs(u[0] * (b2[1] - a2[1]) - u[1] * (b2[0] - a2[0])) / L2
            if cross > 1e-6:
                continue
            t1 = (a2[0] - a1[0]) * u[0] + (a2[1] - a1[1]) * u[1]
            t2 = (b2[0] - a1[0]) * u[0] + (b2[1] - a1[1]) * u[1]
            lo, hi = min(t1, t2), max(t1, t2)
            if abs(lo) > 1e-6 * max(L1, 1.0) or abs(hi - L1) > 1e-6 * max(L1, 1.0):
                continue
            sep = abs((a2[0] - a1[0]) * -u[1] + (a2[1] - a1[1]) * u[0])
            if sep < 1e-6:
                continue
            used.update((i, j))
            out.append({"a": ((a1[0] + (a2[0] if t1 < t2 else b2[0])) / 2.0, (a1[1] + (a2[1] if t1 < t2 else b2[1])) / 2.0), "b": ((b1[0] + (b2[0] if t1 < t2 else a2[0])) / 2.0, (b1[1] + (b2[1] if t1 < t2 else a2[1])) / 2.0), "edge": e1["id"]})
            break
    return out


def inside(poly, p):
    c = False
    n = len(poly)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        if (y0 > p[1]) != (y1 > p[1]) and p[0] < (x1 - x0) * (p[1] - y0) / (y1 - y0) + x0:
            c = not c
    return c


def section_hatches(d, view, st):
    prov = viewsrc.provider_for(view)
    loops = list(prov.section_loops(d, view)) if hasattr(prov, "section_loops") else []
    outers = [lo for lo in loops if lo.get("outer", True)]
    holes = [lo for lo in loops if not lo.get("outer", True)]
    comps = sorted({lo.get("component", "") for lo in outers})
    out = []
    for lo in outers:
        pts = [(v["p"][0], v["p"][1]) for v in lo["vertices"]]
        mine = [lo]
        for h in holes:
            hp = h["vertices"][0]["p"]
            if inside(pts, (hp[0], hp[1])):
                mine.append(h)
        angle = 0.0 if comps.index(lo.get("component", "")) % 2 == 0 else math.pi / 2.0
        hl = [{"vertices": [{"p": [float(v["p"][0]), float(v["p"][1])], "bulge": float(v.get("bulge", 0.0))} for v in m["vertices"]], "sources": [], "outer": bool(m.get("outer", True)), "depth": 0 if m.get("outer", True) else 1} for m in mine]
        e = Hatch(pattern=st["hatch_pattern"], loops=hl, pattern_scale=st["hatch_scale"], pattern_angle=angle, associative=False, style=0)
        e.extra = {"section_view": view.handle, "component": lo.get("component", "")}
        out.append(e)
    return out


def box_ray(box, cx, cy, ux, uy, pad):
    x0, y0, x1, y1 = box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad
    best = 1e18
    for lim, c, u in ((x1, cx, ux), (x0, cx, ux), (y1, cy, uy), (y0, cy, uy)):
        if abs(u) < 1e-12:
            continue
        t = (lim - c) / u
        if t > 0 and t < best:
            best = t
    return cx + ux * best, cy + uy * best, (x0, y0, x1, y1)


def perimeter_s(rect, x, y):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    eps = 1e-6 * max(w, h, 1.0)
    if abs(y - y0) < eps:
        return x - x0
    if abs(x - x1) < eps:
        return w + (y - y0)
    if abs(y - y1) < eps:
        return w + h + (x1 - x)
    return 2 * w + h + (y1 - y)


def perimeter_point(rect, s):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    L = 2 * (w + h)
    s = s % L
    if s <= w:
        return x0 + s, y0
    s -= w
    if s <= h:
        return x1, y0 + s
    s -= h
    if s <= w:
        return x1 - s, y1
    s -= w
    return x0, y1 - s


def anchor_for(d, view, key, centre):
    best = None
    for ed in viewsrc.edges(d, view):
        if ed.get("component", "") not in ([key] if isinstance(key, str) else key) or ed.get("style", "visible") not in ("visible", "silhouette", "sharp"):
            continue
        if ed["type"] == "line":
            a, b = ed["p"]
            m = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
            link = {"h": view.handle, "e": ed["id"], "t": "mid"}
        else:
            c, r = ed["c"], float(ed["r"])
            ang = math.atan2(c[1] - centre[1], c[0] - centre[0]) if math.hypot(c[0] - centre[0], c[1] - centre[1]) > 1e-9 else 0.0
            m = (c[0] + r * math.cos(ang), c[1] + r * math.sin(ang))
            link = {"h": view.handle, "e": ed["id"], "t": "ang", "a": ang}
        dist = math.hypot(m[0] - centre[0], m[1] - centre[1])
        if best is None or dist > best[0] + 1e-9:
            best = (dist, m, link)
    return best


def balloon_plan(d, view, rows, st):
    box = view_box(d, view)
    if box is None:
        return []
    cx, cy = (box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0
    R = st["balloon_diameter"] / 2.0
    pad = st["balloon_ring"] + R
    items = []
    for row in rows:
        key = str(row.get("key", ""))
        if not key:
            continue
        got = anchor_for(d, view, list(row.get("keys") or [key]), (cx, cy))
        if got is None:
            continue
        _dist, m, link = got
        dx, dy = m[0] - cx, m[1] - cy
        n = math.hypot(dx, dy)
        ux, uy = (dx / n, dy / n) if n > 1e-9 else (0.0, 1.0)
        qx, qy, rect = box_ray(box, cx, cy, ux, uy, pad)
        items.append({"row": row, "anchor": m, "link": link, "s": perimeter_s(rect, qx, qy), "rect": rect})
    if not items:
        return []
    rect = items[0]["rect"]
    L = 2 * ((rect[2] - rect[0]) + (rect[3] - rect[1]))
    spc = max(st["balloon_spacing"], st["balloon_diameter"] * 1.15)
    items.sort(key=lambda i: (i["s"], str(i["row"].get("item"))))
    if len(items) * spc > L:
        spc = L / len(items)
    for _pass in range(len(items) + 2):
        moved = False
        for i in range(1, len(items)):
            need = items[i - 1]["s"] + spc
            if items[i]["s"] < need - 1e-9:
                items[i]["s"] = need
                moved = True
        over = items[-1]["s"] - (items[0]["s"] + L - spc)
        if over > 1e-9:
            shift = over / 2.0
            for it in items:
                it["s"] -= shift
            moved = True
        if not moved:
            break
    out = []
    for it in sorted(items, key=lambda i: str(i["row"].get("item")).zfill(6)):
        x, y = perimeter_point(rect, it["s"])
        out.append({"row": it["row"], "position": [x, y, 0.0], "tip": [it["anchor"][0], it["anchor"][1], 0.0], "link": it["link"]})
    return out


def make_balloon(plan, end=""):
    row = plan["row"]
    return Balloon(position=plan["position"], text=str(row.get("item")), tip=plan["tip"], tip_link=plan["link"], item=str(row.get("item")), part_key=str(row.get("key", "")), end=end)
