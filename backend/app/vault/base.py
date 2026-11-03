import getpass
import hashlib
import os
import platform
import time

from blake3 import blake3

FORMAT = 1
MAX_MEMBER = 512 * 1024 * 1024
MAX_CONTAINER = 512 * 1024 * 1024
MAX_UNPACKED = 1536 * 1024 * 1024
MAX_ENTRIES = 20000
AGENT_CONTAINER = 64 * 1024 * 1024
AGENT_UNPACKED = 192 * 1024 * 1024
MAX_NAME = 4096
MAX_MESSAGE = 4000
MAX_BODY = 20000
MAX_MARKUP = 2 * 1024 * 1024
MAX_ANCHOR = 4096
MAX_COMMENTS = 10000
MAX_VAULTS = 32
MAX_DOCS = 5000
MAX_VERSIONS = 200000
MAX_LOG = 5000
MAX_CONFLICTS = 5000
MAX_ENTITIES = 400000
MAX_DOCJSON = 256 * 1024 * 1024
MAX_DEPTH = 12
INLINE = 128 * 1024
CHUNK_FROM = 1024 * 1024
STATES = ("wip", "review", "released", "obsolete")


class VaultError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def now() -> int:
    return int(time.time())


def digest(data: bytes) -> bytes:
    return blake3(data).digest()


def hexed(raw) -> str:
    return raw.hex() if isinstance(raw, (bytes, bytearray)) else (raw or "")


def unhex(text, what: str = "id") -> bytes:
    s = str(text or "").strip().lower()
    if len(s) != 64:
        raise VaultError("The %s must be 64 hexadecimal characters." % what)
    try:
        return bytes.fromhex(s)
    except ValueError:
        raise VaultError("The %s must be 64 hexadecimal characters." % what)


def file_digests(path: str, limit: int) -> tuple:
    size = os.path.getsize(path)
    if size > limit:
        raise VaultError("The file is larger than the %d MB limit." % (limit // (1024 * 1024)))
    b3 = blake3(max_threads=blake3.AUTO)
    s2 = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            b3.update(chunk)
            s2.update(chunk)
    return b3.digest(), s2.hexdigest(), size


def author() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return "user"


def machine() -> str:
    return platform.node() or "this computer"


def clean_text(value, limit: int, what: str, required: bool = False) -> str:
    s = str(value if value is not None else "").replace("\x00", "").strip()
    if required and not s:
        raise VaultError("%s is required." % what)
    if len(s) > limit:
        raise VaultError("%s is longer than %d characters." % (what, limit))
    return s


NAME_OK = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/+ ")


def ref_name(value, what: str = "name") -> str:
    s = str(value or "").strip()
    if not s or len(s) > 100:
        raise VaultError("The %s must be 1 to 100 characters." % what)
    if any(c not in NAME_OK for c in s) or s.startswith(("/", ".", "-")) or s.endswith(("/", ".", " ")) or "//" in s or ".." in s:
        raise VaultError("The %s may hold letters, digits and . _ - + / space, and cannot start with / . or -, end with / . or a space, or contain // or .." % what)
    return s
