import copy
import math
import re

TABLE = "sim"
KINDS = ("study", "material", "load", "fixture", "contact", "mesh_control", "result")
EDITABLE = ("study", "material", "load", "fixture", "contact", "mesh_control")
PREFIX = {"study": "S", "material": "M", "load": "L", "fixture": "X", "contact": "C", "mesh_control": "H", "result": "R"}
LOAD_TYPES = ("force", "pressure", "traction", "gravity", "heat_flux", "convection", "heat_load", "temperature_field", "reference_load", "flow_inlet", "flow_outlet", "injection_gate")
FIXTURE_TYPES = ("fixed", "roller", "symmetry", "displacement", "temperature")
CONTACT_TYPES = ("bonded", "frictionless", "frictional")
MATERIAL_FIELDS = ("rho", "E", "nu", "sigma_y", "sigma_u", "k", "alpha", "cp")
SELECTOR_KEYS = ("faces", "box", "plane", "point", "all")
MAX_RECORDS = 2000
MAX_NAME = 120


class SimRecordError(ValueError):
    pass


def all_rows(d) -> list:
    tbl = d.tables.get(TABLE)
    return list(tbl.values()) if tbl is not None else []


def of_kind(d, kind: str) -> list:
    return [copy.deepcopy(r) for r in all_rows(d) if r.get("kind") == kind]


def get(d, rid: str, kind: str | None = None):
    tbl = d.tables.get(TABLE)
    row = tbl.get(str(rid)) if tbl is not None else None
    if row is None or (kind and row.get("kind") != kind):
        return None
    return copy.deepcopy(row)


def need(d, rid, kind: str) -> dict:
    row = get(d, rid, kind)
    if row is None:
        raise SimRecordError("There is no %s %s." % (kind.replace("_", " "), rid))
    return row


def next_id(d, kind: str) -> str:
    taken = {r.get("id") for r in all_rows(d)}
    top = 0
    pat = re.compile(r"^%s(\d+)$" % PREFIX[kind])
    for t in taken:
        m = pat.match(str(t))
        if m:
            top = max(top, int(m.group(1)))
    return "%s%d" % (PREFIX[kind], top + 1)


def num(v, name, positive=False, minimum=None):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise SimRecordError("%s must be a number." % name)
    if not math.isfinite(x):
        raise SimRecordError("%s must be a finite number." % name)
    if positive and not x > 0:
        raise SimRecordError("%s must be greater than zero." % name)
    if minimum is not None and x < minimum:
        raise SimRecordError("%s must be at least %g." % (name, minimum))
    return x


def vec3(v, name):
    if not isinstance(v, (list, tuple)) or len(v) != 3:
        raise SimRecordError("%s needs three numbers." % name)
    return [num(x, name) for x in v]


def selector(sel, name="select"):
    if not isinstance(sel, dict) or not any(k in sel for k in SELECTOR_KEYS):
        raise SimRecordError("A face selector needs one of: %s." % ", ".join(SELECTOR_KEYS))
    out = {}
    if "faces" in sel:
        faces = sel["faces"]
        if not isinstance(faces, list) or not faces or len(faces) > 4096:
            raise SimRecordError("The selector faces is a list of face numbers.")
        out["faces"] = [int(i) for i in faces]
    if "box" in sel:
        b = sel["box"]
        if not isinstance(b, list) or len(b) != 2:
            raise SimRecordError("The selector box is two corners.")
        out["box"] = [vec3(b[0], "box"), vec3(b[1], "box")]
    if "plane" in sel:
        p = sel["plane"]
        if not isinstance(p, dict) or str(p.get("axis", "")).lower() not in ("x", "y", "z"):
            raise SimRecordError("The selector plane needs an axis x, y or z and a value.")
        out["plane"] = {"axis": str(p["axis"]).lower(), "value": num(p.get("value", 0.0), "plane value")}
        if "tol" in p:
            out["plane"]["tol"] = num(p["tol"], "tolerance", True)
    if "point" in sel:
        out["point"] = vec3(sel["point"], "point")
    if sel.get("all"):
        out["all"] = True
    if "tol" in sel:
        out["tol"] = num(sel["tol"], "tolerance", True)
    return out


def clean_load(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in raw.items() if k not in ("kind", "id", "name")})
    kind = str(row.get("type") or "")
    if kind not in LOAD_TYPES:
        raise SimRecordError("A load type is one of: %s." % ", ".join(LOAD_TYPES))
    out = {"type": kind}
    needs_face = kind not in ("gravity", "temperature_field") and not (kind == "heat_load" and not row.get("select"))
    if needs_face:
        out["select"] = selector(row.get("select"))
    elif row.get("select"):
        out["select"] = selector(row.get("select"))
    if kind in ("force", "reference_load"):
        out["value"] = num(row.get("value"), "The force")
        out["direction"] = vec3(row.get("direction", [0, 0, -1]), "The direction")
    elif kind == "pressure":
        out["value"] = num(row.get("value"), "The pressure")
    elif kind == "traction":
        out["vector"] = vec3(row.get("vector") or row.get("direction"), "The traction vector")
    elif kind == "gravity":
        out["value"] = num(row.get("value", 9.81), "The gravity", True)
        out["direction"] = vec3(row.get("direction", [0, 0, -1]), "The direction")
    elif kind == "heat_flux":
        out["value"] = num(row.get("value"), "The heat flux")
    elif kind == "convection":
        out["h"] = num(row.get("h"), "The film coefficient", True)
        out["t_inf"] = num(row.get("t_inf", 293.15), "The ambient temperature", True)
    elif kind == "heat_load":
        out["value"] = num(row.get("value"), "The heat load")
    elif kind == "temperature_field":
        out["value"] = num(row.get("value"), "The temperature", True)
    elif kind == "flow_inlet":
        if (row.get("speed") in (None, "")) == (row.get("flow") in (None, "")):
            raise SimRecordError("A flow inlet needs either the mean speed (m/s) or the volume flow (m3/s).")
        for key in ("speed", "flow"):
            if row.get(key) not in (None, ""):
                out[key] = num(row.get(key), "The inlet " + key, True)
    elif kind == "flow_outlet":
        out["value"] = num(row.get("value", 0.0), "The outlet pressure")
    return out


def clean_fixture(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in raw.items() if k not in ("kind", "id", "name")})
    kind = str(row.get("type") or "")
    if kind not in FIXTURE_TYPES:
        raise SimRecordError("A fixture type is one of: %s." % ", ".join(FIXTURE_TYPES))
    out = {"type": kind, "select": selector(row.get("select"))}
    if kind == "roller":
        axes = row.get("axes")
        if not isinstance(axes, list) or not axes or any(int(a) not in (0, 1, 2) for a in axes):
            raise SimRecordError("A roller needs the axes it may slide along, 0, 1 or 2.")
        out["axes"] = sorted({int(a) for a in axes})
    elif kind == "symmetry":
        axis = int(row.get("axis", 0))
        if axis not in (0, 1, 2):
            raise SimRecordError("The symmetry axis is 0, 1 or 2.")
        out["axis"] = axis
    elif kind == "displacement":
        out["components"] = [1 if c else 0 for c in (row.get("components") or [1, 1, 1])][:3]
        out["value"] = vec3(row.get("value", [0, 0, 0]), "The displacement")
    elif kind == "temperature":
        out["value"] = num(row.get("value"), "The temperature", True)
    return out


def clean_contact(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in raw.items() if k not in ("kind", "id", "name")})
    kind = str(row.get("type") or "")
    if kind not in CONTACT_TYPES:
        raise SimRecordError("A contact type is one of: %s." % ", ".join(CONTACT_TYPES))
    out = {"type": kind, "a": selector(row.get("a"), "a"), "b": selector(row.get("b"), "b")}
    if kind == "frictional":
        out["friction"] = num(row.get("friction", 0.2), "The friction coefficient", minimum=0.0)
    return out


def clean_control(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in raw.items() if k not in ("kind", "id", "name")})
    return {"select": selector(row.get("select")), "maxh_mm": num(row.get("maxh_mm"), "The element size", True)}


def clean_material(raw: dict, base=None) -> dict:
    row = dict(base or {})
    row.update({k: v for k, v in raw.items() if k not in ("kind", "id", "name")})
    out = {"library": row.get("library") or None, "notes": str(row.get("notes") or "")[:2000]}
    for key in MATERIAL_FIELDS:
        v = row.get(key)
        out[key] = None if v in (None, "") else num(v, key, True)
    if out["nu"] is not None and not 0 < out["nu"] < 0.5:
        raise SimRecordError("Poisson's ratio must be between 0 and 0.5.")
    srcs = row.get("sources") or []
    if not isinstance(srcs, list) or len(srcs) > 64:
        raise SimRecordError("Sources are a list of at most 64 entries.")
    out["sources"] = [{k: str(s.get(k, ""))[:500] for k in ("field", "org", "title", "url", "note")} | ({"value": s["value"]} if "value" in s else {}) for s in srcs if isinstance(s, dict)]
    filled = [k for k in MATERIAL_FIELDS if out[k] is not None]
    cited = {s.get("field") for s in out["sources"]}
    out["uncited"] = [k for k in filled if k not in cited and "all" not in cited]
    return out


def clean_study(d, raw: dict, base=None) -> dict:
    from app.sim import registry

    row = dict(base or {})
    row.update({k: v for k, v in raw.items() if k not in ("kind", "id", "name")})
    kind = str(row.get("type") or "")
    registry.get(kind)
    geo = row.get("geometry") or {}
    if not isinstance(geo, dict) or not isinstance(geo.get("body"), int) or isinstance(geo.get("body"), bool):
        raise SimRecordError("A study names the solid body it analyses: geometry is {\"body\": handle}.")
    out = {"type": kind, "geometry": {"body": int(geo["body"])}}
    for field, rkind in (("loads", "load"), ("fixtures", "fixture"), ("contacts", "contact")):
        ids = row.get(field) or []
        if not isinstance(ids, list) or len(ids) > 256:
            raise SimRecordError("%s is a list of record numbers." % field.capitalize())
        for i in ids:
            need(d, i, rkind)
        out[field] = [str(i) for i in ids]
    if row.get("material"):
        need(d, row["material"], "material")
    out["material"] = str(row["material"]) if row.get("material") else None
    mesh = row.get("mesh") or {}
    ctr = mesh.get("controls") or []
    for i in ctr:
        need(d, i, "mesh_control")
    maxh = mesh.get("maxh_mm")
    out["mesh"] = {"maxh_mm": None if maxh in (None, "") else num(maxh, "The element size", True), "order": 2, "controls": [str(i) for i in ctr]}
    if mesh.get("order") not in (None, 2):
        raise SimRecordError("Structural studies use second-order elements (order 2); first-order tetrahedra lock in bending.")
    out["options"] = dict(row.get("options") or {})
    out["result"] = row.get("result") or None
    out["mesh_blob"] = row.get("mesh_blob") or None
    out["status"] = row.get("status") or "new"
    return out


def label_of(raw: dict, base, default: str) -> str:
    name = raw.get("name", (base or {}).get("name"))
    name = str(name if name not in (None, "") else default).strip()
    if not name or len(name) > MAX_NAME:
        raise SimRecordError("A name is 1 to %d characters." % MAX_NAME)
    return name


def create(d, kind: str, raw: dict) -> dict:
    if kind not in EDITABLE:
        raise SimRecordError("A record kind is one of: %s." % ", ".join(EDITABLE))
    if len(all_rows(d)) >= MAX_RECORDS:
        raise SimRecordError("The document holds the most simulation records it may (%d)." % MAX_RECORDS)
    rid = next_id(d, kind)
    if kind == "material":
        from app.sim import materials

        raw = materials.fill(raw)
    row = build(d, kind, raw, None)
    row.update({"id": rid, "name": rid, "kind": kind, "label": label_of(raw, None, rid)})
    d.table_set(TABLE, row)
    return copy.deepcopy(row)


def build(d, kind, raw, base):
    if kind == "study":
        return clean_study(d, raw, base)
    if kind == "material":
        return clean_material(raw, base)
    if kind == "load":
        return clean_load(raw, base)
    if kind == "fixture":
        return clean_fixture(raw, base)
    if kind == "contact":
        return clean_contact(raw, base)
    return clean_control(raw, base)


def update(d, rid: str, raw: dict) -> dict:
    base = get(d, rid)
    if base is None or base.get("kind") not in EDITABLE:
        raise SimRecordError("There is no editable simulation record %s." % rid)
    kind = base["kind"]
    row = build(d, kind, raw, base)
    row.update({"id": base["id"], "name": base["id"], "kind": kind, "label": label_of(raw, base, base["id"])})
    if kind != "study":
        mark_stale(d, rid)
    else:
        moved = changed(base, row)
        row["result"] = base.get("result")
        row["mesh_blob"] = None if moved else base.get("mesh_blob")
        row["status"] = "stale" if moved and base.get("result") else base.get("status", "new")
    d.table_set(TABLE, row)
    return copy.deepcopy(row)


def changed(a: dict, b: dict) -> bool:
    keys = ("type", "geometry", "material", "loads", "fixtures", "contacts", "mesh", "options")
    return any(a.get(k) != b.get(k) for k in keys)


def users_of(d, rid: str) -> list:
    out = []
    for r in all_rows(d):
        if r.get("kind") != "study":
            continue
        if rid in (r.get("loads") or []) or rid in (r.get("fixtures") or []) or rid in (r.get("contacts") or []) or rid == r.get("material") or rid in ((r.get("mesh") or {}).get("controls") or []):
            out.append(r["id"])
    return out


def mark_stale(d, rid: str) -> None:
    for sid in users_of(d, rid):
        row = get(d, sid)
        if row and row.get("result"):
            row["status"] = "stale"
            d.table_set(TABLE, row)


def remove(d, rid: str) -> dict:
    row = get(d, rid)
    if row is None:
        raise SimRecordError("There is no simulation record %s." % rid)
    if row["kind"] != "study":
        users = users_of(d, rid)
        if users:
            raise SimRecordError("%s is used by %s; remove it from the study first." % (rid, ", ".join(users)))
    else:
        for r in of_kind(d, "result"):
            if r.get("study") == rid:
                d.table_remove(TABLE, r["id"])
    d.table_remove(TABLE, rid)
    return row


def put_result(d, row: dict) -> dict:
    rid = next_id(d, "result")
    out = dict(row)
    out.update({"id": rid, "name": rid, "kind": "result"})
    d.table_set(TABLE, out)
    return copy.deepcopy(out)


def blobs_in_use(d) -> set:
    out = set()
    for r in all_rows(d):
        for key in ("blob", "mesh_blob"):
            if r.get(key):
                out.add(str(r[key]))
    return out
