import math

import numpy as np

from app.drawann import drawview, settings, tabledata, viewsrc

CYLINDER = 1
PARALLEL = 0.999
SKEW = (0.3713, 0.1291)
COLUMNS = ("TAG", "X LOC", "Y LOC", "SIZE")
TITLE = "HOLE TABLE"
MAX_HOLES = 500


class HoleTableError(Exception):
    pass


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return [c / n for c in v] if n > 1e-12 else [0.0, 0.0, 0.0]


def _perp(n):
    a = [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0]
    u = _unit(drawview._cross(n, a))
    w = drawview._cross(n, u)
    return _unit([u[i] + SKEW[0] * w[i] for i in range(3)])


def _matrix(m):
    if not m:
        return np.eye(4)
    a = np.asarray(m, dtype=float)
    return a.reshape(4, 4)


def _apply(m, p, w=1.0):
    v = m @ np.array([p[0], p[1], p[2], w])
    return [float(v[0]), float(v[1]), float(v[2])]


def _kcall(method, params):
    from app.solid import work

    return work.kcall(method, params, work.SHORT)


def _hits(wid, origin, direction):
    return [float(h["t"]) for h in (_kcall("feat_rays", {"id": wid, "origin": origin, "dir": direction}).get("hits") or [])]


def _in_material(wid, point, n):
    d = _unit([_perp(n)[i] + SKEW[1] * n[i] for i in range(3)])
    behind = [t for t in _hits(wid, point, d) if t < -1e-7]
    return len(behind) % 2 == 1


def _thickness(wid, point, n, t_mid):
    ts = sorted(_hits(wid, point, n))
    for i in range(0, len(ts) - 1, 2):
        if ts[i] - 1e-6 <= t_mid <= ts[i + 1] + 1e-6:
            return ts[i + 1] - ts[i]
    return None


def _circles(d, view):
    return [e for e in viewsrc.edges(d, view) if e.get("type") == "circle"]


def _cosmetic(doc, view, items):
    if (view.source or {}).get("doc") or any(it.matrix for it in items):
        return []
    try:
        from app.part import rebuild

        store = getattr(rebuild.cache_of(doc), "cosmetic", None) or {}
    except Exception:
        return []
    out = []
    for threads in store.values():
        out.extend(threads or [])
    return out


def find(doc, view) -> list:
    from app.views import sources

    d = doc.drawing
    if view.kind != "drawview":
        raise HoleTableError("A hole table needs a model view.")
    try:
        items = sources.resolve(doc, view.source, True)
    except Exception as err:
        raise HoleTableError(str(err))
    vn = _unit([float(c) for c in view.vnormal])
    k = float(view.scale) / drawview.unit_mm(d, view)
    pos = [float(view.position[0]), float(view.position[1])]
    circles = _circles(d, view)
    groups = []
    for it in items:
        if not it.wid:
            continue
        m = _matrix(it.matrix)
        inv = np.linalg.inv(m)
        sigs = (_kcall("feat_signatures", {"id": it.wid, "faces": "all"}).get("faces") or {})
        for sig in sigs.values():
            if sig.get("k") != CYLINDER or not sig.get("r") or not sig.get("n"):
                continue
            n_world = _unit(_apply(m, sig["n"], 0.0))
            if abs(sum(n_world[i] * vn[i] for i in range(3))) < PARALLEL:
                continue
            if _in_material(it.wid, sig["c"], sig["n"]):
                continue
            r = float(sig["r"])
            c_world = _apply(m, sig["c"])
            lc = drawview.local_of(view, c_world)
            pc = [pos[0] + k * lc[0], pos[1] + k * lc[1]]
            best = None
            for ci in circles:
                if abs(float(ci["r"]) - r * k) > 1e-4 * max(1.0, r * k):
                    continue
                dist = math.hypot(ci["c"][0] - pc[0], ci["c"][1] - pc[1])
                if dist <= r * k * 1.01 + 1e-6 and (best is None or dist < best[0]):
                    best = (dist, ci)
            center = best[1]["c"] if best else pc
            face = {"r": r, "a": float(sig.get("a") or 0.0), "c": sig["c"], "n": sig["n"], "wid": it.wid, "inv": inv}
            for g in groups:
                if math.hypot(g["center"][0] - center[0], g["center"][1] - center[1]) <= 1e-4 * max(1.0, r * k):
                    g["faces"].append(face)
                    break
            else:
                groups.append({"center": [float(center[0]), float(center[1])], "faces": [face], "circle": best[1] if best else None})
            if len(groups) > MAX_HOLES:
                raise HoleTableError("The view shows more than %d holes." % MAX_HOLES)
    x_ax, y_ax = drawview.frame(view)
    o = drawview.origin(view)
    out = []
    for g in groups:
        radii = sorted({round(f["r"], 6) for f in g["faces"]})
        lx, ly = (g["center"][0] - pos[0]) / k, (g["center"][1] - pos[1]) / k
        world = [o[i] + lx * x_ax[i] + ly * y_ax[i] for i in range(3)]
        steps = []
        for r in radii:
            fs = [f for f in g["faces"] if abs(f["r"] - r) <= 1e-6]
            h = sum(f["a"] for f in fs) / (2.0 * math.pi * r) if r > 0 else 0.0
            f0 = fs[0]
            n = _unit(f0["n"])
            p_local = _apply(f0["inv"], world)
            u = _perp(n)
            q = [p_local[i] + 1.05 * r * u[i] for i in range(3)]
            t_mid = sum((f0["c"][i] - q[i]) * n[i] for i in range(3))
            thick = _thickness(f0["wid"], q, n, t_mid)
            through = thick is not None and h >= thick - 1e-4
            steps.append({"d": 2.0 * r, "depth": h, "through": through})
        out.append({"center": g["center"], "local": [lx, ly], "world": world, "steps": steps, "circle": g["circle"]})
    threads = _cosmetic(doc, view, items)
    for hole in out:
        for th in threads:
            lp = drawview.local_of(view, th.get("position") or [0, 0, 0])
            ax = _unit(th.get("axis") or [0, 0, 1])
            if abs(sum(ax[i] * vn[i] for i in range(3))) < PARALLEL:
                continue
            if math.hypot(lp[0] - hole["local"][0], lp[1] - hole["local"][1]) <= 1e-3 * max(1.0, hole["steps"][0]["d"]):
                hole["thread"] = th
                break
    return out


def _fmt(v, unit):
    return "%.2f" % (float(v) / unit)


def size_text(hole, unit):
    st = hole["steps"]
    first = st[0]
    th = hole.get("thread")
    if th:
        main = "M%gx%g" % (round(float(th["nominal"]), 4), round(float(th["pitch"]), 4))
        depth = float(th.get("depth") or 0.0)
        main += " THRU" if first["through"] and depth >= first["depth"] - 1e-4 else " x %s DEEP" % _fmt(depth, unit)
    else:
        main = "⌀%s %s" % (_fmt(first["d"], unit), "THRU" if first["through"] else "x %s DEEP" % _fmt(first["depth"], unit))
    for s in st[1:]:
        main += ", CBORE ⌀%s x %s DEEP" % (_fmt(s["d"], unit), _fmt(s["depth"], unit))
    return main


def _letters(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def default_origin(d, view):
    xs, ys = [], []
    for e in viewsrc.edges(d, view):
        if e.get("style") != "visible":
            continue
        if e["type"] == "line":
            for p in e["p"]:
                xs.append(p[0])
                ys.append(p[1])
        elif e["type"] in ("circle", "arc"):
            xs.extend([e["c"][0] - e["r"], e["c"][0] + e["r"]])
            ys.extend([e["c"][1] - e["r"], e["c"][1] + e["r"]])
    if not xs:
        return [float(view.position[0]), float(view.position[1])]
    return [min(xs), min(ys)]


def origin_paper(d, view, link):
    if isinstance(link, dict) and link.get("e"):
        p = viewsrc.point(d, dict(link, h=view.handle))
        if p is not None:
            return [float(p[0]), float(p[1])]
    return default_origin(d, view)


def rows(doc, view, origin_link=None) -> list:
    d = doc.drawing
    unit = drawview.unit_mm(d, view)
    k = float(view.scale) / unit
    org = origin_paper(d, view, origin_link)
    holes = find(doc, view)
    sizes = {}
    for h in holes:
        h["size"] = size_text(h, unit)
        sizes.setdefault(h["size"], (h["steps"][0]["d"], h["size"]))
    order = sorted(sizes.values())
    letter = {s: _letters(i) for i, (_d, s) in enumerate(order)}
    holes.sort(key=lambda h: (order.index(sizes[h["size"]]), round(h["center"][0] - org[0], 6), round(h["center"][1] - org[1], 6)))
    count = {}
    for h in holes:
        L = letter[h["size"]]
        count[L] = count.get(L, 0) + 1
        h["tag"] = "%s%d" % (L, count[L])
        h["x"] = (h["center"][0] - org[0]) / k * unit
        h["y"] = (h["center"][1] - org[1]) / k * unit
        h["paper_r"] = h["steps"][0]["d"] / 2.0 * k
    return holes


def fill(d, t, holes, title, unit):
    tabledata.fill_rows(d, t, COLUMNS, [[h["tag"], _fmt(h["x"], unit), _fmt(h["y"], unit), h["size"]] for h in holes], title)


def place_tags(d, t, view, holes):
    from app.doc.entities import Text

    st = settings.get(d)
    th = float(st["text_height"])
    meta = t.extra["holetable"]
    old = [int(h) for h in meta.get("tags") or [] if int(h) in d.ents]
    made = []
    for i, h in enumerate(holes):
        at = [h["center"][0] + h["paper_r"] * 0.75 + th * 0.3, h["center"][1] + h["paper_r"] * 0.75 + th * 0.3, 0.0]
        if i < len(old):
            e = d.modify(old[i])
            e.position, e.text, e.height = at, h["tag"], th
            made.append(old[i])
        else:
            made.append(d.add_entity(Text(position=at, text=h["tag"], height=th, layer=t.layer), view.owner))
    for h in old[len(holes):]:
        d.erase_entity(h)
    return made


def refresh(doc, table_handle) -> dict:
    d = doc.drawing
    t0 = d.get(int(table_handle))
    if t0 is None or "holetable" not in (t0.extra or {}):
        raise HoleTableError("The object is not a hole table.")
    meta = dict(t0.extra["holetable"])
    view = viewsrc.need(d, meta["view"])
    holes = rows(doc, view, meta.get("origin"))
    t = d.modify(t0.handle)
    fill(d, t, holes, meta.get("title") or TITLE, drawview.unit_mm(d, view))
    if meta.get("show_tags", True):
        meta["tags"] = place_tags(d, t, view, holes)
    t.extra = dict(t.extra, holetable=meta)
    return {"handle": t.handle, "holes": [h["tag"] for h in holes]}


def follow(doc, rebuilt) -> None:
    d = doc.drawing
    for e in list(d.ents.values()):
        if e.kind != "table":
            continue
        meta = (e.extra or {}).get("holetable")
        if meta and int(meta.get("view") or 0) in rebuilt:
            try:
                refresh(doc, e.handle)
            except (HoleTableError, viewsrc.ViewError):
                pass
