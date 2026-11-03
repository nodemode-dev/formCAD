import base64
import struct
import zlib

import numpy as np
from scipy.ndimage import binary_erosion

W, H = 144, 108


def png(rgba: np.ndarray) -> bytes:
    h, w, _c = rgba.shape
    raw = b"".join(b"\x00" + rgba[y].tobytes() for y in range(h))

    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def render(solid3: np.ndarray, tint=(122, 162, 214)) -> str:
    s = np.pad(solid3.astype(bool), 1)
    surf = s & ~binary_erosion(s, iterations=1)
    k, j, i = np.nonzero(surf)
    img = np.zeros((H, W, 4), dtype=np.uint8)
    if not len(k):
        return base64.b64encode(png(img)).decode("ascii")
    pts = np.stack([i, j, k], axis=1).astype(float) - np.array(s.shape[::-1], dtype=float)[None, :] / 2.0
    az, el = np.radians(35.0), np.radians(28.0)
    ca, sa, ce, se = np.cos(az), np.sin(az), np.cos(el), np.sin(el)
    x = pts[:, 0] * ca - pts[:, 1] * sa
    y0 = pts[:, 0] * sa + pts[:, 1] * ca
    y = pts[:, 2] * ce - y0 * se
    d = y0 * ce + pts[:, 2] * se
    span = max(float(np.ptp(x)), float(np.ptp(y)), 1.0)
    scale = 0.86 * min(W, H) / span * 1.15
    px = np.round(W / 2 + (x - (x.max() + x.min()) / 2) * scale).astype(int)
    py = np.round(H / 2 - (y - (y.max() + y.min()) / 2) * scale).astype(int)
    up = ~s[k + 1, j, i]
    side = ~s[k, j + 1, i] | ~s[k, j, i + 1]
    shade = np.where(up, 1.0, np.where(side, 0.72, 0.52))
    depth = (d - d.min()) / max(1e-9, float(np.ptp(d)))
    shade = shade * (0.78 + 0.22 * (1.0 - depth))
    order = np.argsort(-d)
    r = max(1, int(np.ceil(scale * 0.9)))
    for dy in range(r):
        for dx in range(r):
            xx = np.clip(px[order] + dx - r // 2, 0, W - 1)
            yy = np.clip(py[order] + dy - r // 2, 0, H - 1)
            sh = shade[order]
            img[yy, xx, 0] = np.clip(tint[0] * sh, 0, 255).astype(np.uint8)
            img[yy, xx, 1] = np.clip(tint[1] * sh, 0, 255).astype(np.uint8)
            img[yy, xx, 2] = np.clip(tint[2] * sh, 0, 255).astype(np.uint8)
            img[yy, xx, 3] = 255
    return base64.b64encode(png(img)).decode("ascii")
