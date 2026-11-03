import copy
import re

HEADER = "DOCPROPS"
STANDARD = ("part_number", "description", "material", "revision", "title", "author", "vendor", "note")
MAX_KEYS = 100
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
VALUE_MAX = 512


class PropError(ValueError):
    pass


def get(d) -> dict:
    raw = d.header.get(HEADER)
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def key_of(name) -> str:
    k = re.sub(r"[\s\-]+", "_", str(name or "").strip().lower())
    if not KEY_RE.match(k):
        raise PropError("A property name starts with a letter and holds letters, digits and underscores (up to 64).")
    return k


def clean_value(value) -> str:
    s = re.sub(r"[\x00-\x08\x0b-\x1f]", " ", str(value if value is not None else "")).strip()
    if len(s) > VALUE_MAX:
        raise PropError("A property value is limited to %d characters." % VALUE_MAX)
    return s


def put(d, values: dict, remove=()) -> dict:
    cur = get(d)
    for k, v in (values or {}).items():
        cur[key_of(k)] = clean_value(v)
    for k in remove or ():
        cur.pop(key_of(k), None)
    if len(cur) > MAX_KEYS:
        raise PropError("A document holds at most %d properties." % MAX_KEYS)
    d.set_header(HEADER, copy.deepcopy(cur))
    return cur
