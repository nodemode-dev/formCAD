import heapq
import math
import time

import numpy as np

from app.pcb import drc
from app.pcb import geom as G
from app.pcb import jobs
from app.pcb import model as M
from app.pcb import rules as R
from app.pcb import zones as Z

LAYERS = ("F.Cu", "B.Cu")
DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1))


class Router:
    def __init__(self, h: dict, act, opts: dict, runner=None):
        self.h = h
        self.act = act
        self.runner = runner
        self.eff = R.effective(h["rules"])
        classes = h["rules"].get("classes", {})
        self.clr = max([self.eff["clearance"]] + [c.get("clearance", 0.0) for c in classes.values()])
        widths = {}
        for net, spec in classes.items():
            widths[net] = spec.get("width", self.eff["track_width"])
        base_w = float(opts.get("width") or self.eff["track_width"])
        self.base_w = max(base_w, self.eff["track_width"])
        self.widths = {n: max(w, self.eff["track_width"]) for n, w in widths.items()}
        self.hw = max([self.base_w] + list(self.widths.values())) / 2.0
        self.via_dia = float(opts.get("via_dia") or self.eff["via_dia"])
        self.via_drill = float(opts.get("via_drill") or self.eff["via_drill"])
        if (self.via_dia - self.via_drill) / 2.0 < self.eff["annular_ring"]:
            self.via_dia = self.via_drill + 2.0 * self.eff["annular_ring"]
        self.via_r = self.via_dia / 2.0
        self.pitch = float(opts.get("pitch") or 0.1)
        if not 0.02 <= self.pitch <= 1.0:
            raise jobs.PcbError("The routing grid pitch is between 0.02 and 1 mm.")
        self.via_cost = float(opts.get("via_cost", 2.5))
        self.passes = max(1, min(int(opts.get("passes", 6)), 20))
        self.margin = self.pitch * 0.25
        self.max_expand = min(int(opts.get("max_expansions") or jobs.cap("expansions", runner)), jobs.cap("expansions", runner))
        self.max_rips = min(int(opts.get("max_rips") or 60), jobs.cap("rips", runner))
        if h["board"]["layers"] != 2:
            raise jobs.PcbError("The autorouter handles two-layer boards; this board has %d copper layers." % h["board"]["layers"])
        self.build_grid()

    def build_grid(self):
        h = self.h
        outline = h["board"]["outline"]
        if len(outline) < 3:
            raise jobs.PcbError("Draw the board outline before routing.")
        x0, y0, x1, y1 = G.bbox(outline)
        self.x0, self.y0 = x0, y0
        p = self.pitch
        self.nx = int(math.floor((x1 - x0) / p)) + 1
        self.ny = int(math.floor((y1 - y0) / p)) + 1
        cells = self.nx * self.ny * 2
        if cells > jobs.cap("grid_cells", self.runner):
            raise jobs.PcbError("The routing grid would hold %d cells, over the limit of %d. Use a coarser pitch or a smaller board." % (cells, jobs.cap("grid_cells", self.runner)))
        shape = (2, self.ny, self.nx)
        self.static_t = np.zeros(shape, dtype=bool)
        self.static_v = np.zeros(shape, dtype=bool)
        self.pad_t = np.zeros(shape, dtype=np.int16)
        self.pad_v = np.zeros(shape, dtype=np.int16)
        self.rt_t = np.zeros(shape, dtype=np.int16)
        self.rt_v = np.zeros(shape, dtype=np.int16)
        self.xs_all = self.x0 + np.arange(self.nx) * p
        self.ys_all = self.y0 + np.arange(self.ny) * p
        self.pstamps = {}
        self.rstamps = {}
        self.pads = M.all_pads(h)
        self.routed = {}
        self.fixed_edge()
        for k in h["keepouts"]:
            self.keepout(k)
        for it in self.pads:
            self.add_fixed(it)
        for hh in h["holes"]:
            it = M.hole_item(hh)
            if not hh.get("plated"):
                it = dict(it, shape=("cap", (hh["x"], hh["y"]), (hh["x"], hh["y"]), hh["drill"] / 2.0), layers=list(LAYERS))
            self.add_fixed(it)
        for t in h["tracks"]:
            self.add_fixed(M.track_item(t))
        for v in h["vias"]:
            self.add_fixed(M.via_item(v, M.via_layers(h, v)))

    def window(self, bb):
        ix0 = max(0, int(math.floor((bb[0] - self.x0) / self.pitch)))
        ix1 = min(self.nx - 1, int(math.ceil((bb[2] - self.x0) / self.pitch)))
        iy0 = max(0, int(math.floor((bb[1] - self.y0) / self.pitch)))
        iy1 = min(self.ny - 1, int(math.ceil((bb[3] - self.y0) / self.pitch)))
        if ix1 < ix0 or iy1 < iy0:
            return None
        return ix0, ix1, iy0, iy1

    def masks(self, item, clr):
        shape = item["shape"]
        reach = clr + max(self.hw, self.via_r) + self.margin + (self.eff["hole_to_hole"] + self.via_drill + item.get("drill", 0.0) if item.get("drill") else 0.0)
        win = self.window(M.shape_bbox(shape, reach))
        if win is None:
            return None
        ix0, ix1, iy0, iy1 = win
        xs, ys = np.meshgrid(self.xs_all[ix0:ix1 + 1], self.ys_all[iy0:iy1 + 1])
        ds = M.shape_field(shape, xs, ys)
        tm = ds < clr + self.hw + self.margin
        vm = ds < clr + self.via_r + self.margin
        if item.get("drill"):
            dh = np.hypot(xs - item["x"], ys - item["y"]) - item["drill"] / 2.0
            vm = vm | (dh < self.eff["hole_to_hole"] + self.via_drill / 2.0 + self.margin)
        return iy0, ix0, tm, vm

    def add_fixed(self, item):
        net = item["net"]
        clr = self.clr
        res = self.masks(item, clr)
        if res is None:
            return
        iy0, ix0, tm, vm = res
        for lname in item["layers"]:
            if lname not in LAYERS:
                continue
            l = LAYERS.index(lname)
            h, w = tm.shape
            if net == "":
                self.static_t[l, iy0:iy0 + h, ix0:ix0 + w] |= tm
                self.static_v[l, iy0:iy0 + h, ix0:ix0 + w] |= vm
            else:
                self.pad_t[l, iy0:iy0 + h, ix0:ix0 + w] += tm
                self.pad_v[l, iy0:iy0 + h, ix0:ix0 + w] += vm
                self.pstamps.setdefault(net, []).append((l, iy0, ix0, tm, vm))

    def fixed_edge(self):
        e = self.eff["edge_clearance"]
        outline = M.outline_loops(self.h)
        xs, ys = np.meshgrid(self.xs_all, self.ys_all)
        inside = G.poly_inside_field(xs, ys, outline[0])
        for c in outline[1:]:
            inside &= ~G.poly_inside_field(xs, ys, c)
        dist = np.full(xs.shape, 1e9)
        reach = e + max(self.hw, self.via_r) + self.margin + 1.0
        for loop in outline:
            for a, b in G.poly_edges(loop):
                win = self.window((min(a[0], b[0]) - reach, min(a[1], b[1]) - reach, max(a[0], b[0]) + reach, max(a[1], b[1]) + reach))
                if win is None:
                    continue
                ix0, ix1, iy0, iy1 = win
                f = G.seg_dist_field(xs[iy0:iy1 + 1, ix0:ix1 + 1], ys[iy0:iy1 + 1, ix0:ix1 + 1], a, b)
                dist[iy0:iy1 + 1, ix0:ix1 + 1] = np.minimum(dist[iy0:iy1 + 1, ix0:ix1 + 1], f)
        tm = (~inside) | (dist < e + self.hw + self.margin)
        vm = (~inside) | (dist < e + self.via_r + self.margin)
        for l in range(2):
            self.static_t[l] |= tm
            self.static_v[l] |= vm

    def keepout(self, k):
        poly = [tuple(p) for p in k["polygon"]]
        win = self.window(G.bbox(poly))
        if win is None:
            return
        ix0, ix1, iy0, iy1 = win
        xs, ys = np.meshgrid(self.xs_all[ix0:ix1 + 1], self.ys_all[iy0:iy1 + 1])
        inside = G.poly_inside_field(xs, ys, poly)
        edge = np.full(xs.shape, 1e9)
        for a, b in G.poly_edges(poly):
            edge = np.minimum(edge, G.seg_dist_field(xs, ys, a, b))
        tm = inside | (edge < self.hw + self.margin)
        vm = inside | (edge < self.via_r + self.margin)
        for lname in k["layers"]:
            if lname in LAYERS:
                l = LAYERS.index(lname)
                if k["tracks"]:
                    self.static_t[l, iy0:iy1 + 1, ix0:ix1 + 1] |= tm
                if k["vias"]:
                    self.static_v[l, iy0:iy1 + 1, ix0:ix1 + 1] |= vm

    def apply(self, stamps, sign, tmap, vmap):
        for l, iy0, ix0, tm, vm in stamps:
            h, w = tm.shape
            if sign > 0:
                tmap[l, iy0:iy0 + h, ix0:ix0 + w] += tm
                vmap[l, iy0:iy0 + h, ix0:ix0 + w] += vm
            else:
                tmap[l, iy0:iy0 + h, ix0:ix0 + w] -= tm
                vmap[l, iy0:iy0 + h, ix0:ix0 + w] -= vm

    def node_xy(self, ix, iy):
        return self.x0 + ix * self.pitch, self.y0 + iy * self.pitch

    def cell_of(self, x, y):
        return int(round((x - self.x0) / self.pitch)), int(round((y - self.y0) / self.pitch))

    def pad_cells(self, item, tblock):
        cells = []
        win = self.window(M.shape_bbox(item["shape"], 0.0))
        if win is None:
            return cells
        ix0, ix1, iy0, iy1 = win
        xs, ys = np.meshgrid(self.xs_all[ix0:ix1 + 1], self.ys_all[iy0:iy1 + 1])
        ds = M.shape_field(item["shape"], xs, ys)
        inside = ds <= 0.0
        for lname in item["layers"]:
            if lname not in LAYERS:
                continue
            l = LAYERS.index(lname)
            ok = inside & ~tblock[l, iy0:iy1 + 1, ix0:ix1 + 1]
            ys_i, xs_i = np.nonzero(ok)
            for yy, xx in zip(ys_i, xs_i):
                cells.append((l, int(xx) + ix0, int(yy) + iy0))
        if not cells:
            cx, cy = self.cell_of(item["x"], item["y"])
            best = None
            for l in range(2):
                if LAYERS[l] not in item["layers"]:
                    continue
                for dy in range(-4, 5):
                    for dx in range(-4, 5):
                        ix, iy = cx + dx, cy + dy
                        if 0 <= ix < self.nx and 0 <= iy < self.ny and not tblock[l, iy, ix]:
                            d = dx * dx + dy * dy
                            if best is None or d < best[0]:
                                best = (d, l, ix, iy)
            if best:
                cells.append((best[1], best[2], best[3]))
        return cells

    def search(self, sources, targets, goal_xy, goal_r, hard_t, hard_v, soft_t, soft_v, soft_cost):
        nx, ny = self.nx, self.ny
        plane = nx * ny
        p = self.pitch
        tgt = set(targets)
        if not sources or not tgt:
            return None, 0
        gx, gy = goal_xy
        heap = []
        g = {}
        came = {}
        for s in sources:
            g[s] = 0.0
            heapq.heappush(heap, (self.hcost(s, gx, gy, goal_r), 0.0, s))
        expanded = 0
        diag = p * 1.4142
        via_cost = self.via_cost
        while heap:
            f, gc, node = heapq.heappop(heap)
            if gc > g.get(node, 1e18):
                continue
            if node in tgt:
                path = [node]
                while node in came:
                    node = came[node]
                    path.append(node)
                path.reverse()
                return path, expanded
            expanded += 1
            if expanded > self.max_expand:
                return None, expanded
            if expanded & 2047 == 0:
                self.act.check()
            l, rem = divmod(node, plane)
            iy, ix = divmod(rem, nx)
            ht = hard_t[l]
            st = soft_t[l] if soft_t is not None else None
            horiz = (l == 0)
            for dx, dy in DIRS:
                jx, jy = ix + dx, iy + dy
                if jx < 0 or jy < 0 or jx >= nx or jy >= ny:
                    continue
                j = jy * nx + jx
                if ht[j]:
                    continue
                if dx and dy:
                    if ht[iy * nx + jx] or ht[jy * nx + ix]:
                        continue
                    c = diag * 1.1
                elif dx:
                    c = p if horiz else p * 1.45
                else:
                    c = p * 1.45 if horiz else p
                if st is not None and st[j]:
                    c += soft_cost
                nn = l * plane + j
                ng = gc + c
                if ng < g.get(nn, 1e18):
                    g[nn] = ng
                    came[nn] = node
                    heapq.heappush(heap, (ng + self.hcost(nn, gx, gy, goal_r), ng, nn))
            o = (1 - l) * plane + rem
            if not hard_v[l][rem] and not hard_v[1 - l][rem] and not hard_t[1 - l][rem]:
                c = via_cost
                if soft_v is not None and (soft_v[l][rem] or soft_v[1 - l][rem]):
                    c += soft_cost
                ng = gc + c
                if ng < g.get(o, 1e18):
                    g[o] = ng
                    came[o] = node
                    heapq.heappush(heap, (ng + self.hcost(o, gx, gy, goal_r), ng, o))
        return None, expanded

    def hcost(self, node, gx, gy, gr):
        rem = node % (self.nx * self.ny)
        iy, ix = divmod(rem, self.nx)
        dx = abs(self.x0 + ix * self.pitch - gx)
        dy = abs(self.y0 + iy * self.pitch - gy)
        d = max(dx, dy) + 0.4142 * min(dx, dy) - gr
        return d if d > 0 else 0.0

    def flat(self, arr):
        return [bytes(arr[l].astype(bool).tobytes()) for l in range(2)]

    def route_net(self, net, groups, soft=False):
        own_p = self.pstamps.get(net, [])
        own_r = self.rstamps.get(net, [])
        self.apply(own_p, -1, self.pad_t, self.pad_v)
        self.apply(own_r, -1, self.rt_t, self.rt_v)
        try:
            hard_t_arr = self.static_t | (self.pad_t > 0)
            hard_v_arr = self.static_v | (self.pad_v > 0)
            if soft:
                soft_t_arr = self.rt_t > 0
                soft_v_arr = self.rt_v > 0
            else:
                hard_t_arr = hard_t_arr | (self.rt_t > 0)
                hard_v_arr = hard_v_arr | (self.rt_v > 0)
                soft_t_arr = soft_v_arr = None
            hard_t = self.flat(hard_t_arr.reshape(2, -1))
            hard_v = self.flat(hard_v_arr.reshape(2, -1))
            st = self.flat(soft_t_arr.reshape(2, -1)) if soft_t_arr is not None else None
            sv = self.flat(soft_v_arr.reshape(2, -1)) if soft_v_arr is not None else None
            plane = self.nx * self.ny
            padcells = {}
            for gi, grp in enumerate(groups):
                for it in grp:
                    for (l, ix, iy) in self.pad_cells(it, hard_t_arr):
                        padcells.setdefault(id(it), []).append(l * plane + iy * self.nx + ix)
            tree_pads = list(groups[0])
            tree = set()
            for it in tree_pads:
                tree.update(padcells.get(id(it), []))
            remaining = [list(g) for g in groups[1:]]
            segs = []
            vias = []
            blockers = set()
            while remaining:
                best = None
                for gi, grp in enumerate(remaining):
                    for it in grp:
                        for tp in tree_pads:
                            d = math.hypot(it["x"] - tp["x"], it["y"] - tp["y"])
                            if best is None or d < best[0]:
                                best = (d, gi, it)
                _, gi, goal = best
                tgt = set()
                for it in remaining[gi]:
                    tgt.update(padcells.get(id(it), []))
                if not tree or not tgt:
                    return None, "No free grid cell inside a pad of net %s (a pad is blocked by neighbouring copper)." % net, blockers
                gr = max(goal["w"], goal["h"]) / 2.0
                path, n = self.search(tree, tgt, (goal["x"], goal["y"]), gr, hard_t, hard_v, st, sv, 40.0)
                if path is None:
                    return None, "No path for net %s between %s.%s and the rest of the net (%d nodes searched)." % (net, goal["ref"], goal["number"], n), blockers
                if soft:
                    for node in path:
                        l, rem = divmod(node, plane)
                        if self.rt_t[l].reshape(-1)[rem]:
                            blockers.add((l, rem))
                s, v = self.path_geometry(net, path, padcells, tree_pads + remaining[gi])
                segs.extend(s)
                vias.extend(v)
                tree.update(path)
                tree.update(tgt)
                tree_pads.extend(remaining.pop(gi))
            return (segs, vias), "", blockers
        finally:
            self.apply(own_p, 1, self.pad_t, self.pad_v)
            self.apply(own_r, 1, self.rt_t, self.rt_v)

    def path_geometry(self, net, path, padcells, pads):
        plane = self.nx * self.ny
        pts = []
        for node in path:
            l, rem = divmod(node, plane)
            iy, ix = divmod(rem, self.nx)
            x, y = self.node_xy(ix, iy)
            pts.append((l, round(x, 5), round(y, 5)))
        owner = {}
        for it in pads:
            for c in padcells.get(id(it), []):
                owner.setdefault(c, it)
        segs = []
        vias = []
        first = path[0]
        if first in owner:
            it = owner[first]
            l, x, y = pts[0]
            if math.hypot(it["x"] - x, it["y"] - y) > 1e-6:
                segs.append((l, (round(it["x"], 5), round(it["y"], 5)), (x, y)))
        last = path[-1]
        if last in owner:
            it = owner[last]
            l, x, y = pts[-1]
            if math.hypot(it["x"] - x, it["y"] - y) > 1e-6:
                segs.append((l, (x, y), (round(it["x"], 5), round(it["y"], 5))))
        start = 0
        for i in range(1, len(pts)):
            if pts[i][0] != pts[i - 1][0]:
                if i - 1 > start:
                    segs.extend(self.merge(pts[start:i]))
                vias.append((pts[i][1], pts[i][2]))
                start = i
        if len(pts) - 1 > start:
            segs.extend(self.merge(pts[start:]))
        return segs, vias

    def merge(self, pts):
        out = []
        l = pts[0][0]
        a = (pts[0][1], pts[0][2])
        prev = a
        dirv = None
        for k in range(1, len(pts)):
            cur = (pts[k][1], pts[k][2])
            d = (round(cur[0] - prev[0], 4), round(cur[1] - prev[1], 4))
            if d == (0, 0):
                continue
            norm = math.hypot(*d)
            d = (round(d[0] / norm, 3), round(d[1] / norm, 3))
            if dirv is not None and d != dirv:
                out.append((l, a, prev))
                a = prev
            dirv = d
            prev = cur
        if prev != a:
            out.append((l, a, prev))
        return out

    def commit_net(self, net, segs, vias):
        width = self.widths.get(net, self.base_w)
        stamps = []
        for l, a, b in segs:
            it = {"net": net, "shape": ("cap", a, b, width / 2.0), "layers": [LAYERS[l]], "kind": "track"}
            res = self.masks(it, self.clr)
            if res is not None:
                iy0, ix0, tm, vm = res
                stamps.append((l, iy0, ix0, tm, vm))
        for x, y in vias:
            it = {"net": net, "shape": ("cap", (x, y), (x, y), self.via_r), "layers": list(LAYERS), "kind": "via", "x": x, "y": y, "drill": self.via_drill}
            res = self.masks(it, self.clr)
            if res is not None:
                iy0, ix0, tm, vm = res
                for l in range(2):
                    stamps.append((l, iy0, ix0, tm, vm))
        self.apply(stamps, 1, self.rt_t, self.rt_v)
        self.rstamps.setdefault(net, []).extend(stamps)
        self.routed.setdefault(net, {"segs": [], "vias": []})
        self.routed[net]["segs"].extend(segs)
        self.routed[net]["vias"].extend(vias)

    def rip(self, net):
        stamps = self.rstamps.pop(net, [])
        self.apply(stamps, -1, self.rt_t, self.rt_v)
        self.routed.pop(net, None)

    def owners_of(self, blocked_cells, exclude):
        hit = set()
        for net, stamps in self.rstamps.items():
            if net == exclude:
                continue
            for l, iy0, ix0, tm, vm in stamps:
                h, w = tm.shape
                for (bl, rem) in blocked_cells:
                    if bl != l:
                        continue
                    iy, ix = divmod(rem, self.nx)
                    if iy0 <= iy < iy0 + h and ix0 <= ix < ix0 + w and tm[iy - iy0, ix - ix0]:
                        hit.add(net)
                        break
                if net in hit:
                    break
        return hit


def net_groups(h: dict, fills: list):
    items = [i for i in M.copper_items(h) if i["layers"]]
    items, find = drc.connectivity(h, fills, items)
    nets = {}
    for i, it in enumerate(items):
        if it["kind"] == "pad" and it["net"]:
            nets.setdefault(it["net"], {}).setdefault(find(i), []).append(it)
    return {n: list(g.values()) for n, g in nets.items() if len(g) > 1}


def hpwl(groups):
    pts = [p for g in groups for p in g]
    xs = [p["x"] for p in pts]
    ys = [p["y"] for p in pts]
    return (max(xs) - min(xs)) + (max(ys) - min(ys))


def autoroute(h: dict, act, opts: dict, runner=None) -> dict:
    t0 = time.time()
    only = opts.get("nets")
    fills = Z.fill_all(h) if h["zones"] else []
    todo = net_groups(h, fills)
    if only:
        todo = {n: g for n, g in todo.items() if n in set(only)}
    if len(todo) > jobs.cap("nets", runner):
        raise jobs.PcbError("The board has %d nets to route, over the limit of %d." % (len(todo), jobs.cap("nets", runner)))
    if len(M.all_pads(h)) > jobs.cap("pads", runner):
        raise jobs.PcbError("The board has more than %d pads, over the limit." % jobs.cap("pads", runner))
    act.step("grid", 0.02)
    router = Router(h, act, opts, runner)
    order = sorted(todo, key=lambda n: (hpwl(todo[n]), n))
    queue = list(order)
    failed = {}
    rips = 0
    attempts = {}
    expansions_note = []
    total = max(1, len(order))
    done_count = 0
    while queue:
        net = queue.pop(0)
        attempts[net] = attempts.get(net, 0) + 1
        act.step("routing %s" % net, 0.05 + 0.85 * done_count / total)
        res, why, _ = router.route_net(net, todo[net])
        if res is None and rips < router.max_rips and attempts[net] <= router.passes:
            res2, why2, blockers = router.route_net(net, todo[net], soft=True)
            if res2 is not None:
                culprits = router.owners_of(blockers, net)
                if culprits and rips + len(culprits) <= router.max_rips + 5:
                    for c in culprits:
                        router.rip(c)
                        rips += 1
                        if c not in queue:
                            queue.append(c)
                        failed.pop(c, None)
                    res, why, _ = router.route_net(net, todo[net])
        if res is None:
            failed[net] = why
            continue
        router.commit_net(net, res[0], res[1])
        done_count += 1
        failed.pop(net, None)
    act.step("finishing", 0.95)
    tracks = []
    vias = []
    for net, rec in router.routed.items():
        w = router.widths.get(net, router.base_w)
        for l, a, b in rec["segs"]:
            tracks.append({"net": net, "layer": LAYERS[l], "width": w, "a": [a[0], a[1]], "b": [b[0], b[1]]})
        for x, y in rec["vias"]:
            vias.append({"net": net, "x": x, "y": y, "dia": router.via_dia, "drill": router.via_drill, "from": "F.Cu", "to": "B.Cu"})
    return {"tracks": tracks, "vias": vias, "nets_total": len(order), "nets_routed": len(router.routed), "failed": failed, "rips": rips, "pitch": router.pitch, "grid": [router.nx, router.ny], "seconds": round(time.time() - t0, 3)}
