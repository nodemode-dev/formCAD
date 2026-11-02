import unicodedata

from app.text import arabic, bidi, fonts, scripts

try:
    import uharfbuzz as hb
except Exception:
    hb = None

MARKS = ("Mn", "Mc", "Me")
PLACEHOLDERS = ("\t", "￼", " ", "\n")
SHAPER = {"enabled": True}


class Cluster:
    __slots__ = ("glyphs", "adv", "trail")

    def __init__(self, glyphs, adv, trail=0.0):
        self.glyphs = glyphs
        self.adv = adv
        self.trail = trail


EMPTY = Cluster([], 0.0, 0.0)


def available():
    return hb is not None and SHAPER["enabled"]


def _plain(fs, ch, level):
    c = bidi.mirror(ch) if level % 2 else ch
    g = fs.glyph(c)
    if g is None:
        return EMPTY
    return Cluster([(g, 0.0, 0.0)], g.adv, g.trail)


def _hb_run(face, text, rtl):
    font = face.shaper()
    buf = hb.Buffer()
    buf.add_str(text)
    buf.direction = "rtl" if rtl else "ltr"
    buf.flags = hb.BufferFlags.REMOVE_DEFAULT_IGNORABLES | hb.BufferFlags.DO_NOT_INSERT_DOTTED_CIRCLE
    buf.guess_segment_properties()
    hb.shape(font, buf)
    k = 1.0 / face.cap
    groups = {}
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        groups.setdefault(info.cluster, []).append((info.codepoint, pos.x_advance, pos.x_offset, pos.y_offset))
    out = {}
    for cl, items in groups.items():
        pen = 0.0
        glyphs = []
        for gid, xa, xo, yo in items:
            glyphs.append((face.glyph_by_id(gid), (pen + xo) * k, yo * k))
            pen += xa
        out[cl] = Cluster(glyphs, pen * k, 0.0)
    return out


def _fallback_run(fs, text, level):
    chars = list(text)
    if any(scripts.script_of(c) == "arabic" for c in chars):
        forms = arabic.presentation(text)
    else:
        forms = chars
    out = []
    prev = None
    for ch, shown in zip(chars, forms):
        if shown == "":
            out.append(EMPTY)
            continue
        if ch in scripts.FORMAT_CHARS:
            out.append(EMPTY)
            continue
        c = bidi.mirror(shown) if level % 2 else shown
        cat = unicodedata.category(ch)
        g = fs.glyph(c)
        if g is None:
            out.append(EMPTY)
            continue
        if cat in MARKS and prev is not None:
            prev.glyphs.append((g, prev.adv, 0.0))
            out.append(EMPTY)
            continue
        cl = Cluster([(g, 0.0, 0.0)], g.adv, g.trail)
        out.append(cl)
        prev = cl
    return out


def _faces(chars, fss):
    faces = []
    prev = None
    for ch, fs in zip(chars, fss):
        if fs is None or ch in PLACEHOLDERS:
            faces.append(None)
            prev = None
            continue
        if ch in scripts.FORMAT_CHARS:
            faces.append(prev)
            continue
        face = None
        if prev is not None and unicodedata.category(ch) in MARKS and prev.has(ch):
            face = prev
        if face is None:
            face = fs.face_for(ch)
        faces.append(face)
        prev = face
    return faces


def shape(fs, chars, fss=None, base=None):
    n = len(chars)
    if fss is None:
        fss = [fs] * n
    text = "".join(chars)
    if scripts.needs_shaping(text) or base is not None:
        levels, para = bidi.resolve(text, base)
    else:
        levels, para = [0] * n, 0
    faces = _faces(chars, fss)
    out = [EMPTY] * n
    use_hb = available()
    i = 0
    while i < n:
        face = faces[i]
        ch = chars[i]
        if face is None:
            if fss[i] is not None and ch not in PLACEHOLDERS and ch not in scripts.FORMAT_CHARS:
                out[i] = _plain(fss[i], ch, levels[i])
            i += 1
            continue
        simple = face.is_stroke or fonts.is_wide(ch)
        if simple:
            out[i] = _plain(fss[i], ch, levels[i])
            i += 1
            continue
        j = i + 1
        while j < n and faces[j] is face and levels[j] == levels[i] and not fonts.is_wide(chars[j]) and chars[j] not in PLACEHOLDERS:
            j += 1
        run = "".join(" " if c == " " else c for c in chars[i:j])
        done = False
        if use_hb:
            try:
                got = _hb_run(face, run, levels[i] % 2 == 1)
                for off in range(j - i):
                    cl = got.get(off)
                    if cl is not None:
                        out[i + off] = cl
                done = True
            except Exception:
                done = False
        if not done:
            fsx = fss[i]
            res = _fallback_run(fsx, run, levels[i])
            for off, cl in enumerate(res):
                out[i + off] = cl
        i = j
    return out, levels, para


def visual(chars, levels, para):
    if not any(v % 2 for v in levels):
        return list(range(len(chars)))
    return bidi.reorder("".join(chars), levels, para)
