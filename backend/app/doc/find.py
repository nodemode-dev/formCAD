import re


class FindError(Exception):
    pass


def _attr_slots(e):
    out = []
    for a in getattr(e, "attributes", None) or []:
        if isinstance(a, dict) and isinstance(a.get("value"), str):
            out.append((lambda a=a: a["value"], lambda v, a=a: a.__setitem__("value", v)))
    return out


def _table_slots(e):
    out = []
    for row in getattr(e, "cells", None) or []:
        cells = row if isinstance(row, list) else [row]
        for c in cells:
            if isinstance(c, dict):
                for key in ("text", "value", "contents"):
                    if isinstance(c.get(key), str):
                        out.append((lambda c=c, key=key: c[key], lambda v, c=c, key=key: c.__setitem__(key, v)))
                        break
    return out


def slots(e) -> list:
    k = e.kind
    if k == "text":
        return [(lambda: e.text, lambda v: setattr(e, "text", v))]
    if k == "mtext":
        return [(lambda: e.contents, lambda v: setattr(e, "contents", v))]
    if k == "insert":
        return _attr_slots(e)
    if k == "dimension":
        return [(lambda: e.text_override, lambda v: setattr(e, "text_override", v))] if e.text_override else []
    if k == "mleader":
        for name in ("contents", "text"):
            if isinstance(getattr(e, name, None), str):
                return [(lambda n=name: getattr(e, n), lambda v, n=name: setattr(e, n, v))]
        return []
    if k == "table":
        return _table_slots(e)
    return []


def pattern(text, match_case=False, whole_word=False):
    if not isinstance(text, str) or text == "":
        raise FindError("Enter text to find.")
    body = re.escape(text)
    if whole_word:
        body = r"(?<!\w)" + body + r"(?!\w)"
    return re.compile(body, 0 if match_case else re.IGNORECASE)


def scan(d, space, rx):
    out = []
    for e in d.entities(space):
        if not d.visible(e):
            continue
        hits = 0
        for get, _set in slots(e):
            hits += len(rx.findall(get()))
        if hits:
            out.append({"handle": e.handle, "kind": e.kind, "hits": hits})
    return out


def replace(d, space, rx, new):
    changed = 0
    locked = 0
    total = 0
    rows = []
    for row in scan(d, space, rx):
        e = d.get(row["handle"])
        if d.layer_locked(e.layer):
            locked += 1
            continue
        live = d.modify(e.handle)
        for get, put in slots(live):
            value = get()
            fresh, n = rx.subn(lambda m: new, value)
            if n:
                put(fresh)
                total += n
        changed += 1
        rows.append(row)
    return {"matches": rows, "replaced": changed, "hits": total, "locked": locked}
