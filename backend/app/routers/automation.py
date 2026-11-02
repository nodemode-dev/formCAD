import json
import os
import shlex
import subprocess
import sys
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.automation import control, macros, mcp, plugins
from app.core import config, guard

router = APIRouter(tags=["automation"])


class MacroPath(BaseModel):
    path: str


class TrustBody(BaseModel):
    path: str
    trusted: bool = True
    grants: Optional[dict[str, Any]] = None
    sha256: Optional[str] = ""


class RunBody(BaseModel):
    path: str
    document: Optional[str] = ""
    timeout: Optional[float] = None


class EnableBody(BaseModel):
    enabled: bool = True
    manifestSha256: Optional[str] = ""


class PythonBody(BaseModel):
    path: str = ""


class LimitsBody(BaseModel):
    limits: dict[str, float]


class SupportBody(BaseModel):
    folders: list[str] = []


@router.get("/lisp-support")
def lisp_support_get() -> dict:
    from app.lisp import support

    return {"folders": support.folders()}


@router.put("/lisp-support")
def lisp_support_put(body: SupportBody) -> dict:
    from app.lisp import support

    try:
        return {"folders": support.set_folders(body.folders)}
    except ValueError as err:
        raise HTTPException(400, str(err))


def engine_command() -> list:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, os.path.abspath(os.path.join(str(config.BACKEND_DIR), "formcad_engine.py"))]


def quote(parts: list) -> str:
    return subprocess.list2cmdline(parts) if os.name == "nt" else " ".join(shlex.quote(p) for p in parts)


def client_config(extra: list) -> dict:
    cmd = engine_command()
    args = cmd[1:] + ["mcp"] + extra
    entry = {"command": cmd[0], "args": args}
    return {
        "addLine": "claude mcp add formcad -- " + quote(cmd + ["mcp"] + extra),
        "mcpJson": json.dumps({"mcpServers": {"formcad": entry}}, indent=2),
        "desktopJson": json.dumps({"mcpServers": {"formcad": entry}}, indent=2),
    }


def _run(fn):
    try:
        return fn()
    except macros.MacroError as err:
        raise HTTPException(400, str(err))
    except plugins.PluginError as err:
        raise HTTPException(400, str(err))


@router.get("/status")
def status(request: Request) -> dict:
    base = "http://%s" % request.headers.get("host", "127.0.0.1")
    return {
        "mcp": {"tools": len(mcp.tool_list()), "protocols": list(mcp.SUPPORTED), "httpEndpoint": base + "/mcp", "tokenHeader": guard.HEADER, "tokenFile": str(config.data_dir() / guard.TOKEN_FILE), "headless": client_config([]), "live": client_config(["--connect", "auto"])},
        "control": control.status(),
        "plugins": len(plugins.discover()),
        "macros": len(macros.listing()),
    }


@router.get("/macros")
def list_macros() -> dict:
    return {"folder": str(macros.macro_folder()), "macros": macros.listing(), "limits": {**macros.DEFAULT_LIMITS, **macros.load_settings().get("macroLimits", {})}}


@router.get("/macros/source")
def macro_source(path: str) -> dict:
    return _run(lambda: {**macros.status(path), "source": macros.source(path)})


@router.post("/macros/trust")
def macro_trust(body: TrustBody) -> dict:
    return _run(lambda: macros.set_trust(body.path, body.trusted, body.grants, body.sha256 or ""))


@router.post("/macros/run")
def macro_run(body: RunBody, request: Request) -> dict:
    base = "http://%s" % request.headers.get("host", "127.0.0.1")
    return _run(lambda: macros.run(body.path, base, body.document or "", body.timeout))


@router.put("/macros/limits")
def macro_limits(body: LimitsBody) -> dict:
    data = macros.load_settings()
    allowed = {k: v for k, v in body.limits.items() if k in macros.DEFAULT_LIMITS and v > 0}
    data["macroLimits"] = allowed
    macros.save_settings(data)
    return {"limits": {**macros.DEFAULT_LIMITS, **allowed}}


@router.get("/python")
def python_status() -> dict:
    return {"chosen": macros.load_settings().get("python", ""), "found": macros.detect_python(), "frozen": bool(getattr(sys, "frozen", False))}


@router.put("/python")
def python_set(body: PythonBody) -> dict:
    path = body.path.strip()
    if path and not os.path.isfile(path):
        raise HTTPException(400, "That interpreter does not exist.")
    if path and not os.path.basename(path).lower().startswith("py"):
        raise HTTPException(400, "The interpreter file name must start with python or py.")
    data = macros.load_settings()
    if path:
        data["python"] = path
    else:
        data.pop("python", None)
    macros.save_settings(data)
    return python_status()


@router.get("/plugins")
def list_plugins() -> dict:
    items = plugins.discover()
    return {"folder": str(plugins.folder()), "api": plugins.API_VERSION, "plugins": items}


@router.post("/plugins/{plugin_id}/enable")
def plugin_enable(plugin_id: str, body: EnableBody) -> dict:
    return _run(lambda: plugins.set_enabled(plugin_id, body.enabled, body.manifestSha256 or ""))


@router.post("/control")
def control_call(body: dict[str, Any]) -> dict:
    return control.reply(body)
