import copy
import hashlib
import json
import re
import time

from app.doc.kinds.solidbody import SolidBody
from app.param import expr as X
from app.param import store as S
from app.param import units as U
from app.part import names, profile, registry, store
from app.part.registry import PartError, RefLost
from app.services import kernel
from app.solid import work
from app.solid.work import SolidError

FEATURE_ID = re.compile(r"F\d+(?=:)")


class Entry:
    def __init__(self):
        self.hash = ""
        self.wid = None
        self.owns = False
        self.faces = []
        self.edges = []
        self.summary = None
        self.tool = None
        self.profile = None
        self.error = False
        self.message = ""
        self.warnings = []
        self.failed = {}
        self.ms = 0.0
        self.status = "ok"
        self.adjacency = None
        self.extras = []


class Cache:
    def __init__(self):
        self.entries: dict = {}
        self.serial = 0
        self.trash: list = []
        self.sides: dict = {}


def cache_of(doc) -> Cache:
    c = getattr(doc, "part_cache", None)
    if c is None:
        c = Cache()
        doc.part_cache = c
    return c


def sync_cache(doc, need_kernel=True) -> Cache:
    c = cache_of(doc)
    try:
        serial = kernel.serial()
    except Exception:
        serial = 0
    if serial != c.serial:
        c.entries.clear()
        c.trash.clear()
        c.sides = {}
        c.serial = serial
    return c


def kcall(method, params, timeout=work.LONG):
    return work.kcall(method, params, timeout)


def release(cache: Cache) -> None:
    ids = [w for w in cache.trash if w]
    cache.trash = []
    if ids:
        try:
            kernel.call("shape_free", {"ids": ids}, 10.0)
        except Exception:
            pass


def drop_entry(cache: Cache, fid: str) -> None:
    e = cache.entries.pop(fid, None)
    if e is not None:
        if e.owns and e.wid:
            cache.trash.append(e.wid)
        if e.tool:
            cache.trash.append(e.tool)
        for x in e.extras:
            cache.trash.append(x["wid"])


def flat_refs(rec):
    out = []
    for slot, val in (rec.get("refs") or {}).items():
        for item in (val if isinstance(val, list) else [val]):
            if isinstance(item, dict):
                out.append((slot, item))
    return out


def parents_of(rec, known) -> list:
    found = []
    for _slot, ref in flat_refs(rec):
        if ref.get("kind") in ("feature", "sketch") and ref.get("id"):
            found.append(ref["id"])
        for tok in FEATURE_ID.findall(ref.get("key") or ""):
            found.append(tok)
    out = []
    for f in found:
        if f != rec["id"] and f in known and f not in out:
            out.append(f)
    return out


def evaluate(d, ft, params) -> dict:
    scope = S.Scope(d)
    out = copy.deepcopy(params or {})
    for p in ft.params:
        v = out.get(p.name, p.default)
        try:
            if p.kind in ("length", "angle"):
                if isinstance(v, str):
                    v = scope.evaluate_text(v) if v.strip() else None
                elif v is not None:
                    v = float(v)
            elif p.kind == "int" and v is not None:
                v = int(v)
            elif p.kind == "bool":
                v = bool(v)
        except (X.ExprError, ValueError, TypeError) as err:
            raise PartError("%s: %s" % (p.label or p.name, err))
        if v is not None and isinstance(v, (int, float)) and not isinstance(v, bool):
            if p.min is not None and v < p.min:
                raise PartError("%s must be at least %s." % (p.label or p.name, p.min))
            if p.max is not None and v > p.max:
                raise PartError("%s must be at most %s." % (p.label or p.name, p.max))
        if p.kind == "enum" and v is not None and p.choices and v not in p.choices:
            raise PartError("%s must be one of %s." % (p.label or p.name, ", ".join(map(str, p.choices))))
        out[p.name] = v
    return out


class Step:
    def __init__(self, rb, rec, ft, values, prev):
        self.rb = rb
        self.d = rb.d
        self.feat = rec
        self.ft = ft
        self.values = values
        self.prev = prev
        self.base = prev.wid if prev is not None else None
        self.base_faces = prev.faces if prev is not None else []
        self.base_edges = prev.edges if prev is not None else []
        self.nfaces = len(self.base_faces)
        self.nedges = len(self.base_edges)
        self.mm = U.mm_per_unit(rb.d)
        self.warnings = []
        self.touched = {"faces": {}, "edges": {}}
        self._sigs = {}
        self._index = {}

    def p(self, name):
        return self.values.get(name)

    def length(self, name):
        v = self.values.get(name)
        return None if v is None else float(v) * self.mm

    def warn(self, text):
        if text not in self.warnings:
            self.warnings.append(text)

    def refs(self, slot):
        v = (self.feat.get("refs") or {}).get(slot)
        if v is None:
            return []
        return [x for x in (v if isinstance(v, list) else [v]) if isinstance(x, dict)]

    def required(self, slot):
        spec = self.ft.slot(slot)
        return spec is None or spec.required

    def key_index(self, tag):
        if tag not in self._index:
            keys = self.base_faces if tag == "faces" else self.base_edges
            self._index[tag] = {k: i for i, k in enumerate(keys)}
        return self._index[tag]

    def sibling(self, tag, ref, idx, taken):
        keys = self.base_faces if tag == "faces" else self.base_edges
        if ("fam", tag) not in self._index:
            fam = {}
            for i, k in enumerate(keys):
                fam.setdefault(names.base_key(k), []).append(i)
            self._index[("fam", tag)] = fam
        group = self._index[("fam", tag)].get(names.base_key(keys[idx])) or []
        if len(group) < 2:
            return idx
        cand = self.signatures(tag)
        pick = names.match_signature(ref["sig"], {str(i): cand[str(i)] for i in group if str(i) in cand}, self.diag(), set(taken))
        if pick is None or pick == idx:
            return idx
        ref["key"] = keys[pick]
        self.rb.healed = True
        return pick

    def signatures(self, tag):
        if tag not in self._sigs:
            if self.base is None:
                self._sigs[tag] = {}
            else:
                got = kcall("feat_signatures", {"id": self.base, tag: "all"}, work.SHORT)
                self._sigs[tag] = got.get(tag) or {}
        return self._sigs[tag]

    def diag(self):
        box = (self.prev.summary or {}).get("bbox") if self.prev is not None else None
        if not box:
            return 1.0
        return max(sum((box[i + 3] - box[i]) ** 2 for i in range(3)) ** 0.5, 1e-6)

    def resolve(self, slot, tag):
        refs = self.refs(slot)
        out = []
        if not refs and self.required(slot):
            raise RefLost("Choose the %s for %s." % (slot, self.ft.label), slot)
        for ref in refs:
            key = ref.get("key") or ""
            idx = self.key_index(tag).get(key)
            if idx is not None and ref.get("sig"):
                idx = self.sibling(tag, ref, idx, out)
            if idx is None:
                sig = ref.get("sig") or {}
                cand = self.signatures(tag)
                idx = names.match_signature(sig, cand, self.diag(), set(out)) if sig else None
                if idx is None:
                    raise names.lost(slot, ref, "face" if tag == "faces" else "edge")
                self.warn("A reference in %s was re-attached by shape because %s no longer exists." % (slot, key))
                newkey = (self.base_faces if tag == "faces" else self.base_edges)[idx]
                ref["key"] = newkey
                self.rb.healed = True
            out.append(idx)
            self.touched[tag][(slot, len(out) - 1)] = idx
        return out

    def faces(self, slot):
        return self.resolve(slot, "faces")

    def edges(self, slot):
        return self.resolve(slot, "edges")

    def face(self, slot):
        got = self.faces(slot)
        if not got:
            raise RefLost("Choose the face for %s." % self.ft.label, slot)
        return got[0]

    def vertices(self, slot):
        out = []
        refs = self.refs(slot)
        if not refs and self.required(slot):
            raise RefLost("Choose the vertex for %s." % self.ft.label, slot)
        for ref in refs:
            p = (ref.get("sig") or {}).get("p")
            if p is None or self.base is None:
                raise RefLost("A vertex reference has no position.", slot)
            got = kcall("feat_signatures", {"id": self.base, "vertices": "all"}, work.SHORT).get("vertices") or {}
            best = min(got.items(), key=lambda kv: names.distance(kv[1]["p"], p), default=None)
            if best is None or names.distance(best[1]["p"], p) > 1e-3 * self.diag() + 1e-6:
                raise RefLost("A vertex in %s no longer exists." % slot, slot)
            out.append(int(best[0]))
        return out

    def entry_for(self, slot):
        refs = self.refs(slot)
        if not refs:
            if self.required(slot):
                raise RefLost("Choose the %s for %s." % (slot, self.ft.label), slot)
            return None
        fid = refs[0].get("id")
        e = self.rb.cache.entries.get(fid)
        rec = store.get(self.d, fid) if fid else None
        if e is None or rec is None:
            raise RefLost("The feature %s in %s no longer exists." % (fid, slot), slot)
        if e.error:
            raise RefLost("%s depends on %s, which failed." % (self.ft.label, fid), slot)
        return e

    def profile(self, slot):
        e = self.entry_for(slot)
        if e is None or e.profile is None:
            raise RefLost("%s needs a sketch." % self.ft.label, slot)
        return e.profile

    def seed(self, slot):
        e = self.entry_for(slot)
        if e is None or not e.tool:
            raise RefLost("The feature in %s keeps no solid to pattern or mirror." % slot, slot)
        return e.tool

    def plane(self, slot):
        refs = self.refs(slot)
        if not refs:
            raise RefLost("Choose the plane for %s." % self.ft.label, slot)
        spec = refs[0]
        fn = registry.PLANE_SOURCES.get(spec.get("source") or spec.get("kind"))
        if fn is None:
            raise RefLost("Unknown plane source in %s." % slot, slot)
        return fn(self, spec)


class Rebuilder:
    def __init__(self, doc, force=False, start=None):
        self.doc = doc
        self.d = doc.drawing
        self.force = force
        self.start = start
        self.cache = sync_cache(doc)
        self.healed = False
        self.report = {"rebuilt": [], "reused": [], "errors": [], "ms": 0.0}

    def ref_hash(self, rec):
        parts = []
        for slot, ref in flat_refs(rec):
            parts.append([slot, ref.get("kind"), ref.get("key"), ref.get("id")])
            if ref.get("id") and ref["id"] in self.cache.entries:
                parts.append(self.cache.entries[ref["id"]].hash)
        return parts

    def tool_stamp(self, values):
        out = []
        for h in values.get("tools") or []:
            try:
                e = self.d.get(int(h))
            except (TypeError, ValueError):
                e = None
            out.append([h, None if e is None else [getattr(e, "version", 0), list(getattr(e, "offset", None) or [])]])
        return out

    def feature_hash(self, rec, values, prev_hash):
        parts = [prev_hash, rec["type"], values, self.ref_hash(rec), bool(rec.get("suppressed"))]
        if values.get("tools"):
            parts.append(self.tool_stamp(values))
        blob = json.dumps(parts, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha1(blob.encode()).hexdigest()[:20]

    def run(self):
        t0 = time.perf_counter()
        d = self.d
        t = store.tree(d)
        recs = copy.deepcopy(store.records(d))
        order = [f for f in t["order"] if f in recs]
        active = order
        if t.get("rollback") in order:
            active = order[: order.index(t["rollback"]) + 1]
        prev = None
        prev_hash = ""
        dirty = False
        states = {}
        for fid in order:
            if fid not in active:
                states[fid] = ("rolled", "", [], {}, 0.0, "")
        for fid in active:
            rec = recs[fid]
            ft = registry.TYPES.get(rec["type"])
            if self.start == fid:
                dirty = True
            if ft is None:
                e = self.fail_entry(prev, "The feature type %s is not installed." % rec["type"])
                self.cache.entries[fid] = e
                prev = e
                states[fid] = ("error", e.message, [], {}, 0.0, "")
                continue
            ev_t = time.perf_counter()
            try:
                values = evaluate(d, ft, rec.get("params"))
            except PartError as err:
                e = self.fail_entry(prev, str(err))
                self.swap(fid, e)
                prev = e
                prev_hash = "x" + prev_hash
                states[fid] = ("error", e.message, [], {}, 0.0, "")
                continue
            if rec.get("suppressed"):
                e = Entry()
                e.status = "suppressed"
                e.hash = self.feature_hash(rec, values, prev_hash)
                self.copy_through(e, prev)
                self.swap(fid, e)
                prev, prev_hash = e, e.hash
                states[fid] = ("suppressed", "", [], {}, 0.0, e.hash)
                continue
            hsh = self.feature_hash(rec, values, prev_hash)
            old = self.cache.entries.get(fid)
            if ft.sketch:
                e = self.build_sketch(rec, ft, values, prev, hsh)
            elif old is not None and old.hash == hsh and not self.force and not dirty and not old.error:
                e = old
                self.report["reused"].append(fid)
            else:
                e = self.build(rec, ft, values, prev, hsh)
            if e is not old:
                self.swap(fid, e)
            if fid in self.report["rebuilt"] and not ft.sketch:
                dirty = True
            prev, prev_hash = e, e.hash if e.hash else prev_hash
            status = "error" if e.error else ("warning" if e.warnings else "ok")
            states[fid] = (status, e.message, e.warnings, e.failed, e.ms, e.hash)
            if e.error:
                self.report["errors"].append(fid)
        for fid in list(self.cache.entries):
            if fid not in recs:
                drop_entry(self.cache, fid)
        self.finish(t, recs, order, active, prev, prev_hash, states)
        release(self.cache)
        self.report["ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
        return self.report

    def swap(self, fid, e):
        old = self.cache.entries.get(fid)
        if old is not None and old is not e:
            if old.owns and old.wid and old.wid != e.wid:
                self.cache.trash.append(old.wid)
            if old.tool and old.tool != e.tool:
                self.cache.trash.append(old.tool)
            for x in old.extras:
                self.cache.trash.append(x["wid"])
        self.cache.entries[fid] = e

    def copy_through(self, e, prev):
        if prev is None:
            return
        e.wid, e.faces, e.edges, e.summary = prev.wid, prev.faces, prev.edges, prev.summary

    def fail_entry(self, prev, message, errors=None, failed=None):
        e = Entry()
        e.error = True
        e.status = "failed"
        e.message = message
        e.failed = failed or {}
        self.copy_through(e, prev)
        e.hash = ""
        return e

    def build_sketch(self, rec, ft, values, prev, hsh):
        step = Step(self, rec, ft, values, prev)
        t0 = time.perf_counter()
        try:
            call = ft.plan(step)
            prof = call["profile"]
        except (PartError, S.ParamError, SolidError, X.ExprError, KeyError) as err:
            e = self.fail_entry(prev, str(err) if not isinstance(err, KeyError) else "The sketch %s is missing." % err)
            return e
        segs = call.get("segs")
        if segs is not None and segs != (rec.get("segs") or {}):
            self.keep_segs(rec, segs)
        dig = hashlib.sha1(profile.digest(prof).encode()).hexdigest()[:20]
        h2 = hashlib.sha1((hsh + dig).encode()).hexdigest()[:20]
        old = self.cache.entries.get(rec["id"])
        if old is not None and old.hash == h2 and not old.error and not self.force:
            self.report["reused"].append(rec["id"])
            old.faces, old.edges, old.wid, old.summary = (prev.faces, prev.edges, prev.wid, prev.summary) if prev else ([], [], None, None)
            return old
        e = Entry()
        e.hash = h2
        e.profile = prof
        e.status = "built"
        self.copy_through(e, prev)
        e.warnings = list(step.warnings)
        e.ms = round((time.perf_counter() - t0) * 1000.0, 2)
        self.report["rebuilt"].append(rec["id"])
        return e

    def keep_segs(self, rec, segs):
        rec["segs"] = segs
        q = copy.deepcopy(self.d.tables[store.TABLE].get(rec["id"]))
        if q is not None:
            q["segs"] = segs
            store.put(self.d, q)

    def build(self, rec, ft, values, prev, hsh):
        step = Step(self, rec, ft, values, prev)
        t0 = time.perf_counter()
        fid = rec["id"]
        try:
            reserve_kernel()
            call = ft.plan(step)
            params = dict(call.get("params") or {})
            if ft.needs_body and step.base is None:
                raise PartError("%s needs a body; add a base feature before it." % ft.label)
            if step.base is not None:
                params.setdefault("id", step.base)
            res = {"passthrough": True} if call.get("passthrough") else kcall(call["method"], params)
            if res.get("ok") is False:
                msg = res.get("message") or "The kernel could not build this feature."
                failed = res.get("failed") or {}
                e = self.fail_entry(prev, msg, res.get("errors"), self.failed_keys(prev, failed))
                e.warnings = [w.get("message", str(w)) if isinstance(w, dict) else str(w) for w in res.get("warnings") or []]
                e.ms = round((time.perf_counter() - t0) * 1000.0, 2)
                return e
            res = self.keep_piece(res, step)
            e = self.carry(hsh, prev) if res.get("passthrough") else self.accept(rec, ft, step, res, prev, hsh)
            e.extras = self.extras_of(call, res, step)
            step.entry = e
            if ft.finish is not None:
                ft.finish(step, res)
            e.warnings = list(step.warnings) + [w.get("message", str(w)) if isinstance(w, dict) else str(w) for w in res.get("warnings") or []]
            e.ms = round((time.perf_counter() - t0) * 1000.0, 2)
            self.refresh_refs(rec, step)
            self.report["rebuilt"].append(fid)
            return e
        except (PartError, S.ParamError, SolidError, X.ExprError) as err:
            e = self.fail_entry(prev, str(err))
            e.ms = round((time.perf_counter() - t0) * 1000.0, 2)
            if isinstance(err, RefLost):
                e.failed = {"slot": err.slot, "key": err.key}
            return e

    def carry(self, hsh, prev):
        e = Entry()
        e.hash = hsh
        e.status = "built"
        self.copy_through(e, prev)
        e.adjacency = prev.adjacency if prev is not None else None
        return e

    def keep_piece(self, res, step):
        pieces = res.get("pieces")
        if not pieces:
            return res
        keep = int(step.p("keep") or 1)
        if not 1 <= keep <= len(pieces):
            for p in pieces:
                self.cache.trash.append(p["id"])
            raise PartError("Keep piece %d does not exist; the split made %d pieces." % (keep, len(pieces)))
        chosen = pieces[keep - 1]
        out = {"id": chosen["id"], "summary": chosen["summary"], "history": {"inputs": [{"id": step.base, "faces": chosen.get("faces") or {}, "edges": chosen.get("edges") or {}}]}}
        out["rest"] = [{"piece": i + 1, "role": "piece", "wid": p["id"], "summary": p["summary"]} for i, p in enumerate(pieces) if i != keep - 1]
        return out

    def extras_of(self, call, res, step):
        out = list(res.get("rest") or [])
        for i, spec in enumerate(call.get("extras") or []):
            params = dict(spec.get("params") or {})
            params.setdefault("id", step.base)
            made = kcall(spec["method"], params)
            out.append({"piece": i + 1, "role": "copy", "wid": made["id"], "summary": made["summary"]})
        return out

    def failed_keys(self, prev, failed):
        out = {}
        if prev is None:
            return out
        for tag, keys in (("faces", prev.faces), ("edges", prev.edges)):
            got = [keys[i] for i in failed.get(tag) or [] if 0 <= i < len(keys)]
            if got:
                out[tag] = got
        return out

    def accept(self, rec, ft, step, res, prev, hsh):
        fid = rec["id"]
        adjacency = res.get("adjacency")
        if adjacency is None:
            adjacency = kcall("feat_topology", {"id": res["id"]}, work.SHORT)["adjacency"]
        nid = res["id"]

        def sig_fetch(tag, idx):
            got = kcall("feat_signatures", {"id": nid, tag: list(idx)}, work.SHORT)
            return {int(k): v for k, v in (got.get(tag) or {}).items()}

        fk, ek = names.name_result(fid, res, step.base, step.base_faces, step.base_edges, adjacency, sig_fetch)
        e = Entry()
        e.hash = hsh
        e.wid = nid
        e.owns = True
        e.faces, e.edges = fk, ek
        e.summary = res["summary"]
        e.tool = res.get("tool")
        e.status = "built"
        e.adjacency = adjacency
        return e

    def refresh_refs(self, rec, step):
        want = {"faces": sorted(set(step.touched["faces"].values())), "edges": sorted(set(step.touched["edges"].values()))}
        if step.base is None or not (want["faces"] or want["edges"]):
            return
        got = kcall("feat_signatures", {"id": step.base, "faces": want["faces"], "edges": want["edges"]}, work.SHORT)
        changed = False
        new = copy.deepcopy(rec)
        for slot, ref in flat_refs(new):
            tag = "faces" if ref.get("kind") == "face" else "edges" if ref.get("kind") == "edge" else None
            if tag is None:
                continue
            keys = step.base_faces if tag == "faces" else step.base_edges
            try:
                idx = keys.index(ref.get("key"))
            except ValueError:
                continue
            sig = (got.get(tag) or {}).get(str(idx))
            if sig and sig != ref.get("sig"):
                ref["sig"] = sig
                changed = True
        if changed or self.healed:
            store.put(self.d, new)
            self.healed = False

    def finish(self, t, recs, order, active, last, last_hash, states):
        d = self.d
        t["built"] = last_hash if last is not None else ""
        for fid in order:
            rec = recs[fid]
            status, message, warnings, failed, ms, hsh = states.get(fid, ("stale", "", [], {}, 0.0, ""))
            new_state = {"status": status, "message": message, "warnings": warnings, "ms": ms, "failed": failed, "hash": hsh}
            old_state = rec.get("state") or {}
            if {k: v for k, v in old_state.items() if k != "ms"} != {k: v for k, v in new_state.items() if k != "ms"} or (ms and old_state.get("ms") != ms):
                q = copy.deepcopy(self.d.tables[store.TABLE].get(fid))
                q["state"] = new_state
                store.put(d, q)
        self.apply_body(t, last)
        self.apply_sides(t, recs, active)
        if t != store.tree(d):
            store.save_tree(d, t)

    def apply_sides(self, t, recs, active):
        d = self.d
        wanted = {}
        for fid in active:
            e = self.cache.entries.get(fid)
            if e is None or e.error or recs[fid].get("suppressed"):
                continue
            for x in e.extras:
                wanted["%s:%d" % (fid, x["piece"])] = (fid, x)
        held = dict(t.get("sides") or {})
        base_body = d.get(int(t.get("body") or 0)) if t.get("body") else None
        base = (base_body.name if base_body is not None else "") or getattr(self.doc, "name", "") or "Part"
        for key in [k for k in held if k not in wanted]:
            old = d.get(held.pop(key))
            self.cache.sides.pop(key, None)
            if old is not None and old.kind == "solidbody":
                d.erase_entity(old.handle)
        for key, (fid, x) in wanted.items():
            body = d.get(held[key]) if key in held else None
            if body is not None and body.kind != "solidbody":
                body = None
            if body is not None and self.cache.sides.get(key) == (x["wid"], body.handle) and body.blob:
                continue
            source = {"op": "part-" + x["role"], "feature": fid, "piece": x["piece"]}
            name = "%s (%d)" % (base, x["piece"]) if x["role"] == "piece" else "%s copy %d" % (base, x["piece"])
            if body is None:
                body = work.new_body(d, x["wid"], x["summary"], name, source, list(base_body.rgb) if base_body is not None else None)
                if base_body is not None:
                    body.layer = base_body.layer
                held[key] = d.add_entity(body, "model")
            else:
                body = d.modify(body.handle)
                work.apply_result(d, body, x["wid"], x["summary"], source)
            self.cache.sides[key] = (x["wid"], held[key])
        if held:
            t["sides"] = held
        else:
            t.pop("sides", None)

    def apply_body(self, t, last):
        d = self.d
        handle = int(t.get("body") or 0)
        body = d.get(handle) if handle else None
        if last is None or last.wid is None:
            if body is not None:
                d.erase_entity(handle)
            t["body"] = 0
            return
        if body is not None and getattr(self.cache, "applied", None) == (last.wid, handle) and body.blob:
            return
        blob = work.save_shape(d, last.wid)
        fids, flin = names.assign_pids(d, t, last.faces, "faces")
        eids, elin = names.assign_pids(d, t, last.edges, "edges")
        if body is None:
            body = SolidBody(name=getattr(self.doc, "name", "") or "Part", source={"op": "part"}, version=0)
            body.blob = blob
            body.face_ids, body.edge_ids = fids, eids
            body.lineage = {**flin, **elin}
            body.summary = work.trim_summary(last.summary)
            body.extent = work.extent_of(d, last.summary.get("bbox"))
            t["body"] = d.add_entity(body, "model")
        else:
            body = d.modify(handle)
            if body.blob != blob or body.face_ids != fids or body.edge_ids != eids:
                body.blob = blob
                body.version = int(body.version) + 1
                body.face_ids, body.edge_ids = fids, eids
                body.lineage = {**flin, **elin}
                body.summary = work.trim_summary(last.summary)
                body.source = {"op": "part"}
                body.offset = [0.0, 0.0, 0.0]
                body.extent = work.extent_of(d, last.summary.get("bbox"))
        self.cache.applied = (last.wid, t["body"])


def reserve_kernel():
    work.reset_if_restarted()


def rebuild(doc, force=False, start=None) -> dict:
    d = doc.drawing
    if not store.has_part(d):
        return {"rebuilt": [], "reused": [], "errors": [], "ms": 0.0}
    tx = getattr(doc, "_tx", None)
    if tx is not None:
        tx.part_done = True
    rb = Rebuilder(doc, force, start)
    try:
        return rb.run()
    except SolidError as err:
        raise PartError(str(err))


def ensure_built(doc) -> None:
    d = doc.drawing
    t = store.tree(d)
    cache = sync_cache(doc)
    if not t["order"]:
        return
    active = t["order"]
    if t.get("rollback") in active:
        active = active[: active.index(t["rollback"]) + 1]
    if any(f not in cache.entries for f in active if not (store.get(d, f) or {}).get("suppressed")):
        rebuild(doc)
