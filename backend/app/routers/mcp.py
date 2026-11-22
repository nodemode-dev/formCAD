import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from app.automation import mcp as protocol

router = APIRouter(tags=["mcp"])
MAX_BODY = 8 * 1024 * 1024
HEADER_MISMATCH = -32020


def _mismatch(message: str) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": HEADER_MISMATCH, "message": message}}, status_code=400)


def _process(text: str, version: str, mode: str = "core") -> str | None:
    return protocol.Server(mode).handle_text(text, version)


@router.post("/mcp")
async def post(request: Request) -> Response:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "The message is too large."}}, status_code=413)
    version = request.headers.get("mcp-protocol-version", "")
    text = raw.decode("utf-8", "replace")
    if version == protocol.MODERN:
        try:
            msg = json.loads(text)
        except ValueError:
            msg = None
        if isinstance(msg, dict):
            method = msg.get("method")
            if request.headers.get("mcp-method") != method:
                return _mismatch("The Mcp-Method header must match the request method.")
            if method in ("tools/call", "prompts/get"):
                name = (msg.get("params") or {}).get("name")
                if request.headers.get("mcp-name") != name:
                    return _mismatch("The Mcp-Name header must match the request name.")
    elif version and version not in protocol.SUPPORTED:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": protocol.UNSUPPORTED_VERSION, "message": "Unsupported protocol version.", "data": {"supported": list(protocol.SUPPORTED), "requested": version}}}, status_code=400)
    reply = await run_in_threadpool(_process, text, version, "all" if request.query_params.get("tools") == "all" else "core")
    if reply is None:
        return Response(status_code=202)
    return Response(content=reply, media_type="application/json")


@router.get("/mcp")
async def not_a_stream() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})


@router.delete("/mcp")
async def no_sessions() -> Response:
    return Response(status_code=405, headers={"Allow": "POST"})
