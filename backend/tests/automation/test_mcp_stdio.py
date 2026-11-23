import json
import os
import subprocess

import pytest

from tests.automation.mcp_client import VERSION, message

pytestmark = pytest.mark.live


def serve(repo, tmp_path, lines: list, *extra) -> tuple[int, list, str]:
    env = dict(os.environ, FORMCAD_DATA_DIR=str(tmp_path))
    env.pop("FORMCAD_LOCKED", None)
    text = "".join(json.dumps(m) + "\n" for m in lines)
    done = subprocess.run([str(repo / "formCAD"), "mcp", "--settings-dir", str(tmp_path), *extra], input=text, capture_output=True, text=True, timeout=90, cwd=str(repo), env=env)
    replies = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    return done.returncode, replies, done.stderr


def test_the_stdio_server_answers_initialize_and_tools_list_and_exits_cleanly_when_input_ends(repo, tmp_path):
    code, replies, err = serve(repo, tmp_path, [
        message("initialize", {"protocolVersion": VERSION, "capabilities": {}, "clientInfo": {"name": "lane11", "version": "1"}}, 1),
        message("notifications/initialized", None, None),
        message("tools/list", {}, 2),
    ])
    assert code == 0, err
    assert [r["id"] for r in replies] == [1, 2]
    assert all(r["jsonrpc"] == "2.0" for r in replies)
    assert replies[0]["result"]["protocolVersion"] == VERSION
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert {"formcad_execute", "formcad_status", "cmd_line"} <= names
    assert "cmd_vaultlog" not in names


def test_the_stdio_server_draws_in_its_own_document_and_reports_it_back(repo, tmp_path):
    code, replies, err = serve(repo, tmp_path, [
        message("initialize", {"protocolVersion": VERSION, "capabilities": {}, "clientInfo": {"name": "lane11", "version": "1"}}, 1),
        message("tools/call", {"name": "formcad_new_document", "arguments": {}}, 2),
        message("tools/call", {"name": "cmd_line", "arguments": {"points": [[0, 0], [3, 4]]}}, 3),
        message("tools/call", {"name": "formcad_no_such_tool", "arguments": {}}, 4),
        message("tools/call", {"name": "formcad_query_entities", "arguments": {"kind": "line"}}, 5),
    ])
    assert code == 0, err
    by_id = {r["id"]: r for r in replies}
    assert by_id[4]["error"]["code"] == -32602
    found = by_id[5]["result"]["structuredContent"]
    assert found["total"] == 1
    line = found["entities"][0]
    assert line["start"][:2] == pytest.approx([0, 0], abs=1e-9) and line["end"][:2] == pytest.approx([3, 4], abs=1e-9)


@pytest.mark.slow
def test_the_stdio_server_with_all_tools_lists_more_command_tools_than_the_default(repo, tmp_path):
    hello = message("initialize", {"protocolVersion": VERSION, "capabilities": {}, "clientInfo": {"name": "lane11", "version": "1"}}, 1)
    listing = message("tools/list", {}, 2)
    _, core, _ = serve(repo, tmp_path, [hello, listing])
    code, every, err = serve(repo, tmp_path, [hello, listing], "--tools", "all")
    assert code == 0, err
    core_names = {t["name"] for t in core[1]["result"]["tools"]}
    all_names = {t["name"] for t in every[1]["result"]["tools"]}
    assert core_names < all_names and "cmd_vaultlog" in all_names
