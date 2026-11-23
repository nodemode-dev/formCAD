import contextlib
import json

from app.core import guard

TAB_SCOPE = ("/mcp",)
PROTOCOL = "2025-06-18"


@contextlib.contextmanager
def tab_token():
    token = guard.issue_run_token(TAB_SCOPE)
    try:
        yield token
    finally:
        guard.revoke_run_token(token)


def call(engine, token, tool, arguments=None):
    message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}
    reply = engine.raw("POST", "/mcp", token=token, headers={"mcp-protocol-version": PROTOCOL}, json=message)
    assert reply.status_code == 200, reply.text
    result = reply.json()["result"]
    return result["structuredContent"], bool(result.get("isError"))


@contextlib.contextmanager
def granted_folders(data_dir, folders):
    path = data_dir / "automation.json"
    before = path.read_text(encoding="utf-8") if path.exists() else None
    settings = json.loads(before) if before else {}
    settings["agentFolders"] = [str(f) for f in folders]
    path.write_text(json.dumps(settings), encoding="utf-8")
    try:
        yield
    finally:
        if before is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(before, encoding="utf-8")
