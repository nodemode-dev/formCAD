import datetime
import hashlib
import math
import zlib

from app.output.sheet import PT_PER_MM

MAX_LAYERS = 500
MAX_LAYER_NAME = 127
MAX_LINKS = 2000
MAX_URL = 2048
MAX_PAGES = 256
UNSAFE = ("javascript:", "vbscript:", "data:", "file:", "script:")


def num(v):
    s = ("%.3f" % v).rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def text_string(s):
    s = str(s)
    try:
        s.encode("ascii")
        return "(" + s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", "\\r").replace("\n", "\\n") + ")"
    except UnicodeEncodeError:
        return "<FEFF" + s.encode("utf-16-be").hex().upper() + ">"


def safe_url(url):
    raw = str(url or "").strip()
    if not raw or len(raw) > MAX_URL:
        return None
    low = raw.casefold().replace(" ", "")
    if any(low.startswith(p) for p in UNSAFE):
        return None
    out = []
    for b in raw.encode("utf-8"):
        if 0x21 <= b <= 0x7E and chr(b) not in "()\\":
            out.append(chr(b))
        else:
            out.append("%%%02X" % b)
    return "".join(out)


def subset_tag(seed, taken):
    h = int(hashlib.sha1(seed).hexdigest(), 16)
    while True:
        tag = "".join(chr(65 + (h >> (5 * i)) % 26) for i in range(6))
        if tag not in taken:
            taken.add(tag)
            return tag
        h += 1


class Pdf:
    def __init__(self, compress=True):
        self.compress = compress
        self.objs = []

    def reserve(self):
        self.objs.append(None)
        return len(self.objs)

    def put(self, n, body):
        self.objs[n - 1] = body if isinstance(body, bytes) else body.encode("latin-1")

    def add(self, body):
        n = self.reserve()
        self.put(n, body)
        return n

    def stream(self, d, data, compress=None):
        if (self.compress if compress is None else compress):
            data = zlib.compress(data, 6)
            d = d + " /Filter /FlateDecode"
        return self.add(("<< %s /Length %d >>\nstream\n" % (d, len(data))).encode("latin-1") + data + b"\nendstream")

    def finish(self, root, info, ident):
        out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
        offs = []
        for i, body in enumerate(self.objs, 1):
            offs.append(len(out))
            out += b"%d 0 obj\n" % i + (body or b"null") + b"\nendobj\n"
        start = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(self.objs) + 1)
        for o in offs:
            out += b"%010d 00000 n \n" % o
        out += ("trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R /ID [<%s> <%s>] >>\nstartxref\n%d\n%%%%EOF\n" % (len(self.objs) + 1, root, info, ident, ident, start)).encode("latin-1")
        return bytes(out)


def dash_op(dash):
    if not dash:
        return "[] 0 d"
    arr, phase = dash
    return "[%s] %s d" % (" ".join(num(v * PT_PER_MM) for v in arr), num(phase * PT_PER_MM))


class PageWriter:
    def __init__(self, sheet, ocg_names, alphas, fonts, min_width):
        self.sheet = sheet
        self.ocg_names = ocg_names
        self.alphas = alphas
        self.fonts = fonts
        self.min_width = min_width
        self.out = []
        self.oc_used = set()
        self.cur_oc = None
        self.state = {}
        self.depth = 0
        self.images = {}

    def pt(self, x, y):
        return "%s %s" % (num(x * PT_PER_MM), num(y * PT_PER_MM))

    def set_oc(self, key):
        if key == self.cur_oc:
            return
        if self.cur_oc is not None:
            self.out.append("EMC")
        self.cur_oc = None
        if key is not None and key in self.ocg_names:
            name = self.ocg_names[key][1]
            self.out.append("/OC /%s BDC" % name)
            self.oc_used.add(key)
            self.cur_oc = key

    def alpha(self, a):
        k = round(min(1.0, max(0.0, a)), 2)
        if self.state.get("a") == k:
            return
        self.state["a"] = k
        self.alphas.setdefault(k, "GS%d" % len(self.alphas))
        self.out.append("/%s gs" % self.alphas[k])

    def stroke_state(self, st):
        w = max(st.width, self.min_width)
        sig = (st.rgb, w, st.cap, st.join, st.dash)
        if self.state.get("s") != sig:
            prev = self.state.get("s")
            if prev is None or prev[1] != w:
                self.out.append("%s w" % num(w * PT_PER_MM))
            if prev is None or prev[2] != st.cap:
                self.out.append("%d J" % st.cap)
            if prev is None or prev[3] != st.join:
                self.out.append("%d j" % st.join)
            if prev is None or prev[4] != st.dash:
                self.out.append(dash_op(st.dash))
            if prev is None or prev[0] != st.rgb:
                self.out.append("%s %s %s RG" % tuple(num(c / 255.0) for c in st.rgb))
            self.state["s"] = sig
        self.alpha(st.alpha)

    def fill_state(self, st):
        if self.state.get("f") != st.rgb:
            self.out.append("%s %s %s rg" % tuple(num(c / 255.0) for c in st.rgb))
            self.state["f"] = st.rgb
        self.alpha(st.alpha)

    def path(self, pts, closed):
        first = True
        for x, y in pts:
            self.out.append("%s %s" % (self.pt(x, y), "m" if first else "l"))
            first = False
        if closed:
            self.out.append("h")

    def clip(self, rings, evenodd):
        self.set_oc(None)
        self.out.append("q")
        self.depth += 1
        for r in rings:
            self.path(r, True)
        self.out.append("W* n" if evenodd else "W n")
        self.state = {}

    def unclip(self):
        self.set_oc(None)
        if self.depth:
            self.out.append("Q")
            self.depth -= 1
        self.state = {}

    def run(self):
        s = self.sheet
        x0, y0, x1, y1 = s.printable
        self.out.append("q")
        self.out.append("%s %s %s %s re W n" % (num(x0 * PT_PER_MM), num(y0 * PT_PER_MM), num((x1 - x0) * PT_PER_MM), num((y1 - y0) * PT_PER_MM)))
        ops = s.ops
        i = 0
        n = len(ops)
        while i < n:
            op = ops[i]
            kind = op[0]
            if kind == "C":
                self.clip(op[1], op[2])
                i += 1
            elif kind == "E":
                self.unclip()
                i += 1
            elif kind == "S":
                st = op[3]
                self.set_oc(st.layer)
                self.stroke_state(st)
                j = i
                while j < n and ops[j][0] == "S" and ops[j][3] == st:
                    self.path(ops[j][1], ops[j][2])
                    j += 1
                self.out.append("S")
                i = j
            elif kind == "F":
                st = op[2]
                self.set_oc(st.layer)
                self.fill_state(st)
                j = i
                if op[3]:
                    for r in op[1]:
                        self.path(r, True)
                    self.out.append("f*")
                    j = i + 1
                else:
                    while j < n and ops[j][0] == "F" and ops[j][2] == st and not ops[j][3]:
                        for r in ops[j][1]:
                            self.path(r, True)
                        j += 1
                    self.out.append("f")
                i = j
            elif kind == "T":
                self.text(op)
                i += 1
            elif kind == "I":
                self.image(op)
                i += 1
            else:
                i += 1
        self.set_oc(None)
        while self.depth:
            self.unclip()
        self.out.append("Q")
        return "\n".join(self.out).encode("latin-1")

    def image(self, op):
        pic, c, alpha, layer = op[1], op[2], op[3], op[4]
        o, r, t = c[0], c[1], c[2]
        longest = max(math.hypot(*(r - o)), math.hypot(*(t - o)))
        side = int(min(6000, max(256, math.ceil(longest / 25.4 * 300.0 / 256.0) * 256)))
        key = (pic["path"], pic["page"], pic["source"], side if pic["source"] == "pdf" else 0)
        name = self.images.setdefault(key, "Im%d" % len(self.images))
        self.set_oc(layer)
        self.out.append("q")
        if alpha < 0.999:
            a = round(min(1.0, max(0.0, alpha)), 2)
            self.alphas.setdefault(a, "GS%d" % len(self.alphas))
            self.out.append("/%s gs" % self.alphas[a])
        k = PT_PER_MM
        self.out.append("%s %s %s %s %s %s cm" % tuple(num(v) for v in ((r[0] - o[0]) * k, (r[1] - o[1]) * k, (t[0] - o[0]) * k, (t[1] - o[1]) * k, o[0] * k, o[1] * k)))
        self.out.append("/%s Do" % name)
        self.out.append("Q")
        self.state.pop("a", None)

    def text(self, op):
        font, glyphs, st = op[1], op[2], op[3]
        if not glyphs:
            return
        self.set_oc(st.layer)
        self.fill_state(st)
        ref = self.fonts.setdefault(font.key, [font, "F%d" % len(self.fonts)])[1]
        self.out.append("BT")
        self.out.append("/%s 1 Tf" % ref)
        group = None
        parts = []

        def flush():
            if group is not None and parts:
                self.out.append("%s Tm" % group[0])
                self.out.append("[%s] TJ" % " ".join(parts))

        prev = None
        for gid, a, b, c, d, e, f in glyphs:
            font.use(gid)
            lin = (a * PT_PER_MM, b * PT_PER_MM, c * PT_PER_MM, d * PT_PER_MM)
            pos = (e * PT_PER_MM, f * PT_PER_MM)
            adj = None
            if prev is not None and all(abs(lin[k] - prev[0][k]) <= 1e-7 * (abs(lin[k]) + 1e-9) + 1e-9 for k in range(4)):
                pa, pb, pc, pd = prev[0]
                det = pa * pd - pb * pc
                if abs(det) > 1e-18:
                    de, df = pos[0] - prev[1][0], pos[1] - prev[1][1]
                    tx = (de * pd - df * pc) / det
                    ty = (pa * df - pb * de) / det
                    if abs(ty) < 1e-4:
                        adj = (tx - prev[2] / 1000.0) * 1000.0
            if adj is None:
                flush()
                parts = []
                group = ("%s %s %s %s %s %s" % tuple(num(v) for v in (lin[0], lin[1], lin[2], lin[3], pos[0], pos[1])),)
            elif abs(adj) >= 0.5:
                parts.append(num(-adj))
            parts.append("<%04X>" % gid)
            prev = (lin, pos, font.width(gid))
        flush()
        self.out.append("ET")


def image_xobject(pdf, key):
    from app.doc import underlays as U

    path, page, source, side = key
    head = "/Type /XObject /Subtype /Image"
    try:
        if source == "image" and U.kind_of(path) == "jpeg":
            j = U.jpeg_passthrough(path)
            if j is not None:
                cs = "/DeviceRGB" if j["comps"] == 3 else "/DeviceGray"
                return pdf.stream("%s /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode" % (head, j["w"], j["h"], cs), j["data"], compress=False)
        if source == "image" and U.kind_of(path) == "png":
            p = U.png_passthrough(path)
            if p is not None:
                colors = {0: 1, 2: 3, 3: 1}[p["ctype"]]
                if p["ctype"] == 3:
                    n = max(1, len(p["plte"]) // 3)
                    cs = "[/Indexed /DeviceRGB %d <%s>]" % (n - 1, p["plte"][: n * 3].hex())
                else:
                    cs = "/DeviceRGB" if colors == 3 else "/DeviceGray"
                parms = "/DecodeParms << /Predictor 15 /Colors %d /BitsPerComponent %d /Columns %d >>" % (colors, p["bits"], p["w"])
                return pdf.stream("%s /Width %d /Height %d /ColorSpace %s /BitsPerComponent %d /Filter /FlateDecode %s" % (head, p["w"], p["h"], cs, p["bits"], parms), p["idat"], compress=False)
        px = U.pixels(path, page, side)
    except (U.UnderlayError, OSError):
        return None
    h, w = px.shape[:2]
    smask = ""
    if (px[:, :, 3] < 255).any():
        sm = pdf.stream("%s /Width %d /Height %d /ColorSpace /DeviceGray /BitsPerComponent 8" % (head, w, h), px[:, :, 3].tobytes(), compress=True)
        smask = " /SMask %d 0 R" % sm
    return pdf.stream("%s /Width %d /Height %d /ColorSpace /DeviceRGB /BitsPerComponent 8%s" % (head, w, h, smask), px[:, :, :3].tobytes(), compress=True)


def to_unicode_cmap(font):
    pairs = []
    for gid in sorted(font.gids):
        cp = font.unicode_of(gid)
        if cp is not None and 0 < cp <= 0x10FFFF and not 0xD800 <= cp <= 0xDFFF:
            pairs.append((gid, cp))
    lines = ["/CIDInit /ProcSet findresource begin", "12 dict begin", "begincmap", "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def", "/CMapName /Adobe-Identity-UCS def", "/CMapType 2 def", "1 begincodespacerange", "<0000> <FFFF>", "endcodespacerange"]
    for k in range(0, len(pairs), 100):
        chunk = pairs[k:k + 100]
        lines.append("%d beginbfchar" % len(chunk))
        for gid, cp in chunk:
            lines.append("<%04X> <%s>" % (gid, chr(cp).encode("utf-16-be").hex().upper()))
        lines.append("endbfchar")
    lines += ["endcmap", "CMapName currentdict /CMap defineresource pop", "end", "end"]
    return "\n".join(lines).encode("ascii")


def write_font(pdf, font, tag):
    data = font.subset_bytes()
    base = "%s+%s" % (tag, "".join(c for c in font.family if c.isalnum()) or "Font")
    ff = pdf.stream("/Length1 %d" % len(data), data)
    fd = pdf.add("<< /Type /FontDescriptor /FontName /%s /Flags 4 /FontBBox [%s] /ItalicAngle %s /Ascent %s /Descent %s /CapHeight %s /StemV 80 /FontFile2 %d 0 R >>" % (base, " ".join(num(v) for v in font.bbox), num(font.italic), num(font.ascent), num(font.descent), num(font.cap), ff))
    ws = " ".join("%d [%s]" % (g, num(font.width(g))) for g in sorted(font.gids))
    cid = pdf.add("<< /Type /Font /Subtype /CIDFontType2 /BaseFont /%s /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >> /FontDescriptor %d 0 R /DW 1000 /W [%s] /CIDToGIDMap /Identity >>" % (base, fd, ws))
    tu = pdf.stream("", to_unicode_cmap(font))
    return pdf.add("<< /Type /Font /Subtype /Type0 /BaseFont /%s /Encoding /Identity-H /DescendantFonts [%d 0 R] /ToUnicode %d 0 R >>" % (base, cid, tu))


def render(sheets, title="", compress=True, layers=True, min_width=0.05, links=True, when=None):
    sheets = list(sheets)[:MAX_PAGES]
    pdf = Pdf(compress)
    ocg_names = {}
    order = []
    if layers:
        for sh in sheets:
            for key, (name, on) in sh.layers.items():
                if key in ocg_names:
                    if on:
                        ocg_names[key][2] = True
                    continue
                if len(ocg_names) >= MAX_LAYERS:
                    continue
                ocg_names[key] = [name[:MAX_LAYER_NAME], "OC%d" % len(ocg_names), on]
                order.append(key)
    catalog = pdf.reserve()
    pages_root = pdf.reserve()
    info = pdf.reserve()
    ocg_refs = {}
    for key in order:
        name, res, on = ocg_names[key]
        ocg_refs[key] = pdf.add("<< /Type /OCG /Name %s /Intent /View >>" % text_string(name))
    taken = set()
    fonts = {}
    alphas = {1.0: "GS0"}
    page_objs = []
    meta = []
    for sh in sheets:
        pw = PageWriter(sh, {k: (ocg_names[k][0], ocg_names[k][1]) for k in order}, alphas, fonts, min_width)
        data = pw.run()
        cs = pdf.stream("", data)
        po = pdf.reserve()
        annots = []
        if links:
            for rect, url in sh.links[:MAX_LINKS]:
                u = safe_url(url)
                if u is None:
                    continue
                r = [rect[0] * PT_PER_MM, rect[1] * PT_PER_MM, rect[2] * PT_PER_MM, rect[3] * PT_PER_MM]
                annots.append(pdf.add("<< /Type /Annot /Subtype /Link /Rect [%s] /Border [0 0 0] /A << /S /URI /URI (%s) >> >>" % (" ".join(num(v) for v in r), u)))
        page_objs.append(po)
        meta.append((sh, po, cs, pw, annots))
    font_objs = {}
    for key, (font, ref) in fonts.items():
        if not font.gids:
            continue
        tag = subset_tag(repr((key, sorted(font.gids))).encode("utf-8"), taken)
        font_objs[ref] = write_font(pdf, font, tag)
    gs_dict = " ".join("/%s << /Type /ExtGState /CA %s /ca %s >>" % (name, num(a) if a < 1 else "1", num(a) if a < 1 else "1") for a, name in alphas.items())
    ximgs = {}
    for sh, po, cs, pw, annots in meta:
        props = " ".join("/%s %d 0 R" % (ocg_names[k][1], ocg_refs[k]) for k in sorted(pw.oc_used))
        fdict = " ".join("/%s %d 0 R" % (ref, font_objs[ref]) for key, (font, ref) in fonts.items() if ref in font_objs)
        res = "<< /ExtGState << %s >>" % gs_dict
        if fdict:
            res += " /Font << %s >>" % fdict
        xo = []
        for key, iname in pw.images.items():
            if key not in ximgs:
                ximgs[key] = image_xobject(pdf, key) or pdf.stream("/Type /XObject /Subtype /Form /BBox [0 0 1 1]", b"", compress=False)
            xo.append("/%s %d 0 R" % (iname, ximgs[key]))
        if xo:
            res += " /XObject << %s >>" % " ".join(xo)
        if props:
            res += " /Properties << %s >>" % props
        res += " >>"
        w, h = sh.width * PT_PER_MM, sh.height * PT_PER_MM
        body = "<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %s %s] /Contents %d 0 R /Resources %s" % (pages_root, num(w), num(h), cs, res)
        if annots:
            body += " /Annots [%s]" % " ".join("%d 0 R" % a for a in annots)
        pdf.put(po, body + " >>")
    pdf.put(pages_root, "<< /Type /Pages /Kids [%s] /Count %d >>" % (" ".join("%d 0 R" % p for p in page_objs), len(page_objs)))
    cat = "<< /Type /Catalog /Pages %d 0 R" % pages_root
    if sheets:
        nums = " ".join("%d << /P %s >>" % (i, text_string(sh.name)) for i, sh in enumerate(sheets))
        cat += " /PageLabels << /Nums [%s] >>" % nums
        outlines = pdf.reserve()
        items = [pdf.reserve() for _ in sheets]
        for i, (sh, po) in enumerate(zip(sheets, page_objs)):
            extra = ""
            if i > 0:
                extra += " /Prev %d 0 R" % items[i - 1]
            if i + 1 < len(items):
                extra += " /Next %d 0 R" % items[i + 1]
            pdf.put(items[i], "<< /Title %s /Parent %d 0 R /Dest [%d 0 R /Fit]%s >>" % (text_string(sh.name), outlines, po, extra))
        pdf.put(outlines, "<< /Type /Outlines /First %d 0 R /Last %d 0 R /Count %d >>" % (items[0], items[-1], len(items)))
        cat += " /Outlines %d 0 R" % outlines
    if order:
        on = [ocg_refs[k] for k in order if ocg_names[k][2]]
        off = [ocg_refs[k] for k in order if not ocg_names[k][2]]
        cat += " /OCProperties << /OCGs [%s] /D << /Order [%s] /BaseState /ON /ON [%s] /OFF [%s] >> >>" % (" ".join("%d 0 R" % r for r in ocg_refs.values()), " ".join("%d 0 R" % ocg_refs[k] for k in order), " ".join("%d 0 R" % r for r in on), " ".join("%d 0 R" % r for r in off))
    pdf.put(catalog, cat + " >>")
    stamp = (when or datetime.datetime.now(datetime.timezone.utc)).strftime("D:%Y%m%d%H%M%SZ")
    pdf.put(info, "<< /Title %s /Producer (FormCAD) /Creator (FormCAD) /CreationDate (%s) /ModDate (%s) >>" % (text_string(title or "FormCAD plot"), stamp, stamp))
    ident = hashlib.md5(("%s%s%d" % (title, stamp, len(pdf.objs))).encode("utf-8")).hexdigest().upper()
    return pdf.finish(catalog, info, ident)
