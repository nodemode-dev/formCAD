import threading

from app.display import insert, shapes
from app.text import mtext, single
from app.text.model import Sink, compose

SESSION = threading.RLock()


class Capture:
    def __init__(self):
        self.thread = threading.get_ident()
        self.pending = []
        self.owned = {}
        self.keep = []
        self.fonts = {}

    def record(self, runs, m):
        for src, gm, ckey in runs:
            self.pending.append((src, compose(m, gm), ckey))

    def runs_of(self, prims):
        return self.owned.get(id(prims))


class RecSink(Sink):
    def __init__(self, cap):
        super().__init__()
        self.runs = []
        self.cap = cap

    def prims(self, m, digits=6):
        out = super().prims(m, digits)
        self.cap.record(self.runs, m)
        return out


class Patched:
    def __init__(self, cap):
        self.cap = cap

    def __enter__(self):
        SESSION.acquire()
        cap = self.cap
        self.saved = (single.Sink, mtext.Sink, shapes.build, insert.xf_prims)
        orig_build = shapes.build
        orig_xf = insert.xf_prims
        me = cap.thread

        def sink_factory():
            return RecSink(cap) if threading.get_ident() == me else Sink()

        def build(e, ctx):
            if threading.get_ident() != me:
                return orig_build(e, ctx)
            start = len(cap.pending)
            res = orig_build(e, ctx)
            runs = cap.pending[start:]
            del cap.pending[start:]
            if res and runs:
                cap.owned[id(res[1])] = runs
                cap.keep.append(res)
            return res

        def xf(prims, m, tag):
            out = orig_xf(prims, m, tag)
            if threading.get_ident() == me:
                runs = cap.owned.get(id(prims))
                if runs:
                    key = None
                    if tag:
                        key = ("c7",) if tag.get("c7") else ("r",) + tuple(tag["c"])
                    for src, gm, ck in runs:
                        cap.pending.append((src, compose(m, gm), ck if ck is not None else key))
            return out

        single.Sink = sink_factory
        mtext.Sink = sink_factory
        shapes.build = build
        insert.xf_prims = xf
        return cap

    def __exit__(self, *exc):
        single.Sink, mtext.Sink, shapes.build, insert.xf_prims = self.saved
        SESSION.release()
        return False
