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
        await self.app(scope, receive, send)
