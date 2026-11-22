import json
from pathlib import Path

from app.core import config
from app.part.registry import PartError

SHIPPED = Path(__file__).resolve().parents[1] / "data" / "hole-sizes.json"
USER_NAME = "hole-sizes.json"
MAX_FILE = 1024 * 1024
SECTIONS = ("thread_series", "clearance", "counterbore", "countersink", "tap_drill")
KINDS = ("simple", "counterbore", "countersink", "tapped")
FITS = ("fine", "medium", "coarse")
TIP_DEFAULT = 0.0
NUMBERS = {
    "thread_series": ("nominal", "pitch"),
    "clearance": ("fine", "medium", "coarse"),
    "counterbore": ("diameter", "depth"),
    "countersink": ("diameter", "angle"),
    "tap_drill": ("diameter",),
}


def read_json(path: Path) -> dict | None:
    try:
        if not path.is_file() or path.stat().st_size > MAX_FILE:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def user_path() -> Path:
    return config.data_dir() / USER_NAME


def valid_row(section: str, row) -> bool:
    if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
        return False
    for key in NUMBERS[section]:
        v = row.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0 or v != v):
            return False
    return True


def load() -> dict:
    shipped = read_json(SHIPPED) or {"sources": {}, "notice": "The shipped hole table could not be read."}
    out = {"notice": shipped.get("notice", ""), "sources": dict(shipped.get("sources") or {}), "problems": []}
    user = read_json(user_path())
    for section in SECTIONS:
        rows = {}
        for origin, doc in (("shipped", shipped), ("user", user)):
            if doc is None:
                continue
            for row in doc.get(section) or []:
                if not valid_row(section, row):
                    out["problems"].append("%s: a row in %s was skipped (needs an id and positive numbers)." % (section, origin))
                    continue
                key = (row.get("standard") or "", row["id"])
                rows[key] = dict(row, origin=origin)
        out[section] = list(rows.values())
    if user is not None:
        for key, src in (user.get("sources") or {}).items():
            if isinstance(src, dict):
                out["sources"][key] = src
    return out


def find(table: dict, section: str, size: str, standard: str = ""):
    for row in table.get(section) or []:
        if row["id"] == size and (not standard or not row.get("standard") or row.get("standard") == standard):
            return row
    return None


def dialog_data() -> dict:
    t = load()
    return {
        "notice": t["notice"],
        "sources": t["sources"],
        "problems": t["problems"],
        "user_file": str(user_path()),
        "kinds": list(KINDS),
        "fits": list(FITS),
        "sections": {s: t[s] for s in SECTIONS},
        "empty": [s for s in SECTIONS if not t[s]],
        "rules": [
            "Tap drill, when the table has no readable row, is derived as nominal diameter minus pitch. That is a rule from the basic thread profile, not a table value; check it against your standard.",
            "Every number can be typed over in the feature. A typed number is stored in the feature and is never replaced by the table.",
        ],
    }


def resolve(values: dict, mm: float, table: dict | None = None) -> tuple:
    kind = str(values.get("kind") or "simple")
    if kind not in KINDS:
        raise PartError("Unknown hole kind %s." % kind)
    t = table if table is not None else load()
    size = str(values.get("size") or "").strip()
    standard = str(values.get("standard") or "")
    fit = str(values.get("fit") or "medium")
    notes, spec, info = [], {"kind": kind}, {"size": size, "origin": {}}

    def given(key):
        v = values.get(key)
        return None if v is None or v == "" else float(v) * mm

    row_thread = find(t, "thread_series", size, standard) if size else None
    if kind == "tapped":
        if not size and given("thread_nominal") is None:
            raise PartError("A tapped hole needs a thread size such as M6, or a typed nominal diameter and pitch.")
        nominal = given("thread_nominal")
        pitch = given("thread_pitch")
        if nominal is None:
            if row_thread is None:
                raise PartError("The size %s is not in the hole table; type the nominal diameter and pitch." % size)
            nominal = float(row_thread["nominal"])
            info["origin"]["nominal"] = "table"
        else:
            info["origin"]["nominal"] = "typed"
        if pitch is None:
            if row_thread is None or row_thread.get("pitch") is None:
                raise PartError("The table has no verified pitch for %s; type the pitch from your standard." % (size or "this size"))
            pitch = float(row_thread["pitch"])
            info["origin"]["pitch"] = "table:%s" % row_thread.get("status", "")
            if row_thread.get("status") not in ("read_twice", "two_sources"):
                notes.append("The pitch of %s comes from a row marked %s; confirm it against your standard." % (size, row_thread.get("status", "unverified")))
        else:
            info["origin"]["pitch"] = "typed"
        drill = given("tap_drill")
        if drill is None:
            row = find(t, "tap_drill", size, standard)
            if row is not None and row.get("diameter") is not None:
                drill = float(row["diameter"])
                info["origin"]["tap_drill"] = "table:%s" % row.get("status", "")
                if row.get("status") not in ("read_twice", "two_sources"):
                    notes.append("The tap drill of %s comes from a row marked %s; confirm it against your standard." % (size, row.get("status", "unverified")))
            else:
                drill = nominal - pitch
                info["origin"]["tap_drill"] = "derived"
                notes.append("The tap drill is derived as nominal minus pitch (%.4g mm); that is a rule, not a table value. Confirm it against your standard." % drill)
        else:
            info["origin"]["tap_drill"] = "typed"
        if drill <= 0 or drill >= nominal:
            raise PartError("The tap drill must be smaller than the nominal diameter and positive.")
        spec.update({"diameter": nominal, "tap_drill": drill})
        spec["thread"] = {"nominal": nominal, "pitch": pitch}
        tdepth = given("thread_depth")
        if tdepth is not None:
            spec["thread"]["depth"] = tdepth
    else:
        diameter = given("diameter")
        if diameter is None:
            row = find(t, "clearance", size, standard) if size else None
            if row is None or row.get(fit) is None:
                raise PartError("No clearance diameter for %s (%s series) in the hole table; type the hole diameter or add a row to the table." % (size or "this size", fit))
            diameter = float(row[fit])
            info["origin"]["diameter"] = "table"
        else:
            info["origin"]["diameter"] = "typed"
        spec["diameter"] = diameter
    if kind == "counterbore":
        cd, cdepth = given("cbore_diameter"), given("cbore_depth")
        if cd is None or cdepth is None:
            row = find(t, "counterbore", size, standard) if size else None
            if row is None or row.get("diameter") is None or row.get("depth") is None:
                raise PartError("No counterbore size for %s in the hole table; type the counterbore diameter and depth." % (size or "this size"))
            cd = row["diameter"] if cd is None else cd
            cdepth = row["depth"] if cdepth is None else cdepth
            info["origin"]["counterbore"] = "table"
        else:
            info["origin"]["counterbore"] = "typed"
        spec.update({"cbore_diameter": cd, "cbore_depth": cdepth})
    if kind == "countersink":
        sd, sa = given("csk_diameter"), values.get("csk_angle")
        if sd is None or sa in (None, ""):
            row = find(t, "countersink", size, standard) if size else None
            if row is None or row.get("diameter") is None or row.get("angle") is None:
                raise PartError("No countersink size for %s in the hole table; type the countersink diameter and angle." % (size or "this size"))
            sd = row["diameter"] if sd is None else sd
            sa = row["angle"] if sa in (None, "") else sa
            info["origin"]["countersink"] = "table"
        else:
            info["origin"]["countersink"] = "typed"
        spec.update({"csk_diameter": sd, "csk_angle": float(sa)})
    end = str(values.get("end") or "blind")
    if end == "through":
        spec["through"] = True
    else:
        depth = given("depth")
        if depth is None or depth <= 0:
            raise PartError("A blind hole needs a depth.")
        spec["depth"] = depth
    tip = values.get("tip_angle")
    if tip not in (None, "") and float(tip) > 0:
        spec["tip_angle"] = float(tip)
    return spec, info, notes
