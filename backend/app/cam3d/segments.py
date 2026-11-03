import math

import numpy as np

from app.cam import toolpath as T


class Segments:
    def __init__(self):
        self.p0 = []
        self.p1 = []
        self.rapid = []
        self.feed = []
        self.tool = []
        self.op = []
        self.move = []
        self.ax = []
        self.abc = []
        self.count = 0

    def add(self, a, b, rapid, feed, tool, op, move, ax=None, abc=None):
        self.p0.append(a)
        self.p1.append(b)
        self.rapid.append(rapid)
        self.feed.append(feed)
        self.tool.append(tool)
        self.op.append(op)
        self.move.append(move)
        self.ax.append(ax)
        self.abc.append(abc)
        self.count += 1

    def arrays(self):
        n = self.count
        out = {
            "p0": np.asarray(self.p0, dtype=float).reshape(n, 3),
            "p1": np.asarray(self.p1, dtype=float).reshape(n, 3),
            "rapid": np.asarray(self.rapid, dtype=bool),
            "feed": np.asarray(self.feed, dtype=float),
            "tool": np.asarray(self.tool, dtype=np.int64),
            "op": np.asarray(self.op, dtype=np.int64),
            "move": np.asarray(self.move, dtype=np.int64),
        }
        has = any(a is not None for a in self.ax)
        if has:
            out["ax"] = np.asarray([a if a is not None else (0.0, 0.0, 1.0) for a in self.ax], dtype=float).reshape(n, 3)
        else:
            out["ax"] = None
        has_abc = any(a is not None for a in self.abc)
        out["abc"] = np.asarray([a if a is not None else (np.nan, np.nan, np.nan) for a in self.abc], dtype=float).reshape(n, 3) if has_abc else None
        return out


def from_moves(seg: Segments, moves: list, op_index: int, arc_tol: float = 0.01, start=None, tool=0, limit=2_000_000):
    pos = tuple(start) if start is not None else None
    cur_tool = tool
    cur_ax = None
    cur_abc = None
    for mi, m in enumerate(moves):
        kind = m[0]
        if seg.count > limit:
            raise ValueError("The toolpath has more than %d segments." % limit)
        if kind in ("rapid", "feed"):
            end = (float(m[1]), float(m[2]), float(m[3]))
            opts = T.opts_of(m)
            if "ax" in opts:
                cur_ax = tuple(float(v) for v in opts["ax"])
            elif "abc" not in opts:
                cur_ax = cur_ax
            if "abc" in opts:
                cur_abc = tuple(float(v) for v in opts["abc"])
            if pos is not None and math.dist(pos, end) > 1e-12:
                seg.add(pos, end, kind == "rapid", float(m[4]) if kind == "feed" else 0.0, cur_tool, op_index, mi, cur_ax, cur_abc)
            pos = end
        elif kind == "arc":
            if pos is None:
                continue
            opts = T.opts_of(m)
            if "ax" in opts:
                cur_ax = tuple(float(v) for v in opts["ax"])
            prev = pos
            for p in T.arc_points(pos, m, arc_tol):
                if math.dist(prev, p) > 1e-12:
                    seg.add(prev, p, False, float(m[8]), cur_tool, op_index, mi, cur_ax, cur_abc)
                prev = p
            pos = prev
        elif kind == "cycle":
            _, ck, x, y, zb, zr, q, p, f = m[:9]
            top = (float(x), float(y), float(zr))
            if pos is not None and math.dist(pos, top) > 1e-12:
                seg.add(pos, top, True, 0.0, cur_tool, op_index, mi)
            peck = float(q) if q else 0.0
            if ck in ("peck", "chip") and peck > 0:
                z = float(zr)
                start = float(zr)
                while z > float(zb) + 1e-9:
                    z2 = max(z - peck, float(zb))
                    seg.add((float(x), float(y), start), (float(x), float(y), z2), False, float(f), cur_tool, op_index, mi)
                    seg.add((float(x), float(y), z2), top, True, 0.0, cur_tool, op_index, mi)
                    if z2 > float(zb) + 1e-9:
                        start = z2 + 0.254
                        seg.add(top, (float(x), float(y), start), True, 0.0, cur_tool, op_index, mi)
                    z = z2
            else:
                seg.add(top, (float(x), float(y), float(zb)), False, float(f), cur_tool, op_index, mi)
                seg.add((float(x), float(y), float(zb)), top, True, 0.0, cur_tool, op_index, mi)
            pos = top
        elif kind == "tool":
            cur_tool = int(m[1])
    return pos, cur_tool
