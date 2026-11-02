import fnmatch

TABLE = "groups"
MAX_GROUPS = 100000
BAD_CHARS = set('<>/\\":;?*|,=`')


def valid_name(name) -> bool:
    if not isinstance(name, str) or not name or len(name) > 255:
        return False
    if name.startswith("*"):
        return False
    return not any(ch in BAD_CHARS or ord(ch) < 32 or ord(ch) == 127 for ch in name)


def all_groups(d) -> list:
    return sorted(d.tables[TABLE].values(), key=lambda g: g.get("serial", 0))


def find(d, name):
    if name is None:
        return None
    return d.table_get(TABLE, str(name))


def next_unnamed(d) -> str:
    n = 1
    while d.tables[TABLE].has("*A%d" % n):
        n += 1
    return "*A%d" % n


def next_serial(d) -> int:
    return max([g.get("serial", 0) for g in d.tables[TABLE].values()], default=0) + 1


def create(d, members, name=None, description="", selectable=True) -> dict:
    if len(d.tables[TABLE]) >= MAX_GROUPS:
        raise ValueError("Too many groups.")
    unnamed = name is None or name == ""
    if unnamed:
        name = next_unnamed(d)
    elif not valid_name(name):
        raise ValueError("%s is not a valid group name." % name)
    elif d.tables[TABLE].has(name):
        raise ValueError('A group named %s already exists.' % name)
    seen = []
    for h in members:
        if h not in seen and h in d.ents:
            seen.append(h)
    rec = {"name": name, "description": description or "", "selectable": bool(selectable), "unnamed": unnamed, "members": seen, "serial": next_serial(d)}
    d.table_set(TABLE, rec)
    return rec


def remove(d, name) -> None:
    d.table_remove(TABLE, name)


def groups_of(d, handle) -> list:
    return [g for g in all_groups(d) if handle in g["members"]]


def purge(d) -> int:
    if not len(d.tables[TABLE]):
        return 0
    n = 0
    for g in all_groups(d):
        keep = []
        for h in g["members"]:
            e = d.ents.get(h)
            if e is not None and not e.owner.startswith("block:"):
                keep.append(h)
        if len(keep) == len(g["members"]):
            continue
        n += 1
        if not keep:
            d.table_remove(TABLE, g["name"])
        else:
            rec = d.modify_record(TABLE, g["name"])
            rec["members"] = keep
    return n


def expand(d, handles, visible) -> list:
    if not len(d.tables[TABLE]):
        return list(handles)
    out = list(handles)
    seen = set(out)
    for g in all_groups(d):
        if not g.get("selectable", True):
            continue
        if not any(h in seen for h in g["members"]):
            continue
        for h in g["members"]:
            if h in visible and h not in seen:
                seen.add(h)
                out.append(h)
    return out


def expand_hatch(d, handles, visible) -> list:
    out = list(handles)
    seen = set(out)
    for h in list(out):
        e = d.ents.get(h)
        if e is None or e.kind != "hatch" or not e.associative:
            continue
        for loop in e.loops:
            for s in loop.get("sources", ()) or ():
                if s in visible and s not in seen:
                    seen.add(s)
                    out.append(s)
    return out


def match(d, pattern) -> list:
    pats = [p.strip() for p in str(pattern or "*").split(",") if p.strip()] or ["*"]
    out = []
    for g in all_groups(d):
        if any(fnmatch.fnmatchcase(g["name"].casefold(), p.casefold()) for p in pats):
            out.append(g)
    return out


def summary(g) -> dict:
    return {"name": g["name"], "description": g["description"], "selectable": bool(g.get("selectable", True)), "unnamed": bool(g.get("unnamed", False)), "members": list(g["members"])}
