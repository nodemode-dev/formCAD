import asyncio
import base64
import concurrent.futures
import hmac
import json
import os
import secrets
import threading

from app.automation import ops

MAX_CONNECTIONS = 16
MAX_LINE = 256 * 1024 * 1024
PRE_AUTH_LINE = 64 * 1024
MAX_QUEUE = 64
IDLE_SECONDS = 600
CALL_SECONDS = 60
POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="control")


class ControlError(Exception):
    def __init__(self, code: str, message: str, state: str = ""):
        super().__init__(message)
        self.code, self.message, self.state = code, message, state


def _doc(params: dict):
    try:
        return ops.document(str(params.get("document") or ""))
    except ops.OpError as err:
        raise ControlError("no-document", str(err))


def _need(params: dict, key: str):
    if key not in params:
        raise ControlError("bad-params", "The parameter %s is required." % key)
    return params[key]


def m_ping(p):
    return "pong"


def m_line_type(p):
    return ops.type_line(_doc(p), str(_need(p, "text")))


def m_line_script(p):
    return ops.run_script_text(_doc(p), str(_need(p, "text")))


def m_line_enter(p):
    return ops.press(_doc(p), "enter")


def m_line_escape(p):
    return ops.press(_doc(p), "escape")


def m_line_state(p):
    return ops.command_state(_doc(p))


def m_execute(p):
    return ops.execute(_doc(p), str(_need(p, "command")), p.get("args") or {})


def m_commands(p):
    return {"commands": ops.catalogue(str(p.get("filter", "")))}


def m_docs(p):
    from app.doc.service import service

    return {"documents": service.summaries(), "active": service.active_id}


def m_inspect(p):
    return ops.summary(_doc(p))


def m_entities(p):
    return ops.query_entities(_doc(p), str(p.get("kind", "")), str(p.get("layer", "")), bool(p.get("selected")), p.get("window"), bool(p.get("crossing", True)), int(p.get("offset", 0)), int(p.get("limit", ops.DEFAULT_PAGE)), p.get("handle"))


def m_render(p):
    doc = _doc(p)
    shot = ops.render_b64(doc, p.get("window"), int(p.get("size", 1600)))
    path = p.get("path")
    if path:
        full = ops.checked_output(str(path), (".png",))
        with open(full, "wb") as fh:
            fh.write(base64.b64decode(shot["data"]))
        shot["path"] = full
    return shot


def m_open(p):
    return ops.open_path(str(_need(p, "path")))


def m_new(p):
    return ops.new_doc(str(p.get("name", "")), str(p.get("template", "")))


def m_save(p):
    return ops.save_doc(_doc(p), str(p.get("path", "")))


def m_export(p):
    return ops.export(_doc(p), str(_need(p, "path")), str(p.get("version", "")), p.get("window"), "", str(p.get("layout", "Model")), p.get("dpi"), str(p.get("paper", "")))


def m_quit(p):
    callback = getattr(m_quit, "callback", None)
    if callback is None:
        raise ControlError("unsupported", "This engine was not started with a quit hook.")
    threading.Timer(0.2, callback).start()
    return {"quitting": True}


METHODS = {
    "ping": m_ping,
    "line.type": m_line_type,
    "line.script": m_line_script,
    "line.enter": m_line_enter,
    "line.escape": m_line_escape,
    "line.state": m_line_state,
    "engine.execute": m_execute,
    "execute": m_execute,
    "engine.commands": m_commands,
    "docs.list": m_docs,
    "drawing.inspect": m_inspect,
    "drawing.entities": m_entities,
    "capture.render": m_render,
    "app.open": m_open,
    "app.new": m_new,
    "app.save": m_save,
    "app.export": m_export,
    "app.quit": m_quit,
}


def method_names() -> list:
    return sorted(set(METHODS) | {"meta.methods"})


def dispatch(method: str, params) -> object:
    if method == "meta.methods":
        return {"methods": method_names()}
    fn = METHODS.get(method)
    if fn is None:
        raise ControlError("unknown-method", "Unknown method %s. Ask meta.methods for the list." % method)
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise ControlError("bad-params", "params must be an object.")
    try:
        return fn(params)
    except ops.OpError as err:
        raise ControlError("failed", str(err))
    except ControlError:
        raise
    except Exception as err:
        raise ControlError("failed", "%s: %s" % (type(err).__name__, err))


def reply(request: dict) -> dict:
    rid = request.get("id")
    try:
        result = dispatch(str(request.get("method")), request.get("params"))
        return {"id": rid, "ok": True, "result": result}
    except ControlError as err:
        out = {"id": rid, "ok": False, "error": {"code": err.code, "message": err.message}}
        if err.state:
            out["error"]["state"] = err.state
        return out


class Listener:
    def __init__(self, port: int, data_dir):
        self.port = port
        self.token = secrets.token_urlsafe(32)
        self.data_dir = data_dir
        self.token_path = data_dir / ("control-%d.token" % port)
        self.loop: asyncio.AbstractEventLoop | None = None
        self.server = None
        self.ready = threading.Event()
        self.active = 0
        self.queued = 0
        self.error = ""

    def write_token(self) -> None:
        for stale in self.data_dir.glob("control-*.token"):
            try:
                stale.unlink()
            except OSError:
                pass
        fd = os.open(self.token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(self.token)

    async def handle(self, reader, writer) -> None:
        if self.active >= MAX_CONNECTIONS:
            writer.close()
            return
        self.active += 1
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(reader.readline(), IDLE_SECONDS)
                except (asyncio.TimeoutError, ValueError, ConnectionError):
                    break
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                request = None
                try:
                    request = json.loads(line.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    request = None
                if not isinstance(request, dict) or not isinstance(request.get("method"), str):
                    writer.write(self.encode({"id": None, "ok": False, "error": {"code": "bad-request", "message": "Send one JSON object per line with a string method."}}))
                    await writer.drain()
                    break
                token = request.get("token")
                if not isinstance(token, str) or not hmac.compare_digest(token.encode("utf-8"), self.token.encode("utf-8")):
                    writer.write(self.encode({"id": request.get("id"), "ok": False, "error": {"code": "unauthorized", "message": "A valid token is required."}}))
                    await writer.drain()
                    break
                reader._limit = MAX_LINE
                if self.queued >= MAX_QUEUE:
                    out = {"id": request.get("id"), "ok": False, "error": {"code": "busy", "message": "Too many queued requests.", "state": "not-run"}}
                else:
                    out = await self.run(request)
                writer.write(self.encode(out))
                await writer.drain()
        finally:
            self.active -= 1
            try:
                writer.close()
            except Exception:
                pass

    def encode(self, out: dict) -> bytes:
        return (json.dumps(out, separators=(",", ":"), default=str) + "\n").encode("utf-8")

    async def run(self, request: dict) -> dict:
        self.queued += 1
        loop = asyncio.get_running_loop()
        future = POOL.submit(reply, request)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future, loop=loop), CALL_SECONDS)
        except asyncio.TimeoutError:
            state = "not-run" if future.cancel() else "may-have-run"
            return {"id": request.get("id"), "ok": False, "error": {"code": "timeout", "message": "The engine did not answer in time.", "state": state}}
        finally:
            self.queued -= 1

    def serve(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.server = self.loop.run_until_complete(asyncio.start_server(self.handle, "127.0.0.1", self.port, limit=PRE_AUTH_LINE))
            self.port = self.server.sockets[0].getsockname()[1]
            self.token_path = self.data_dir / ("control-%d.token" % self.port)
            self.write_token()
        except OSError as err:
            self.error = str(err)
            self.ready.set()
            return
        self.ready.set()
        try:
            self.loop.run_forever()
        finally:
            self.server.close()

    def stop(self) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self.loop.stop)
        try:
            self.token_path.unlink()
        except OSError:
            pass


CURRENT: Listener | None = None


def start(port: int, data_dir) -> Listener:
    global CURRENT
    listener = Listener(port, data_dir)
    threading.Thread(target=listener.serve, name="formcad-control", daemon=True).start()
    listener.ready.wait(10)
    CURRENT = listener
    return listener


def status() -> dict:
    if CURRENT is None or CURRENT.error:
        return {"enabled": False, "error": CURRENT.error if CURRENT else ""}
    return {"enabled": True, "host": "127.0.0.1", "port": CURRENT.port, "tokenFile": str(CURRENT.token_path), "connections": CURRENT.active}
