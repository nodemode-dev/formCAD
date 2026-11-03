import itertools

import numpy as np

from app.assembly import parts, walk
from app.joints import store as J
from app.mates import store as S
from app.mates.interf import matrix12
from app.param.units import mm_per_unit
from app.solid import surfwork, work


def default_touch(d) -> float:
    return 0.01 / mm_per_unit(d)


def new_set(d, name=None, all_pairs=False, pairs=None, touch=None, caps=None) -> dict:
    data = J.load(d)
    caps = caps or J.limits(False)
    if len(data["contacts"]) >= caps["contacts"]:
        raise J.MotionError("A document keeps at most %d contact sets." % caps["contacts"])
    kid = "K%d" % data["next_contact"]
    data["next_contact"] += 1
    rec = {"id": kid, "name": J.clean_name(name or kid), "all": bool(all_pairs), "pairs": clean_pairs(d, pairs or [], caps), "touch": J.number(touch if touch is not None else default_touch(d), "The touch gap", 0.0)}
    data["contacts"][kid] = rec
    J.save(d, data)
    return rec


def edit_set(d, kid, name=None, all_pairs=None, pairs=None, touch=None, caps=None) -> dict:
    data = J.load(d)
    rec = J.contact(data, kid)
    caps = caps or J.limits(False)
    if name is not None:
        rec["name"] = J.clean_name(name)
    if all_pairs is not None:
        rec["all"] = bool(all_pairs)
    if pairs is not None:
        rec["pairs"] = clean_pairs(d, pairs, caps)
    if touch is not None:
        rec["touch"] = J.number(touch, "The touch gap", 0.0)
    J.save(d, data)
    return rec


def delete_set(d, kid) -> dict:
    data = J.load(d)
    rec = J.contact(data, kid)
    data["contacts"].pop(rec["id"])
    for s in data["studies"].values():
        sets = (s.get("contact") or {}).get("sets") or []
        if rec["id"] in sets:
            s["contact"]["sets"] = [k for k in sets if k != rec["id"]]
    J.save(d, data)
    return {"deleted": rec["id"]}


def clean_pairs(d, pairs, caps) -> list:
    from app.assembly import store as A

    if not isinstance(pairs, list) or len(pairs) > caps["pairs"]:
        raise J.MotionError("A contact set holds at most %d pairs." % caps["pairs"])
    out = []
    seen = set()
    for p in pairs:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise J.MotionError("A pair is two component ids.")
        a, b = str(p[0]), str(p[1])
        for c in (a, b):
            if A.get(d, c) is None:
                raise J.MotionError("There is no component %s." % c)
        if a == b:
            raise J.MotionError("A pair needs two different components.")
        key = frozenset((a, b))
        if key not in seen:
            seen.add(key)
            out.append([a, b])
    return out


def joined_pairs(d) -> set:
    out = set()
    for r in S.records(d):
        if r["kind"] == "joint" and not r.get("suppressed"):
            a, b = r["refs"][0].get("comp"), r["refs"][1].get("comp")
            out.add(frozenset((a, b)))
    return out


def component_pairs(d, sets: list, fixed: set) -> tuple:
    data = J.load(d)
    from app.assembly import store as A

    live = [r["id"] for r in A.components(d) if not r.get("suppressed")]
    skip = joined_pairs(d)
    pairs = {}
    touch = None
    for kid in sets:
        rec = J.contact(data, kid)
        t = float(rec.get("touch") or default_touch(d))
        touch = t if touch is None else min(touch, t)
        if rec.get("all"):
            for a, b in itertools.combinations(live, 2):
                key = frozenset((a, b))
                if key in skip or (a in fixed and b in fixed):
                    continue
                pairs[key] = (a, b)
        for a, b in rec.get("pairs") or []:
            if a in live and b in live and not (a in fixed and b in fixed):
                pairs[frozenset((a, b))] = (a, b)
    return list(pairs.values()), (touch if touch is not None else default_touch(d))


class Prober:
    def __init__(self, doc, comp_pairs: list, touch: float):
        d = doc.drawing
        self.mmu = mm_per_unit(d)
        self.touch = float(touch)
        self.probe = max(self.touch * 25.0, 3.0 / self.mmu)
        tol = surfwork.model_tolerance(d)
        self.fuzzy = float(tol["tol"])
        wanted = {c for p in comp_pairs for c in p}
        insts = walk.instances(doc)
        tops = {i.cid: i.world for i in insts if i.depth == 0 and not i.index}
        self.items = []
        self.keys = {}
        for inst in insts:
            lp = inst.part
            if lp is None or getattr(lp, "is_assembly", False) or not lp.bodies or inst.suppressed:
                continue
            top = inst.path[0].split("#")[0].split("/")[0] if inst.path else inst.cid
            if top not in wanted:
                continue
            for b in lp.bodies:
                key = inst.key if len(lp.bodies) == 1 else "%s|%s" % (inst.key, b.handle)
                try:
                    wid = parts.shapes(lp, b)
                except work.SolidError:
                    continue
                self.items.append({"key": key, "id": wid, "world": inst.world, "top": top, "base": tops.get(top)})
                self.keys.setdefault(top, []).append(key)
        self.tops = tops
        self.pairs = []
        for a, b in comp_pairs:
            for ka in self.keys.get(a, []):
                for kb in self.keys.get(b, []):
                    self.pairs.append((ka, kb))
        self.owner = {i["key"]: i["top"] for i in self.items}
        self.calls = 0
        self.ms = 0.0

    def check(self, poses: dict) -> dict:
        items = []
        for it in self.items:
            world = it["world"]
            new = poses.get(it["top"])
            if new is not None and it["base"] is not None:
                world = np.asarray(new, dtype=float).reshape(4, 4) @ np.linalg.inv(it["base"]) @ world
            items.append({"key": it["key"], "id": it["id"], "matrix": matrix12(world, self.mmu)})
        params = {"items": items, "fuzzy": self.fuzzy * self.mmu, "min_volume": 1e-3, "skip": [], "clearance": self.probe * self.mmu, "pairs": [list(p) for p in self.pairs]}
        res = work.kcall("asm_interference", params, work.LONG)
        self.calls += 1
        self.ms += float(res.get("ms", 0.0))
        best = None
        over = None
        for r in res["interferences"]:
            pair = (self.owner[r["a"]], self.owner[r["b"]])
            vol = r["volume"] / self.mmu**3
            if over is None or vol > over["volume"]:
                over = {"pair": pair, "volume": vol}
        for r in res["clearances"]:
            dist = r["distance"] / self.mmu
            pair = (self.owner[r["a"]], self.owner[r["b"]])
            if best is None or dist < best["gap"]:
                best = {"pair": pair, "gap": dist}
        out = {"over": over is not None, "gap": None, "pair": None}
        if over is not None:
            out.update(pair=over["pair"], gap=0.0, volume=over["volume"])
        elif best is not None:
            out.update(pair=best["pair"], gap=best["gap"])
        out["state"] = "over" if out["over"] else ("contact" if out["gap"] is not None and out["gap"] <= self.touch else "clear")
        return out


def view(rec: dict) -> dict:
    return {"id": rec["id"], "name": rec["name"], "all": bool(rec.get("all")), "pairs": rec.get("pairs") or [], "touch": rec.get("touch")}
