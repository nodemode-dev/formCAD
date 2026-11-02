import json
import weakref
from bisect import bisect_right

from app.cmd.grips import grips_of
from app.display import annot, arrays, dimensions, extra_d2, hatch_d, insert, palette, shapes, viewport_frame
from app.display.resolve import Context
from app.doc import annotation

BUILDER_MODULES = (insert, shapes, extra_d2, arrays, annot, hatch_d, dimensions, viewport_frame)
STEP = 1024
_encode = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode
_states = weakref.WeakKeyDictionary()
TEXT_KINDS = ("text", "mtext", "insert", "dimension")


class Entry:
    __slots__ = ("h", "order", "bounds", "js", "rev", "layer", "deps")

    def __init__(self, h, order, bounds, js, rev, layer, deps):
        self.h = h
        self.order = order
        self.bounds = bounds
        self.js = js
        self.rev = rev
        self.layer = layer
        self.deps = deps


def head_of(pp):
    head = pp.head
    if head is None:
        head = '"layer":%s,"color":[%d,%d,%d],"color7":%s,"lw":%r,"lt":%s,"tr":%r,"plot":%s' % (_encode(pp.layer), pp.rgb[0], pp.rgb[1], pp.rgb[2], "true" if pp.c7 else "false", pp.lw, _encode(pp.lt), pp.tr, "true" if pp.plot else "false")
        pp.head = head
    return head


LINE_FMT = '{"h":%d,"kind":"line",%s,"order":%d,"geom":{"type":"line","p1":[%r,%r],"p2":[%r,%r]},"prims":[],"grips":[{"id":"start","p":[%r,%r],"kind":"end"},{"id":"mid","p":[%r,%r],"kind":"mid"},{"id":"end","p":[%r,%r],"kind":"end"}],"bounds":[%r,%r,%r,%r]}'


def line_entry(e, ctx, order, rev):
    pp = ctx.props(e)
    s, t = e.start, e.end
    x0, y0, x1, y1 = float(s[0]), float(s[1]), float(t[0]), float(t[1])
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    if x0 > x1:
        bx0, bx1 = x1, x0
    else:
        bx0, bx1 = x0, x1
    if y0 > y1:
        by0, by1 = y1, y0
    else:
        by0, by1 = y0, y1
    js = LINE_FMT % (e.handle, head_of(pp), order, x0, y0, x1, y1, x0, y0, mx, my, x1, y1, bx0, by0, bx1, by1)
    return Entry(e.handle, order, (bx0, by0, bx1, by1), js, rev, pp.layer.casefold(), None)


def session_values():
    try:
        from app.sysvars import registry as sv

        return {name: sv.session_value(name) for name in ("TEXTFILL", "FONTALT", "FONTFALLBACK")}
    except Exception:
        return {}


def space_key(doc, name):
    raw = str(name or "model").strip()
    low = raw.casefold()
    if low in ("", "model"):
        return "model"
    prefix = "layout:"
    if low.startswith("layout:") or low.startswith("block:"):
        prefix = low.split(":", 1)[0] + ":"
        raw = raw.split(":", 1)[1]
    rec = doc.drawing.table_get("layouts" if prefix == "layout:" else "blocks", raw)
    if rec is None:
        return None
    return prefix + rec["name"]


def fix_prims(prims):
    for p in prims:
        if "ci" in p:
            n = p.pop("ci")
            p["c"] = list(palette.index_rgb(n))
            if n == 7:
                p["c7"] = True
    return prims


def make_entry(e, ctx, order, rev):
    d = ctx.d
    if not ctx.visible(e) or e.handle in d.session_hidden:
        return None
    if e.kind == "line":
        return line_entry(e, ctx, order, rev)
    ctx.deps = set()
    shown = annotation.display_entity(ctx, e) if e.annotation_scales else e
    if shown is None:
        return None
    res = shapes.build(shown, ctx)
    if res is None:
        return None
    g, prims, _shape_grips, bb = res
    grips = grips_of(shown)
    pp = ctx.props(e)
    if prims and e.kind in TEXT_KINDS:
        fix_prims(prims)
    lt = pp.lt
    if lt is not None and e.kind == "lwpolyline" and e.linetype_gen:
        lt = dict(lt)
        lt["gen"] = True
    item = {"h": e.handle, "kind": e.kind, "layer": pp.layer, "color": list(pp.rgb), "color7": pp.c7, "lw": pp.lw, "lt": lt, "tr": pp.tr, "plot": pp.plot, "order": order, "geom": g, "prims": prims, "grips": grips, "bounds": bb}
    return Entry(e.handle, order, bb, _encode(item), rev, pp.layer.casefold(), frozenset(ctx.deps) if ctx.deps else None)


def touches(box, ext):
    return box[0] <= ext[0] or box[1] <= ext[1] or box[2] >= ext[2] or box[3] >= ext[3]


class DisplayState:
    def __init__(self, space):
        self.space = space
        self.entries = None
        self.okey = {}
        self.gsig = None
        self.layer_sig = {}
        self.built_rev = 0
        self.built_len = -1
        self.floor = 0
        self.log_revs = []
        self.log_h = []
        self.ext = None
        self.ext_dirty = False
        self.by_layer = {}
        self.by_block = {}

    def global_sig(self, doc, ctx):
        s = ctx.session
        return (ctx.ltscale, ctx.lw_default, ctx.pdmode, ctx.pdsize, ctx.fillmode, ctx.textfill, doc.table_rev.get("linetypes", 0), doc.table_rev.get("textstyles", 0), str(s.get("FONTALT", "")), str(s.get("FONTFALLBACK", "")), frozenset(doc.drawing.session_hidden), doc.drawing.metric, str(doc.drawing.header.get("CANNOSCALE", "1:1")), int(doc.drawing.header.get("ANNOALLVISIBLE", 1)), doc.table_rev.get("scales", 0), doc.table_rev.get("mleaderstyles", 0), doc.table_rev.get("tablestyles", 0), doc.table_rev.get("dimstyles", 0))

    def layer_signature(self, ctx):
        out = {}
        for rec in ctx.layers.values():
            out[rec["name"].casefold()] = (ctx.layer_props(rec["name"]), bool(rec.get("on", True)), bool(rec.get("frozen", False)))
        return out

    def log(self, rev, h):
        self.log_revs.append(rev)
        self.log_h.append(h)

    def index(self, h, entry):
        self.by_layer.setdefault(entry.layer, set()).add(h)
        for b in entry.deps or ():
            self.by_block.setdefault(b, set()).add(h)

    def unindex(self, h, entry):
        s = self.by_layer.get(entry.layer)
        if s is not None:
            s.discard(h)
        for b in entry.deps or ():
            s = self.by_block.get(b)
            if s is not None:
                s.discard(h)

    def renumber(self, seq):
        return {h: (i + 1) * STEP for i, h in enumerate(seq)}

    def assign_keys(self, seq):
        prev = self.okey
        known = [prev.get(h) for h in seq]
        last = 0
        for k in known:
            if k is None:
                continue
            if k <= last:
                return self.renumber(seq)
            last = k
        out = {}
        i, n = 0, len(seq)
        lo = 0
        while i < n:
            if known[i] is not None:
                out[seq[i]] = known[i]
                lo = known[i]
                i += 1
                continue
            j = i
            while j < n and known[j] is None:
                j += 1
            count = j - i
            hi = known[j] if j < n else None
            if hi is None:
                for t in range(count):
                    out[seq[i + t]] = lo + (t + 1) * STEP
            else:
                gap = (hi - lo) // (count + 1)
                if gap < 1:
                    return self.renumber(seq)
                for t in range(count):
                    out[seq[i + t]] = lo + (t + 1) * gap
            i = j
        return out

    def current_seq(self, doc):
        d = doc.drawing
        return [h for h in d.spaces.get(self.space, ()) if h in d.ents]

    def build_all(self, doc, ctx, first):
        d = doc.drawing
        rev = doc.rev
        seq = self.current_seq(doc)
        self.okey = self.renumber(seq) if first else self.assign_keys(seq)
        old = self.entries or {}
        entries = {}
        self.by_layer = {}
        self.by_block = {}
        ents = d.ents
        okey = self.okey
        ent_rev = doc.ent_rev
        for h in seq:
            made = make_entry(ents[h], ctx, okey[h], rev)
            prev = old.get(h)
            if made is None:
                if prev is not None:
                    self.log(rev, h)
                continue
            if first:
                made.rev = ent_rev.get(h, 0)
            elif prev is not None and prev.js == made.js:
                made.rev = prev.rev
            else:
                self.log(rev, h)
            entries[h] = made
            self.index(h, made)
        for h in old:
            if h not in entries and h not in ents:
                self.log(rev, h)
        self.entries = entries
        self.ext_dirty = True

    def drop(self, h, prev, rev):
        self.unindex(h, prev)
        del self.entries[h]
        self.mark_ext(prev)
        self.log(rev, h)

    def refresh(self, doc, ctx, handles):
        d = doc.drawing
        rev = doc.rev
        entries = self.entries
        for h in handles:
            e = d.ents.get(h)
            prev = entries.get(h)
            order = self.okey.get(h)
            if e is None or e.owner != self.space or order is None:
                if prev is not None:
                    self.drop(h, prev, rev)
                continue
            made = make_entry(e, ctx, order, rev)
            if made is None:
                if prev is not None:
                    self.drop(h, prev, rev)
                continue
            if prev is not None:
                self.unindex(h, prev)
                self.mark_ext(prev)
                if prev.js == made.js:
                    made.rev = prev.rev
                else:
                    self.log(rev, h)
            else:
                self.log(rev, h)
            entries[h] = made
            self.index(h, made)
            self.add_ext(made)

    def mark_ext(self, entry):
        if self.ext is None or self.ext_dirty:
            return
        b = entry.bounds
        if b is not None and touches(b, self.ext):
            self.ext_dirty = True

    def add_ext(self, entry):
        if self.ext_dirty:
            return
        b = entry.bounds
        if b is None:
            return
        if self.ext is None:
            self.ext = list(b)
        else:
            e = self.ext
            self.ext = [min(e[0], b[0]), min(e[1], b[1]), max(e[2], b[2]), max(e[3], b[3])]

    def recompute_ext(self):
        lo_x = lo_y = float("inf")
        hi_x = hi_y = float("-inf")
        for en in self.entries.values():
            b = en.bounds
            if b is None:
                continue
            if b[0] < lo_x:
                lo_x = b[0]
            if b[1] < lo_y:
                lo_y = b[1]
            if b[2] > hi_x:
                hi_x = b[2]
            if b[3] > hi_y:
                hi_y = b[3]
        self.ext = None if lo_x == float("inf") else [lo_x, lo_y, hi_x, hi_y]
        self.ext_dirty = False

    def unchanged(self, doc, gsig, lsig):
        return self.entries is not None and gsig == self.gsig and lsig == self.layer_sig and doc.rev == self.built_rev and self.built_len == len(doc.drawing.spaces.get(self.space, ()))

    def update(self, doc):
        d = doc.drawing
        ctx = Context(doc, session_values())
        gsig = self.global_sig(doc, ctx)
        lsig = self.layer_signature(ctx)
        if self.unchanged(doc, gsig, lsig):
            return
        first = self.entries is None
        if not first and doc.rev == self.built_rev:
            doc.bump("display")
        if first:
            shapes.reset_fonts()
            self.build_all(doc, ctx, True)
            self.floor = max(doc.table_rev.get("layers", 0), doc.table_rev.get("linetypes", 0), doc.table_rev.get("textstyles", 0), doc.header_rev, doc.space_rev.get(self.space, 0))
            pairs = sorted((en.rev, h) for h, en in self.entries.items() if en.rev > 0)
            self.log_revs = [p[0] for p in pairs]
            self.log_h = [p[1] for p in pairs]
        elif gsig != self.gsig:
            shapes.reset_fonts()
            self.build_all(doc, ctx, False)
        else:
            self.incremental(doc, ctx, lsig)
        self.gsig = gsig
        self.layer_sig = lsig
        self.built_rev = doc.rev
        self.built_len = len(d.spaces.get(self.space, ()))
        if self.ext_dirty:
            self.recompute_ext()

    def incremental(self, doc, ctx, lsig):
        d = doc.drawing
        since = self.built_rev
        handles = {h for h, r in doc.ent_rev.items() if r > since}
        handles.update(h for h, r in doc.removed_rev.items() if r > since)
        changed = {k for k in set(lsig) | set(self.layer_sig) if lsig.get(k) != self.layer_sig.get(k)}
        if changed:
            for k in changed:
                handles |= self.by_layer.get(k, set())
            for s in self.by_block.values():
                handles |= s
            for h in self.current_seq(doc):
                if h not in self.entries and d.ents[h].layer.casefold() in changed:
                    handles.add(h)
        blocks = {k.split(":", 1)[1].casefold() for k, r in doc.space_rev.items() if k.startswith("block:") and r > since}
        for h in list(handles):
            e = d.ents.get(h)
            if e is not None and e.owner.startswith("block:"):
                blocks.add(e.owner.split(":", 1)[1].casefold())
            elif e is None and h not in self.entries:
                blocks.add("*")
        for b in blocks:
            if b == "*":
                for s in self.by_block.values():
                    handles |= s
            else:
                handles |= self.by_block.get(b, set())
        if doc.space_rev.get(self.space, 0) > since or self.built_len != len(d.spaces.get(self.space, ())):
            seq = self.current_seq(doc)
            fresh = self.assign_keys(seq)
            for h, k in fresh.items():
                if h in self.entries and self.okey.get(h) != k:
                    handles.add(h)
            self.okey = fresh
        self.refresh(doc, ctx, handles)

    def collect(self, doc, since):
        full = since is None or since < self.floor or since > doc.rev
        if full:
            if self.unsorted():
                ordered = sorted(self.entries.values(), key=lambda en: en.order)
                self.entries = {en.h: en for en in ordered}
            return True, [en.js for en in self.entries.values()], []
        lo = bisect_right(self.log_revs, since)
        seen = set()
        got = []
        removed = []
        for h in self.log_h[lo:]:
            if h in seen:
                continue
            seen.add(h)
            en = self.entries.get(h)
            if en is None:
                removed.append(h)
            elif en.rev > since:
                got.append(en)
        got.sort(key=lambda en: en.order)
        return False, [en.js for en in got], removed

    def unsorted(self):
        last = -1
        for en in self.entries.values():
            k = en.order
            if k < last:
                return True
            last = k
        return False


def state_for(doc, space):
    per = _states.get(doc)
    if per is None:
        per = {}
        _states[doc] = per
    st = per.get(space)
    if st is None:
        st = DisplayState(space)
        per[space] = st
    return st
