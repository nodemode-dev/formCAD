import contextvars
import hmac
import json
import os
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

LOOPBACK = {"127.0.0.1", "localhost", "::1"}
HEADER = "x-formcad-token"
TOKEN_FILE = "session.token"
OPEN_PATHS = {"/api/health"}
TOKEN = secrets.token_urlsafe(32)


def write_token(data: Path) -> Path:
    path = data / TOKEN_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(TOKEN)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def needs_token(path: str) -> bool:
    if path in OPEN_PATHS:
        return False
    return path == "/api" or path.startswith("/api/") or path == "/mcp" or path.startswith("/mcp/")


def _host_of(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):
        return value[1:].split("]", 1)[0]
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def _origin_key(value: str) -> tuple[str, str, int | None] | None:
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not parts.hostname:
        return None
    if port is None:
        port = {"http": 80, "https": 443}.get(parts.scheme)
    return parts.scheme.lower(), parts.hostname.lower(), port


def _same(given: str | None) -> bool:
    return bool(given) and hmac.compare_digest(given.encode("utf-8"), TOKEN.encode("utf-8"))


RUN_TOKENS: dict[str, tuple[str, ...]] = {}


RUN_FILES: dict[str, tuple] = {}


def issue_run_token(prefixes: tuple[str, ...], files=()) -> str:
    token = secrets.token_urlsafe(24)
    RUN_TOKENS[token] = prefixes
    RUN_FILES[token] = tuple(str(f) for f in files)
    return token


def revoke_run_token(token: str) -> None:
    RUN_TOKENS.pop(token, None)
    RUN_FILES.pop(token, None)


def run_files(given) -> tuple:
    return RUN_FILES.get(given or "", ())


CALLER = contextvars.ContextVar("formcad_caller", default="")
FILES = contextvars.ContextVar("formcad_files", default=())
MACRO_DENIED_FIRST = {"open", "recovery", "autosave", "3dm"}
MACRO_DENIED_LATER = {"save", "saveas", "plot", "macro", "export", "xrefs", "import", "materiallib", "assembly", "matesettings", "motionsettings", "docprops", "video", "renderjobs", "vault"}
MACRO_DENIED_WRITE = {"drawann", "graphs", "sim", "topo", "gen", "pipes", "schem", "link", "kicad", "costing", "toolbox"}
MACRO_WRITE_OK = {"solve", "cancel"}


def _macro_route_ok(path: str, method: str = "") -> bool:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 3 and parts[:2] == ["api", "docs"]:
        if parts[2] in MACRO_DENIED_FIRST:
            return False
        if method.upper() in ("PUT", "POST", "PATCH", "DELETE") and any(p in MACRO_DENIED_WRITE for p in parts[3:]) and not (len(parts) == 6 and parts[3] == "graphs" and parts[5] in MACRO_WRITE_OK):
            return False
        return not any(p in MACRO_DENIED_LATER for p in parts[3:])
    return True


def _scoped(given: str | None, path: str, method: str = "") -> bool:
    if not given:
        return False
    for token, prefixes in list(RUN_TOKENS.items()):
        if hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
            return any(path == p or path.startswith(p + "/") for p in prefixes) and _macro_route_ok(path, method)
    return False


class Guard:
    def __init__(self, app, origins: list[str]) -> None:
        self.app = app
        self.allowed = {key for key in (_origin_key(o) for o in origins) if key is not None}

    def origin_ok(self, headers: dict[str, str]) -> bool:
        host = headers.get("host", "")
        if _host_of(host) not in LOOPBACK:
            return False
        origin = headers.get("origin")
        if origin is None:
            return headers.get("sec-fetch-site", "").strip().lower() != "cross-site"
        key = _origin_key(origin)
        if key is None:
            return False
        if key in self.allowed:
            return True
        own = _origin_key(f"{key[0]}://{host}")
        return key[0] == "http" and own is not None and own == key

    def token_ok(self, scope, headers: dict[str, str]) -> bool:
        if scope["type"] == "http" and scope.get("method") == "OPTIONS":
            return True
        if _same(headers.get(HEADER)):
            return True
        if scope["type"] == "http" and _scoped(headers.get(HEADER), scope.get("path", ""), scope.get("method", "")):
            scope["formcad_caller"] = "macro"
            scope["formcad_files"] = run_files(headers.get(HEADER))
            return True
        if scope["type"] == "websocket":
            query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
            return _same((query.get("token") or [None])[0])
        return False

    async def deny(self, scope, send, status: int, code: int, detail: str) -> None:
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": code})
            return
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({"type": "http.response.start", "status": status, "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        if not self.origin_ok(headers):
            await self.deny(scope, send, 403, 4403, "FormCAD answers this computer's own window and agents only")
            return
        if needs_token(scope.get("path", "")) and not self.token_ok(scope, headers):
            await self.deny(scope, send, 401, 4401, "A valid X-FormCAD-Token is required")
            return
        mark = CALLER.set(scope.get("formcad_caller", ""))
        held = FILES.set(scope.get("formcad_files", ()))
        try:
            await self.app(scope, receive, send)
        finally:
            FILES.reset(held)
            CALLER.reset(mark)
