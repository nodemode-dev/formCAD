import os
import re
import zipfile

from app.interchange.errors import InterchangeError
from app.param.units import LENGTH_MM, mm_per_unit

ALIASES = {
    "mm": "mm", "millimeter": "mm", "millimetre": "mm", "cm": "cm", "centimeter": "cm", "centimetre": "cm", "m": "m", "meter": "m", "metre": "m", "km": "km",
    "in": "in", "inch": "in", "inches": "in", "ft": "ft", "foot": "ft", "feet": "ft", "mi": "mi", "mil": "mil", "thou": "mil", "um": "um", "micron": "um", "micrometer": "um", "micrometre": "um", "yd": "yd", "dm": "dm",
}
SI_PREFIX = {".MILLI.": "mm", ".CENTI.": "cm", "$": "m", ".KILO.": "km", ".MICRO.": "um", ".DECI.": "dm"}
IGES_FLAG = {1: "in", 2: "mm", 4: "ft", 5: "mi", 6: "m", 7: "km", 8: "mil", 9: "um", 10: "cm"}
STEP_ENTITY = re.compile(rb"#(\d+)\s*=\s*\(([^;]{0,400}?LENGTH_UNIT\s*\(\s*\)[^;]{0,400}?)\)\s*;", re.S | re.I)
STEP_CONV = re.compile(rb"CONVERSION_BASED_UNIT\s*\(\s*'([^']*)'", re.I)
STEP_SI = re.compile(rb"SI_UNIT\s*\(\s*(\.[A-Z]+\.|\$)\s*,\s*\.METRE\.\s*\)", re.I)
STEP_CONTEXT = re.compile(rb"GLOBAL_UNIT_ASSIGNED_CONTEXT\s*\(\s*\(([^)]*)\)", re.I)
CHUNK = 16 * 1024 * 1024
OVERLAP = 65536
MAX_SCAN = 512 * 1024 * 1024


def unit_key(name, fallback="") -> str:
    key = ALIASES.get(str(name or "").strip().lower())
    if key is None:
        if fallback:
            return fallback
        raise InterchangeError('Unknown unit "%s". Use mm, cm, m, in, ft or um.' % name, "badunit")
    return key


def document_unit(d) -> tuple:
    s = mm_per_unit(d)
    for key, mm in LENGTH_MM.items():
        if abs(mm - s) < 1e-9 * max(mm, 1.0) and key in ("mm", "cm", "m", "in", "ft", "um", "km", "mil", "dm", "yd", "mi"):
            return key, s
    return "mm", 1.0


def step_header(path):
    with open(path, "rb") as fh:
        head = fh.read(16384).decode("latin-1")
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", head)
    schema = m.group(1) if m else ""
    name = re.search(r"FILE_NAME\s*\(\s*'([^']*)'", head)
    return schema, name.group(1) if name else ""


def step_unit(path):
    size = os.path.getsize(path)
    if size > MAX_SCAN:
        raise InterchangeError("The file is larger than the 512 MB limit.", "toolarge")
    units = {}
    contexts = []
    tail = b""
    with open(path, "rb") as fh:
        while True:
            block = fh.read(CHUNK)
            if not block:
                break
            data = tail + block
            for m in STEP_ENTITY.finditer(data):
                body = m.group(2)
                conv = STEP_CONV.search(body)
                si = STEP_SI.search(body)
                key = None
                if conv:
                    key = ALIASES.get(conv.group(1).decode("latin-1").strip().lower())
                elif si:
                    key = SI_PREFIX.get(si.group(1).decode("latin-1").upper())
                if key:
                    units[int(m.group(1))] = (key, bool(conv))
            for m in STEP_CONTEXT.finditer(data):
                ids = [int(x) for x in re.findall(rb"#(\d+)", m.group(1))]
                if ids not in contexts:
                    contexts.append(ids)
            tail = data[-OVERLAP:]
    for ids in contexts:
        hit = [units[i][0] for i in ids if i in units]
        if hit:
            return hit[:1]
    outer = [k for k, conv in units.values() if conv]
    return (outer or [k for k, _c in units.values()])[:1]


def iges_fields(path):
    lines = []
    with open(path, "rb") as fh:
        for raw in fh:
            line = raw.decode("latin-1").rstrip("\r\n")
            if len(line) >= 73 and line[72] == "G":
                lines.append(line[:72])
            elif len(line) >= 73 and line[72] in "DPT":
                break
    text = "".join(lines)
    if not text:
        return []
    delim, rec = ",", ";"
    pos = 0
    if text[0] != delim:
        m = re.match(r"\s*(\d+)H", text)
        if not m:
            return []
        n = int(m.group(1))
        delim = text[m.end():m.end() + n] or ","
        pos = m.end() + n + 1
    else:
        pos = 1
    if text[pos:pos + 1] != delim:
        m = re.match(r"\s*(\d+)H", text[pos:])
        if m:
            n = int(m.group(1))
            rec = text[pos + m.end():pos + m.end() + n] or ";"
            pos += m.end() + n + 1
    else:
        pos += 1
    fields = []
    while pos < len(text) and len(fields) < 24:
        m = re.match(r"\s*(\d+)H", text[pos:])
        if m:
            n = int(m.group(1))
            start = pos + m.end()
            fields.append(text[start:start + n])
            pos = start + n
            while pos < len(text) and text[pos] not in (delim, rec):
                pos += 1
        else:
            end = pos
            while end < len(text) and text[end] not in (delim, rec):
                end += 1
            fields.append(text[pos:end].strip())
            pos = end
        if pos >= len(text) or text[pos] == rec:
            break
        pos += 1
    return fields


def iges_unit(path):
    f = iges_fields(path)
    if len(f) < 12:
        return []
    try:
        flag = int(f[11])
    except ValueError:
        return []
    if flag == 3 and len(f) > 12:
        key = ALIASES.get(f[12].strip().lower())
        return [key] if key else []
    key = IGES_FLAG.get(flag)
    return [key] if key else []


def threemf_unit(path):
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".model")]
        if not names:
            return []
        with zf.open(names[0]) as fh:
            head = fh.read(4096).decode("utf-8", errors="replace")
    m = re.search(r"<model\b[^>]*\bunit\s*=\s*[\"']([^\"']+)[\"']", head)
    return [unit_key(m.group(1), "mm")] if m else ["mm"]


def inspect_file(path: str, d=None) -> dict:
    full = os.path.realpath(os.path.expanduser(path))
    if not os.path.isfile(full):
        raise InterchangeError('Cannot find the file "%s".' % path, "missing")
    ext = os.path.splitext(full)[1].lower()
    out = {"path": full, "ext": ext, "bytes": os.path.getsize(full), "schema": "", "unit": "", "unit_mm": None, "units_known": False, "warnings": [], "mismatch": False}
    found = []
    try:
        if ext in (".step", ".stp"):
            out["schema"], out["file_name"] = step_header(full)
            found = step_unit(full)
        elif ext in (".iges", ".igs"):
            found = iges_unit(full)
        elif ext == ".3mf":
            found = threemf_unit(full)
        elif ext in (".glb", ".gltf"):
            found = ["m"]
    except zipfile.BadZipFile:
        raise InterchangeError("The 3MF file is not a valid archive.", "badfile")
    except OSError as err:
        raise InterchangeError("Cannot read the file: %s" % err, "io")
    if len(found) > 1:
        out["warnings"].append("The file declares more than one length unit (%s); the first is used." % ", ".join(found))
    if found:
        out["unit"] = found[0]
        out["unit_mm"] = LENGTH_MM[found[0]]
        out["units_known"] = True
    elif ext in (".step", ".stp", ".iges", ".igs"):
        out["warnings"].append("The file does not declare a length unit that could be read; millimetres are assumed.")
        out["unit"], out["unit_mm"] = "mm", 1.0
    else:
        out["warnings"].append("The format carries no unit; choose the unit the numbers are in.")
    if d is not None:
        name, s = document_unit(d)
        out["document_unit"], out["document_unit_mm"] = name, s
        if out["units_known"] and abs(out["unit_mm"] - s) > 1e-9 * max(s, 1.0):
            out["mismatch"] = True
            out["warnings"].append("The file is in %s and the document is in %s; choose to convert the numbers (scale %g) or keep them." % (out["unit"], name, out["unit_mm"] / s))
    return out
