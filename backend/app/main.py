import asyncio
import importlib
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.core import config, guard, runtime
from app.routers.events import hub
from app.services import kernel

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("text/css", ".css")

ROUTERS = [
    ("app.routers.system", "/api"),
    ("app.routers.kernel", "/api/kernel"),
    ("app.routers.events", "/api"),
    ("app.routers.docs", "/api/docs"),
    ("app.routers.display", "/api/docs"),
    ("app.routers.commands", "/api/commands"),
    ("app.routers.sysvars", "/api/sysvars"),
    ("app.routers.canvas", "/api/docs"),
    ("app.routers.tables", "/api/docs"),
    ("app.routers.drawann", "/api/docs"),
    ("app.routers.mtext", "/api/docs"),
    ("app.routers.properties", "/api/docs"),
    ("app.routers.layers", "/api/docs"),
    ("app.routers.layouts", "/api/docs"),
    ("app.routers.drawviews", "/api/docs"),
    ("app.routers.xrefs", "/api/docs"),
    ("app.routers.blocks", "/api/docs"),
    ("app.routers.scene", "/api/docs"),
    ("app.routers.planes", "/api/docs"),
    ("app.routers.constraints", "/api/docs"),
    ("app.routers.part", "/api/docs"),
    ("app.routers.part_preview", "/api/docs"),
    ("app.routers.bodies", "/api/docs"),
    ("app.routers.sheetflat", "/api/docs"),
    ("app.routers.sheetfeat", "/api/docs"),
    ("app.routers.assembly", "/api/docs"),
    ("app.routers.mates", "/api/docs"),
    ("app.routers.curves", "/api/docs"),
    ("app.routers.analysis", "/api/docs"),
    ("app.routers.gumball", "/api/docs"),
    ("app.routers.meshes", "/api/docs"),
    ("app.routers.holes", "/api/holes"),
    ("app.routers.interchange", "/api"),
    ("app.routers.plot", "/api"),
    ("app.routers.calc", "/api"),
    ("app.routers.uistyle", "/api"),
    ("app.routers.filetools", "/api"),
    ("app.routers.docquery", "/api/docs"),
    ("app.routers.graph", "/api"),
    ("app.routers.graphrun", "/api"),
    ("app.routers.automation", "/api/automation"),
    ("app.routers.mcp", ""),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    data = config.data_dir()
    runtime.start_logging(data)
    guard.write_token(data)
    loop = asyncio.get_running_loop()
    hub.bind(loop)
    loop.run_in_executor(None, kernel.probe)
    yield
    kernel.stop()
    runtime.stop_logging()
    runtime.release(data)


def register(app: FastAPI) -> None:
    for path, prefix in ROUTERS:
        try:
            module = importlib.import_module(path)
        except ModuleNotFoundError as err:
            if err.name == path:
                continue
            raise
        app.include_router(module.router, prefix=prefix)


class Frontend(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        target = getattr(response, "path", None)
        if target and os.path.basename(str(target)) == "index.html":
            html = Path(target).read_text(encoding="utf-8")
            meta = f'<meta name="formcad-token" content="{guard.TOKEN}">'
            html = html.replace("</head>", meta + "</head>", 1) if "</head>" in html else meta + html
            return HTMLResponse(html, headers={"Cache-Control": "no-store"})
        return response


def create_app() -> FastAPI:
    open_docs = os.environ.get("FORMCAD_API_DOCS") == "1"
    app = FastAPI(
        title=config.APP_NAME,
        version=config.VERSION,
        lifespan=lifespan,
        docs_url="/docs" if open_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if open_docs else None,
    )
    app.add_middleware(CORSMiddleware, allow_origins=config.cors_origins(), allow_methods=["*"], allow_headers=["*"])
    app.add_middleware(guard.Guard, origins=config.allowed_origins())
    register(app)
    dist = config.dist_dir()
    if dist is not None:
        app.mount("/", Frontend(directory=str(dist), html=True), name="frontend")
    return app


app = create_app()
