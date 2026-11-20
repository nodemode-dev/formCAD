import asyncio
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.services import agent_programs, terminal

router = APIRouter(tags=["terminal"])
MAX_SOCKETS = 24
_sockets = {"n": 0}


class OpenBody(BaseModel):
    cols: int = Field(100, ge=1, le=10000)
    rows: int = Field(30, ge=1, le=10000)
    title: str | None = Field(None, max_length=60)


class AgentBody(BaseModel):
    kind: Literal["claude", "codex", "cursor", "antigravity"]
    cols: int = Field(100, ge=1, le=10000)
    rows: int = Field(30, ge=1, le=10000)
    prompt: str | None = Field(None, max_length=100_000)
    resume: str | None = Field(None, max_length=200, pattern=r"^[A-Za-z0-9_-]*$")


def _size(cols: int, rows: int) -> tuple[int, int]:
    return min(max(cols, terminal.MIN_COLS), 500), min(max(rows, terminal.MIN_ROWS), 200)


def _port(request: Request) -> int:
    server = request.scope.get("server")
    return terminal.note_port(server[1] if server and len(server) > 1 else None)


def _bind() -> None:
    try:
        terminal.bind(asyncio.get_running_loop())
    except RuntimeError:
        pass


def _no_pty() -> HTTPException:
    return HTTPException(status_code=503, detail="This engine has no pseudo-terminal library, so the agent dock cannot open tabs.")


@router.get("/terminal")
async def list_terminals() -> dict:
    _bind()
    return {"terminals": terminal.listing(), "contract": agent_programs.CONTRACT, "available": terminal.available()}


@router.get("/terminal/contract")
async def contract() -> dict:
    return {"contract": agent_programs.CONTRACT, "available": terminal.available(), "kinds": ["shell", *agent_programs.KINDS]}


@router.post("/terminal")
async def open_terminal(body: OpenBody, request: Request) -> dict:
    _bind()
    _port(request)
    if not terminal.available():
        raise _no_pty()
    cols, rows = _size(body.cols, body.rows)
    try:
        return terminal.open_session(cols=cols, rows=rows, title=body.title).describe()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"The shell could not start: {exc}")


@router.post("/terminal/agent")
def open_agent(body: AgentBody, request: Request) -> dict:
    port = _port(request)
    if not terminal.available():
        raise _no_pty()
    cols, rows = _size(body.cols, body.rows)
    try:
        return agent_programs.open_terminal(body.kind, port, cols, rows, body.prompt, body.resume or None)
    except LookupError as exc:
        raise HTTPException(status_code=424, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"The program could not start: {exc}")


@router.post("/terminal/{sid}/restart")
async def restart_terminal(sid: str) -> dict:
    _bind()
    try:
        return terminal.restart(sid).describe()
    except KeyError:
        raise HTTPException(status_code=404, detail="There is no such terminal.")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"The program could not start again: {exc}")


@router.delete("/terminal/{sid}")
async def close_terminal(sid: str) -> dict:
    terminal.close(sid)
    return {"ok": True}


@router.get("/agents/status")
def agent_status(fresh: bool = False) -> dict:
    return agent_programs.report(fresh) | {"contract": agent_programs.CONTRACT}


@router.websocket("/terminal/{sid}/stream")
async def attach(ws: WebSocket, sid: str) -> None:
    _bind()
    if _sockets["n"] >= MAX_SOCKETS:
        await ws.close(code=4429)
        return
    try:
        session = terminal.get(sid)
    except KeyError:
        await ws.close(code=4404)
        return
    _sockets["n"] += 1
    await ws.accept()
    queue: asyncio.Queue = asyncio.Queue()
    session.subscribers.add(queue)

    async def outbound() -> None:
        await ws.send_text(session.scrollback())
        if not session.alive:
            await ws.send_bytes(json.dumps({"type": "exit"}).encode())
        while True:
            text = await queue.get()
            if text is None:
                await ws.send_bytes(json.dumps({"type": "exit"}).encode())
                continue
            await ws.send_text(text)

    sender = asyncio.create_task(outbound())
    try:
        while True:
            try:
                msg = json.loads(await ws.receive_text())
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "input" and session.alive:
                try:
                    terminal.write(sid, str(msg.get("data", "")))
                except (KeyError, OSError):
                    continue
            elif msg.get("type") == "resize":
                try:
                    terminal.resize(sid, int(msg.get("cols", 80)), int(msg.get("rows", 24)))
                except (KeyError, TypeError, ValueError, OSError):
                    continue
    except WebSocketDisconnect:
        pass
    finally:
        _sockets["n"] = max(0, _sockets["n"] - 1)
        sender.cancel()
        session.subscribers.discard(queue)
