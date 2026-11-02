import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN_FILE = "session.token"
PORT_FILE = "engine.port"
TIMEOUT = 300.0


def _emit(out, text: str) -> None:
    out.write(text + "\n")
    out.flush()


def serve_headless(mode: str = "all") -> int:
    from app.automation.mcp import Server

    out = sys.stdout
    sys.stdout = sys.stderr
    server = Server(mode)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        reply = server.handle_text(line)
        if reply is not None:
            _emit(out, reply)
    return 0


def discover_engine(connect: str = "") -> tuple[str, str]:
    url = os.environ.get("FORMCAD_URL", "").rstrip("/")
    token = os.environ.get("FORMCAD_TOKEN", "")
    if connect and connect != "auto":
        url = "http://" + connect if "://" not in connect else connect
    if (connect == "auto" or not url) and not (url and token):
        from app.core import config

        data = config.data_dir()
        if not url:
            try:
                port = json.loads((data / PORT_FILE).read_text(encoding="utf-8"))["port"]
            except (OSError, ValueError, KeyError):
                raise RuntimeError("FormCAD is not running: no engine.port file in %s." % data)
            url = "http://127.0.0.1:%d" % int(port)
        if not token:
            try:
                token = (data / TOKEN_FILE).read_text(encoding="utf-8").strip()
            except OSError:
                raise RuntimeError("Cannot read the session token file in %s." % data)
    if not url or not token:
        raise RuntimeError("Set FORMCAD_URL and FORMCAD_TOKEN, or use --connect auto.")
    if (urllib.parse.urlsplit(url).hostname or "").lower() not in ("127.0.0.1", "localhost", "::1"):
        raise RuntimeError("The engine address must be 127.0.0.1 or localhost; the session token is never sent elsewhere.")
    return url.rstrip("/"), token


def _error(rid, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def forward(url: str, token: str, text: str, version: str = "") -> tuple[str | None, bool]:
    req = urllib.request.Request(url + "/mcp", data=text.encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    req.add_header("X-FormCAD-Token", token)
    if version:
        req.add_header("MCP-Protocol-Version", version)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            body = res.read().decode("utf-8")
            return (body or None), True
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")
        if err.code == 202:
            return None, True
        return "HTTP %d: %s" % (err.code, detail[:300]), False
    except urllib.error.URLError as err:
        reason = getattr(err, "reason", err)
        refused = isinstance(reason, ConnectionRefusedError)
        return ("refused" if refused else "lost: %s" % reason), False
    except OSError as err:
        return "lost: %s" % err, False


def serve_bridge(connect: str = "") -> int:
    out = sys.stdout
    sys.stdout = sys.stderr
    version = ""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            _emit(out, _error(None, -32700, "Parse error."))
            continue
        rid = msg.get("id") if isinstance(msg, dict) else None
        method = msg.get("method") if isinstance(msg, dict) else None
        try:
            url, token = discover_engine(connect)
        except RuntimeError as err:
            if rid is not None:
                _emit(out, _error(rid, -32603, "%s Start FormCAD, then retry." % err))
            continue
        if method == "initialize" and isinstance(msg.get("params"), dict):
            version = str(msg["params"].get("protocolVersion", ""))
        body, ok = forward(url, token, line, version)
        if rid is None:
            continue
        if ok:
            if body:
                _emit(out, body)
            continue
        if body == "refused":
            _emit(out, _error(rid, -32603, "FormCAD is not accepting connections at %s. Start the app, then retry; this call did not run." % url))
        elif body and body.startswith("lost"):
            note = "The reply was lost, so this call may have run. Inspect the drawing before sending it again." if method == "tools/call" else "The reply was lost."
            _emit(out, _error(rid, -32603, "%s (%s)" % (note, body)))
        else:
            _emit(out, _error(rid, -32603, body or "FormCAD refused the call."))
    return 0
