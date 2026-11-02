import math
import re

from app.text import codes, fonts, place
from app.text.model import Sink, affine, compose, rotation

STACK_SCALE = 0.7
LINE_PITCH = 5.0 / 3.0
TAB_INTERVAL = 4.0
MAX_COLUMNS = 16
MAX_TABS = 32
NUM = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")


class State:
    __slots__ = ("face", "bold", "italic", "h", "wf", "obl", "track", "ckey", "ul", "ol", "sk", "avert")

    def __init__(self, h, wf, obl):
        self.face = None
        self.bold = False
        self.italic = False
        self.h = h
        self.wf = wf
        self.obl = obl
        self.track = 1.0
        self.ckey = None
        self.ul = False
        self.ol = False
        self.sk = False
        self.avert = 1

    def copy(self):
        n = State.__new__(State)
        for k in State.__slots__:
            setattr(n, k, getattr(self, k))
        return n


class Props:
    __slots__ = ("first", "left", "right", "align", "tabs", "before", "after")

    def __init__(self):
        self.first = 0.0
        self.left = 0.0
        self.right = 0.0
        self.align = None
        self.tabs = []
        self.before = 0.0
        self.after = 0.0

    def copy(self):
        n = Props()
        n.first, n.left, n.right, n.align, n.before, n.after = self.first, self.left, self.right, self.align, self.before, self.after
        n.tabs = list(self.tabs)
        return n


class Para:
    def __init__(self, props, break_before=False):
        self.props = props
        self.items = []
        self.break_before = break_before


def _num(text):
    t = text.strip()
    if NUM.match(t):
        return float(t)
    return None


def apply_props(spec, props):
    p = props.copy()
    in_tab = False
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok[0] == "x" and len(tok) > 1 and tok[1].isalpha():
            tok = tok[1:]
        c, rest = tok[0], tok[1:]
        if in_tab:
            if c in "crd" and _num(rest) is not None:
                if len(p.tabs) < MAX_TABS:
                    p.tabs.append((float(rest), c))
                continue
            if _num(tok) is not None:
                if len(p.tabs) < MAX_TABS:
                    p.tabs.append((float(tok), "l"))
                continue
        in_tab = False
        v = _num(rest)
        if c == "i" and v is not None:
            p.first = v
        elif c == "l" and v is not None:
            p.left = v
        elif c == "r" and v is not None:
            p.right = v
        elif c == "b" and v is not None:
            p.before = v
        elif c == "a" and v is not None:
            p.after = v
        elif c == "q":
            p.align = rest[:1] if rest[:1] in ("l", "c", "r", "j", "d") else None
        elif c == "t":
            p.tabs = []
            in_tab = True
            if v is not None:
                p.tabs.append((v, "l"))
            elif rest[:1] in ("c", "r", "d") and _num(rest[1:]) is not None:
                p.tabs.append((float(rest[1:]), rest[0]))
    p.tabs.sort(key=lambda t: t[0])
    return p


def _scaled(value, current):
    t = value.strip()
    if t.endswith(("x", "X")):
        v = _num(t[:-1])
        return None if v is None else current * v
    return _num(t)


class Parsed:
    def __init__(self):
        self.paras = []
        self.columns_used = False


def parse(contents, base, props0, column_mode):
    out = Parsed()
    props = props0.copy()
    para = Para(props)
    out.paras.append(para)
    st = base.copy()
    stack = []
    buf = []

    def flush():
        if not buf:
            return
        for ch, ul, ol, sk in codes.decode("".join(buf)):
            s = st
            if ul or ol or sk:
                s = st.copy()
                s.ul = s.ul or ul
                s.ol = s.ol or ol
                s.sk = s.sk or sk
            para.items.append(("c", ch, s, False))
        buf.clear()

    def new_para(break_before=False):
        nonlocal para
        flush()
        para = Para(props, break_before)
        out.paras.append(para)

    text = contents.replace("\r\n", "\n").replace("\r", "\n")
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "{":
            flush()
            stack.append(st.copy())
            i += 1
        elif c == "}":
            flush()
            if stack:
                st = stack.pop()
            i += 1
        elif c == "\n":
            new_para()
            i += 1
        elif c == "\t":
            flush()
            para.items.append(("tab", st))
            i += 1
        elif c == "^" and i + 1 < n:
            d = text[i + 1]
            if d == "I":
                flush()
                para.items.append(("tab", st))
            elif d == "J":
                new_para()
            elif d == " ":
                buf.append("^")
            else:
                buf.append(c)
                buf.append(d)
            i += 2
        elif c == "\\" and i + 1 < n:
            d = text[i + 1]
            i += 2
            if d in ("\\", "{", "}"):
                buf.append(d)
            elif d == "P":
                new_para()
            elif d == "N":
                if column_mode:
                    out.columns_used = True
                    new_para(True)
                else:
                    flush()
                    para.items.append(("br", st))
            elif d == "~":
                flush()
                para.items.append(("c", " ", st, True))
            elif d in "LlOoKk":
                flush()
                st = st.copy()
                on = d.isupper()
                if d in "Ll":
                    st.ul = on
                elif d in "Oo":
                    st.ol = on
                else:
                    st.sk = on
            elif d in "SfFHWQTCcApP":
                end = text.find(";", i)
                if end < 0:
                    end = n
                arg = text[i:end]
                i = end + 1
                flush()
                if d == "S":
                    _stack(para, arg, st)
                    continue
                if d in "pP":
                    props = apply_props(arg, props)
                    if not para.items:
                        para.props = props
                    continue
                st = st.copy()
                _code(d, arg, st)
            else:
                pass
        else:
            buf.append(c)
            i += 1
    flush()
    return out


def _stack(para, arg, st):
    sep = None
    k = 0
    while k < len(arg):
        ch = arg[k]
        if ch == "\\" and k + 1 < len(arg):
            k += 2
            continue
        if ch in "/#^":
            sep = ch
            break
        k += 1
    if sep is None:
        top, bot = arg, ""
        sep = "^"
    else:
        top, bot = arg[:k], arg[k + 1:]
    para.items.append(("stack", top.replace("\\", ""), bot.replace("\\", ""), sep, st))


def _code(d, arg, st):
    if d in "fF":
        parts = arg.split("|")
        st.face = parts[0] or None
        st.bold = False
        st.italic = False
        for flag in parts[1:]:
            if flag[:1] == "b":
                st.bold = flag[1:] == "1"
            elif flag[:1] == "i":
                st.italic = flag[1:] == "1"
    elif d == "H":
        v = _scaled(arg, st.h)
        if v is not None and v > 0:
            st.h = v
    elif d == "W":
        v = _scaled(arg, st.wf)
        if v is not None and 0.01 <= v <= 100:
            st.wf = v
    elif d == "Q":
        v = _num(arg)
        if v is not None:
            st.obl = math.radians(max(-85.0, min(85.0, v)))
    elif d == "T":
        v = _scaled(arg, st.track)
        if v is not None and 0.1 <= v <= 20:
            st.track = v
    elif d == "C":
        v = _num(arg)
        if v is not None and 1 <= int(v) <= 255:
            st.ckey = ("i", int(v))
        elif v is not None:
            st.ckey = None
    elif d == "c":
        v = _num(arg)
        if v is not None and 0 <= int(v) <= 0xFFFFFF:
            n = int(v)
            st.ckey = ("rgb", (n >> 16) & 255, (n >> 8) & 255, n & 255)
    elif d == "A":
        v = _num(arg)
        if v is not None and int(v) in (0, 1, 2):
            st.avert = int(v)


class Ctx:
    def __init__(self, base_fs, fill):
        self.base = base_fs
        self.fill = fill
        self.sets = {}

    def fs(self, st):
        if st.face is None and not st.bold and not st.italic:
            return self.base
        k = (st.face, st.bold, st.italic)
        fs = self.sets.get(k)
        if fs is None:
            if st.face is None:
                fs = self.base
            else:
                fs = fonts.FontSet(fonts.resolve(st.face, st.bold, st.italic))
            self.sets[k] = fs
        return fs


def _cwidth(ctx, st, ch, scale=1.0):
    g = ctx.fs(st).glyph(ch)
    return g.adv * st.h * scale * st.wf * st.track


def _text_width(ctx, st, text, scale):
    total = 0.0
    last = 0.0
    for ch, _u, _o, _k in codes.decode(text):
        g = ctx.fs(st).glyph(ch)
        total += g.adv * st.h * scale * st.wf * st.track
        last = g.trail * st.h * scale * st.wf
    return max(total - last, 0.0)


def item_width(ctx, it):
    if it[0] == "c":
        return _cwidth(ctx, it[2], it[1])
    if it[0] == "stack":
        _k, top, bot, sep, st = it
        wn = _text_width(ctx, st, top, STACK_SCALE)
        wd = _text_width(ctx, st, bot, STACK_SCALE)
        if sep == "#":
            return wn + wd + 0.35 * st.h
        return max(wn, wd) + (0.1 * st.h if sep == "/" else 0.0)
    return 0.0


def _trail(ctx, it):
    if it[0] != "c":
        return 0.0
    st = it[2]
    return ctx.fs(st).glyph(it[1]).trail * st.h * st.wf


def item_height(it):
    return it[2].h if it[0] == "c" else (it[4].h * 1.2 if it[0] == "stack" else 0.0)


class Line:
    __slots__ = ("cells", "x0", "x1", "hmax", "hard", "para", "first", "col", "y", "shift", "spaces")

    def __init__(self, para, x0, first):
        self.cells = []
        self.x0 = x0
        self.x1 = x0
        self.hmax = 0.0
        self.hard = False
        self.para = para
        self.first = first
        self.col = 0
        self.y = 0.0
        self.shift = 0.0
        self.spaces = 0


def _tokens(items):
    toks = []
    cur = []
    in_space = False
    for it in items:
        if it[0] in ("tab", "br"):
            if cur:
                toks.append(cur)
                cur = []
            toks.append([it])
            in_space = False
            continue
        is_space = it[0] == "c" and it[1] == " " and not it[3]
        if is_space:
            cur.append(it)
            in_space = True
        else:
            if in_space and cur:
                toks.append(cur)
                cur = []
            in_space = False
            cur.append(it)
    if cur:
        toks.append(cur)
    return toks


def _tok_widths(ctx, tok):
    total = 0.0
    vis = 0.0
    for it in tok:
        w = item_width(ctx, it)
        total += w
        if not (it[0] == "c" and it[1] == " " and not it[3]):
            vis = total
    return vis, total


def _next_stop(props, x, base_h):
    for pos, kind in props.tabs:
        if pos > x + 1e-9:
            return pos, kind
    step = TAB_INTERVAL * base_h
    last = props.tabs[-1][0] if props.tabs else 0.0
    k = math.floor((max(x, last) - 0.0) / step) + 1
    return k * step, "l"


def _decimal_offset(ctx, tok):
    w = 0.0
    for it in tok:
        if it[0] == "c" and it[1] in ".,":
            return w
        w += item_width(ctx, it)
    return w


def break_lines(ctx, para, width, base_h):
    p = para.props
    lines = []
    toks = _tokens(para.items)
    start = p.left + p.first
    line = Line(para, start, True)
    x = start
    limit = width - p.right if width > 0 else float("inf")
    idx = 0
    while idx < len(toks):
        tok = toks[idx]
        idx += 1
        head = tok[0]
        if head[0] == "br":
            line.hard = True
            lines.append(line)
            line = Line(para, p.left, False)
            x = p.left
            continue
        if head[0] == "tab":
            stop, kind = _next_stop(p, x, base_h)
            nxt = toks[idx] if idx < len(toks) and toks[idx][0][0] not in ("tab", "br") else None
            nvis = _tok_widths(ctx, nxt)[0] if nxt else 0.0
            if kind == "c":
                target = stop - nvis / 2.0
            elif kind == "r":
                target = stop - nvis
            elif kind == "d":
                target = stop - (_decimal_offset(ctx, nxt) if nxt else 0.0)
            else:
                target = stop
            target = max(target, x)
            line.cells.append((head, x, target - x))
            x = target
            line.x1 = max(line.x1, x)
            continue
        vis, total = _tok_widths(ctx, tok)
        if line.cells and width > 0 and x + vis > limit + 1e-9:
            lines.append(line)
            line = Line(para, p.left, False)
            x = p.left
        for it in tok:
            w = item_width(ctx, it)
            line.cells.append((it, x, w))
            line.hmax = max(line.hmax, item_height(it))
            if it[0] == "c" and it[1] == " " and not it[3]:
                line.spaces += 1
            else:
                line.x1 = x + w - _trail(ctx, it)
            x += w
    line.hard = True
    lines.append(line)
    for ln in lines:
        if ln.hmax <= 0:
            ln.hmax = base_h
        while ln.cells and ln.cells[-1][0][0] == "c" and ln.cells[-1][0][1] == " " and not ln.cells[-1][0][3]:
            ln.cells.pop()
            ln.spaces = max(0, ln.spaces - 1)
    return lines


def _align_of(line, attach_col):
    a = line.para.props.align
    if a is None:
        return ("l", "c", "r")[attach_col]
    return a


def layout(base_fs, contents, height, width, attachment, rot, position, line_spacing, spacing_style, columns, style_wf, style_obl, fill, desc):
    ctx = Ctx(base_fs, fill)
    base = State(height, style_wf, style_obl)
    col = columns or {}
    ctype = str(col.get("type") or "none").lower()
    ncols_decl = int(col.get("count") or 0)
    gutter = float(col.get("gutter") or 0.0)
    colmode = ctype in ("static", "dynamic") and width > 0
    parsed = parse(contents or "", base, Props(), colmode)
    lines = []
    for para in parsed.paras:
        got = break_lines(ctx, para, width, height)
        got[-1].hard = True
        lines.extend(got)
    attach_col = (max(1, min(9, int(attachment))) - 1) % 3
    attach_row = (max(1, min(9, int(attachment))) - 1) // 3
    heights = col.get("heights") or []
    hc = float(col.get("height") or 0.0)
    if colmode and not hc and heights:
        hc = float(heights[0])
    spacing = line_spacing if line_spacing and line_spacing > 0 else 1.0
    y = 0.0
    cur_col = 0
    first_in_col = True
    prev_para = None
    col_bottoms = {}
    for ln in lines:
        if ln.para is not prev_para:
            if prev_para is not None:
                y -= prev_para.props.after * height
            if prev_para is not None and ln.para.props.before:
                y -= ln.para.props.before * height
            if ln.para.break_before and colmode:
                nxt = _advance(cur_col, ncols_decl, ctype)
                if nxt != cur_col:
                    cur_col = nxt
                    y = 0.0
                    first_in_col = True
            prev_para = ln.para
        if first_in_col:
            base_y = y - ln.hmax
        else:
            basis = ln.hmax if spacing_style != 2 else height
            base_y = y - LINE_PITCH * basis * spacing
        if colmode and hc > 0 and not first_in_col:
            limit = _col_height(cur_col, hc, heights)
            if base_y - desc * ln.hmax < -limit - 1e-9:
                nxt = _advance(cur_col, ncols_decl, ctype)
                if nxt != cur_col:
                    cur_col = nxt
                    y = 0.0
                    base_y = y - ln.hmax
                    first_in_col = True
        ln.col = cur_col
        ln.y = base_y
        y = base_y
        first_in_col = False
        col_bottoms[cur_col] = min(col_bottoms.get(cur_col, 0.0), base_y - desc * ln.hmax)
    ncols = (max(col_bottoms) + 1) if col_bottoms else 1
    block_h = -min(col_bottoms.values()) if col_bottoms else height
    if colmode:
        block_w = ncols * width + (ncols - 1) * gutter
        line_w = width
    else:
        line_w = width if width > 0 else max((ln.x1 for ln in lines), default=0.0)
        block_w = line_w
    for ln in lines:
        mode = _align_of(ln, attach_col)
        extra = line_w - ln.para.props.right - ln.x1
        if mode == "c":
            ln.shift = extra / 2.0
        elif mode == "r":
            ln.shift = extra
    sink = Sink()
    ident = affine()
    for ln in lines:
        mode = _align_of(ln, attach_col)
        stretch = 0.0
        if mode in ("j", "d") and ln.spaces and (not ln.hard or mode == "d"):
            extra = (line_w - ln.para.props.right) - ln.x1
            if extra > 0:
                stretch = extra / ln.spaces
        coff = (ncols - 1 - ln.col if str(col.get("reversed")).lower() in ("1", "true", "yes") else ln.col) * (width + gutter) if colmode else 0.0
        run = 0
        marks = []
        for it, x, w in ln.cells:
            if it[0] == "c" and it[1] == " " and not it[3]:
                run += 1
            gx = x + ln.shift + stretch * run + coff
            if it[0] == "c":
                _draw_char(ctx, sink, it[2], it[1], gx, ln.y, fill)
                st = it[2]
                if st.ul or st.ol or st.sk:
                    marks.append((gx, gx + w, st))
            elif it[0] == "stack":
                _draw_stack(ctx, sink, it, gx, ln.y, fill, ident)
        _draw_marks(sink, marks, ln.y, ident)
    ox = -(0.0, block_w / 2.0, block_w)[attach_col]
    oy = (0.0, block_h / 2.0, block_h)[attach_row]
    m = compose(rotation(rot, position[0], position[1]), affine(1, 0, 0, 1, ox, oy))
    corners = [(0.0, -block_h), (block_w, -block_h), (block_w, 0.0), (0.0, 0.0)]
    box = [[m[0] * x + m[2] * yy + m[4], m[1] * x + m[3] * yy + m[5]] for x, yy in corners]
    from app.text.single import Laid

    return Laid(sink.prims(m), box, sink.bounds(m), [m[4], m[5]], block_w, block_h)


def _advance(cur, declared, ctype):
    if ctype == "static" and declared > 0 and cur + 1 >= min(declared, MAX_COLUMNS):
        return cur
    if cur + 1 >= MAX_COLUMNS:
        return cur
    return cur + 1


def _col_height(col, hc, heights):
    if heights:
        return float(heights[min(col, len(heights) - 1)]) or hc
    return hc


def _draw_char(ctx, sink, st, ch, x, y, fill, scale=1.0, dy=0.0):
    fs = ctx.fs(st)
    g = fs.glyph(ch)
    if g is None:
        return
    place.emit(sink, fs, g, x, y + dy, st.h * scale, st.wf, place.shear_of(st.obl), 1.0, 1.0, st.ckey, fill)


def _draw_string(ctx, sink, st, text, x, y, fill, scale):
    cur = x
    for ch, _u, _o, _k in codes.decode(text):
        _draw_char(ctx, sink, st, ch, cur, y, fill, scale)
        cur += _cwidth(ctx, st, ch, scale)


def _draw_stack(ctx, sink, it, x, y, fill, ident):
    _k, top, bot, sep, st = it
    h = st.h
    wn = _text_width(ctx, st, top, STACK_SCALE)
    wd = _text_width(ctx, st, bot, STACK_SCALE)
    shift = {0: 0.3, 1: 0.0, 2: -0.4}.get(st.avert, 0.0) * h
    if sep == "/":
        w = max(wn, wd)
        bar = y + 0.45 * h + shift
        _draw_string(ctx, sink, st, top, x + 0.05 * h + (w - wn) / 2.0, bar + 0.12 * h, fill, STACK_SCALE)
        _draw_string(ctx, sink, st, bot, x + 0.05 * h + (w - wd) / 2.0, bar - 0.12 * h - STACK_SCALE * h, fill, STACK_SCALE)
        sink.segment(x, bar, x + w + 0.1 * h, bar, st.ckey, ident)
    elif sep == "#":
        xs = x + wn + 0.02 * h
        _draw_string(ctx, sink, st, top, x, y + 0.45 * h + shift, fill, STACK_SCALE)
        sink.segment(xs, y - 0.15 * h + shift, xs + 0.3 * h, y + 1.1 * h + shift, st.ckey, ident)
        _draw_string(ctx, sink, st, bot, xs + 0.34 * h, y - 0.05 * h + shift, fill, STACK_SCALE)
    else:
        _draw_string(ctx, sink, st, top, x, y + 0.42 * h + shift, fill, STACK_SCALE)
        _draw_string(ctx, sink, st, bot, x, y - 0.32 * h + shift, fill, STACK_SCALE)


def _draw_marks(sink, marks, y, ident):
    merged = []
    for x0, x1, st in marks:
        flags = (st.ul, st.ol, st.sk, st.ckey, st.h)
        if merged and abs(merged[-1][1] - x0) < 1e-9 and merged[-1][2] == flags:
            merged[-1] = (merged[-1][0], x1, flags)
        else:
            merged.append((x0, x1, flags))
    for x0, x1, (ul, ol, sk, ckey, h) in merged:
        for on, level in ((ul, place.UNDERLINE), (ol, place.OVERLINE), (sk, place.STRIKE)):
            if on:
                sink.segment(x0, y + level * h, x1, y + level * h, ckey, ident)
