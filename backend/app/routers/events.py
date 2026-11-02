import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["events"])


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.tasks: set[asyncio.Task] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def publish(self, message: dict) -> None:
        loop = self.loop
        if loop is None or loop.is_closed() or not self.clients:
            return
        loop.call_soon_threadsafe(self.schedule, message)

    def schedule(self, message: dict) -> None:
        task = asyncio.ensure_future(self.send(message))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def send(self, message: dict) -> None:
        for client in list(self.clients):
            try:
                await client.send_json(message)
            except Exception:
                self.clients.discard(client)


hub = Hub()


@router.websocket("/events")
async def events(socket: WebSocket) -> None:
    await socket.accept()
    hub.clients.add(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(socket)
