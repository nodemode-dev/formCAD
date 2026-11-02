from app.display import shapes
from app.text import single


def measurer(ctx, style_name):
    rec, fs = shapes.fontset(ctx, style_name)
    wf = float(rec.get("width_factor", 1.0) or 1.0)
    obl = float(rec.get("oblique", 0.0) or 0.0)
    key0 = str(rec.get("font", "txt")).casefold()
    cache = getattr(ctx, "dim_widths", None)
    if cache is None:
        cache = {}
        ctx.dim_widths = cache

    def measure(text, height):
        key = (key0, wf, obl, text, round(float(height), 9))
        hit = cache.get(key)
        if hit is None:
            laid = single.layout(fs, text, float(height), wf, obl, False, False, 0, 0, (0.0, 0.0), None, 0.0, False)
            hit = laid.width
            if len(cache) > 20000:
                cache.clear()
            cache[key] = hit
        return hit

    return measure, rec, fs


def text_height(rec, V, S):
    fixed = float(rec.get("height") or 0.0)
    return fixed if fixed > 0 else float(V["DIMTXT"]) * S
