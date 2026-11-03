import time

from app.cam import feeds as F
from app.cam import geom, limits, model
from app.cam.limits import CamError, Cancelled
from app.cam.tools import Tool


class Heights:
    def __init__(self, clearance, retract, feed, top, bottom):
        self.clearance = clearance
        self.retract = retract
        self.feed = feed
        self.top = top
        self.bottom = bottom


class GenCtx:
    def __init__(self, doc, setup, op, tool_rec, params, job=None, default_geometry=None):
        self.default_geometry = default_geometry
        self.doc = doc
        self.setup = setup
        self.op = op
        self.tool = Tool(tool_rec)
        self.p = params
        self.job = job
        self.warnings: list = []
        self.limit = limits.get()
        self.started = time.monotonic()
        self._tris = None
        self._region = None
        self._stock = None
        self.fixtures = None
        h = op.get("heights") or {}
        sb = self.stock
        safe = setup.get("safe") or {}
        top_stock = sb["max"][2]
        top = h.get("top")
        top = top_stock if top is None else float(top)
        clear = h.get("clearance")
        retr = h.get("retract")
        fd = h.get("feed")
        self.h = Heights(top_stock + float(safe.get("clearance", 20.0)) if clear is None else float(clear), top_stock + float(safe.get("retract", 5.0)) if retr is None else float(retr), top_stock + float(safe.get("feed", 2.0)) if fd is None else float(fd), top, None if h.get("bottom") is None else float(h["bottom"]))
        if not (self.h.clearance >= self.h.retract >= self.h.feed):
            raise CamError("Heights must satisfy clearance >= retract >= feed.")

    @property
    def stock(self) -> dict:
        if self._stock is None:
            self._stock = model.stock_box(self.doc, self.setup)
            self._stock["polygon"] = None
        return self._stock

    def stock_polygon(self) -> list:
        return model.stock_polygon(self.doc, self.setup)

    def triangles(self):
        if self._tris is None:
            self._tris = model.setup_triangles(self.doc, self.setup)
        return self._tris

    def fixture_triangles(self):
        return model.fixture_triangles(self.doc, self.setup)

    def bottom(self) -> float:
        if self.h.bottom is None:
            raise CamError("Give the bottom height of the cut.")
        return self.h.bottom

    def region(self) -> geom.Region:
        if self._region is None:
            g = self.op.get("geometry") or self.default_geometry or {}
            if not g:
                raise CamError("The operation has no geometry. Pick an outline, entities or a model section.")
            sz = None
            if self.h.bottom is not None:
                sz = self.h.bottom + 0.05
            tris = self.triangles() if g.get("kind") in ("section", "removal") else None
            self._region = geom.Region(model.build_region(self.doc, self.setup, g, self.tool.radius, sz, tris))
            limits.need(geom.vertex_count(self._region.rings), "region_vertices", "Region")
        return self._region

    def points(self) -> list:
        g = self.op.get("geometry") or {}
        if not g:
            raise CamError("The operation has no geometry. Give points, circles or a model hole search.")
        tris = self.triangles() if g.get("kind") == "model_holes" else None
        return model.build_points(self.doc, self.setup, g, tris)

    def check(self) -> None:
        if self.job is not None:
            self.job.check()
        if time.monotonic() - self.started > self.limit["seconds"]:
            raise CamError("Generation stopped after %d s (time limit). Use a larger stepover or a smaller region." % int(self.limit["seconds"]))

    def progress(self, fraction: float) -> None:
        if self.job is not None:
            self.job.report(op_fraction=fraction)

    def warn(self, text: str) -> None:
        if text not in self.warnings:
            self.warnings.append(text)

    def feed_for(self, ae: float = 0.0, ap: float = 0.0) -> dict:
        return F.resolve(self.tool, self.op.get("feeds") or {}, ae, ap)

    @property
    def feeds(self) -> dict:
        return self.feed_for()
