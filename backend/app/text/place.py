import math

UNDERLINE = -0.2
OVERLINE = 1.2
STRIKE = 0.5


def emit(sink, fs, glyph, x, y, h, wf, shear, sx, sy, ckey, fill):
    from app.text.model import affine

    m = affine(h * wf * sx, 0.0, h * shear * sx, h * sy, x * sx, y * sy)
    runs = getattr(sink, "runs", None)
    if runs is not None and glyph.src is not None:
        runs.append((glyph.src, m, ckey))
        return
    if glyph.strokes is not None and fs_is_stroke(glyph):
        for arr in glyph.strokes:
            if len(arr) >= 2:
                sink.stroke(arr, False, ckey, m)
        return
    if fill:
        t = glyph.triangles()
        if t is not None and len(t):
            sink.tri(t, ckey, m)
    else:
        for arr in glyph.contours or ():
            if len(arr) >= 3:
                sink.stroke(arr, True, ckey, m)


def fs_is_stroke(glyph):
    return glyph.strokes is not None and glyph.contours is None


def shear_of(oblique):
    a = max(-1.4, min(1.4, oblique))
    return math.tan(a)
