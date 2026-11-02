import colorsys
import re

BASIC = {
    1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255), 7: (255, 255, 255),
    8: (128, 128, 128), 9: (192, 192, 192),
}
LEVELS = (255, 165, 127, 76, 38)
GREYS = (51, 91, 132, 173, 214, 255)
HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _build():
    table = [(0, 0, 0)] * 256
    for k, v in BASIC.items():
        table[k] = v
    for idx in range(10, 250):
        hue = ((idx - 10) // 10) * 15.0 / 360.0
        step = idx % 10
        value = LEVELS[step // 2]
        sat = 1.0 if step % 2 == 0 else 0.5
        r, g, b = colorsys.hsv_to_rgb(hue, sat, 1.0)
        table[idx] = (int(r * value + 1e-6), int(g * value + 1e-6), int(b * value + 1e-6))
    for i, g in enumerate(GREYS):
        table[250 + i] = (g, g, g)
    return table


TABLE = _build()
WHITE = (255, 255, 255)


def index_rgb(n):
    if 1 <= n <= 255:
        return TABLE[n]
    return WHITE


def true_rgb(value):
    if isinstance(value, (list, tuple)) and len(value) == 3:
        return tuple(max(0, min(255, int(c))) for c in value)
    if isinstance(value, str):
        m = HEX.match(value.strip())
        if m:
            h = m.group(1)
            return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return None


def nearest_index(rgb):
    best = 7
    best_d = None
    for i in range(1, 256):
        t = TABLE[i]
        d = (t[0] - rgb[0]) ** 2 + (t[1] - rgb[1]) ** 2 + (t[2] - rgb[2]) ** 2
        if best_d is None or d < best_d:
            best, best_d = i, d
    return best


def resolve(value, layer_value=7, block=None):
    rgb = true_rgb(value)
    if rgb is not None:
        return rgb, False
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return WHITE, True
    n = int(value)
    if n == 256:
        return resolve(layer_value, 7, block) if not _bylike(layer_value) else (WHITE, True)
    if n == 0:
        if block is not None:
            return block
        return WHITE, True
    if 1 <= n <= 255:
        return TABLE[n], n == 7
    return WHITE, True


def _bylike(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and int(v) in (0, 256)
