import logging
import os
import sys
import threading
from pathlib import Path

from app.text import scripts, stroke
from app.text.model import Glyph, box_of

EXTS = (".ttf", ".otf", ".ttc", ".otc")
STROKE_NAMES = {"txt", "simplex", "romans", "romanc", "monotxt", "iso", "isocp", "isocp2", "isocpeur", "isoct", "gothice", "italic", "scripts", "complex", "formcad-stroke"}
WELL_KNOWN = ("arialunicodems", "arialuni", "notosanscjkjp-regular", "notosanscjk-regular", "notosanscjksc-regular", "notosanscjk", "msgothic", "meiryo", "pingfang", "hiragino", "applegothic", "malgun", "simsun", "dejavusans", "liberationsans-regular", "arial", "segoeui", "seguisym", "helvetica", "notosans-regular", "freesans", "unifont")
SCRIPT_FONTS = {
    "arabic": ("Noto Sans Arabic", "Noto Naskh Arabic", "Segoe UI", "Tahoma", "Arial", "Geeza Pro", "Al Bayan", "Damascus", "DejaVu Sans", "FreeSerif", "FreeSans", "Arial Unicode MS"),
    "hebrew": ("Noto Sans Hebrew", "Segoe UI", "Arial", "Arial Hebrew", "Lucida Grande", "DejaVu Sans", "FreeSerif", "FreeSans", "Arial Unicode MS"),
    "thai": ("TH Sarabun New", "Angsana New", "Cordia New", "IBM Plex Sans Thai", "Noto Sans Thai", "Leelawadee UI", "Leelawadee", "Tahoma", "Thonburi", "Ayuthaya", "Loma", "Garuda", "Norasi", "FreeSerif", "DejaVu Sans", "Arial Unicode MS"),
}
SCRIPT_FACES = {}
MAX_SCAN_FILES = 60
MAX_SCAN_BYTES = 512 * 1024 * 1024
MAX_FAMILY_FILES = 3000
WIDE = ((0x1100, 0x11FF), (0x2E80, 0xA4CF), (0xAC00, 0xD7AF), (0xF900, 0xFAFF), (0xFE30, 0xFE6F), (0xFF00, 0xFF60), (0xFFE0, 0xFFE6), (0x20000, 0x3FFFF))

_lock = threading.RLock()


def font_dirs():
    home = Path.home()
    out = []
    try:
        from app.core import config

        out.append(config.data_dir() / "fonts")
    except Exception:
        pass
    extra = os.environ.get("FORMCAD_FONTS", "")
    out.extend(Path(p) for p in extra.split(os.pathsep) if p)
    if sys.platform == "darwin":
        out += [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"), home / "Library" / "Fonts"]
    elif sys.platform.startswith("win"):
        root = Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows")
        out += [root / "Fonts"]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            out.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    else:
        out += [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), home / ".fonts", Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share") / "fonts"]
        for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
            if d:
                out.append(Path(d) / "fonts")
    seen = []
    for p in out:
        if p not in seen:
            seen.append(p)
    return seen


def key_of(name):
    s = str(name).strip().lower().replace("\\", "/").rsplit("/", 1)[-1]
    for ext in EXTS + (".shx",):
        if s.endswith(ext):
            s = s[: -len(ext)]
            break
    return s


def squash(s):
    return "".join(c for c in str(s).lower() if c.isalnum())


def is_wide(ch):
    cp = ord(ch)
    return any(a <= cp <= b for a, b in WIDE)


class Registry:
    def __init__(self):
        self.files = None
        self.stems = {}
        self.families = None
        self.faces = {}
        self.char_cache = {}
        self.scanned_bytes = 0

    def scan(self):
        with _lock:
            if self.files is not None:
                return
            files = []
            stems = {}
            for root in font_dirs():
                if not root.is_dir():
                    continue
                for dirpath, _dirs, names in os.walk(root, followlinks=False):
                    for fn in sorted(names):
                        if fn.lower().endswith(EXTS):
                            p = os.path.join(dirpath, fn)
                            files.append(p)
                            stems.setdefault(squash(key_of(fn)), []).append(p)
            self.files = files
            self.stems = stems

    def load(self, path, index=0):
        from app.text.outline import OutlineFont

        k = (path, index)
        with _lock:
            if k in self.faces:
                return self.faces[k]
            try:
                face = OutlineFont(path, index)
            except Exception:
                face = None
            if len(self.faces) > 64:
                self.faces.clear()
            self.faces[k] = face
            return face

    def by_stem(self, name, bold=False, italic=False):
        self.scan()
        k = squash(key_of(name))
        paths = self.stems.get(k)
        if not paths:
            return None
        return self.load(paths[0], 0)

    def build_families(self):
        with _lock:
            if self.families is not None:
                return
            from fontTools.ttLib import TTCollection, TTFont

            logging.getLogger("fontTools").setLevel(logging.ERROR)
            fam = {}
            for path in self.files[:MAX_FAMILY_FILES]:
                try:
                    if path.lower().endswith((".ttc", ".otc")):
                        coll = TTCollection(path, lazy=True)
                        fonts = list(enumerate(coll.fonts))
                    else:
                        fonts = [(0, TTFont(path, lazy=True))]
                except Exception:
                    continue
                for i, f in fonts:
                    try:
                        names = f["name"]
                        rec = names.getName(16, 3, 1, 0x409) or names.getName(1, 3, 1, 0x409) or names.getName(1, 1, 0, 0)
                        style = int(f["head"].macStyle)
                    except Exception:
                        continue
                    if rec is None:
                        continue
                    fam.setdefault(squash(str(rec)), []).append((path, i, bool(style & 1), bool(style & 2)))
            self.families = fam

    def by_family(self, name, bold=False, italic=False):
        self.scan()
        k = squash(key_of(name))
        self.build_families()
        recs = self.families.get(k)
        if not recs:
            for fk, v in self.families.items():
                if fk.startswith(k) or k.startswith(fk):
                    recs = v
                    break
        if not recs:
            return None
        pick = None
        for r in recs:
            if r[2] == bold and r[3] == italic:
                pick = r
                break
        if pick is None:
            for r in recs:
                if r[2] == bold:
                    pick = r
                    break
        pick = pick or recs[0]
        return self.load(pick[0], pick[1])

    def find(self, name, bold=False, italic=False):
        if not str(name).strip():
            return None
        if bold or italic:
            face = self.by_family(name, bold, italic)
            if face is not None and face.bold == bold and face.italic == italic:
                return face
            alt = self.by_stem(key_of(name) + ("bd" if bold and not italic else "i" if italic and not bold else "bi"))
            if alt is not None:
                return alt
            if face is not None:
                return face
        face = self.by_stem(name)
        if face is not None:
            return face
        return self.by_family(name, bold, italic)

    def search(self, ch):
        with _lock:
            if ch in self.char_cache:
                return self.char_cache[ch]
            self.scan()
            for stem in WELL_KNOWN:
                for k, paths in self.stems.items():
                    if k.startswith(stem):
                        face = self.load(paths[0], 0)
                        if face is not None and face.has(ch):
                            self.char_cache[ch] = face
                            return face
                        break
            checked = 0
            for path in self.files:
                if checked >= MAX_SCAN_FILES or self.scanned_bytes > MAX_SCAN_BYTES:
                    break
                if (path, 0) in self.faces:
                    continue
                try:
                    self.scanned_bytes += os.path.getsize(path)
                except OSError:
                    continue
                checked += 1
                face = self.load(path, 0)
                if face is not None and face.has(ch):
                    self.char_cache[ch] = face
                    return face
            self.char_cache[ch] = None
            return None


registry = Registry()


def settings():
    try:
        from app.sysvars import registry as sv

        return str(sv.session_value("FONTALT") or ""), str(sv.session_value("FONTFALLBACK") or "")
    except Exception:
        return "", ""


def resolve(name, bold=False, italic=False):
    alt, _fb = settings()
    raw = str(name or "").strip()
    key = key_of(raw)
    if not key or key in STROKE_NAMES:
        return stroke.default()
    if raw.lower().endswith(".shx"):
        face = registry.find(alt, bold, italic) if alt else None
        return face or stroke.default()
    face = registry.find(raw, bold, italic)
    if face is not None:
        return face
    face = registry.find(alt, bold, italic) if alt else None
    return face or stroke.default()


class FontSet:
    def __init__(self, primary):
        self.primary = primary
        self.cache = {}
        self.sticky = None

    def _chain(self):
        alt, fb = settings()
        for item in [s for s in fb.replace(";", ",").split(",") if s.strip()] + ([alt] if alt else []):
            face = registry.find(item)
            if face is not None:
                yield face

    def face_for(self, ch):
        return self._lookup(" " if ch == " " else ch)

    def _script_faces(self, script):
        got = SCRIPT_FACES.get(script)
        if got is None:
            got = []
            for name in SCRIPT_FONTS.get(script, ()):
                face = registry.find(name)
                if face is not None and all(face is not f for f in got):
                    got.append(face)
            SCRIPT_FACES[script] = got
        return got

    def _lookup(self, ch):
        if self.primary.has(ch):
            return self.primary
        if self.sticky is not None and self.sticky.has(ch):
            return self.sticky
        script = scripts.script_of(ch)
        if script != "other":
            for face in self._script_faces(script):
                if face.has(ch):
                    self.sticky = face
                    return face
        for face in self._chain():
            if face.has(ch):
                self.sticky = face
                return face
        if ch.isprintable() and not ch.isspace():
            face = registry.search(ch)
            if face is not None:
                self.sticky = face
                return face
        d = stroke.default()
        if d.has(ch):
            return d
        return None

    def glyph(self, ch):
        g = self.cache.get(ch)
        if g is not None:
            return g
        if ch in ("\u00a0",):
            ch2 = " "
        else:
            ch2 = ch
        face = self._lookup(ch2)
        if face is None:
            if ch2.isspace():
                g = Glyph(0.5, 0.0, strokes=[], contours=[], box=(0, 0, 0, 0))
            else:
                g = stroke.default().missing()
        else:
            g = face.glyph(ch2)
            if g is None:
                g = stroke.default().missing()
            elif not face.is_stroke and is_wide(ch2):
                g = wide(face, g)
        self.cache[ch] = g
        return g

    @property
    def is_stroke(self):
        return self.primary.is_stroke

    @property
    def desc(self):
        return self.primary.desc

    def derive(self, face):
        return FontSet(face)


def wide(face, g):
    s = 1.0 / face.em_over_cap
    contours = [c * s for c in g.contours]
    return Glyph(1.0, 0.0, contours=contours, box=box_of(contours), build_tris=g.build_tris)
