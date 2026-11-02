import io
import logging
import threading

from fontTools import subset
from fontTools.ttLib import TTFont

logging.getLogger("fontTools").setLevel(logging.ERROR)
LOCK = threading.RLock()


def embeddable(ttf) -> bool:
    if "glyf" not in ttf or "CFF " in ttf or "CFF2" in ttf:
        return False
    os2 = ttf["OS/2"] if "OS/2" in ttf else None
    fs = int(getattr(os2, "fsType", 0) or 0)
    if fs & 0x0002 or fs & 0x0100 or fs & 0x0200:
        return False
    return True


class EmbedFont:
    def __init__(self, src):
        self.src = src
        self.path = src.path
        self.index = getattr(src, "index", 0)
        self.key = (self.path, self.index)
        self.gids = set()
        with LOCK:
            ttf = src.ttf
            self.ok = embeddable(ttf)
            self.upem = float(ttf["head"].unitsPerEm)
            self.em_over_cap = float(src.em_over_cap)
            hhea = ttf["hhea"]
            self.ascent = float(hhea.ascent) * 1000.0 / self.upem
            self.descent = float(hhea.descent) * 1000.0 / self.upem
            head = ttf["head"]
            self.bbox = [float(head.xMin) * 1000.0 / self.upem, float(head.yMin) * 1000.0 / self.upem, float(head.xMax) * 1000.0 / self.upem, float(head.yMax) * 1000.0 / self.upem]
            os2 = ttf["OS/2"] if "OS/2" in ttf else None
            cap = float(getattr(os2, "sCapHeight", 0) or 0) if os2 is not None else 0.0
            self.cap = (cap or src.cap) * 1000.0 / self.upem
            post = ttf["post"] if "post" in ttf else None
            self.italic = float(getattr(post, "italicAngle", 0.0) or 0.0)
            self.hmtx = ttf["hmtx"]
            self.order = ttf.getGlyphOrder()
            self.reverse = {}
            for cp, name in sorted((ttf.getBestCmap() or {}).items(), reverse=True):
                self.reverse[name] = cp
            self.family = src.family() or "Font"

    def use(self, gid):
        self.gids.add(int(gid))

    def width(self, gid):
        name = self.order[gid] if 0 <= gid < len(self.order) else None
        try:
            return float(self.hmtx[name][0]) * 1000.0 / self.upem
        except Exception:
            return 1000.0

    def unicode_of(self, gid):
        name = self.order[gid] if 0 <= gid < len(self.order) else None
        return self.reverse.get(name)

    def subset_bytes(self):
        with LOCK:
            ttf = TTFont(self.path, fontNumber=self.index, lazy=False) if self.path.lower().endswith((".ttc", ".otc")) else TTFont(self.path, lazy=False)
            opts = subset.Options()
            opts.retain_gids = True
            opts.glyph_names = False
            opts.notdef_outline = True
            opts.name_IDs = [1, 2, 3, 4, 6]
            opts.layout_features = []
            opts.hinting = False
            opts.drop_tables += ["DSIG", "GSUB", "GPOS", "GDEF", "kern", "gasp"]
            sub = subset.Subsetter(opts)
            sub.populate(gids=sorted(self.gids | {0}))
            sub.subset(ttf)
            out = io.BytesIO()
            ttf.save(out)
            ttf.close()
            return out.getvalue()
