import json
import os
import urllib.error
import urllib.request

API_VERSION = 1
URL = os.environ.get("FORMCAD_URL", "").rstrip("/")
TOKEN = os.environ.get("FORMCAD_TOKEN", "")
TIMEOUT = float(os.environ.get("FORMCAD_CALL_TIMEOUT", "60") or 60)
raise_on_error = True


class FormCADError(Exception):
    pass


def _call(method, path, body=None, raw=False):
    if not URL or not TOKEN:
        raise FormCADError("This script is not connected to FormCAD. Run it from FormCAD, or with formcad-engine run --python-macro FILE.")
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(URL + path, data=data, method=method)
    req.add_header("X-FormCAD-Token", TOKEN)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            payload = res.read()
    except urllib.error.HTTPError as err:
        if err.code == 401:
            raise FormCADError("FormCAD does not let a macro call %s. Macros draw and edit; saving, opening, exporting, printing and settings are done from the FormCAD window." % path.split("?")[0])
        text = err.read().decode("utf-8", "replace")
        try:
            text = json.loads(text).get("detail", text)
        except ValueError:
            pass
        raise FormCADError(str(text))
    except OSError as err:
        raise FormCADError("FormCAD did not answer: %s" % err)
    if raw:
        return payload
    return json.loads(payload.decode("utf-8")) if payload else {}


class State(dict):
    @property
    def ok(self):
        return not self.get("error")

    @property
    def output(self):
        return list(self.get("output", []))

    @property
    def result(self):
        return self.get("result")


def _checked(state):
    state = State(state)
    if raise_on_error and state.get("error"):
        raise FormCADError(state["error"])
    return state


def _pt(p):
    return [float(p[0]), float(p[1])] + ([float(p[2])] if len(p) > 2 else [])


class Document:
    def __init__(self, info):
        self.info = dict(info)
        self.id = info["id"]

    @property
    def name(self):
        return self.info.get("name", "")

    def __repr__(self):
        return "<formcad.Document %s %r>" % (self.id, self.name)

    def _path(self, tail=""):
        return "/api/docs/%s%s" % (self.id, tail)

    def refresh(self):
        self.info = _call("GET", self._path())
        return self.info

    def send(self, text):
        return _checked(_call("POST", self._path("/input"), {"text": str(text)}))

    def point(self, x, y):
        return _checked(_call("POST", self._path("/input"), {"point": [float(x), float(y)]}))

    def state(self):
        return State(_call("GET", self._path("/state")))

    def cancel(self):
        return State(_call("POST", self._path("/cancel")))

    def command(self, name, **args):
        state = _checked(_call("POST", self._path("/command"), {"command": name, "args": args}))
        return state.get("result") if state.get("result") is not None else {}

    def script(self, text):
        state = _checked(self.command_state("script", data=str(text)))
        return state

    def command_state(self, name, **args):
        return State(_call("POST", self._path("/command"), {"command": name, "args": args}))

    def line(self, *points, closed=False):
        return self.command("line", points=[_pt(p) for p in points], closed=closed).get("handles", [])

    def circle(self, center, radius):
        return self.command("circle", center=_pt(center), radius=float(radius)).get("handle")

    def arc(self, p1, p2, p3):
        return self.command("arc", points=[_pt(p1), _pt(p2), _pt(p3)]).get("handle")

    def rectangle(self, corner1, corner2):
        return self.command("rectang", p1=_pt(corner1), p2=_pt(corner2)).get("handle")

    def polyline(self, *points):
        return self.command("pline", vertices=[_pt(p) for p in points]).get("handle")

    def move(self, handles, delta):
        return self.command("move", handles=list(handles), delta=_pt(delta))

    def copy(self, handles, delta):
        return self.command("copy", handles=list(handles), delta=_pt(delta))

    def rotate(self, handles, base, angle):
        return self.command("rotate", handles=list(handles), base=_pt(base), angle=float(angle))

    def scale(self, handles, base, factor):
        return self.command("scale", handles=list(handles), base=_pt(base), factor=float(factor))

    def erase(self, handles):
        return self.command("erase", handles=list(handles))

    def entities(self, kind=None, layer=None, selected=False, window=None, crossing=True, limit=500, offset=0):
        q = ["limit=%d" % limit, "offset=%d" % offset]
        if kind:
            q.append("kind=" + urllib.request.quote(str(kind)))
        if layer:
            q.append("layer=" + urllib.request.quote(str(layer)))
        if selected:
            q.append("selected=true")
        if window:
            q.append("window=" + ",".join("%.12g" % float(v) for v in window))
            q.append("crossing=%s" % ("true" if crossing else "false"))
        return _call("GET", self._path("/entities?" + "&".join(q)))["entities"]

    def entity(self, handle):
        found = _call("GET", self._path("/entities?handle=%d" % int(handle)))["entities"]
        if not found:
            raise FormCADError("No object with handle %s." % handle)
        return found[0]

    def select(self, handles, mode="set"):
        return _call("PUT", self._path("/selection"), {"handles": [int(h) for h in handles], "mode": mode})["handles"]

    def selection(self):
        return _call("GET", self._path("/selection"))["handles"]

    def variable(self, name):
        return _call("GET", self._path("/variable/" + urllib.request.quote(str(name))))["value"]

    def set_variable(self, name, value):
        return _call("POST", self._path("/variable/" + urllib.request.quote(str(name))), {"value": value})["value"]

    def undo(self, steps=1):
        return _call("POST", self._path("/undo"), {"steps": int(steps)})

    def redo(self, steps=1):
        return _call("POST", self._path("/redo"), {"steps": int(steps)})

    def save(self, path=None):
        self.info = _call("POST", self._path("/save"), {"path": path} if path else {})
        return self.info

    def close(self, force=False):
        return _call("POST", self._path("/close"), {"force": bool(force)})

    def export(self, path, **options):
        return _call("POST", self._path("/automation/export"), {"path": path, **options})

    def render(self, window=None, size=1600):
        return _call("POST", self._path("/automation/render"), {"window": window, "size": size}, raw=True)

    def extents(self):
        return self.summary().get("extents")

    def summary(self):
        return _call("GET", self._path("/automation/summary"))


def documents():
    return _call("GET", "/api/docs")["docs"]


def active_document():
    listing = _call("GET", "/api/docs")
    wanted = os.environ.get("FORMCAD_DOC") or listing.get("active") or ""
    for info in listing["docs"]:
        if info["id"] == wanted:
            return Document(info)
    if listing["docs"]:
        return Document(listing["docs"][-1])
    return new_document()


def new_document(name=None, template=None):
    return Document(_call("POST", "/api/docs", {"name": name, "template": template}))


def open_document(path):
    return Document(_call("POST", "/api/docs/open", {"path": os.fspath(path)}))


def commands(filter=""):
    items = _call("GET", "/api/commands")["commands"]
    needle = str(filter).lower()
    return [c for c in items if not needle or needle in c["name"] or needle in c["label"].lower()]


def log(message):
    import sys

    sys.stderr.write(str(message) + "\n")
    sys.stderr.flush()
