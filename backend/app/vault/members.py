import io
import json
import struct
import zipfile
import zlib

from app.vault.base import MAX_ENTRIES, MAX_MEMBER, MAX_NAME, VaultError, digest

DERIVED_PREFIX = ("cache/",)
LEVELS = (6, 9, 1, 5, 4, 3, 2, 7, 8, 0)


class Member:
    def __init__(self, name: str, data: bytes, is_dir: bool):
        self.name = name
        self.data = data
        self.is_dir = is_dir
        self.derived = name.startswith(DERIVED_PREFIX)


def _raw_stream(data: bytes, info: zipfile.ZipInfo) -> bytes:
    head = data[info.header_offset: info.header_offset + 30]
    if len(head) < 30 or head[:4] != b"PK\x03\x04":
        return b""
    nlen, xlen = struct.unpack("<HH", head[26:30])
    start = info.header_offset + 30 + nlen + xlen
    return data[start: start + info.compress_size]


def _deflate(data: bytes, level: int) -> bytes:
    comp = zlib.compressobj(level, zlib.DEFLATED, -15)
    return comp.compress(data) + comp.flush()


def split(container: bytes, unpacked_limit: int) -> tuple:
    try:
        zf = zipfile.ZipFile(io.BytesIO(container))
    except zipfile.BadZipFile:
        raise VaultError("The file is not a FormCAD container (not a zip archive).")
    members = []
    recipe = {"v": 1, "order": [], "info": {}, "comment": zf.comment.hex()}
    total = 0
    seen = set()
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_ENTRIES:
            raise VaultError("The container has too many entries.")
        for info in infos:
            name = info.filename
            if not name or len(name) > MAX_NAME or "\x00" in name or name.startswith("/") or ".." in name.split("/"):
                raise VaultError("The container holds an unsafe member name.")
            if name in seen:
                raise VaultError("The container holds two members named %s." % name)
            seen.add(name)
            if info.file_size > MAX_MEMBER:
                raise VaultError("Member %s is larger than the %d MB limit." % (name, MAX_MEMBER // (1024 * 1024)))
            total += info.file_size
            if total > unpacked_limit:
                raise VaultError("The container unpacks to more than %d MB." % (unpacked_limit // (1024 * 1024)))
            is_dir = info.is_dir()
            try:
                data = b"" if is_dir else zf.read(info)
            except (zipfile.BadZipFile, RuntimeError, OSError, zlib.error) as err:
                raise VaultError("Member %s cannot be read: %s" % (name, err))
            level = -1
            if info.compress_type == zipfile.ZIP_STORED:
                level = 0
            elif info.compress_type == zipfile.ZIP_DEFLATED:
                if is_dir or not data:
                    level = 6
                else:
                    raw = _raw_stream(container, info)
                    for lv in LEVELS:
                        if _deflate(data, lv) == raw:
                            level = lv
                            break
            recipe["order"].append(name)
            recipe["info"][name] = {
                "dt": list(info.date_time), "ct": info.compress_type, "lv": level, "ea": info.external_attr, "ia": info.internal_attr,
                "cs": info.create_system, "cv": info.create_version, "xv": info.extract_version, "fb": info.flag_bits & ~0x08,
                "ex": info.extra.hex(), "cm": info.comment.hex(),
            }
            members.append(Member(name, data, is_dir))
    return members, recipe


def rebuild(members: dict, recipe: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in recipe["order"]:
            r = recipe["info"][name]
            zi = zipfile.ZipInfo(name, tuple(r["dt"]))
            zi.external_attr = r["ea"]
            zi.internal_attr = r["ia"]
            zi.create_system = r["cs"]
            zi.create_version = r["cv"]
            zi.extract_version = r["xv"]
            zi.extra = bytes.fromhex(r["ex"])
            zi.comment = bytes.fromhex(r["cm"])
            zi.compress_type = r["ct"]
            level = r["lv"] if r["lv"] >= 0 else 6
            zf.writestr(zi, members[name], compress_type=r["ct"], compresslevel=level if r["ct"] == zipfile.ZIP_DEFLATED else None)
        zf.comment = bytes.fromhex(recipe.get("comment", ""))
    return buf.getvalue()


def recipe_bytes(recipe: dict) -> bytes:
    return json.dumps(recipe, separators=(",", ":"), sort_keys=True).encode("utf-8")


def reproduces(members: list, recipe: dict, want: bytes) -> bool:
    if any(r["lv"] < 0 for r in recipe["info"].values()):
        return False
    try:
        return digest(rebuild({m.name: m.data for m in members}, recipe)) == want
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, struct.error):
        return False
