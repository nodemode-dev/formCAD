import math


class Out:
    def __init__(self):
        self.segs = []
        self.arcs = []
        self.polys = []
        self.fills = []
        self.circles = []
        self.blocks = []
        self.text_center = None
        self.text_rot = 0.0
        self.notes = {}

    def seg(self, p, q, role):
        if abs(p[0] - q[0]) > 1e-12 or abs(p[1] - q[1]) > 1e-12:
            self.segs.append((p, q, role))

    def arc(self, c, r, a0, sweep, role):
        if r > 1e-12 and sweep > 1e-12:
            self.arcs.append((c, r, a0, sweep, role))

    def poly(self, pts, closed, role):
        if len(pts) >= 2:
            self.polys.append((pts, closed, role))

    def add_arrow(self, a, role="arrow"):
        for f in a.fills:
            self.fills.append((f, role))
        for pts, closed in a.polys:
            self.polys.append((pts, closed, role))
        for c, r, filled in a.circles:
            self.circles.append((c, r, filled, role))
        for p, q in a.segs:
            self.seg(p, q, role)

    def points(self):
        pts = []
        for p, q, _r in self.segs:
            pts += [p, q]
        for c, r, a0, sw, _role in self.arcs:
            n = max(4, int(sw / 0.2) + 2)
            for i in range(n + 1):
                a = a0 + sw * i / n
                pts.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
        for ps, _c, _r in self.polys:
            pts += list(ps)
        for ps, _r in self.fills:
            pts += list(ps)
        for c, r, _f, _role in self.circles:
            pts += [(c[0] - r, c[1] - r), (c[0] + r, c[1] + r)]
        for b in self.blocks:
            pts += b.corners()
        return pts
