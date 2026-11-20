from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from app.core import config, guard
from app.services import agent_lookup, terminal

CONTRACT = "2.2.0"
KINDS = ("claude", "codex", "cursor", "antigravity")
OVERRIDES = {"claude": ("FORMCAD_CLAUDE_BIN",), "codex": ("FORMCAD_CODEX_BIN",), "cursor": ("FORMCAD_CURSOR_BIN",), "antigravity": ("FORMCAD_ANTIGRAVITY_BIN",)}
SHELL_WAIT = 10.0
CHECK_WAIT = 15.0
CACHE_SECONDS = 60.0
SERVER = "formcad_tab"
TOKEN_VAR = "FORMCAD_TAB_TOKEN"
MCP_URL_VAR = "FORMCAD_MCP_URL"
HEADER = "X-FormCAD-Token"
SCOPE = ("/mcp",)
NOTE = ("You are running in a tab of the agent dock inside FormCAD, the drafting and modelling app open on this computer. "
        "The formcad_tab MCP server is that window's engine: its formcad_* tools act on the drawings open there, and the person sees every change. "
        "Use the formcad-driving skill when it is available.")
_cache: dict = {"at": 0.0, "value": None}
_open_lock = threading.Lock()


def mcp_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/mcp"


def child_env(path: str | None = None) -> dict:
    return agent_lookup.child_env(path, shell_timeout=SHELL_WAIT)


def located(kind: str, fresh: bool = False) -> agent_lookup.Found:
    found = agent_lookup.find(kind, setting=None, override_vars=OVERRIDES.get(kind, ()), shell_timeout=SHELL_WAIT, fresh=fresh)
    return agent_lookup.check(found, child_env(found.path), CHECK_WAIT, fresh)


def usable(kind: str) -> agent_lookup.Found:
    found = located(kind)
    return found if found.state == "runs" else located(kind, fresh=True)


def said(found: agent_lookup.Found) -> str:
    return agent_lookup.sentence(found, agent_lookup.install(found.program), "")


def _signed_in(path: str) -> bool | None:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return True
    try:
        out = agent_lookup.run([path, "auth", "status"], child_env(path), CHECK_WAIT)
        data = json.loads(out.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    return bool(data.get("loggedIn")) if isinstance(data, dict) and "loggedIn" in data else None


def report(fresh: bool = False) -> dict:
    if not fresh and _cache["value"] is not None and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["value"]
    out = {}
    for kind in KINDS:
        found = located(kind, fresh)
        install = agent_lookup.install(kind)
        signed = _signed_in(found.path) if kind == "claude" and found.state == "runs" and found.path else None
        out[kind] = agent_lookup.answer(found, install, "") | {"signedIn": signed, "install": install, "title": found.title}
        if found.state != "runs":
            out[kind]["note"] = out[kind]["said"]
    _cache.update(at=time.time(), value=out)
    return out


def tab_folder(kind: str) -> Path:
    folder = config.data_dir() / "agent-tabs" / kind
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _write_private(path: Path, data: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    part = path.with_name(path.name + f".part-{os.getpid()}")
    with os.fdopen(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as fh:
        fh.write(json.dumps(data, indent=2) + "\n")
    os.replace(part, path)


def _servers(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8") or "{}") if path.exists() else {}
    if not isinstance(data, dict) or not isinstance(data.get("mcpServers", {}), dict):
        raise OSError(f"{path} is not an MCP servers file FormCAD can read, so it was left alone")
    return data


def antigravity_file(folder: Path) -> Path:
    return folder / ".agents" / "mcp_config.json"


def write_antigravity(folder: Path, port: int, token: str) -> None:
    path = antigravity_file(folder)
    data = _servers(path)
    data.setdefault("mcpServers", {})[SERVER] = {"serverUrl": mcp_url(port), "headers": {HEADER: token}}
    _write_private(path, data)


def remove_antigravity(folder: Path, token: str) -> None:
    path = antigravity_file(folder)
    try:
        data = _servers(path)
        entry = data.get("mcpServers", {}).get(SERVER)
        if not isinstance(entry, dict) or (entry.get("headers") or {}).get(HEADER) != token:
            return
        del data["mcpServers"][SERVER]
        _write_private(path, data)
    except (OSError, ValueError):
        return


def write_cursor(folder: Path) -> None:
    path = folder / ".cursor" / "mcp.json"
    entry = {"url": "${env:" + MCP_URL_VAR + "}", "headers": {HEADER: "${env:" + TOKEN_VAR + "}"}}
    try:
        data = _servers(path)
    except (OSError, ValueError):
        return
    if data.get("mcpServers", {}).get(SERVER) == entry:
        return
    data.setdefault("mcpServers", {})[SERVER] = entry
    _write_private(path, data)


def claude_args(port: int, prompt: str | None, resume: str | None) -> list[str]:
    config_json = json.dumps({"mcpServers": {SERVER: {"type": "http", "url": mcp_url(port), "headers": {HEADER: "${" + TOKEN_VAR + "}"}}}})
    args = ["--mcp-config", config_json, "--allowedTools", f"mcp__{SERVER}", "--append-system-prompt", NOTE]
    if resume:
        args += ["--resume", resume]
    if prompt:
        args += ["--", prompt]
    return args


def codex_args(port: int) -> list[str]:
    return ["-c", f'mcp_servers.{SERVER}.url="{mcp_url(port)}"',
            "-c", f'mcp_servers.{SERVER}.env_http_headers={{"{HEADER}"="{TOKEN_VAR}"}}']


def open_terminal(kind: str, port: int, cols: int, rows: int, prompt: str | None = None, resume: str | None = None) -> dict:
    if kind not in KINDS:
        raise ValueError(f"No agent program called {kind}")
    with _open_lock:
        if kind == "claude" and prompt and not resume:
            running = terminal.live("claude")
            if running is not None:
                terminal.write(running.id, prompt.replace("\r\n", "\n").replace("\r", "\n") + "\r")
                return running.describe()
        found = usable(kind)
        if found.state != "runs" or not found.path:
            raise LookupError(said(found))
        extra = claude_args(port, prompt, resume) if kind == "claude" else codex_args(port) if kind == "codex" else []
        argv = agent_lookup.start_argv([found.path, *extra])
        own = tab_folder(kind) if kind == "antigravity" else None
        folder = own or Path(terminal.workdir())
        token = guard.issue_run_token(SCOPE)
        env = agent_lookup.child_env(found.path, base=terminal.base_env(), extra={TOKEN_VAR: token, MCP_URL_VAR: mcp_url(port)}, shell_timeout=SHELL_WAIT)
        try:
            if kind == "cursor":
                write_cursor(folder)
            if own:
                write_antigravity(own, port, token)
            session = terminal.open_session(str(folder), cols, rows, found.title, argv, env, kind)
        except BaseException:
            guard.revoke_run_token(token)
            if own:
                remove_antigravity(own, token)
            raise
        session.on_close.append(lambda: guard.revoke_run_token(token))
        if own:
            session.on_close.append(lambda: remove_antigravity(own, token))
        return session.describe()
