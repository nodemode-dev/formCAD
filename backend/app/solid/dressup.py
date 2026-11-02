from app.solid import work

LONG = work.LONG

LENGTH_KEYS = ("radius", "radius1", "radius2", "distance", "distance2", "thickness", "tolerance", "spacing", "length")

SCHEMAS = {
    "fillet": {
        "method": "feature_fillet",
        "label": "Fillet",
        "refs": {"edges": "edge", "faces": "face"},
        "params": {
            "edges": {"type": "list", "item": "edge or {edge, radius | radius1 + radius2 | points}"},
            "faces": {"type": "list", "item": "face", "note": "every shared edge of these faces is rounded"},
            "radius": {"type": "length", "min": 0, "note": "default for entries without their own size"},
            "profile": {"type": "enum", "values": ["rational", "quasi_angular", "polynomial"], "default": "rational"},
        },
        "notes": ["Rounding follows tangent edges; the kernel has no switch to stop it.", "A face selection rounds its boundary; full round is not offered by the kernel."],
    },
    "chamfer": {
        "method": "feature_chamfer",
        "label": "Chamfer",
        "refs": {"edges": "edge", "faces": "face", "face": "face"},
        "params": {
            "edges": {"type": "list", "item": "edge or {edge, distance, distance2, angle, face}"},
            "faces": {"type": "list", "item": "face"},
            "distance": {"type": "length", "min": 0},
            "distance2": {"type": "length", "min": 0, "note": "second distance; with face"},
            "angle": {"type": "angle", "min": 0, "max": 90, "note": "degrees; distance and angle mode"},
            "face": {"type": "face", "note": "the face on which distance is measured"},
        },
    },
    "shell": {
        "method": "feature_shell",
        "label": "Shell",
        "refs": {"faces": "face"},
        "params": {
            "faces": {"type": "list", "item": "face to remove"},
            "thickness": {"type": "length", "min": 0, "required": True},
            "direction": {"type": "enum", "values": ["inward", "outward"], "default": "inward"},
            "join": {"type": "enum", "values": ["arc", "intersection"], "default": "arc"},
        },
    },
    "draft": {
        "method": "feature_draft",
        "label": "Draft",
        "refs": {"faces": "face"},
        "params": {
            "faces": {"type": "list", "item": "face", "required": True},
            "angle": {"type": "angle", "required": True, "note": "positive removes material on the pull side of the neutral plane"},
            "pull": {"type": "vector", "default": [0, 0, 1]},
            "neutral_plane": {"type": "plane", "note": "origin and normal, document units"},
            "allow_partial": {"type": "bool", "default": False},
        },
    },
    "pattern": {
        "method": "feature_pattern",
        "label": "Pattern",
        "refs": {},
        "params": {
            "pattern": {"type": "enum", "values": ["linear", "circular"], "required": True},
            "op": {"type": "enum", "values": ["fuse", "cut", "copies"], "default": "fuse"},
            "directions": {"type": "list", "item": "{vector, count, spacing | length}", "note": "linear: one or two"},
            "axis": {"type": "axis", "note": "circular: origin and direction"},
            "count": {"type": "int", "min": 1},
            "angle": {"type": "angle", "default": 360},
            "step": {"type": "angle"},
            "skip": {"type": "list", "item": "instance index"},
            "include_seed": {"type": "bool", "default": False},
        },
        "notes": ["Instance 0 is the seed in place and is expected to be in the body already."],
    },
    "mirror": {
        "method": "feature_mirror",
        "label": "Mirror",
        "refs": {},
        "params": {
            "mode": {"type": "enum", "values": ["feature", "body"], "default": "feature"},
            "plane": {"type": "plane", "required": True},
            "op": {"type": "enum", "values": ["fuse", "cut"], "default": "fuse"},
            "merge": {"type": "bool", "default": False},
        },
    },
}


class Unresolved(Exception):
    def __init__(self, message, lost=None):
        super().__init__(message)
        self.lost = list(lost or [])


def index_map(id_list) -> dict:
    return {int(pid): i for i, pid in enumerate(id_list)}


def to_indices(pids, id_list, label) -> list:
    table = index_map(id_list)
    out, lost = [], []
    for pid in pids or []:
        got = table.get(int(pid))
        if got is None:
            lost.append(int(pid))
        else:
            out.append(got)
    if lost:
        raise Unresolved("The %s reference(s) %s no longer exist in the body." % (label, ", ".join(map(str, lost))), lost)
    return out


def to_pids(indices, id_list) -> list:
    return [int(id_list[i]) for i in indices or [] if 0 <= i < len(id_list)]


def scale_vec(v, s):
    return [float(c) * s for c in v]


def metric(kind, params, s):
    out = dict(params)
    for key in LENGTH_KEYS:
        if out.get(key) is not None:
            out[key] = float(out[key]) * s
    if out.get("edges"):
        rows = []
        for item in out["edges"]:
            if isinstance(item, dict):
                row = dict(item)
                for key in LENGTH_KEYS:
                    if row.get(key) is not None:
                        row[key] = float(row[key]) * s
                if row.get("points"):
                    row["points"] = [[float(u), float(r) * s] for u, r in row["points"]]
                rows.append(row)
            else:
                rows.append(item)
        out["edges"] = rows
    if out.get("neutral_plane"):
        pl = dict(out["neutral_plane"])
        if pl.get("origin"):
            pl["origin"] = scale_vec(pl["origin"], s)
        out["neutral_plane"] = pl
    if out.get("plane"):
        pl = dict(out["plane"])
        if pl.get("origin"):
            pl["origin"] = scale_vec(pl["origin"], s)
        out["plane"] = pl
    if out.get("axis") and out["axis"].get("origin"):
        out["axis"] = {**out["axis"], "origin": scale_vec(out["axis"]["origin"], s)}
    if out.get("directions"):
        rows = []
        for d in out["directions"]:
            row = dict(d)
            for key in ("spacing", "length"):
                if row.get(key) is not None:
                    row[key] = float(row[key]) * s
            rows.append(row)
        out["directions"] = rows
    return out


def resolve_refs(params, face_ids, edge_ids):
    out = dict(params)
    if "faces" in out and out["faces"] is not None:
        out["faces"] = to_indices(out["faces"], face_ids, "face")
    if out.get("face") is not None:
        out["face"] = to_indices([out["face"]], face_ids, "face")[0]
    if out.get("edges"):
        rows = []
        for item in out["edges"]:
            if isinstance(item, dict):
                row = dict(item)
                row["edge"] = to_indices([row["edge"]], edge_ids, "edge")[0]
                if row.get("face") is not None:
                    row["face"] = to_indices([row["face"]], face_ids, "face")[0]
                rows.append(row)
            else:
                rows.append(to_indices([item], edge_ids, "edge")[0])
        out["edges"] = rows
    return out


def run(d, kind, params, wid, face_ids, edge_ids, seed_wid=None):
    schema = SCHEMAS[kind]
    s = work.mm(d)
    try:
        wp = metric(kind, resolve_refs(params, face_ids, edge_ids), s)
    except Unresolved as err:
        return {"ok": False, "message": str(err), "errors": [{"message": str(err), "lost": err.lost}], "warnings": [], "failed": {"edges": [], "faces": []}}
    wp["id"] = wid
    if seed_wid:
        wp["seed"] = seed_wid
    res = work.kcall(schema["method"], wp, LONG)
    failed = res.get("failed") or {}
    res["failed_ids"] = {"edges": to_pids(failed.get("edges"), edge_ids), "faces": to_pids(failed.get("faces"), face_ids)}
    return res


def precheck(d, kind, params, wid, face_ids, edge_ids):
    s = work.mm(d)
    wp = metric(kind, resolve_refs(params, face_ids, edge_ids), s)
    wp.update({"id": wid, "kind": kind})
    res = work.kcall("feature_precheck", wp, work.SHORT)
    for row in list(res.get("errors", [])) + list(res.get("warnings", [])):
        row["edge_ids"] = to_pids(row.get("edges"), edge_ids)
        row["face_ids"] = to_pids(row.get("faces"), face_ids)
    return res


def history_parts(res, sources):
    inputs = (res.get("history") or {}).get("inputs") or []
    return [(faces, edges, hist) for (faces, edges), hist in zip(sources, inputs)]
