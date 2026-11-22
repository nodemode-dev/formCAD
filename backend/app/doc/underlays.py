import os
import struct
import threading
import zlib
from collections import OrderedDict

import numpy as np

MAX_FILE = 512 * 1024 * 1024
MAX_SIDE = 65535
DECODE_PIXELS = 16_000_000
SCREEN_SIDE = 2048
PLOT_SIDE = 6000
CACHE_ITEMS = 8
EXT_KIND = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".pdf": "pdf"}
PNG_SIG = b"\x89PNG\r\n\x1a\n"
SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}

_lock = threading.Lock()
_cache: OrderedDict = OrderedDict()
_pdfium_lock = threading.Lock()


class UnderlayError(ValueError):
    pass


def folder_of(doc) -> str:
    return os.path.dirname(os.path.abspath(doc.path)) if getattr(doc, "path", "") else ""


def resolve(path: str, folder: str) -> str:
    p = os.path.expanduser(str(path or "").replace("\\", "/"))
    if not p:
        return ""
    if os.path.isabs(p):
        if os.path.isfile(p) or not folder:
            return os.path.abspath(p)
        beside = os.path.join(folder, os.path.basename(p))
        return beside if os.path.isfile(beside) else os.path.abspath(p)
    if folder:
        full = os.path.abspath(os.path.join(folder, p))
        if os.path.isfile(full):
            return full
        beside = os.path.join(folder, os.path.basename(p))
        return beside if os.path.isfile(beside) else full
    return os.path.abspath(p)


def stored(full: str, folder: str) -> str:
    if folder:
        rel = os.path.relpath(full, folder)
        if not rel.startswith("..") and not os.path.isabs(rel):
            return rel.replace(os.sep, "/")
    return full


def stamp(full: str) -> str:
    try:
        st = os.stat(full)
    except OSError:
        return ""
    return "%x-%x" % (st.st_mtime_ns, st.st_size)


def kind_of(full: str) -> str:
    try:
        with open(full, "rb") as fh:
            head = fh.read(8)
    except OSError:
        return ""
    if head.startswith(PNG_SIG):
        return "png"
    if head[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if head[:5] == b"%PDF-":
        return "pdf"
    return ""


def _read(full: str) -> bytes:
    size = os.path.getsize(full)
    if size > MAX_FILE:
        raise UnderlayError("The file is larger than 512 MB.")
    with open(full, "rb") as fh:
        return fh.read()


def png_info(data: bytes) -> dict:
    if not data.startswith(PNG_SIG) or len(data) < 33 or data[12:16] != b"IHDR":
        raise UnderlayError("The file is not a PNG image.")
    w, h, bits, ctype, _comp, _filt, interlace = struct.unpack(">IIBBBBB", data[16:29])
    if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE) or bits not in (1, 2, 4, 8, 16) or ctype not in (0, 2, 3, 4, 6):
        raise UnderlayError("The PNG image header is not valid.")
    return {"w": w, "h": h, "bits": bits, "ctype": ctype, "interlace": interlace}


def jpeg_info(data: bytes) -> dict:
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            i += 1 if marker == 0xFF else 2
            continue
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in SOF and i + 10 <= n:
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            comps = data[i + 9]
            if not (0 < w <= MAX_SIDE and 0 < h <= MAX_SIDE):
                break
            adobe = b"Adobe" in data[:i]
            return {"w": w, "h": h, "comps": comps, "adobe": adobe}
        if marker == 0xDA:
            break
        i += 2 + length
    raise UnderlayError("The JPEG image header could not be read.")


def _pdfium():
    try:
        import pypdfium2 as pdfium
    except ImportError:
        raise UnderlayError("PDF underlays need pypdfium2, which is not installed in this engine.")
    return pdfium


def pdf_info(full: str, page: int) -> dict:
    pdfium = _pdfium()
    with _pdfium_lock:
        try:
            pdf = pdfium.PdfDocument(full)
        except pdfium.PdfiumError as err:
            raise UnderlayError("The PDF could not be opened: %s" % err)
        try:
            count = len(pdf)
            if not 1 <= page <= count:
                raise UnderlayError("The PDF has %d page(s); page %d does not exist." % (count, page))
            w, h = pdf[page - 1].get_size()
        finally:
            pdf.close()
    return {"w": float(w), "h": float(h), "pages": count}


def probe(full: str, page: int = 1) -> dict:
    if not os.path.isfile(full):
        raise UnderlayError("The file %s was not found." % os.path.basename(full))
    kind = kind_of(full)
    if not kind:
        raise UnderlayError("Only PNG, JPEG and PDF files can be attached.")
    if kind == "pdf":
        info = pdf_info(full, page)
        info["kind"] = "pdf"
        return info
    with open(full, "rb") as fh:
        head = fh.read(256 * 1024)
    info = png_info(head) if kind == "png" else jpeg_info(head)
    info["kind"] = kind
    return info


def _cached(key, make):
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    val = make()
    with _lock:
        _cache[key] = val
        while len(_cache) > CACHE_ITEMS:
            _cache.popitem(last=False)
    return val


def _unfilter(raw: bytes, w: int, h: int, bpp: int, stride: int) -> np.ndarray:
    out = np.zeros((h, stride), dtype=np.uint8)
    prev = bytearray(stride)
    pos = 0
    for y in range(h):
        if pos + 1 + stride > len(raw):
            raise UnderlayError("The PNG image data is shorter than its size.")
        ft = raw[pos]
        line = raw[pos + 1:pos + 1 + stride]
        pos += 1 + stride
        if ft == 0:
            cur = bytearray(line)
        elif ft == 2:
            cur = bytearray((np.frombuffer(line, np.uint8) + np.frombuffer(bytes(prev), np.uint8)).tobytes())
        elif ft == 1:
            a = np.frombuffer(line, np.uint8).astype(np.uint64)
            c = np.empty(stride, dtype=np.uint8)
            for k in range(bpp):
                c[k::bpp] = (np.cumsum(a[k::bpp]) & 255).astype(np.uint8)
            cur = bytearray(c.tobytes())
        elif ft == 3:
            cur = bytearray(line)
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 255
        elif ft == 4:
            cur = bytearray(line)
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else (b if pb <= pc else c))) & 255
        else:
            raise UnderlayError("The PNG image uses an unknown row filter.")
        out[y] = np.frombuffer(bytes(cur), np.uint8)
        prev = cur
    return out


def png_chunks(data: bytes):
    i = 8
    n = len(data)
    while i + 8 <= n:
        length, kind = struct.unpack(">I4s", data[i:i + 8])
        body = data[i + 8:i + 8 + length]
        yield kind, body
        i += 12 + length
        if kind == b"IEND":
            return


def png_parts(data: bytes) -> dict:
    info = png_info(data)
    idat = []
    plte = b""
    trns = b""
    for kind, body in png_chunks(data):
        if kind == b"IDAT":
            idat.append(body)
        elif kind == b"PLTE":
            plte = body
        elif kind == b"tRNS":
            trns = body
    info.update({"idat": b"".join(idat), "plte": plte, "trns": trns})
    return info


def decode_png(data: bytes) -> np.ndarray:
    p = png_parts(data)
    w, h, bits, ctype = p["w"], p["h"], p["bits"], p["ctype"]
    if w * h > DECODE_PIXELS:
        raise UnderlayError("The PNG image is larger than %d million pixels." % (DECODE_PIXELS // 1_000_000))
    if p["interlace"]:
        raise UnderlayError("Interlaced PNG images are not read; save the image without interlacing.")
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    stride = (w * chans * bits + 7) // 8
    bpp = max(1, chans * bits // 8)
    expect = h * (stride + 1)
    z = zlib.decompressobj()
    try:
        raw = z.decompress(p["idat"], expect + 1)
    except zlib.error as err:
        raise UnderlayError("The PNG image data is damaged: %s" % err)
    rows = _unfilter(raw, w, h, bpp, stride)
    if bits == 16:
        samples = rows.reshape(h, w * chans, 2)[:, :, 0]
    elif bits == 8:
        samples = rows[:, : w * chans]
    else:
        per = 8 // bits
        unpacked = np.unpackbits(rows, axis=1) if bits == 1 else None
        if bits == 1:
            samples = unpacked[:, :w]
        else:
            shifts = np.arange(per - 1, -1, -1, dtype=np.uint8) * bits
            samples = ((rows[:, :, None] >> shifts) & ((1 << bits) - 1)).reshape(h, -1)[:, :w]
        if ctype == 0:
            samples = (samples.astype(np.uint16) * 255 // ((1 << bits) - 1)).astype(np.uint8)
    out = np.empty((h, w, 4), dtype=np.uint8)
    s = samples.reshape(h, w, chans)
    if ctype == 3:
        pal = np.frombuffer(p["plte"], np.uint8).reshape(-1, 3) if p["plte"] else np.zeros((1, 3), np.uint8)
        alpha = np.full(len(pal), 255, np.uint8)
        t = np.frombuffer(p["trns"], np.uint8)
        alpha[: min(len(t), len(alpha))] = t[: len(alpha)]
        idx = np.minimum(s[:, :, 0], len(pal) - 1)
        out[:, :, :3] = pal[idx]
        out[:, :, 3] = alpha[idx]
    elif ctype in (0, 4):
        out[:, :, 0] = out[:, :, 1] = out[:, :, 2] = s[:, :, 0]
        out[:, :, 3] = s[:, :, 1] if ctype == 4 else 255
    else:
        out[:, :, :3] = s[:, :, :3]
        out[:, :, 3] = s[:, :, 3] if ctype == 6 else 255
    return out


def _bitmap_rgba(bitmap) -> np.ndarray:
    arr = bitmap.to_numpy()
    mode = getattr(bitmap, "mode", "") or ""
    if arr.ndim == 2:
        arr = np.repeat(arr[:, :, None], 3, axis=2)
    h, w = arr.shape[:2]
    out = np.empty((h, w, 4), dtype=np.uint8)
    if arr.shape[2] >= 3:
        rgb = arr[:, :, :3]
        if not mode.startswith("RGB"):
            rgb = rgb[:, :, ::-1]
        out[:, :, :3] = rgb
    out[:, :, 3] = arr[:, :, 3] if arr.shape[2] == 4 else 255
    return out


def decode_jpeg(full: str) -> np.ndarray:
    pdfium = _pdfium()
    with _pdfium_lock:
        pdf = pdfium.PdfDocument.new()
        try:
            img = pdfium.PdfImage.new(pdf)
            img.load_jpeg(full, inline=False)
            return _bitmap_rgba(img.get_bitmap(render=False))
        finally:
            pdf.close()


def render_pdf(full: str, page: int, side: int) -> np.ndarray:
    pdfium = _pdfium()
    with _pdfium_lock:
        pdf = pdfium.PdfDocument(full)
        try:
            pg = pdf[page - 1]
            w, h = pg.get_size()
            scale = max(0.05, min(8.0, side / max(w, h, 1.0)))
            bm = pg.render(scale=scale, fill_color=(255, 255, 255, 255), may_draw_forms=True)
            return _bitmap_rgba(bm)
        finally:
            pdf.close()


def pixels(full: str, page: int = 1, side: int = PLOT_SIDE) -> np.ndarray:
    kind = kind_of(full)
    key = ("px", full, stamp(full), page, side if kind == "pdf" else 0)

    def make():
        if kind == "png":
            return decode_png(_read(full))
        if kind == "jpeg":
            return decode_jpeg(full)
        if kind == "pdf":
            return render_pdf(full, page, side)
        raise UnderlayError("Only PNG, JPEG and PDF files can be shown.")

    return _cached(key, make)


def screen_bytes(full: str, page: int = 1) -> tuple:
    kind = kind_of(full)
    if kind in ("png", "jpeg"):
        return _read(full), "image/png" if kind == "png" else "image/jpeg"
    if kind == "pdf":
        from app.output import pngwrite

        key = ("screen", full, stamp(full), page)
        data = _cached(key, lambda: pngwrite.encode(render_pdf(full, page, SCREEN_SIDE)[:, :, :3].copy(), level=4))
        return data, "image/png"
    raise UnderlayError("Only PNG, JPEG and PDF files can be shown.")


def png_passthrough(full: str):
    data = _read(full)
    p = png_parts(data)
    if p["interlace"] or p["ctype"] in (4, 6) or (p["ctype"] in (0, 2, 3) and p["trns"]):
        return None
    return p


def jpeg_passthrough(full: str):
    data = _read(full)
    info = jpeg_info(data[: 256 * 1024])
    if info["comps"] not in (1, 3):
        return None
    info["data"] = data
    return info
