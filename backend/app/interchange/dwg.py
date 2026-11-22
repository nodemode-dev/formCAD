import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

from app.interchange.errors import InterchangeError

MAX_DWG = 512 * 1024 * 1024
MAX_DXF = 1024 * 1024 * 1024
TIMEOUT = 300
ODA_NAMES = ("ODAFileConverter", "ODAFileConverter.exe", "TeighaFileConverter", "TeighaFileConverter.exe")
LIBRE_READ = ("dwg2dxf", "dwg2dxf.exe")
LIBRE_WRITE = ("dxf2dwg", "dxf2dwg.exe")
KNOWN_NAMES = frozenset(n.lower() for n in ODA_NAMES + LIBRE_READ + LIBRE_WRITE)
MAX_TAIL = 64 * 1024
ODA_VERSIONS = {"R2000": "ACAD2000", "R2004": "ACAD2004", "R2007": "ACAD2007", "R2010": "ACAD2010", "R2013": "ACAD2013", "R2018": "ACAD2018"}
SETTINGS_FILE = "interchange.json"


def settings_path():
    from app.core import config

    return config.data_dir() / SETTINGS_FILE


def load_settings() -> dict:
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    return {"dwgEnabled": bool(raw.get("dwgEnabled", False)), "dwgConverter": str(raw.get("dwgConverter", "") or "")}


def save_settings(enabled=None, converter=None) -> dict:
    cur = load_settings()
    if converter is not None:
        want = str(converter).strip()
        if want and os.path.basename(want.replace("\\", "/")).lower() not in KNOWN_NAMES:
            raise InterchangeError("The converter must be ODAFileConverter, TeighaFileConverter, dwg2dxf or dxf2dwg.", "badconv")
    if enabled is not None:
        cur["dwgEnabled"] = bool(enabled)
    if converter is not None:
        cur["dwgConverter"] = str(converter).strip()
    from app.doc import container

    container.atomic_write(str(settings_path()), json.dumps(cur).encode("utf-8"), 0o600)
    return cur


def candidate_dirs() -> list:
    out = []
    if sys.platform == "darwin":
        out += ["/Applications/ODAFileConverter.app/Contents/MacOS", "/opt/homebrew/bin", "/usr/local/bin"]
    elif os.name == "nt":
        for env in ("ProgramFiles", "ProgramFiles(x86)"):
            base = os.environ.get(env)
            if not base:
                continue
            out.append(os.path.join(base, "ODA"))
            try:
                for n in sorted(os.listdir(os.path.join(base, "ODA"))):
                    out.append(os.path.join(base, "ODA", n))
            except OSError:
                pass
    else:
        out += ["/usr/bin", "/usr/local/bin", "/opt/ODAFileConverter", "/opt/libredwg/bin", "/usr/local/libredwg/bin", os.path.expanduser("~/.local/bin")]
    return out


def find_tool(names) -> str:
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    for d in candidate_dirs():
        for n in names:
            p = os.path.join(d, n)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    return ""


def kind_of(path: str) -> str:
    base = os.path.basename(path).lower()
    if "dwg2dxf" in base or "dxf2dwg" in base:
        return "libredwg"
    if "oda" in base or "teigha" in base:
        return "oda"
    return "oda"


def status() -> dict:
    from app.services import dwgtools

    s = load_settings()
    chosen = s["dwgConverter"]
    detected_oda = find_tool(ODA_NAMES)
    detected_read = find_tool(LIBRE_READ)
    detected_write = find_tool(LIBRE_WRITE)
    own = chosen or detected_oda or detected_read
    own_usable = bool(s["dwgEnabled"] and own and os.path.isfile(own))
    tools = dwgtools.status()
    kit = dwgtools.installed()
    path, kind = (own, kind_of(own)) if own_usable else ((kit["read"], "dwgtools") if kit else (own, kind_of(own) if own else ""))
    usable = own_usable or kit is not None
    if usable:
        message = ""
    elif not s["dwgEnabled"]:
        message = "DWG support is off. Turn it on and point at a converter you installed" + (", or install the DWG tools." if tools["published"] else ".")
    else:
        message = "No DWG converter was found. Install one and set its path" + (", or install the DWG tools." if tools["published"] else ".")
    return {
        "enabled": s["dwgEnabled"],
        "converterPath": chosen,
        "converter": path,
        "converterKind": kind,
        "detected": {"oda": detected_oda, "libredwgRead": detected_read, "libredwgWrite": detected_write},
        "usable": usable,
        "writeExperimental": kind in ("libredwg", "dwgtools"),
        "writeVersions": ["R2000"] if kind in ("libredwg", "dwgtools") else list(ODA_VERSIONS),
        "tools": tools,
        "message": message,
    }


def _need(write: bool = False) -> tuple:
    from app.services import dwgtools

    s = load_settings()
    kit = dwgtools.installed()
    if not s["dwgEnabled"]:
        if kit:
            return (kit["write"] if write else kit["read"]), "libredwg"
        raise InterchangeError("DWG files need a converter you install yourself. Turn DWG support on in the interchange settings and set the converter path.", "dwgoff")
    path = s["dwgConverter"]
    if path and not os.path.isfile(path):
        raise InterchangeError('The DWG converter "%s" was not found.' % path, "noconv")
    if not path:
        path = find_tool(ODA_NAMES) or find_tool(LIBRE_WRITE if write else LIBRE_READ)
    if not path and kit:
        return (kit["write"] if write else kit["read"]), "libredwg"
    if not path:
        raise InterchangeError("No DWG converter was found on this computer. Install one and set its path in the interchange settings.", "noconv")
    kind = kind_of(path)
    if kind == "libredwg":
        base = os.path.dirname(path)
        want = LIBRE_WRITE if write else LIBRE_READ
        exe = ""
        for n in want:
            p = os.path.join(base, n)
            if os.path.isfile(p):
                exe = p
        exe = exe or find_tool(want)
        if not exe:
            raise InterchangeError("The LibreDWG tool for this direction was not found next to the converter.", "noconv")
        path = exe
    return path, kind


def mid_version(version: str) -> str:
    try:
        return "R2000" if _need(True)[1] == "libredwg" else version
    except InterchangeError:
        return version


def oda_command(exe: str, src_dir: str, out_dir: str, version: str, out_type: str, recurse: bool = False, audit: bool = True, flt: str = "*.*") -> list:
    return [exe, src_dir, out_dir, ODA_VERSIONS.get(version, "ACAD2018"), out_type, "1" if recurse else "0", "1" if audit else "0", flt]


def _run(cmd: list, timeout: int = TIMEOUT) -> str:
    with tempfile.TemporaryFile() as errs:
        try:
            proc = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=errs, timeout=timeout, shell=False)
        except subprocess.TimeoutExpired:
            raise InterchangeError("The DWG converter did not finish within %d seconds and was stopped." % timeout, "timeout")
        except OSError as err:
            raise InterchangeError("The DWG converter could not be started: %s" % err, "start")
        size = errs.seek(0, os.SEEK_END)
        errs.seek(max(0, size - MAX_TAIL))
        text = errs.read(MAX_TAIL)
    said = text.decode("utf-8", "replace")
    if proc.returncode != 0:
        tail = said.strip().splitlines()[-3:]
        raise InterchangeError("The DWG converter stopped with code %d. %s" % (proc.returncode, " ".join(tail)[-400:]), "convfail")
    return said


def losses(said: str) -> list:
    seen = {}
    for line in said.splitlines():
        line = line.strip()
        if not line.startswith(("Warning:", "ERROR:")):
            continue
        key = re.sub(r"0x[0-9A-Fa-f]+|\b\d+(\.\d+)?\b|\([^)]*\)|\[[^\]]*\]", "#", line)
        seen.setdefault(key, [line, 0])[1] += 1
    return ["LibreDWG: %s%s" % (first, "" if n == 1 else " (%d times)" % n) for first, n in list(seen.values())[:20]]


def dwg_to_dxf(path: str, timeout: int = TIMEOUT, report=None) -> tuple:
    if os.path.getsize(path) > MAX_DWG:
        raise InterchangeError("The DWG file is larger than 512 MB.", "toolarge")
    exe, kind = _need(False)
    work = tempfile.mkdtemp(prefix="fcdwg_")
    try:
        src = os.path.join(work, "in")
        out = os.path.join(work, "out")
        os.mkdir(src)
        os.mkdir(out)
        name = os.path.splitext(os.path.basename(path))[0] or "drawing"
        local = os.path.join(src, name + ".dwg")
        shutil.copyfile(path, local)
        if kind == "oda":
            _run(oda_command(exe, src, out, "R2018", "DXF", False, True, "*.dwg"), timeout)
            produced = os.path.join(out, name + ".dxf")
        else:
            produced = os.path.join(out, name + ".dxf")
            said = _run([exe, "-y", "-o", produced, local], timeout)
            if report is not None:
                report.note("Read through LibreDWG.")
                for line in losses(said):
                    report.warn(line)
        if not os.path.isfile(produced):
            raise InterchangeError("The DWG converter finished but produced no DXF file. The DWG may be damaged or newer than the converter supports.", "noout")
        if os.path.getsize(produced) > MAX_DXF:
            raise InterchangeError("The converted DXF is larger than 1 GB.", "toolarge")
        return produced, work
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def dxf_to_dwg(dxf_path: str, dest: str, version: str = "R2018", timeout: int = TIMEOUT) -> list:
    exe, kind = _need(True)
    notes = []
    work = tempfile.mkdtemp(prefix="fcdwg_")
    try:
        src = os.path.join(work, "in")
        out = os.path.join(work, "out")
        os.mkdir(src)
        os.mkdir(out)
        name = os.path.splitext(os.path.basename(dest))[0] or "drawing"
        local = os.path.join(src, name + ".dxf")
        shutil.copyfile(dxf_path, local)
        produced = os.path.join(out, name + ".dwg")
        if kind == "oda":
            _run(oda_command(exe, src, out, version, "DWG", False, True, "*.dxf"), timeout)
        else:
            notes.append("Saved as DWG in the 2000 format (R2000), the only DWG version LibreDWG writes." + ("" if str(version).upper() == "R2000" else " The %s version you asked for needs the ODA File Converter." % version))
            notes.extend(losses(_run([exe, "-y", "--as", "r2000", "-o", produced, local], timeout)))
        if not os.path.isfile(produced):
            raise InterchangeError("The DWG converter finished but produced no DWG file.", "noout")
        os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
        tmp = dest + ".part"
        shutil.copyfile(produced, tmp)
        os.replace(tmp, dest)
        return notes
    finally:
        shutil.rmtree(work, ignore_errors=True)
