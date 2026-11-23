HOST = "http://127.0.0.1:8290"
HEADER = "X-FormCAD-Token"


class Refused(AssertionError):
    def __init__(self, method: str, path: str, status: int, body: str) -> None:
        super().__init__("%s %s answered %d: %s" % (method, path, status, body[:600]))
        self.status = status
        self.body = body


class Engine:
    def __init__(self, client, token: str) -> None:
        self.client = client
        self.token = token

    def raw(self, method: str, path: str, token: str | None = "", **kw):
        headers = dict(kw.pop("headers", None) or {})
        given = self.token if token == "" else token
        if given is not None:
            headers[HEADER] = given
        return self.client.request(method, path, headers=headers, **kw)

    def call(self, method: str, path: str, **kw):
        r = self.raw(method, path, **kw)
        if r.status_code >= 400:
            raise Refused(method, path, r.status_code, r.text)
        kind = r.headers.get("content-type", "")
        return r.json() if kind.startswith("application/json") else r

    def get(self, path: str, **params):
        return self.call("GET", path, params=params or None)

    def post(self, path: str, body=None):
        return self.call("POST", path, json=body if body is not None else {})

    def put(self, path: str, body=None):
        return self.call("PUT", path, json=body if body is not None else {})

    def patch(self, path: str, body=None):
        return self.call("PATCH", path, json=body if body is not None else {})

    def delete(self, path: str):
        return self.call("DELETE", path)

    def status_of(self, method: str, path: str, **kw) -> int:
        return self.raw(method, path, **kw).status_code

    def new_doc(self, name: str = "", template: str = "") -> "Doc":
        return Doc(self, self.post("/api/docs", {"name": name, "template": template}))

    def open_doc(self, path) -> "Doc":
        return Doc(self, self.post("/api/docs/open", {"path": str(path)}))

    def docs(self) -> list:
        return self.get("/api/docs")["docs"]


class Doc:
    def __init__(self, engine: Engine, summary: dict) -> None:
        self.engine = engine
        self.summary = summary
        self.id = summary["id"]
        self.last: dict = {}

    def url(self, tail: str = "") -> str:
        return "/api/docs/%s%s" % (self.id, tail)

    def get(self, tail: str, **params):
        return self.engine.get(self.url(tail), **params)

    def post(self, tail: str, body=None):
        return self.engine.post(self.url(tail), body)

    def put(self, tail: str, body=None):
        return self.engine.put(self.url(tail), body)

    def patch(self, tail: str, body=None):
        return self.engine.patch(self.url(tail), body)

    def delete(self, tail: str):
        return self.engine.delete(self.url(tail))

    def type(self, *lines: str) -> dict:
        for line in lines:
            self.last = self.post("/input", {"text": line})
        return self.last

    def enter(self) -> dict:
        return self.type("")

    def point(self, x: float, y: float, z: float | None = None, snap: dict | None = None) -> dict:
        pt = [x, y] if z is None else [x, y, z]
        self.last = self.post("/input", {"point": pt, "snap": snap})
        return self.last

    def pick(self, **pick) -> dict:
        self.last = self.post("/input", {"pick": pick})
        return self.last

    def select(self, **selection) -> dict:
        self.last = self.post("/input", {"selection": selection})
        return self.last

    def command(self, name: str, /, **args) -> dict:
        self.last = self.post("/command", {"command": name, "args": args or None})
        return self.last

    def run(self, name: str, /, *inputs) -> dict:
        self.last = self.post("/command", {"command": name, "args": {"inputs": [str(i) for i in inputs]}})
        return self.last

    def cancel(self) -> dict:
        self.last = self.post("/cancel")
        return self.last

    def state(self) -> dict:
        return self.get("/state")

    def idle(self) -> bool:
        return not self.state()["active"]

    def error(self) -> str:
        return self.last.get("error") or ""

    def output(self) -> list:
        return list(self.last.get("output") or [])

    def snapshot(self, since: int = 0) -> dict:
        return self.get("/snapshot", since=since)

    def entities(self, kind: str | None = None) -> list:
        found = self.snapshot()["entities"]
        return [e for e in found if kind is None or e.get("kind") == kind]

    def only(self, kind: str | None = None) -> dict:
        found = self.entities(kind)
        assert len(found) == 1, "expected one %s, found %d" % (kind or "entity", len(found))
        return found[0]

    def kinds(self) -> dict:
        out: dict = {}
        for e in self.entities():
            out[e.get("kind")] = out.get(e.get("kind"), 0) + 1
        return out

    def handles(self) -> list:
        return [e.get("handle") for e in self.entities()]

    def rev(self) -> int:
        return self.snapshot()["rev"]

    def undo(self, steps: int = 1) -> dict:
        return self.post("/undo", {"steps": steps})

    def redo(self, steps: int = 1) -> dict:
        return self.post("/redo", {"steps": steps})

    def save(self, path=None) -> dict:
        return self.post("/save", {"path": str(path)} if path else {})

    def close(self, force: bool = True) -> dict:
        return self.post("/close", {"force": force})

    def var(self, name: str):
        return self.get("/variable/%s" % name)["value"]

    def set_var(self, name: str, value):
        return self.post("/variable/%s" % name, {"value": value})["value"]
