VERSION = "2025-06-18"


def message(method: str, params=None, rid=1) -> dict:
    msg = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        msg["id"] = rid
    if params is not None:
        msg["params"] = params
    return msg


def post(engine, method: str, params=None, rid=1, path: str = "/mcp", **kw):
    headers = {"mcp-protocol-version": VERSION}
    headers.update(kw.pop("headers", {}) or {})
    return engine.raw("POST", path, json=message(method, params, rid), headers=headers, **kw)


def rpc(engine, method: str, params=None, rid=1, path: str = "/mcp", **kw) -> dict:
    r = post(engine, method, params, rid, path, **kw)
    assert r.status_code == 200, r.text
    return r.json()


def tool(engine, name: str, arguments: dict | None = None, path: str = "/mcp") -> dict:
    return rpc(engine, "tools/call", {"name": name, "arguments": arguments or {}}, path=path)


def tools(engine, path: str = "/mcp") -> list:
    return rpc(engine, "tools/list", {}, path=path)["result"]["tools"]
