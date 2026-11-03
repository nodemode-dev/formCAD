import string

from app.schem import store
from app.schem.errors import SchemError

LETTERS = string.ascii_uppercase


def find(parent, a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


def nodes(d) -> list:
    wires = store.rows(d, "wire")
    parent = {}
    for w in wires:
        for end in ("from", "to"):
            k = (w[end]["device"], w[end]["pin"])
            parent.setdefault(k, k)
    for w in wires:
        a = find(parent, (w["from"]["device"], w["from"]["pin"]))
        b = find(parent, (w["to"]["device"], w["to"]["pin"]))
        if a != b:
            parent[a] = b
    groups = {}
    for k in parent:
        groups.setdefault(find(parent, k), []).append(k)
    by_root = {}
    for w in wires:
        root = find(parent, (w["from"]["device"], w["from"]["pin"]))
        by_root.setdefault(root, []).append(w)
    out = []
    for root, ws in by_root.items():
        ws.sort(key=lambda w: (len(w["id"]), w["id"]))
        out.append({"pins": sorted("%s:%s" % p for p in groups[root]), "wires": [w["id"] for w in ws], "sheet": min(w["sheet"] for w in ws), "_w": ws})
    out.sort(key=lambda n: (n["sheet"], len(n["wires"][0]), n["wires"][0]))
    for i, n in enumerate(out):
        n["node"] = i + 1
    return out


def render(template: str, prefix: str, sheet: int, seq: int, first: dict, refs: dict) -> str:
    def sub(m):
        tok, width = m.group(1), m.group(2)
        if tok == "prefix":
            v = prefix
        elif tok == "sheet":
            v = str(sheet).zfill(int(width or 0))
        elif tok == "seq":
            v = str(seq).zfill(int(width or 0))
        elif tok == "class":
            v = first.get("signal_class", "")
        elif tok == "net":
            v = first.get("net", "")
        elif tok == "from":
            v = refs.get(first["from"]["device"], "") + first["from"]["pin"]
        else:
            v = refs.get(first["to"]["device"], "") + first["to"]["pin"]
        return v

    return store.TOKEN.sub(sub, template)


def renumber(d, template=None, prefix=None, keep_manual=True) -> dict:
    cfg = store.settings(d)
    if template is not None or prefix is not None:
        cfg = store.save_settings(d, {"template": template if template is not None else cfg["template"], "prefix": prefix if prefix is not None else cfg["prefix"]})
    tmpl, pre = cfg["template"], cfg["prefix"]
    refs = {r["id"]: r["refdes"] for r in store.rows(d, "device")}
    groups = nodes(d)
    used = {}
    conflicts = []
    if keep_manual:
        for n in groups:
            manual = [w["number"] for w in n["_w"] if w.get("manual") and w.get("number")]
            if len(set(manual)) > 1:
                conflicts.append({"node": n["node"], "wires": n["wires"], "numbers": sorted(set(manual)), "message": "Wires in one node carry different manual numbers; the first is used."})
            n["manual_number"] = manual[0] if manual else None
            if manual:
                used[manual[0]] = n["node"]
    has_seq = "{seq" in tmpl
    counters = {}
    plan = {}
    for n in groups:
        if n.get("manual_number"):
            plan[n["node"]] = n["manual_number"]
            continue
        s = n["sheet"]
        while True:
            counters[s] = counters.get(s, 0) + 1
            num = render(tmpl, pre, s, counters[s], n["_w"][0], refs)
            if num not in used:
                break
            if not has_seq:
                raise SchemError("The template gives %s to more than one node; add {seq} so every node gets its own number." % num)
        used[num] = n["node"]
        plan[n["node"]] = num
    names_taken = {w["wire"].casefold() for w in store.rows(d, "wire") if w["wire"] and not w.get("name_auto")}
    changed = 0
    out = []
    for n in groups:
        num = plan[n["node"]]
        for k, w in enumerate(n["_w"]):
            row = d.modify_record(store.TABLE, w["id"])
            if row.get("number") != num or (row.get("manual") and not keep_manual):
                changed += 1
            row["number"] = num
            if not keep_manual:
                row["manual"] = False
            if row.get("name_auto") or not row.get("wire"):
                base = num if len(n["wires"]) == 1 else num + (LETTERS[k] if k < 26 else str(k))
                nm = base
                j = 0
                while nm.casefold() in names_taken:
                    j += 1
                    nm = "%s_%d" % (base, j)
                names_taken.add(nm.casefold())
                row["wire"] = nm
                row["name_auto"] = True
            out.append({"wire": w["id"], "name": row["wire"], "number": num, "node": n["node"]})
    return {"template": tmpl, "prefix": pre, "nodes": len(groups), "wires": len(out), "changed": changed, "conflicts": conflicts, "rows": out}


def check_numbers(d) -> list:
    problems = []
    seen = {}
    for n in nodes(d):
        nums = {w["number"] for w in n["_w"] if w.get("number")}
        if len(nums) > 1:
            problems.append({"code": "node_numbers", "message": "Wires %s are one electrical node but carry the numbers %s." % (", ".join(n["wires"]), ", ".join(sorted(nums)))})
        for num in nums:
            if num in seen and seen[num] != n["node"]:
                problems.append({"code": "duplicate_number", "message": "The number %s is on more than one node." % num})
            seen[num] = n["node"]
        if any(not w.get("number") for w in n["_w"]):
            problems.append({"code": "unnumbered", "message": "Wires %s have no number yet; run the numbering." % ", ".join(w["id"] for w in n["_w"] if not w.get("number"))})
    return problems
