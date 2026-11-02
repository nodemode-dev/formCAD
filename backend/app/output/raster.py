import math

import numpy as np

from app.output.sheet import dash_pieces

SS = 4
BAND = 96
CHUNK = 24.0
MAX_PIXELS = 40000000


class RasterError(Exception):
    pass


def size_for(sheet, dpi, max_pixels=MAX_PIXELS):
    dpi = float(dpi)
    w_in, h_in = sheet.width / 25.4, sheet.height / 25.4
    px = w_in * dpi * h_in * dpi
    if px > max_pixels:
        dpi = math.sqrt(max_pixels / (w_in * h_in))
    if dpi < 20.0:
        raise RasterError("The sheet is too large to draw as an image.")
    return dpi, max(1, int(round(w_in * dpi))), max(1, int(round(h_in * dpi)))


def ring_mask(rings, x0, y0, x1, y1, evenodd):
    w, h = x1 - x0, y1 - y0
    out = np.zeros((h, w), dtype=np.float32)
    edges = []
    for r in rings:
        r = np.asarray(r, dtype=float)
        if len(r) < 3:
            continue
        edges.append(np.hstack([r, np.roll(r, -1, axis=0)]))
    if not edges:
        return out
    e = np.vstack(edges)
    e = e[e[:, 1] != e[:, 3]]
    if not len(e):
        return out
    for by in range(0, h, BAND):
        bh = min(BAND, h - by)
        ya = (y0 + by)
        sub_h = bh * SS
        diff = np.zeros((sub_h, w * SS + 2), dtype=np.int16)
        ex0, ey0, ex1, ey1 = e[:, 0], e[:, 1], e[:, 2], e[:, 3]
        up = ey1 > ey0
        lo = np.where(up, ey0, ey1)
        hi = np.where(up, ey1, ey0)
        dirv = np.where(up, 1, -1)
        j0 = np.ceil((lo - ya) * SS - 0.5).astype(np.int64)
        j1 = np.ceil((hi - ya) * SS - 0.5).astype(np.int64)
        j0 = np.maximum(j0, 0)
        j1 = np.minimum(j1, sub_h)
        cnt = np.maximum(j1 - j0, 0)
        total = int(cnt.sum())
        if total == 0:
            continue
        idx = np.repeat(np.arange(len(e)), cnt)
        starts = np.cumsum(cnt) - cnt
        j = np.arange(total) - np.repeat(starts, cnt) + np.repeat(j0, cnt)
        yy = ya + (j + 0.5) / SS
        t = (yy - ey0[idx]) / (ey1[idx] - ey0[idx])
        xx = ex0[idx] + t * (ex1[idx] - ex0[idx])
        xi = np.floor((xx - x0) * SS + 0.5).astype(np.int64)
        xi = np.clip(xi, 0, w * SS + 1)
        val = np.ones(total, dtype=np.int16) if evenodd else dirv[idx].astype(np.int16)
        np.add.at(diff, (j, xi), val)
        acc = np.cumsum(diff, axis=1)[:, : w * SS]
        inside = (acc % 2 != 0) if evenodd else (acc != 0)
        cov = inside.reshape(bh, SS, w, SS).mean(axis=(1, 3))
        out[by:by + bh] = cov
    return out


class Canvas:
    def __init__(self, sheet, dpi, max_pixels=MAX_PIXELS):
        self.dpi, self.w, self.h = size_for(sheet, dpi, max_pixels)
        self.k = self.dpi / 25.4
        self.height_mm = sheet.height
        self.px = np.full((self.h, self.w, 3), 255, dtype=np.uint8)
        self.clips = []

    def map(self, pts):
        p = np.asarray(pts, dtype=float)
        out = np.empty_like(p)
        out[:, 0] = p[:, 0] * self.k
        out[:, 1] = (self.height_mm - p[:, 1]) * self.k
        return out

    def clip_state(self):
        if not self.clips:
            return (0, 0, self.w, self.h, None)
        return self.clips[-1]

    def push_clip(self, rings, evenodd):
        cur = self.clip_state()
        mp = [self.map(r) for r in rings]
        allp = np.vstack(mp)
        bx0 = max(cur[0], int(math.floor(allp[:, 0].min())))
        by0 = max(cur[1], int(math.floor(allp[:, 1].min())))
        bx1 = min(cur[2], int(math.ceil(allp[:, 0].max())))
        by1 = min(cur[3], int(math.ceil(allp[:, 1].max())))
        if bx1 <= bx0 or by1 <= by0:
            self.clips.append((0, 0, 0, 0, None))
            return
        rect = len(mp) == 1 and len(mp[0]) == 4 and _is_rect(mp[0])
        if rect:
            r = mp[0]
            rx0, ry0 = int(round(r[:, 0].min())), int(round(r[:, 1].min()))
            rx1, ry1 = int(round(r[:, 0].max())), int(round(r[:, 1].max()))
            nx0, ny0, nx1, ny1 = max(cur[0], rx0), max(cur[1], ry0), min(cur[2], rx1), min(cur[3], ry1)
            if nx1 <= nx0 or ny1 <= ny0:
                self.clips.append((0, 0, 0, 0, None))
                return
            mask = None
            if cur[4] is not None:
                mask = _crop(cur, nx0, ny0, nx1, ny1)
            self.clips.append((nx0, ny0, nx1, ny1, mask))
            return
        m = ring_mask(mp, bx0, by0, bx1, by1, evenodd)
        if cur[4] is not None:
            m = m * _crop(cur, bx0, by0, bx1, by1)
        self.clips.append((bx0, by0, bx1, by1, m))

    def pop_clip(self):
        if self.clips:
            self.clips.pop()

    def blend(self, x0, y0, cov, rgb, alpha):
        h, w = cov.shape
        cx0, cy0, cx1, cy1, mask = self.clip_state()
        ax0, ay0 = max(x0, cx0, 0), max(y0, cy0, 0)
        ax1, ay1 = min(x0 + w, cx1, self.w), min(y0 + h, cy1, self.h)
        if ax1 <= ax0 or ay1 <= ay0:
            return
        c = cov[ay0 - y0:ay1 - y0, ax0 - x0:ax1 - x0]
        if mask is not None:
            c = c * mask[ay0 - cy0:ay1 - cy0, ax0 - cx0:ax1 - cx0]
        c = (c * alpha)[:, :, None]
        win = self.px[ay0:ay1, ax0:ax1]
        col = np.array(rgb, dtype=np.float32)[None, None, :]
        win[:] = np.clip(win + (col - win) * c + 0.5, 0, 255).astype(np.uint8)

    def segment(self, p0, p1, hw, cap0, cap1, rgb, alpha, acc=None):
        x0, y0 = p0
        x1, y1 = p1
        pad = hw + 1.5
        bx0 = int(math.floor(min(x0, x1) - pad))
        by0 = int(math.floor(min(y0, y1) - pad))
        bx1 = int(math.ceil(max(x0, x1) + pad))
        by1 = int(math.ceil(max(y0, y1) + pad))
        cx0, cy0, cx1, cy1, _m = self.clip_state()
        bx0, by0, bx1, by1 = max(bx0, cx0, 0), max(by0, cy0, 0), min(bx1, cx1, self.w), min(by1, cy1, self.h)
        if bx1 <= bx0 or by1 <= by0:
            return
        xs = np.arange(bx0, bx1, dtype=np.float32)[None, :] + 0.5
        ys = np.arange(by0, by1, dtype=np.float32)[:, None] + 0.5
        dx, dy = x1 - x0, y1 - y0
        ln = math.hypot(dx, dy)
        if ln < 1e-9:
            d = np.hypot(xs - x0, ys - y0)
            cov = np.clip(hw + 0.5 - d, 0.0, 1.0)
        else:
            ux, uy = dx / ln, dy / ln
            rx, ry = xs - x0, ys - y0
            along = rx * ux + ry * uy
            perp = np.abs(-rx * uy + ry * ux)
            cov = np.clip(hw + 0.5 - perp, 0.0, 1.0)
            lo = {"butt": 0.0, "square": -hw, "round": None}[cap0]
            hi = {"butt": ln, "square": ln + hw, "round": None}[cap1]
            if lo is not None:
                cov = cov * np.clip(along - lo + 0.5, 0.0, 1.0)
            else:
                d0 = np.hypot(rx, ry)
                cov = np.where(along < 0, np.clip(hw + 0.5 - d0, 0.0, 1.0), cov)
            if hi is not None:
                cov = cov * np.clip(hi - along + 0.5, 0.0, 1.0)
            else:
                d1 = np.hypot(xs - x1, ys - y1)
                cov = np.where(along > ln, np.clip(hw + 0.5 - d1, 0.0, 1.0), cov)
        if acc is not None:
            acc.merge(bx0, by0, cov)
        else:
            self.blend(bx0, by0, cov, rgb, alpha)

    def stroke(self, pts, closed, style):
        p = self.map(pts)
        hw = max(style.width * self.k, 1.0) / 2.0
        rgb, alpha = style.rgb, style.alpha
        cap = {0: "butt", 1: "round", 2: "square"}[style.cap]
        if style.dash:
            arr = tuple(v * self.k for v in style.dash[0])
            pieces, dots = dash_pieces(p, closed, arr, style.dash[1] * self.k)
            for piece in pieces:
                self._chain(piece, False, hw, cap, rgb, alpha)
            for d in dots:
                self.segment(d, d, hw, "round", "round", rgb, alpha)
            return
        self._chain(p, closed, hw, cap, rgb, alpha)

    def _chain(self, p, closed, hw, cap, rgb, alpha):
        if closed and len(p) >= 2:
            p = np.vstack([p, p[:1]])
        n = len(p)
        if n == 1:
            self.segment(p[0], p[0], hw, "round", "round", rgb, alpha)
            return
        acc = Acc(self)
        for i in range(n - 1):
            a, b = p[i], p[i + 1]
            c0 = cap if (i == 0 and not closed) else "round"
            c1 = cap if (i == n - 2 and not closed) else "round"
            ln = math.hypot(b[0] - a[0], b[1] - a[1])
            if ln > CHUNK:
                m = int(math.ceil(ln / CHUNK))
                for k in range(m):
                    s = a + (b - a) * (k / m)
                    e = a + (b - a) * ((k + 1) / m)
                    self.segment(s, e, hw, c0 if k == 0 else "round", c1 if k == m - 1 else "round", rgb, alpha, acc)
            else:
                self.segment(a, b, hw, c0, c1, rgb, alpha, acc)
        if acc is not None:
            acc.flush(rgb, alpha)

    def fill(self, rings, style, evenodd):
        mp = [self.map(r) for r in rings if len(r) >= 3]
        if not mp:
            return
        allp = np.vstack(mp)
        cx0, cy0, cx1, cy1, _m = self.clip_state()
        x0 = max(int(math.floor(allp[:, 0].min())), cx0, 0)
        y0 = max(int(math.floor(allp[:, 1].min())), cy0, 0)
        x1 = min(int(math.ceil(allp[:, 0].max())) + 1, cx1, self.w)
        y1 = min(int(math.ceil(allp[:, 1].max())) + 1, cy1, self.h)
        if x1 <= x0 or y1 <= y0:
            return
        cov = ring_mask(mp, x0, y0, x1, y1, evenodd)
        self.blend(x0, y0, cov, style.rgb, style.alpha)


class Acc:
    def __init__(self, canvas):
        self.c = canvas
        self.parts = []

    def merge(self, x0, y0, cov):
        self.parts.append((x0, y0, cov))

    def flush(self, rgb, alpha):
        if not self.parts:
            return
        x0 = min(p[0] for p in self.parts)
        y0 = min(p[1] for p in self.parts)
        x1 = max(p[0] + p[2].shape[1] for p in self.parts)
        y1 = max(p[1] + p[2].shape[0] for p in self.parts)
        if len(self.parts) == 1 or (x1 - x0) * (y1 - y0) > 8000000:
            for x, y, c in self.parts:
                self.c.blend(x, y, c, rgb, alpha)
            return
        buf = np.zeros((y1 - y0, x1 - x0), dtype=np.float32)
        for x, y, c in self.parts:
            sl = buf[y - y0:y - y0 + c.shape[0], x - x0:x - x0 + c.shape[1]]
            np.maximum(sl, c, out=sl)
        self.c.blend(x0, y0, buf, rgb, alpha)


def _is_rect(r):
    xs = np.unique(np.round(r[:, 0], 6))
    ys = np.unique(np.round(r[:, 1], 6))
    return len(xs) == 2 and len(ys) == 2


def _crop(state, x0, y0, x1, y1):
    sx0, sy0, sx1, sy1, mask = state
    return mask[y0 - sy0:y1 - sy0, x0 - sx0:x1 - sx0]


def render(sheet, dpi=300.0, max_pixels=MAX_PIXELS):
    from app.output.sheet import rect_ring

    cv = Canvas(sheet, dpi, max_pixels)

    cv.push_clip([rect_ring(sheet.printable)], False)
    for op in sheet.ops:
        kind = op[0]
        if kind == "S":
            cv.stroke(op[1], op[2], op[3])
        elif kind == "F":
            cv.fill(op[1], op[2], op[3])
        elif kind == "C":
            cv.push_clip(op[1], op[2])
        elif kind == "E":
            cv.pop_clip()
    alpha = np.full((cv.h, cv.w, 1), 255, dtype=np.uint8)
    return np.concatenate([cv.px, alpha], axis=2), cv.dpi
