import re

import pytest

from app.main import app


class Crash:
    def __init__(self, err):
        self.status_code = 500
        self.text = "%s: %s" % (type(err).__name__, err)


def _ask(engine, method, url, body=None):
    try:
        return engine.raw(method, url, json=body)
    except Exception as err:
        return Crash(err)


def _sweep(engine, route, body_for):
    names = [c["name"] for c in engine.get("/api/commands")["commands"]]
    assert len(names) >= 700
    before = {d["id"] for d in engine.docs()}
    doc = engine.new_doc()
    failures = []
    try:
        for name in names:
            reply = _ask(engine, "POST", doc.url(route), body_for(name))
            if reply.status_code == 404:
                doc = engine.new_doc()
                reply = _ask(engine, "POST", doc.url(route), body_for(name))
            if reply.status_code >= 500:
                failures.append((name, reply.status_code, reply.text[:200]))
            cancelled = _ask(engine, "POST", doc.url("/cancel"))
            if cancelled.status_code >= 500:
                failures.append((name, "cancel", cancelled.status_code, cancelled.text[:200]))
    finally:
        for d in engine.docs():
            if d["id"] not in before:
                engine.raw("POST", "/api/docs/%s/close" % d["id"], json={"force": True})
    return failures


@pytest.mark.parametrize("route", ["/command", "/input"])
def test_every_registered_command_started_and_cancelled_gives_no_server_error(engine, route):
    body = (lambda n: {"command": n, "args": None}) if route == "/command" else (lambda n: {"text": n})
    assert _sweep(engine, route, body) == []


def test_every_read_route_of_a_fresh_document_answers_without_a_server_error(engine, doc):
    paths = [p for p, ops in app.openapi()["paths"].items() if "get" in ops and re.findall(r"{(\w+)}", p) == ["doc_id"]]
    assert len(paths) >= 100
    failures = []
    for path in paths:
        reply = _ask(engine, "GET", path.replace("{doc_id}", doc.id))
        if reply.status_code >= 500:
            failures.append((path, reply.status_code, reply.text[:200]))
    assert failures == []
