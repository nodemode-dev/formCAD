import struct
import zlib

import numpy as np

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def chunk(kind, data):
    body = kind + data
    return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)


def encode(pixels, dpi=None, level=6):
    arr = np.ascontiguousarray(pixels, dtype=np.uint8)
    h, w, ch = arr.shape
    kind = {3: 2, 4: 6}[ch]
    out = [SIGNATURE, chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, kind, 0, 0, 0))]
    if dpi:
        ppm = int(round(float(dpi) / 0.0254))
        out.append(chunk(b"pHYs", struct.pack(">IIB", ppm, ppm, 1)))
    comp = zlib.compressobj(level)
    buf = []
    for y in range(h):
        buf.append(comp.compress(b"\x00" + arr[y].tobytes()))
    buf.append(comp.flush())
    data = b"".join(buf)
    for k in range(0, len(data), 1 << 20):
        out.append(chunk(b"IDAT", data[k:k + (1 << 20)]))
    if not data:
        out.append(chunk(b"IDAT", b""))
    out.append(chunk(b"IEND", b""))
    return b"".join(out)
