import math
import random
import time

import numpy as np
import pyclipper as pc

from app.cutting import shapes as S
from app.cutting.shapes import CutError

MAX_INSTANCES = 400
MAX_INSTANCES_AGENT = 60
MAX_SHEETS = 60
MAX_SECONDS = 300.0
MAX_SECONDS_AGENT = 30.0
MAX_ROTATIONS = 36
NEST_TOL = 0.04
MAX_PIECES = 14
MAX_DECIMATE = 3.0
TOUCH = 1


class Cancelled(Exception):
    pass


class TimeUp(Exception):
    pass


def _ints(pts):
    return S.to_ints(pts)


def _rot_part(part, rot, c, tol):
    outer = part["loops"][0]["pts"]
    pts = S.transform(outer, rot, 0.0, 0.0)
    x0, y0, x1, y1 = S.bbox(pts)
    base = [(x - x0, y - y0) for x, y in pts]
    dtol = tol * 0.75
    while True:
        real = S.decimate(base, dtol)
        infl = S.offset([real], c / 2.0 + tol + (dtol - tol * 0.75))
        if not infl:
            raise CutError("Part %s collapsed while adding the clearance." % part["name"])
        q = max(infl, key=lambda p: abs(S.area(p)))
        q = S.orient(q, True)
        neg = [(-x, -y) for x, y in q]
        neg = S.orient(neg, True)
        pieces = S.convex_parts(neg)
        if len(pieces) <= MAX_PIECES or dtol >= MAX_DECIMATE:
            break
        dtol *= 2.0
    qx0, qy0, qx1, qy1 = S.bbox(q)
    pos = S.convex_parts(q)
    return {"rot": rot, "shift": (x0, y0), "real": real, "q": q, "qb": (qx0, qy0, qx1, qy1), "pieces": [_ints(p) for p in pieces], "qi": _ints(q), "pos": [_ints(p) for p in pos], "w": x1 - x0, "h": y1 - y0}


class Nester:
    def __init__(self, parts, sheets, clearance, kerf, margin, deadline, cancel=None, defects=None):
        self.parts = parts
        self.sheets = sheets
        self.c = max(0.0, float(clearance)) + max(0.0, float(kerf))
        self.margin = float(margin)
        self.deadline = deadline
        self.hard = None
        self.timed_out = False
        self.cancel = cancel
        self.defects = defects or []
        self.rots = {}
        self.nfp = {}
        self.defect_paths = []
        for d in self.defects:
            infl = S.offset([S.orient(d, True)], self.c / 2.0)
            for p in infl:
                self.defect_paths.append([S.to_ints(q) for q in S.convex_parts(S.orient(p, True))])

    def rot(self, ti, r):
        k = (ti, r)
        v = self.rots.get(k)
        if v is None:
            if self.hard and time.time() > self.hard:
                raise TimeUp()
            if self.cancel:
                self.cancel()
            v = _rot_part(self.parts[ti], r, self.c, NEST_TOL)
            self.rots[k] = v
        return v

    def nfp_of(self, a, ra, b, rb):
        k = (a, ra, b, rb)
        v = self.nfp.get(k)
        if v is not None:
            return v
        A = self.rot(a, ra)
        B = self.rot(b, rb)
        sub = pc.Pyclipper()
        for piece in A["pieces"]:
            for ob in B["pos"]:
                sub.AddPath(S.convex_sum(piece, ob), pc.PT_SUBJECT, True)
        res = sub.Execute(pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO)
        bb = None
        if res:
            xs = [p[0] for path in res for p in path]
            ys = [p[1] for path in res for p in path]
            bb = (min(xs), min(ys), max(xs), max(ys))
        v = (res, bb)
        self.nfp[k] = v
        return v

    def place_on(self, sheet, ti, order_rots):
        W, H = sheet["w"], sheet["h"]
        best = None
        for r in order_rots:
            if self.hard and time.time() > self.hard:
                raise TimeUp()
            R = self.rot(ti, r)
            qx1 = R["qb"][2]
            xlo = self.margin
            ylo = self.margin
            xhi = W - self.margin - R["w"]
            yhi = H - self.margin - R["h"]
            if xlo > xhi + 1e-9 or ylo > yhi + 1e-9:
                continue
            rect = [(int(round(xlo * S.SCALE)), int(round(ylo * S.SCALE))), (int(round(xhi * S.SCALE)), int(round(ylo * S.SCALE))), (int(round(xhi * S.SCALE)), int(round(yhi * S.SCALE))), (int(round(xlo * S.SCALE)), int(round(yhi * S.SCALE)))]
            if xhi - xlo < 1e-9 or yhi - ylo < 1e-9:
                rect = [(rect[0][0], rect[0][1]), (rect[0][0] + 1, rect[0][1]), (rect[0][0] + 1, rect[0][1] + 1), (rect[0][0], rect[0][1] + 1)]
            clip = pc.Pyclipper()
            clip.AddPath(rect, pc.PT_SUBJECT, True)
            rb = (rect[0][0], rect[0][1], rect[2][0], rect[2][1])
            for item in sheet["items"]:
                if self.hard and time.time() > self.hard:
                    raise TimeUp()
                res, bb = self.nfp_of(ti, r, item["ti"], item["rot"])
                if not res:
                    continue
                ox = int(round(item["tx"] * S.SCALE))
                oy = int(round(item["ty"] * S.SCALE))
                if bb[2] + ox <= rb[0] or bb[0] + ox >= rb[2] or bb[3] + oy <= rb[1] or bb[1] + oy >= rb[3]:
                    continue
                for path in res:
                    clip.AddPath([(x + ox, y + oy) for x, y in path], pc.PT_CLIP, True)
            for dp in self.defect_nfps(ti, r):
                clip.AddPath(dp, pc.PT_CLIP, True)
            sol = clip.Execute(pc.CT_DIFFERENCE, pc.PFT_NONZERO, pc.PFT_NONZERO)
            if not sol:
                continue
            for path in sol:
                for x, y in path:
                    tx, ty = x / S.SCALE, y / S.SCALE
                    key = (round(tx + qx1, 3), round(ty, 3), round(tx, 3), r)
                    if best is None or key < best[0]:
                        best = (key, r, tx, ty)
        return best

    def defect_nfps(self, ti, r):
        if not self.defect_paths:
            return []
        key = ("d", ti, r)
        if key in self.nfp:
            return self.nfp[key]
        R = self.rot(ti, r)
        out = []
        for dp in self.defect_paths:
            sub = pc.Pyclipper()
            for piece in R["pieces"]:
                for ob in dp:
                    sub.AddPath(S.convex_sum(piece, ob), pc.PT_SUBJECT, True)
            out.extend(sub.Execute(pc.CT_UNION, pc.PFT_NONZERO, pc.PFT_NONZERO))
        self.nfp[key] = out
        return out

    def run(self, order, rot_order_fn):
        st = {"sheets": [], "unplaced": [], "i": 0}
        try:
            self.run_inner(order, rot_order_fn, st)
        except TimeUp:
            self.timed_out = True
            st["unplaced"].extend(order[st["i"] :])
        return st["sheets"], st["unplaced"]

    def run_inner(self, order, rot_order_fn, st):
        sheets = st["sheets"]
        specs = list(self.sheets)
        unplaced = st["unplaced"]
        for idx, inst in enumerate(order):
            st["i"] = idx
            ti = inst["ti"]
            if self.cancel:
                self.cancel()
            part = self.parts[ti]
            placed = False
            rots = rot_order_fn(part["rotations"])
            for sh in sheets:
                best = self.place_on(sh, ti, rots)
                if best:
                    _, r, tx, ty = best
                    sh["items"].append({"ti": ti, "inst": inst["k"], "rot": r, "tx": tx, "ty": ty})
                    placed = True
                    break
            if placed:
                continue
            if len(sheets) < MAX_SHEETS:
                for spec in specs:
                    if spec["qty"] is not None and spec["qty"] <= 0:
                        continue
                    sh = {"w": spec["w"], "h": spec["h"], "spec": spec["index"], "items": []}
                    best = self.place_on(sh, ti, rots)
                    if best:
                        _, r, tx, ty = best
                        sh["items"].append({"ti": ti, "inst": inst["k"], "rot": r, "tx": tx, "ty": ty})
                        sheets.append(sh)
                        if spec["qty"] is not None:
                            spec["qty"] -= 1
                        placed = True
                        break
            if not placed:
                unplaced.append(inst)
        return sheets, unplaced

    def extent(self, sh):
        m = 0.0
        for it in sh["items"]:
            R = self.rot(it["ti"], it["rot"])
            m = max(m, it["tx"] + R["qb"][2])
        return m


def objective(sheets, unplaced, nester):
    last = nester.extent(sheets[-1]) if sheets else 0.0
    return (len(unplaced), len(sheets), round(last, 3))


def parse_sheets(sheets):
    if not sheets:
        raise CutError("Give at least one sheet size.")
    out = []
    for i, s in enumerate(sheets):
        w, h = float(s["width"]), float(s["height"])
        if not (w > 0 and h > 0):
            raise CutError("Sheet %d has no size." % (i + 1))
        q = s.get("qty")
        out.append({"w": w, "h": h, "qty": None if q is None else int(q), "index": i})
    return out


def nest(parts_in, sheets, clearance=0.0, kerf=0.0, margin=5.0, seconds=20.0, restarts=8, seed=1, rotations=None, defects=None, agent=False, progress=None, cancelled=None):
    parts = []
    for i, p in enumerate(parts_in):
        np_ = p if "area" in p and "loops" in p and "gross" in p else S.normalize_part(p, i)
        if rotations is not None:
            np_ = dict(np_)
            np_["rotations"] = sorted(set(float(r) % 360.0 for r in rotations))
        if len(np_["rotations"]) > MAX_ROTATIONS:
            raise CutError("At most %d rotations per part." % MAX_ROTATIONS)
        parts.append(np_)
    limit = MAX_INSTANCES_AGENT if agent else MAX_INSTANCES
    total = sum(p["qty"] for p in parts)
    if total > limit:
        raise CutError("%d part instances is more than the limit of %d%s." % (total, limit, " for an automation caller" if agent else ""))
    if total == 0:
        raise CutError("There is nothing to nest.")
    cap_s = MAX_SECONDS_AGENT if agent else MAX_SECONDS
    seconds = max(0.5, min(float(seconds), cap_s))
    restarts = max(0, min(int(restarts), 200))
    sheet_specs = parse_sheets(sheets)
    t0 = time.time()
    deadline = t0 + seconds
    clearance = float(clearance)
    kerf = float(kerf)
    if clearance < 0 or kerf < 0 or margin < 0:
        raise CutError("Clearance, kerf and margin cannot be negative.")
    defect_polys = [S.orient([(float(x), float(y)) for x, y in d], True) for d in (defects or [])]

    def check():
        if cancelled and cancelled():
            raise Cancelled()

    nester = Nester(parts, sheet_specs, clearance, kerf, margin, deadline, check, defect_polys)
    instances = []
    for ti, p in enumerate(parts):
        for k in range(p["qty"]):
            instances.append({"ti": ti, "k": k})
    base = sorted(instances, key=lambda it: (-parts[it["ti"]]["gross"], it["ti"], it["k"]))
    rng = random.Random(seed)

    def fresh_specs():
        return [dict(s) for s in sheet_specs]

    def attempt(order, rot_fn):
        nester.sheets = fresh_specs()
        sh, un = nester.run(order, rot_fn)
        return sh, un

    best = None
    tried = 0
    plans = [(base, lambda r: list(r))]
    for i in range(restarts):
        order = list(base)
        mode = i % 3
        if mode == 0:
            for _ in range(max(1, len(order) // 4)):
                a = rng.randrange(len(order))
                b = min(len(order) - 1, a + rng.randint(1, 3))
                order[a], order[b] = order[b], order[a]
        elif mode == 1:
            order.sort(key=lambda it: -(parts[it["ti"]]["gross"] * (0.7 + 0.6 * rng.random())))
        else:
            order.sort(key=lambda it: (-max(S.bbox(parts[it["ti"]]["loops"][0]["pts"])[2:]) * (0.8 + 0.4 * rng.random())))
        rr = rng.random()
        plans.append((order, (lambda r, rr=rr: list(r) if rr < 0.5 else list(reversed(r)))))
    for pi, (order, rot_fn) in enumerate(plans):
        if pi > 0 and time.time() > deadline:
            break
        nester.hard = deadline
        nester.timed_out = False
        try:
            sh, un = attempt(order, rot_fn)
        except Cancelled:
            if best is None:
                raise
            break
        tried += 1
        ob = objective(sh, un, nester)
        if best is None or ob < best[0]:
            best = (ob, sh, un, nester.timed_out)
        if progress:
            progress(min(0.98, (pi + 1) / len(plans)), "Nesting pass %d of %d: %d sheets" % (pi + 1, len(plans), len(best[1])))
    ob, sh, un, timed = best
    out = finish(nester, parts, sheet_specs, sh, un, clearance, kerf, margin, tried, time.time() - t0, seed)
    out["timed_out"] = timed
    return out


def finish(nester, parts, specs, sheets, unplaced, clearance, kerf, margin, tried, elapsed, seed):
    out_sheets = []
    total_part = 0.0
    total_sheet = 0.0
    total_cut = 0.0
    for si, sh in enumerate(sheets):
        pl = []
        used = 0.0
        cut = 0.0
        for it in sh["items"]:
            p = parts[it["ti"]]
            R = nester.rot(it["ti"], it["rot"])
            pl.append({"part": p["name"], "index": it["ti"], "instance": it["inst"], "rotation": it["rot"], "x": it["tx"], "y": it["ty"], "bbox": [it["tx"], it["ty"], it["tx"] + R["w"], it["ty"] + R["h"]], "transform": {"rot": it["rot"], "dx": it["tx"] - R["shift"][0], "dy": it["ty"] - R["shift"][1]}})
            used += p["area"]
            cut += p["cut_length"]
        total_part += used
        total_sheet += sh["w"] * sh["h"]
        total_cut += cut
        out_sheets.append({"index": si, "width": sh["w"], "height": sh["h"], "placements": pl, "part_area": used, "utilization": used / (sh["w"] * sh["h"]), "extent": nester.extent(sh) - 0.0, "cut_length": cut})
    for s in out_sheets:
        s["extent"] = max([pl["bbox"][2] for pl in s["placements"]] or [0.0])
    verify = check_result(parts, out_sheets, clearance + kerf, margin)
    return {"sheets": out_sheets, "sheet_count": len(out_sheets), "utilization": (total_part / total_sheet) if total_sheet else 0.0, "part_area": total_part, "sheet_area": total_sheet, "cut_length": total_cut, "unplaced": [{"part": parts[u["ti"]]["name"], "instance": u["k"]} for u in unplaced], "placed": sum(len(s["placements"]) for s in out_sheets), "parts": [{"name": p["name"], "qty": p["qty"], "area": p["area"], "rotations": p["rotations"]} for p in parts], "params": {"clearance": clearance, "kerf": kerf, "margin": margin, "seed": seed}, "passes": tried, "seconds": round(elapsed, 3), "verify": verify}


def placed_outline(part, tr):
    return S.transform(part["loops"][0]["pts"], tr["rot"], tr["dx"], tr["dy"])


def min_distance(a, b) -> float:
    A = np.asarray(a, float)
    B = np.asarray(b, float)

    def pts_to_segs(P, Q):
        Q1 = np.roll(Q, -1, axis=0)
        d = Q1 - Q
        L = (d ** 2).sum(axis=1)
        L[L == 0] = 1e-18
        diff = P[:, None, :] - Q[None, :, :]
        t = np.clip((diff * d[None, :, :]).sum(axis=2) / L[None, :], 0.0, 1.0)
        proj = Q[None, :, :] + t[:, :, None] * d[None, :, :]
        return np.sqrt(((P[:, None, :] - proj) ** 2).sum(axis=2)).min()

    return float(min(pts_to_segs(A, B), pts_to_segs(B, A)))


def check_result(parts, sheets, c, margin):
    worst_gap = None
    overlaps = 0
    outside = 0
    for sh in sheets:
        polys = []
        for pl in sh["placements"]:
            p = parts[pl["index"]]
            poly = placed_outline(p, pl["transform"])
            x0, y0, x1, y1 = S.bbox(poly)
            if x0 < margin - 0.01 or y0 < margin - 0.01 or x1 > sh["width"] - margin + 0.01 or y1 > sh["height"] - margin + 0.01:
                outside += 1
            polys.append((poly, (x0, y0, x1, y1)))
        for i in range(len(polys)):
            for j in range(i + 1, len(polys)):
                bi, bj = polys[i][1], polys[j][1]
                if bi[2] + c + 1.0 < bj[0] or bj[2] + c + 1.0 < bi[0] or bi[3] + c + 1.0 < bj[1] or bj[3] + c + 1.0 < bi[1]:
                    continue
                clip = pc.Pyclipper()
                clip.AddPath(S.to_ints(polys[i][0]), pc.PT_SUBJECT, True)
                clip.AddPath(S.to_ints(polys[j][0]), pc.PT_CLIP, True)
                inter = clip.Execute(pc.CT_INTERSECTION, pc.PFT_NONZERO, pc.PFT_NONZERO)
                if inter and sum(abs(pc.Area(p)) for p in inter) > 4:
                    overlaps += 1
                    continue
                d = min_distance(polys[i][0], polys[j][0])
                if worst_gap is None or d < worst_gap:
                    worst_gap = d
    return {"overlaps": overlaps, "outside": outside, "min_gap": worst_gap, "required_gap": c}
