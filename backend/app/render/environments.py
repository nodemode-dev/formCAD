import hashlib
import json
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from app.core import config

DATA = Path(__file__).resolve().parents[1] / "data" / "render"
CATALOGUE = DATA / "environments.json"
SHIPPED_DIR = DATA / "env"
RESOLUTIONS = ("1k", "2k", "4k")
ID = re.compile(r"^[a-z0-9_]{1,80}$")
TIMEOUT = 60
_lock = threading.Lock()


class EnvironmentError_(ValueError):
    pass


def downloaded_dir() -> Path:
    path = config.data_dir() / "environments"
    path.mkdir(parents=True, exist_ok=True)
    return path


def catalogue_file() -> dict:
    try:
        data = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"environments": []}
    return data if isinstance(data, dict) else {"environments": []}


def entry(eid: str):
    if not ID.match(str(eid or "")):
        return None
    for e in catalogue_file().get("environments") or []:
        if e.get("id") == eid:
            return e
    return None


def path_for(eid: str, res: str):
    e = entry(eid)
    if e is None or res not in (e.get("files") or {}):
        return None
    name = "%s_%s.hdr" % (eid, res)
    for base in (SHIPPED_DIR, downloaded_dir()):
        p = base / name
        if p.is_file():
            return p
    return None


def listing() -> dict:
    cat = catalogue_file()
    out = []
    for e in cat.get("environments") or []:
        files = []
        for res in RESOLUTIONS:
            f = (e.get("files") or {}).get(res)
            if not f:
                continue
            files.append({"resolution": res, "size": f["size"], "md5": f["md5"], "url": f["url"], "shipped": bool(f.get("shipped")), "present": path_for(e["id"], res) is not None})
        out.append({"id": e["id"], "name": e["name"], "author": e["author"], "page": e.get("page", ""), "category": e.get("category", ""), "files": files})
    return {"licence": cat.get("licence") or {}, "shipped_resolution": cat.get("shipped_resolution", "1k"), "download_hosts": cat.get("download_hosts") or [], "environments": out}


def default_id() -> str:
    envs = catalogue_file().get("environments") or []
    return envs[0]["id"] if envs else ""


def read_bytes(eid: str, res: str) -> bytes:
    p = path_for(eid, res)
    if p is None:
        e = entry(eid)
        if e is None:
            raise EnvironmentError_("There is no environment called %s." % eid)
        raise EnvironmentError_("The %s file of %s is not on this computer; download it first." % (res, eid))
    return p.read_bytes()


def download(eid: str, res: str) -> dict:
    cat = catalogue_file()
    e = entry(eid)
    if e is None:
        raise EnvironmentError_("There is no environment called %s." % eid)
    f = (e.get("files") or {}).get(res)
    if not f:
        raise EnvironmentError_("%s has no %s file." % (eid, res))
    have = path_for(eid, res)
    if have is not None:
        return {"id": eid, "resolution": res, "path": str(have), "downloaded": False, "size": have.stat().st_size}
    url = str(f["url"])
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "") not in (cat.get("download_hosts") or []):
        raise EnvironmentError_("That address is not an allowed download host.")
    cap = min(int(cat.get("max_download_bytes", 134217728)), 268435456)
    want = int(f["size"])
    if want > cap:
        raise EnvironmentError_("That file is larger than the %d MB download limit." % (cap // 1048576))
    target = downloaded_dir() / ("%s_%s.hdr" % (eid, res))
    with _lock:
        fd, tmp = tempfile.mkstemp(prefix="env-", suffix=".part", dir=str(target.parent))
        digest = hashlib.md5()
        total = 0
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FormCAD environment download"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp, os.fdopen(fd, "wb") as fh:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > want or total > cap:
                        raise EnvironmentError_("The download is larger than the catalogue says; stopped.")
                    digest.update(chunk)
                    fh.write(chunk)
            if total != want or digest.hexdigest() != f["md5"]:
                raise EnvironmentError_("The downloaded file does not match the catalogue size and checksum; it was discarded.")
            os.replace(tmp, target)
        except (urllib.error.URLError, OSError, TimeoutError) as err:
            raise EnvironmentError_("The download failed (%s)." % (getattr(err, "reason", None) or err))
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return {"id": eid, "resolution": res, "path": str(target), "downloaded": True, "size": total}
