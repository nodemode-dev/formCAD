import json

from app.display.resolve import Context
from app.display.state import session_values, space_key, state_for


class NoSuchSpace(Exception):
    pass


def _flag(v):
    return "true" if v else "false"


def build(doc, since=None, space="model"):
    key = space_key(doc, space)
    if key is None:
        raise NoSuchSpace(str(space))
    state = state_for(doc, key)
    state.update(doc)
    full, items, removed = state.collect(doc, None if since is None else int(since))
    ctx = Context(doc, session_values())
    layers = json.dumps(ctx.layer_summary(), separators=(",", ":"), ensure_ascii=False)
    ext = json.dumps(state.ext) if state.ext else "null"
    shown = key.split(":", 1)[1] if ":" in key else "model"
    trd = session_values_flag("TRANSPARENCYDISPLAY")
    head = '{"rev":%d,"full":%s,"space":%s,"removed":%s,"items":[' % (doc.rev, _flag(full), json.dumps(shown), json.dumps(removed))
    tail = '],"layers":%s,"extents":%s,"lwdisplay":%s,"trdisplay":%s}' % (layers, ext, _flag(ctx.lwdisplay), _flag(trd))
    return (head + ",".join(items) + tail).encode("utf-8")


def session_values_flag(name):
    try:
        from app.sysvars import registry as sv

        return bool(sv.session_value(name))
    except Exception:
        return True


def build_items(doc, since=None, space="model"):
    return json.loads(build(doc, since, space))
