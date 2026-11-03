import copy
import json
import os

DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "plastic")
_cache: dict = {}


def load(name: str) -> dict:
    got = _cache.get(name)
    if got is None:
        try:
            with open(os.path.join(DIR, name), "r", encoding="utf-8") as fh:
                got = json.load(fh)
        except (OSError, ValueError):
            got = {}
        if not isinstance(got, dict):
            got = {}
        _cache[name] = got
    return got


def materials() -> list:
    return copy.deepcopy(load("materials.json").get("materials") or [])


def material(mid) -> dict | None:
    mid = str(mid or "")
    for row in load("materials.json").get("materials") or []:
        if row.get("id") == mid:
            return copy.deepcopy(row)
    return None


def rule_values() -> dict:
    out = {}
    for key, row in (load("rules.json").get("values") or {}).items():
        out[key] = row.get("value")
    return out


def listing() -> dict:
    mats, rules = load("materials.json"), load("rules.json")
    return {
        "materials": copy.deepcopy(mats.get("materials") or []),
        "material_sources": copy.deepcopy(mats.get("sources") or {}),
        "material_note": mats.get("note", ""),
        "rules": copy.deepcopy(rules.get("values") or {}),
        "rule_sources": copy.deepcopy(rules.get("sources") or {}),
        "rule_note": rules.get("note", ""),
    }
