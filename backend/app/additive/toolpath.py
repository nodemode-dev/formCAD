import math

import numpy as np

from app.additive import fill
from app.additive import regions as rg
from app.additive.settings import SettingError

TRAVEL, OUTER, INNER, SPARSE, SOLID, TOP, BRIDGE, SUPPORT, INTERFACE, SKIRT, GAPFILL = range(11)
FEATURE_CODES = {"travel": 0, "outer_wall": 1, "inner_wall": 2, "sparse_infill": 3, "solid_infill": 4, "top_skin": 5, "bridge": 6, "support": 7, "support_interface": 8, "skirt_brim": 9, "gap_fill": 10}
FEATURE_NAMES = {v: k for k, v in FEATURE_CODES.items()}
GCODE_TYPE = {1: "WALL-OUTER", 2: "WALL-INNER", 3: "FILL", 4: "SOLID-FILL", 5: "SKIN", 6: "BRIDGE", 7: "SUPPORT", 8: "SUPPORT-INTERFACE", 9: "SKIRT", 10: "GAP-FILL"}
K_SECT = 1.0 - math.pi / 4.0
MAX_MOVES = 6_000_000


def section(w: float, h: float) -> float:
    return h * (w - h) + math.pi * (h / 2.0) ** 2


def spacing_of(w: float, h: float) -> float:
    return w - h * K_SECT


class Layer:
    __slots__ = ("index", "z", "h", "ops", "time_s", "fil_mm", "fan")

    def __init__(self, index, z, h):
        self.index, self.z, self.h = index, z, h
        self.ops = []
        self.time_s = 0.0
        self.fil_mm = 0.0
        self.fan = 0.0


class Plan:
    def __init__(self):
        self.layers = []
        self.warnings = []
        self.support_volume = 0.0
        self.model_volume = 0.0
        self.bridge_layers = 0
        self.support_layers = 0


def rotate_to(loop: np.ndarray, target, mode: str) -> np.ndarray:
    if len(loop) < 3:
        return loop
    dist = np.hypot(loop[:, 0] - target[0], loop[:, 1] - target[1])
    if mode == "corner":
        a = loop - np.roll(loop, 1, axis=0)
        b = np.roll(loop, -1, axis=0) - loop
        turn = np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], a[:, 0] * b[:, 0] + a[:, 1] * b[:, 1])
        i = int(np.argmin(turn + 1e-4 * dist))
    else:
        i = int(np.argmin(dist))
    return np.roll(loop, -i, axis=0)


def medial(region, min_width: float) -> list:
    out = []
    for isl in rg.islands(region):
        piece = rg.union(isl)
        lo, hi = 0.0, 4.0 * min_width + 1.0
        best = None
        for _ in range(8):
            mid = (lo + hi) / 2.0
            got = rg.offset(piece, -mid)
            if got:
                best = got
                lo = mid
            else:
                hi = mid
        if not best:
            continue
        for sl in rg.islands(best):
            outer = rg.floats(sl[0])
            if len(sl) > 1 and len(outer) >= 3:
                out.append((outer, True))
                continue
            if len(outer) < 3:
                continue
            sub_idx = np.linspace(0, len(outer) - 1, min(len(outer), 300)).astype(int)
            sub = outer[sub_idx]
            dd = np.hypot(sub[:, None, 0] - sub[None, :, 0], sub[:, None, 1] - sub[None, :, 1])
            a, b = np.unravel_index(np.argmax(dd), dd.shape)
            a, b = sorted((int(sub_idx[a]), int(sub_idx[b])))
            arc = outer[a:b + 1]
            if len(arc) >= 2:
                out.append((arc, False))
    return out


class Builder:
    def __init__(self, s: dict, stack: list, regions: list, activity):
        self.s = s
        self.stack = stack
        self.R = regions
        self.act = activity
        self.n = len(stack)
        self.afil = math.pi * (s["filament_diameter"] / 2.0) ** 2
        self.plan = Plan()
        self.I = [[] for _ in range(self.n)]
        self.walls = [[] for _ in range(self.n)]
        self.gaps = [[] for _ in range(self.n)]
        self.S = [[] for _ in range(self.n)]
        self.moves = 0
        self.skirt_units = []

    def width(self, li: int, outer: bool) -> float:
        s = self.s
        if li == 0:
            return s["first_layer_width"]
        return s["outer_width"] if outer else s["line_width"]

    def eper(self, w: float, h: float) -> float:
        return section(w, h) * self.s["flow"] / self.afil

    def shells(self, li: int) -> None:
        s = self.s
        h = self.stack[li][1]
        R = self.R[li]
        if not R:
            return
        w_out, w_in = self.width(li, True), self.width(li, False)
        n = s["perimeters"]
        if n == 0:
            self.I[li] = rg.union(R)
            return
        P = rg.clean(rg.offset(R, -w_out / 2.0))
        if not P:
            if s["thin_walls"] and rg.offset(R, -0.2 * w_out):
                self.gaps[li] = medial(R, 0.2 * w_out)
            return
        walls = [P]
        prev = P
        last_w = w_out
        for k in range(1, n):
            d = (w_in + (w_out if k == 1 else w_in)) / 2.0 - h * K_SECT
            P2 = rg.clean(rg.offset(prev, -d))
            if not P2:
                if s["thin_walls"]:
                    left = rg.offset(prev, -w_in / 2.0)
                    if left and rg.offset(left, -0.2 * w_in):
                        self.gaps[li] = medial(left, 0.2 * w_in)
                break
            walls.append(P2)
            prev = P2
            last_w = w_in
        self.walls[li] = walls
        self.I[li] = rg.clean(rg.offset(prev, -(last_w / 2.0 - s["infill_overlap"] / 100.0 * w_in)))

    def skin(self, idx: int, down: bool, count: int) -> list:
        I = self.I[idx]
        if not I or count <= 0:
            return []
        chain = None
        same = True
        for k in range(1, count + 1):
            j = idx - k if down else idx + k
            other = self.I[j] if 0 <= j < self.n else []
            if other != I:
                same = False
            chain = other if chain is None else rg.inter(chain, other)
            if not chain:
                break
        if same:
            return []
        return rg.diff(I, chain) if chain else rg.union(I)

    def build(self) -> Plan:
        s, n, act = self.s, self.n, self.act
        for li in range(n):
            act.check()
            self.shells(li)
            if li % 8 == 0:
                act.step("walls", 0.22 + 0.12 * li / n)
        bridges = [None] * n
        needs = [[] for _ in range(n)]
        for li in range(1, n):
            act.check()
            if self.R[li] == self.R[li - 1] or not self.R[li]:
                continue
            self.overhang(li, bridges, needs)
            if li % 8 == 0:
                act.step("overhangs", 0.34 + 0.08 * li / n)
        self.supports(needs)
        self.plan.bridge_layers = sum(1 for b in bridges if b)
        self.assemble(bridges)
        return self.plan

    def overhang(self, li: int, bridges: list, needs: list) -> None:
        s = self.s
        R = self.R
        h = self.stack[li][1]
        reach = h * math.tan(math.radians(s["support_angle"]))
        prev_exp = rg.offset(R[li - 1], reach + 0.002) if R[li - 1] else []
        F = rg.drop_small(rg.diff(R[li], prev_exp), s["support_min_area"])
        if not F:
            return
        B = rg.diff(R[li], R[li - 1]) if R[li - 1] else rg.union(R[li])
        anchor = rg.offset(R[li - 1], 0.05) if R[li - 1] else []
        grown = rg.offset(F, reach + 0.05)
        bridged, unsup = [], []
        for isl in rg.islands(B):
            part = rg.union(isl)
            if not rg.inter(part, grown):
                continue
            best = self.bridge_angle(rg.union([isl[0]]), anchor) if anchor else None
            if best is not None and best[1] <= s["bridge_max_span"]:
                bridged.append((part, best[0]))
                if s["support"] and s["support_bridges"]:
                    unsup.append(part)
            else:
                unsup.append(part)
        if bridged:
            bridges[li] = bridged
        if unsup:
            if s["support"]:
                needs[li] = [p for part in unsup for p in part]
            else:
                self.plan.warnings.append({"kind": "overhang", "severity": "warning", "message": "An overhang at layer %d (z %.2f mm) has no support and no bridge." % (li, self.stack[li][0]), "where": {"layer": li}})

    def bridge_angle(self, part, anchor):
        x0, y0, x1, y1 = fill.bbox_mm(part)
        probe = max(0.8, min(2.0, max(x1 - x0, y1 - y0) / 40.0))
        best = None
        for ang in range(0, 180, 6):
            segs = fill.lines(part, probe, float(ang))
            if not segs:
                continue
            longest = 0.0
            ok = 0
            for sg in segs:
                a, b = sg[0], sg[-1]
                longest = max(longest, math.hypot(b[0] - a[0], b[1] - a[1]) / rg.S)
                if rg.point_in((a[0] / rg.S, a[1] / rg.S), anchor) and rg.point_in((b[0] / rg.S, b[1] / rg.S), anchor):
                    ok += 1
            if ok >= 0.9 * len(segs) and (best is None or longest < best[1]):
                best = (float(ang), longest)
        return best

    def supports(self, needs: list) -> None:
        s, n = self.s, self.n
        if not s["support"] or not any(needs):
            return
        zg = s["support_z_layers"]
        gap = s["support_xy_gap"]
        w = s["line_width"]
        cache = {}

        def block(k):
            if k < 0 or k >= n or not self.R[k]:
                return []
            if k not in cache:
                cache[k] = rg.offset(self.R[k], gap) if gap > 0 else rg.union(self.R[k])
            return cache[k]

        last = []
        reach = []
        for i in range(n - 1, -1, -1):
            self.act.check()
            add_i = i + 1 + zg
            add = needs[add_i] if add_i < n else []
            if add:
                reach = rg.union(reach, add) if reach else rg.union(add)
            grown = rg.inter(rg.offset(last, 1.5), reach) if last else []
            cand = rg.union(grown, add) if (grown or add) else []
            if cand:
                blockers = []
                for k in range(max(0, i - zg), i + 1):
                    b = block(k)
                    if b:
                        blockers = rg.union(blockers, b) if blockers else b
                cand = rg.diff(cand, blockers) if blockers else rg.union(cand)
            self.S[i] = rg.drop_small(rg.clean(rg.offset(rg.offset(cand, -0.4 * w), 0.4 * w)), 0.6) if cand else []
            last = cand
            if i % 8 == 0:
                self.act.step("supports", 0.42 + 0.1 * (n - i) / n)

    def support_lines(self, i: int, region, h: float, w: float) -> list:
        s = self.s
        weff = spacing_of(w, h)
        out = []
        nif = s["support_interface_layers"]
        iface = []
        if nif > 0:
            chain = None
            for k in range(1, nif + 1):
                other = self.S[i + k] if i + k < self.n else []
                chain = other if chain is None else rg.inter(chain, other)
                if not chain:
                    break
            iface = rg.drop_small(rg.diff(region, chain) if chain else list(region), 0.3)
        sparse = rg.diff(region, iface) if iface else region
        ang = s["infill_angle"] + 90.0
        if iface:
            ls = fill.lines(iface, weff / 0.8, ang + 90.0 * (i % 2))
            if s["support_style"] == "block" and s["support_teeth"] > 0:
                ls = self.dash(ls, s["support_teeth"])
            out.append((INTERFACE, ls))
        if sparse:
            out.append((SUPPORT, fill.lines(sparse, weff * 100.0 / s["support_density"], ang)))
        return out

    def dash(self, lines: list, pitch: float) -> list:
        res = []
        for ln in lines:
            a = np.asarray(ln[0], dtype=np.float64)
            b = np.asarray(ln[-1], dtype=np.float64)
            length = float(np.hypot(*(b - a))) / rg.S
            if length <= pitch:
                res.append(ln)
                continue
            for k in range(int(length // pitch)):
                t0 = (k * pitch) / length
                t1 = min(1.0, (k * pitch + pitch * 0.5) / length)
                res.append([(a + (b - a) * t0).astype(np.int64).tolist(), (a + (b - a) * t1).astype(np.int64).tolist()])
        return res

    def model_units(self, li: int, bridged) -> list:
        s = self.s
        z, h = self.stack[li]
        w_out, w_in = self.width(li, True), self.width(li, False)
        first = li == 0
        sp = (lambda v: min(v, s["speed_first_layer"])) if first else (lambda v: v)
        I = self.I[li]
        units = []
        top_ex = self.skin(li, False, s["top_layers"])
        bot = self.skin(li, True, s["bottom_layers"])
        solid = rg.union(top_ex, bot) if (top_ex and bot) else (top_ex or bot)
        solid = rg.drop_small(solid, 0.4) if solid else []
        sparse = rg.diff(I, solid) if (I and solid) else (rg.union(I) if I else [])
        if sparse and s["solid_area"] > 0:
            keep, tiny = [], []
            for isl in rg.islands(sparse):
                a = abs(rg.pc.Area(isl[0])) - sum(abs(rg.pc.Area(x)) for x in isl[1:])
                (tiny if a / (rg.S ** 2) < s["solid_area"] else keep).extend(isl)
            if tiny:
                solid = rg.union(solid, tiny) if solid else rg.union(tiny)
                sparse = keep
        bridge_parts = []
        if bridged:
            allb = []
            for part, ang in bridged:
                p = rg.inter(rg.offset(part, w_in), I) if I else []
                if p:
                    bridge_parts.append((p, ang))
                    allb = rg.union(allb, p) if allb else p
            if allb:
                solid = rg.diff(solid, allb) if solid else []
                sparse = rg.diff(sparse, allb) if sparse else []
        walls = []
        for k, wl in enumerate(self.walls[li]):
            for p in wl:
                walls.append((k, rg.floats(p)))
        for k, lp in walls:
            units.append(("L", OUTER if k == 0 else INNER, lp, w_out if k == 0 else w_in, sp(s["speed_outer"] if k == 0 else s["speed_inner"]), k))
        for pts, closed in self.gaps[li]:
            units.append(("G", GAPFILL, pts, w_in, sp(s["speed_inner"]), closed))
        if solid:
            spc = spacing_of(w_in, h)
            ang = s["infill_angle"] + (90.0 if li % 2 else 0.0)
            nxt = self.I[li + 1] if li + 1 < self.n else []
            top_now = rg.inter(solid, rg.diff(I, nxt) if nxt else I)
            rest = rg.diff(solid, top_now) if top_now else solid
            if rest:
                units.append(("S", SOLID, fill.lines(rest, spc, ang), w_in, sp(s["speed_solid"])))
            if top_now:
                units.append(("S", TOP, fill.lines(top_now, spc, ang), w_in, sp(s["speed_solid"])))
        for p, ang in bridge_parts:
            ls = fill.lines(p, s["nozzle"], ang)
            if ls:
                units.append(("S", BRIDGE, ls, s["nozzle"], s["speed_bridge"]))
        density = s["infill_density"]
        if sparse and density > 0:
            weff = spacing_of(w_in, h)
            spc = weff * 100.0 / density
            pat = s["infill_pattern"]
            if pat == "rectilinear":
                ls = fill.lines(sparse, spc, s["infill_angle"] + (90.0 if li % 2 else 0.0))
            elif pat == "grid":
                ls = fill.grid(sparse, spc, s["infill_angle"])
            elif pat == "gyroid":
                ls = fill.gyroid(sparse, z - h / 2.0, fill.gyroid_period(weff, density))
            else:
                ls = fill.waves(sparse, fill.gyroid_period(weff, density), spc * 1.2, z, li)
            units.append(("S", SPARSE, ls, w_in, sp(s["speed_infill"])))
        return units

    def support_units(self, li: int) -> list:
        s = self.s
        h = self.stack[li][1]
        reg = self.S[li]
        if not reg:
            return []
        sp = (lambda v: min(v, s["speed_first_layer"])) if li == 0 else (lambda v: v)
        sw = s["line_width"]
        step = spacing_of(sw, h)
        units = []
        nw = s["support_walls"]
        for k in range(nw):
            for lp in rg.offset(reg, -(sw / 2.0 + k * step)):
                units.append(("L", SUPPORT, rg.floats(lp), sw, sp(s["speed_support"])))
        inner = rg.offset(reg, -(sw + (nw - 1) * step - 0.1 * sw)) if nw > 0 else reg
        if inner:
            for feat, ls in self.support_lines(li, inner, h, sw):
                units.append(("S", feat, ls, sw, sp(s["speed_support"])))
        return units

    def skirt(self, base, w: float, h: float) -> None:
        s = self.s
        if not base:
            return
        loops = []
        step = spacing_of(w, h)
        brim_n = int(s["brim_width"] / step) if s["brim_width"] > 0 else 0
        for k in range(brim_n):
            for isl in rg.islands(rg.offset(base, w / 2.0 + k * step)):
                loops.append(rg.floats(isl[0]))
        start = w / 2.0 + brim_n * step + s["skirt_distance"]
        for k in range(s["skirt_loops"]):
            for isl in rg.islands(rg.offset(base, start + k * step)):
                loops.append(rg.floats(isl[0]))
        self.skirt_units = [("L", SKIRT, lp, w, min(s["speed_outer"], s["speed_first_layer"])) for lp in loops]

    def assemble(self, bridges: list) -> None:
        n = self.n
        head = [None]
        for li in range(n):
            self.act.check()
            z, h = self.stack[li]
            L = Layer(li, z, h)
            self.plan.layers.append(L)
            R = self.R[li]
            units = self.model_units(li, bridges[li])
            sup = self.support_units(li)
            if self.S[li]:
                self.plan.support_layers += 1
                self.plan.support_volume += rg.area(self.S[li]) * h
            if li == 0:
                self.skirt(rg.union(R, self.S[0]) if self.S[0] else R, self.width(0, True), h)
                if self.skirt_units:
                    self.run_batch(L, self.paths_of(self.skirt_units), head, h, None)
            tr = rg.offset(R, -self.width(li, True)) if R else []
            self.layer_order(L, units, sup, rg.islands(R), tr, self.S[li], head, h)
            if li % 4 == 0:
                self.act.step("paths", 0.52 + 0.4 * li / n)

    def unit_point(self, u):
        if u[0] in ("L", "G"):
            return (float(u[2][0][0]), float(u[2][0][1]))
        if not u[2]:
            return (0.0, 0.0)
        a, b = u[2][0][0], u[2][0][-1]
        return ((a[0] + b[0]) / 2.0 / rg.S, (a[1] + b[1]) / 2.0 / rg.S)

    def layer_order(self, L, units, sup, islands, tr, sup_region, head, h):
        info = [(abs(rg.pc.Area(isl[0])), isl[0]) for isl in islands]
        buckets = [[] for _ in islands] + [[]]
        for u in units:
            pt = self.unit_point(u)
            ip = [int(round(pt[0] * rg.S)), int(round(pt[1] * rg.S))]
            hit, best = len(islands), None
            for k, (a, outer) in enumerate(info):
                if rg.pc.PointInPolygon(ip, outer) != 0 and (best is None or a < best):
                    hit, best = k, a
            buckets[hit].append(u)
        idx = [k for k, b in enumerate(buckets) if b]
        cur = head[0] or (0.0, 0.0)
        order = []
        while idx:
            k = min(idx, key=lambda q: math.hypot(*(np.subtract(self.unit_point(buckets[q][0]), cur))))
            order.append(k)
            idx.remove(k)
            cur = self.unit_point(buckets[k][0])
        for k in order:
            self.run_units(L, buckets[k], head, h, tr)
        if sup:
            self.run_units(L, sup, head, h, rg.union(tr, sup_region) if (tr and sup_region) else (sup_region or tr))

    def run_units(self, L, units, head, h, tr):
        by_k = {}
        for u in units:
            if u[0] == "L":
                by_k.setdefault(u[5] if len(u) > 5 else 0, []).append(u)
        groups = [by_k[k] for k in sorted(by_k, reverse=self.s["wall_order"] == "inner_first")]
        groups.append([u for u in units if u[0] == "G"])
        for feat in (INTERFACE, SOLID, TOP, BRIDGE, SPARSE, SUPPORT):
            groups.append([u for u in units if u[0] == "S" and u[1] == feat])
        for batch in groups:
            if batch:
                self.run_batch(L, self.paths_of(batch), head, h, tr)

    def paths_of(self, batch):
        s = self.s
        paths = []
        for u in batch:
            kind, feat = u[0], u[1]
            if kind == "L":
                lp = u[2]
                if len(lp) < 3:
                    continue
                if feat in (OUTER, INNER):
                    lp = rotate_to(lp, s["seam_point"], s["seam"])
                paths.append((feat, np.vstack([lp, lp[:1]]), u[3], u[4], True))
            elif kind == "G":
                pts = u[2]
                if len(pts) >= 2:
                    paths.append((feat, np.vstack([pts, pts[:1]]) if u[5] else pts, u[3], u[4], bool(u[5])))
            else:
                for ln in u[2]:
                    arr = rg.floats(ln)
                    if len(arr) >= 2:
                        paths.append((feat, arr, u[3], u[4], False))
        return paths

    def run_batch(self, L, paths, head, h, tr):
        if not paths:
            return
        s0 = np.array([p[1][0] for p in paths])
        s1 = np.array([p[1][-1] for p in paths])
        openm = np.array([not p[4] for p in paths])
        alive = np.ones(len(paths), dtype=bool)
        cur = head[0] or (float(s0[0][0]), float(s0[0][1]))
        for _ in range(len(paths)):
            d0 = np.where(alive, np.hypot(s0[:, 0] - cur[0], s0[:, 1] - cur[1]), np.inf)
            d1 = np.where(alive & openm, np.hypot(s1[:, 0] - cur[0], s1[:, 1] - cur[1]), np.inf)
            i0, i1 = int(np.argmin(d0)), int(np.argmin(d1))
            rev = d1[i1] < d0[i0]
            i = i1 if rev else i0
            alive[i] = False
            feat, pts, width, speed, _closed = paths[i]
            if rev:
                pts = pts[::-1]
            self.extrude(L, feat, pts, width, speed, h, head, tr)
            cur = head[0]

    def extrude(self, L, feat, pts, width, speed, h, head, tr):
        s = self.s
        if self.moves > MAX_MOVES:
            raise SettingError("The toolpath is larger than %d moves; use thicker layers or a lower infill density." % MAX_MOVES)
        p0 = (float(pts[0][0]), float(pts[0][1]))
        cur = head[0]
        if cur is None:
            L.ops.append(("T", p0[0], p0[1], False))
        else:
            dist = math.hypot(p0[0] - cur[0], p0[1] - cur[1])
            if dist > 1e-4:
                retract = dist > s["retract_min_travel"] and s["retract_length"] > 0 and not (tr and rg.line_inside(cur, p0, tr))
                L.ops.append(("T", p0[0], p0[1], bool(retract)))
        if feat == BRIDGE:
            e = math.pi * (s["nozzle"] / 2.0) ** 2 * s["bridge_flow"] / self.afil
        else:
            e = self.eper(width, h)
        L.ops.append(("E", feat, pts, width, speed, e))
        self.moves += len(pts)
        head[0] = (float(pts[-1][0]), float(pts[-1][1]))
