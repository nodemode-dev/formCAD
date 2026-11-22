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
from app.services import kernel, terminal

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
    ("app.routers.weld", "/api/docs"),
    ("app.routers.plastic", "/api/docs"),
    ("app.routers.mold", "/api/docs"),
    ("app.routers.assembly", "/api/docs"),
    ("app.routers.mates", "/api/docs"),
    ("app.routers.joints", "/api/docs"),
    ("app.routers.anim", "/api/docs"),
    ("app.routers.curves", "/api/docs"),
    ("app.routers.analysis", "/api/docs"),
    ("app.routers.gumball", "/api/docs"),
    ("app.routers.meshes", "/api/docs"),
    ("app.routers.subd", "/api/docs"),
    ("app.routers.holes", "/api/holes"),
    ("app.routers.pmi", "/api/docs"),
    ("app.routers.vault", "/api/vault"),
    ("app.routers.vaultdoc", "/api/docs"),
    ("app.routers.interchange", "/api"),
    ("app.routers.plot", "/api"),
    ("app.routers.calc", "/api"),
    ("app.routers.uistyle", "/api"),
    ("app.routers.filetools", "/api"),
    ("app.routers.docquery", "/api/docs"),
    ("app.routers.graph", "/api"),
    ("app.routers.graphrun", "/api"),
    ("app.routers.render", "/api"),
    ("app.routers.cam", "/api"),
    ("app.routers.camx", "/api"),
    ("app.routers.cam3d", "/api"),
    ("app.routers.additive", "/api/docs"),
    ("app.routers.sim", "/api/docs"),
    ("app.routers.simnl", "/api/docs"),
    ("app.routers.topo", "/api/docs"),
    ("app.routers.gen", "/api/docs"),
    ("app.routers.ecad", "/api/docs"),
    ("app.routers.pcb", "/api/docs"),
    ("app.routers.ecadout", "/api/docs"),
    ("app.routers.flow", "/api"),
    ("app.routers.pipes", "/api/docs"),
    ("app.routers.schem", "/api/docs"),
    ("app.routers.harness", "/api/docs"),
    ("app.routers.costing", "/api/docs"),
    ("app.routers.toolbox", "/api"),
    ("app.routers.inspection", "/api/docs"),
    ("app.routers.automation", "/api/automation"),
    ("app.routers.terminal", "/api"),
    ("app.demos.router", "/api/demos"),
    ("app.routers.mcp", ""),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    data = config.data_dir()
    runtime.start_logging(data)
    guard.write_token(data)
    loop = asyncio.get_running_loop()
    hub.bind(loop)
    terminal.bind(loop)
    loop.run_in_executor(None, kernel.probe)
    yield
    terminal.close_all()
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
            key = guard.page_token()
            if key is not None:
                meta = f'<meta name="formcad-token" content="{key}">'
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
