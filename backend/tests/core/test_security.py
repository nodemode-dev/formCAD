import re
import shutil

import pytest
from starlette.websockets import WebSocketDisconnect

from app.main import app
from tests.core import agent

NO_KEY = "A valid X-FormCAD-Token is required"
TAB_ONLY = "good only for its own routes"
OUTSIDE = "outside the folders granted to this agent"
LOCAL = {"host": "127.0.0.1:8290"}


def _routes():
    out = []
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            out.append((method.upper(), path, re.sub(r"{\w+}", "x", path)))
    return out


def test_every_api_route_except_health_refuses_a_missing_or_wrong_session_key(engine):
    wrong = []
    checked = 0
    for method, path, url in _routes():
        if path == "/api/health":
            continue
        for token in (None, "not-the-session-key"):
            reply = engine.raw(method, url, token=token)
            checked += 1
            if reply.status_code != 401 or NO_KEY not in reply.text:
                wrong.append((method, path, token, reply.status_code))
    assert checked > 1000
    assert wrong == []


def test_health_answers_without_a_session_key(engine):
    reply = engine.raw("GET", "/api/health", token=None)
    assert reply.status_code == 200 and reply.json()["ok"] is True


def test_the_session_key_written_to_the_data_folder_opens_window_routes(engine, data_dir, doc):
    key = (data_dir / "session.token").read_text(encoding="utf-8").strip()
    reply = engine.raw("GET", doc.url("/state"), token=key)
    assert reply.status_code == 200 and reply.json()["prompt"] == "Command:"


@pytest.mark.parametrize("host", ["evil.example", "evil.example:8290", "192.168.1.20:8290", "localhost.evil.example", "127.0.0.1.evil.example"])
def test_a_request_whose_host_is_not_loopback_is_refused_even_with_the_key(engine, doc, host):
    for path in ("/api/health", doc.url("/snapshot")):
        reply = engine.raw("GET", path, headers={"host": host})
        assert reply.status_code == 403 and "own window" in reply.json()["detail"]


@pytest.mark.parametrize("host", ["127.0.0.1:8290", "localhost:8290", "[::1]:8290", "localhost"])
def test_a_request_whose_host_is_loopback_is_answered(engine, host):
    reply = engine.raw("GET", "/api/health", headers={"host": host})
    assert reply.status_code == 200 and reply.json()["ok"] is True


@pytest.mark.parametrize("headers", [
    {"origin": "http://evil.example"},
    {"origin": "https://localhost.evil.example"},
    {"origin": "null"},
    {"origin": "http://127.0.0.1:9999"},
    {"sec-fetch-site": "cross-site"},
])
def test_a_cross_site_request_is_refused_even_with_the_key(engine, doc, headers):
    reply = engine.raw("GET", doc.url("/snapshot"), headers=headers)
    assert reply.status_code == 403 and "own window" in reply.json()["detail"]


@pytest.mark.parametrize("origin", ["http://localhost:5290", "http://127.0.0.1:5290", "tauri://localhost"])
def test_the_interface_origins_are_answered(engine, doc, origin):
    reply = engine.raw("GET", doc.url("/state"), headers={"origin": origin})
    assert reply.status_code == 200 and reply.json()["prompt"] == "Command:"


def test_an_agent_tab_key_reaches_mcp_but_every_window_route_answers_403(engine, doc):
    with agent.tab_token() as token:
        listed, failed = agent.call(engine, token, "formcad_list_documents")
        assert not failed and doc.id in [d["id"] for d in listed["documents"]]
        wrong = []
        for method, path, url in _routes():
            if path in ("/api/health", "/mcp"):
                continue
            url = url.replace("/x", "/" + doc.id, 1) if "{doc_id}" in path else url
            reply = engine.raw(method, url, token=token)
            if reply.status_code != 403 or TAB_ONLY not in reply.text:
                wrong.append((method, path, reply.status_code))
        assert wrong == []
    assert doc.entities() == []


def test_an_agent_tab_key_stops_working_when_the_tab_closes(engine):
    with agent.tab_token() as token:
        _, failed = agent.call(engine, token, "formcad_list_documents")
        assert not failed
    reply = engine.raw("POST", "/mcp", token=token, json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert reply.status_code == 401


def test_an_agent_cannot_open_a_file_outside_the_granted_folders(engine, fixtures):
    before = [d["id"] for d in engine.docs()]
    with agent.tab_token() as token:
        out, failed = agent.call(engine, token, "formcad_open_document", {"path": str(fixtures / "doc-basic.fcad")})
    assert failed and OUTSIDE in out["error"]
    assert [d["id"] for d in engine.docs()] == before


def test_an_agent_cannot_save_to_a_path_outside_the_granted_folders(engine, doc, tmp_path, data_dir):
    doc.type("LINE", "0,0", "10,0", "")
    granted = tmp_path / "granted"
    granted.mkdir()
    target = tmp_path / "elsewhere.fcad"
    with agent.granted_folders(data_dir, [granted]), agent.tab_token() as token:
        out, failed = agent.call(engine, token, "formcad_save_document", {"document": doc.id, "path": str(target)})
        sneaky, sneaky_failed = agent.call(engine, token, "formcad_save_document", {"document": doc.id, "path": str(granted / ".." / "sneaky.fcad")})
    assert failed and OUTSIDE in out["error"] and not target.exists()
    assert sneaky_failed and OUTSIDE in sneaky["error"] and not (tmp_path / "sneaky.fcad").exists()


def test_an_agent_opens_and_saves_inside_a_granted_folder(engine, docs, fixtures, tmp_path, data_dir):
    source = tmp_path / "basic.fcad"
    shutil.copy(fixtures / "doc-basic.fcad", source)
    target = tmp_path / "copy.fcad"
    with agent.granted_folders(data_dir, [tmp_path]), agent.tab_token() as token:
        opened, failed = agent.call(engine, token, "formcad_open_document", {"path": str(source)})
        assert not failed and opened["entities"] == 11
        try:
            saved, save_failed = agent.call(engine, token, "formcad_save_document", {"document": opened["id"], "path": str(target)})
            assert not save_failed
        finally:
            engine.raw("POST", "/api/docs/%s/close" % opened["id"], json={"force": True})
    assert docs.open(target).summary["entities"] == 11


def test_the_event_stream_refuses_a_socket_without_the_key(engine):
    with pytest.raises(WebSocketDisconnect) as refused:
        with engine.client.websocket_connect("/api/events", headers=LOCAL) as socket:
            socket.receive_text()
    assert refused.value.code == 4401


def test_the_event_stream_with_the_key_announces_a_new_document(engine, docs):
    with engine.client.websocket_connect("/api/events?token=" + engine.token, headers=LOCAL) as socket:
        made = docs()
        for _ in range(20):
            message = socket.receive_json()
            if message.get("type") == "docs" and message.get("id") == made.id:
                break
        assert message["reason"] == "open" and message["id"] == made.id
