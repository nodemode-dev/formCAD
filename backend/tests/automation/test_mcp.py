import re

import pytest

from tests.automation.mcp_client import VERSION, message, post, rpc, tool, tools


def shape(e: dict) -> tuple:
    keep = []
    for key in ("kind", "start", "end", "center", "radius", "closed"):
        if key in e:
            v = e[key]
            keep.append((key, tuple(round(x, 9) for x in v) if isinstance(v, list) else v))
    for v in e.get("vertices") or []:
        p = v.get("p") if isinstance(v, dict) else v
        keep.append(("v", tuple(round(x, 9) for x in p)))
    return tuple(keep)


def shapes(d) -> list:
    return sorted(shape(e) for e in d.entities())


def catalogue(repo) -> tuple[set, set]:
    text = (repo / "skills/formcad-driving/references/command-catalogue.md").read_text(encoding="utf-8")
    words = []
    for block in text.split("\n## ")[2:]:
        words += block.split("\n", 1)[1].split()
    return {w for w in words if not w.endswith("*")}, {w[:-1] for w in words if w.endswith("*")}


def tool_name(command: str) -> str:
    return "cmd_" + re.sub(r"[^A-Za-z0-9_]", "_", command)


def test_initialize_answers_with_the_requested_protocol_version_and_the_server_identity(engine):
    reply = rpc(engine, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "lane11", "version": "1"}}, rid=41)
    assert reply["jsonrpc"] == "2.0" and reply["id"] == 41 and "error" not in reply
    result = reply["result"]
    assert result["protocolVersion"] == "2024-11-05"
    assert result["serverInfo"]["name"] == "formcad"
    assert "tools" in result["capabilities"]


def test_initialize_with_an_unknown_protocol_version_offers_a_version_the_server_speaks(engine):
    result = rpc(engine, "initialize", {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": {"name": "lane11", "version": "1"}})["result"]
    offered = result["protocolVersion"]
    assert offered != "1999-01-01" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", offered)
    again = rpc(engine, "initialize", {"protocolVersion": offered, "capabilities": {}, "clientInfo": {"name": "lane11", "version": "1"}})["result"]
    assert again["protocolVersion"] == offered


def test_every_listed_tool_has_a_name_a_description_and_an_object_input_schema(engine):
    listed = tools(engine)
    names = [t["name"] for t in listed]
    assert len(names) == len(set(names))
    for t in listed:
        assert t["description"].strip(), t["name"]
        assert t["inputSchema"]["type"] == "object", t["name"]


def test_the_default_tool_list_holds_the_fixed_tools_and_the_common_drafting_commands_only(engine, repo):
    names = {t["name"] for t in tools(engine)}
    for fixed in ("formcad_status", "formcad_execute", "formcad_command_line", "formcad_list_commands", "formcad_inspect", "formcad_query_entities", "formcad_undo", "formcad_redo", "formcad_graph_run", "formcad_sim_start", "formcad_cam_start", "formcad_job_status"):
        assert fixed in names
    for drafting in ("line", "circle", "arc", "pline", "rectang", "move", "copy", "erase", "rotate", "scale", "mirror", "offset"):
        assert tool_name(drafting) in names
    plain, _ = catalogue(repo)
    command_tools = {n for n in names if n.startswith("cmd_")}
    assert len(command_tools) < len(plain) / 10
    assert tool_name("vaultlog") not in names


def test_the_full_tool_list_has_one_tool_per_catalogued_command_and_none_for_barred_ones(engine, repo):
    plain, starred = catalogue(repo)
    names = {t["name"] for t in tools(engine, "/mcp?tools=all")}
    assert sorted(c for c in plain if tool_name(c) not in names) == []
    assert sorted(c for c in starred if tool_name(c) in names) == []


@pytest.mark.parametrize(
    "tool_args, typed",
    [
        (("cmd_line", {"points": [[0, 0], [30, 40], [50, 10]]}), ("LINE", "0,0", "30,40", "50,10", "")),
        (("cmd_circle", {"center": [10, 10], "radius": 7.5}), ("CIRCLE", "10,10", "7.5")),
        (("cmd_rectang", {"p1": [0, 0], "p2": [200, 120]}), ("RECTANG", "0,0", "200,120")),
        (("formcad_command_line", {"text": "LINE 5,5 25,5 25,30 "}), ("LINE", "5,5", "25,5", "25,30", "")),
        (("formcad_execute", {"command": "circle", "args": {"center": [3, 4], "radius": 5}}), ("CIRCLE", "3,4", "5")),
    ],
)
def test_a_drawing_tool_makes_the_same_objects_as_the_same_command_typed_by_a_person(engine, docs, tool_args, typed):
    by_agent, by_person = docs(), docs()
    name, args = tool_args
    reply = tool(engine, name, dict(args, document=by_agent.id))
    assert not reply["result"].get("isError"), reply
    by_person.type(*typed)
    assert shapes(by_agent) == shapes(by_person) != []


def test_an_agent_line_is_taken_back_by_formcad_undo_and_put_back_by_formcad_redo(engine, doc):
    tool(engine, "cmd_line", {"points": [[0, 0], [30, 40]], "document": doc.id})
    made = shapes(doc)
    assert len(made) == 1
    tool(engine, "formcad_undo", {"document": doc.id})
    assert doc.entities() == []
    tool(engine, "formcad_redo", {"document": doc.id})
    assert shapes(doc) == made


def test_a_query_through_mcp_reports_the_geometry_the_document_holds(engine, doc):
    doc.type("LINE", "0,0", "30,40", "")
    doc.type("CIRCLE", "10,10", "7.5")
    found = tool(engine, "formcad_query_entities", {"kind": "circle", "document": doc.id})["result"]["structuredContent"]
    assert found["total"] == 1
    circle = found["entities"][0]
    assert circle["radius"] == pytest.approx(7.5, abs=1e-9) and circle["center"][:2] == pytest.approx([10.0, 10.0], abs=1e-9)


def test_an_unknown_tool_is_a_json_rpc_invalid_params_error_and_the_server_keeps_answering(engine):
    reply = tool(engine, "formcad_no_such_tool", {})
    assert reply["error"]["code"] == -32602 and "formcad_no_such_tool" in reply["error"]["message"]
    assert "result" not in reply
    assert tools(engine)


@pytest.mark.parametrize(
    "name, args, word",
    [
        ("cmd_circle", {"center": [0, 0], "radius": "big"}, "radius"),
        ("cmd_line", {"points": [[0, 0]]}, "points"),
        ("cmd_line", {}, "points"),
        ("formcad_execute", {"command": "line", "colour": 3}, "colour"),
    ],
)
def test_bad_tool_arguments_are_a_json_rpc_invalid_params_error_naming_the_field(engine, doc, name, args, word):
    reply = tool(engine, name, dict(args, document=doc.id))
    assert reply["error"]["code"] == -32602 and word in reply["error"]["message"]
    assert doc.entities() == []


def test_an_unknown_method_is_method_not_found_and_broken_json_is_a_parse_error(engine):
    assert rpc(engine, "drawing/teleport", {})["error"]["code"] == -32601
    r = engine.raw("POST", "/mcp", content=b'{"jsonrpc": "2.0", "id": 1, "method": ', headers={"content-type": "application/json", "mcp-protocol-version": VERSION})
    assert r.json()["error"]["code"] == -32700


def test_a_notification_gets_no_json_rpc_reply(engine):
    r = post(engine, "notifications/initialized", None, rid=None)
    assert r.status_code == 202 and r.content == b""


def test_a_command_that_fails_is_reported_as_a_tool_error_not_a_crash(engine, doc):
    reply = tool(engine, "formcad_execute", {"command": "circle", "args": {"center": [0, 0], "radius": -4}, "document": doc.id})
    assert reply["result"]["isError"] is True
    assert reply["result"]["structuredContent"]["error"]
    assert doc.entities() == []


def test_mcp_without_the_session_key_is_refused_and_runs_nothing(engine, doc):
    call = message("tools/call", {"name": "cmd_line", "arguments": {"points": [[0, 0], [1, 1]], "document": doc.id}})
    for token in (None, "not-the-key"):
        r = engine.raw("POST", "/mcp", token=token, json=call, headers={"mcp-protocol-version": VERSION})
        assert r.status_code == 401 and "result" not in r.json()
    assert doc.entities() == []


@pytest.fixture()
def agent_tab_key():
    from app.core import guard
    from app.services import agent_programs

    key = guard.issue_run_token(agent_programs.SCOPE)
    yield key
    guard.revoke_run_token(key)


def test_an_agent_tab_key_drives_the_mcp_route(engine, doc, agent_tab_key):
    call = message("tools/call", {"name": "cmd_line", "arguments": {"points": [[0, 0], [30, 40]], "document": doc.id}})
    r = engine.raw("POST", "/mcp", token=agent_tab_key, json=call, headers={"mcp-protocol-version": VERSION})
    assert r.status_code == 200 and not r.json()["result"].get("isError")
    assert shapes(doc) == [(("kind", "line"), ("start", (0.0, 0.0, 0.0)), ("end", (30.0, 40.0, 0.0)))]


@pytest.mark.parametrize(
    "method, tail, body",
    [
        ("GET", "/api/docs", None),
        ("POST", "/api/docs", {"name": "", "template": ""}),
        ("GET", "{doc}/snapshot", None),
        ("POST", "{doc}/input", {"text": "LINE"}),
        ("POST", "/api/vault", {"name": "stolen"}),
        ("GET", "/api/automation/plugins", None),
    ],
)
def test_an_agent_tab_key_is_refused_with_403_on_window_routes(engine, doc, agent_tab_key, method, tail, body):
    path = tail.replace("{doc}", doc.url(""))
    before = len(engine.docs())
    r = engine.raw(method, path, token=agent_tab_key, json=body)
    assert r.status_code == 403 and "agent" in r.json()["detail"]
    assert len(engine.docs()) == before and doc.entities() == []


def test_an_agent_cannot_create_a_vault(engine, doc, tmp_path):
    before = engine.get("/api/vault")["vaults"]
    reply = tool(engine, "formcad_execute", {"command": "vaultcreate", "args": {"name": "agentvault", "folder": str(tmp_path / "v")}, "document": doc.id})
    assert reply["result"]["isError"] is True and "agent" in reply["result"]["structuredContent"]["error"]
    assert engine.get("/api/vault")["vaults"] == before
    assert not (tmp_path / "v").exists()


def test_an_agent_cannot_save_outside_the_granted_folders(engine, doc, tmp_path):
    doc.type("LINE", "0,0", "1,1", "")
    target = tmp_path / "agent.fcad"
    reply = tool(engine, "formcad_save_document", {"path": str(target), "document": doc.id})
    assert reply["result"]["isError"] is True and "outside the folders" in reply["result"]["structuredContent"]["error"]
    assert not target.exists()


def test_an_agent_cannot_enable_a_plugin(engine, doc):
    before = engine.get("/api/automation/plugins")["plugins"]
    reply = tool(engine, "formcad_execute", {"command": "pluginenable", "args": {"id": "example-nodes"}, "document": doc.id})
    assert reply["result"]["isError"] is True and "agent" in reply["result"]["structuredContent"]["error"]
    assert engine.get("/api/automation/plugins")["plugins"] == before
