import os

from app.doc import tables as T
from app.doc.model import block_space

LIST_LIMIT = 100
STYLE_FIELDS = (("text", "style", "textstyles", "Standard"), ("mtext", "style", "textstyles", "Standard"), ("attdef", "style", "textstyles", "Standard"), ("dimension", "style", "dimstyles", "Standard"), ("mleader", "style", "mleaderstyles", "Standard"), ("table", "style", "tablestyles", "Standard"), ("mline", "style", "mlinestyles", "Standard"))
HEADER_REFS = (("CLAYER", "layers", "0"), ("CELTYPE", "linetypes", "ByLayer"), ("TEXTSTYLE", "textstyles", "Standard"), ("DIMSTYLE", "dimstyles", "Standard"), ("CMLEADERSTYLE", "mleaderstyles", "Standard"), ("CTABLESTYLE", "tablestyles", "Standard"))


class Auditor:
    def __init__(self, doc, fix: bool):
        self.doc = doc
        self.d = doc.drawing
        self.fix = fix
        self.issues: list = []
        self.fixed = 0

    def note(self, location: str, handle, message: str, fixtext: str, apply=None) -> None:
        self.issues.append({"location": location, "handle": handle, "message": message, "fix": fixtext})
        if self.fix and apply is not None:
            apply()
            self.fixed += 1

    def where(self, e) -> str:
        o = e.owner
        if o == "model":
            return "model space"
        if o.startswith("layout:"):
            return "layout " + o[7:]
        if o.startswith("block:"):
            return "block " + o[6:]
        return o

    def standard_tables(self) -> None:
        d = self.d
        metric = d.metric
        makers = {
            "layers": [("0", lambda: T.new_layer("0"))],
            "linetypes": [(r["name"], (lambda r=r: r)) for r in T.standard_linetypes(metric) if r["name"].lower() in ("bylayer", "byblock", "continuous")],
            "textstyles": [("Standard", lambda: T.new_textstyle("Standard"))],
            "dimstyles": [("Standard", lambda: T.new_dimstyle("Standard"))],
            "mleaderstyles": [("Standard", lambda: T.new_mleaderstyle(metric))],
            "tablestyles": [("Standard", lambda: T.new_tablestyle(metric))],
            "mlinestyles": [("Standard", lambda: T.new_mlinestyle())],
        }
        for table, items in makers.items():
            for name, make in items:
                if not d.tables[table].has(name):
                    self.note("table " + table, None, 'The standard entry "%s" is missing' % name, "recreated", lambda t=table, m=make: d.table_set(t, m()))

    def table_refs(self) -> None:
        d = self.d
        for rec in list(d.tables["layers"].values()):
            lt = rec.get("linetype", "Continuous")
            if not d.tables["linetypes"].has(lt):
                self.note("layer " + rec["name"], None, 'Linetype "%s" does not exist' % lt, "set to Continuous", lambda n=rec["name"]: d.modify_record("layers", n).__setitem__("linetype", "Continuous"))
        for rec in list(d.tables["dimstyles"].values()):
            ts = (rec.get("vars") or {}).get("DIMTXSTY", "Standard")
            if not d.tables["textstyles"].has(ts):
                self.note("dimension style " + rec["name"], None, 'Text style "%s" does not exist' % ts, "set to Standard", lambda n=rec["name"]: d.modify_record("dimstyles", n)["vars"].__setitem__("DIMTXSTY", "Standard"))
        for rec in list(d.tables["mleaderstyles"].values()):
            ts = rec.get("text_style", "Standard")
            if ts and not d.tables["textstyles"].has(ts):
                self.note("multileader style " + rec["name"], None, 'Text style "%s" does not exist' % ts, "set to Standard", lambda n=rec["name"]: d.modify_record("mleaderstyles", n).__setitem__("text_style", "Standard"))

    def header(self) -> None:
        d = self.d
        for key, table, fallback in HEADER_REFS:
            val = d.header.get(key, fallback)
            if val and not d.tables[table].has(str(val)):
                self.note("header " + key, None, '%s names "%s", which does not exist' % (key, val), "set to %s" % fallback, lambda k=key, f=fallback: d.set_header(k, f))
        top = max(d.ents) if d.ents else 0
        if d.next_handle <= top:
            def bump():
                d.next_handle = top + 1

            self.note("header HANDSEED", None, "The next handle %d is not above the largest handle %d" % (d.next_handle, top), "moved past it", bump)

    def objects(self) -> None:
        d = self.d
        for key, e in list(d.ents.items()):
            if e.handle != key or e.handle <= 0:
                def renum(k=key):
                    ent = d.erase_entity(k)
                    ent.handle = 0
                    d.add_entity(ent, ent.owner)

                self.note(self.where(e), key, "The handle is not valid", "new handle", renum)
                continue
            if not self.sound(e):
                self.note(self.where(e), e.handle, "The %s has invalid geometry" % e.kind, "removed", lambda h=e.handle: d.erase_entity(h))
                continue
            self.object_refs(e)

    @staticmethod
    def sound(e) -> bool:
        try:
            e.bounds()
            return bool(e.valid())
        except (TypeError, ValueError, IndexError, KeyError, AttributeError, ZeroDivisionError, OverflowError):
            return False

    def object_refs(self, e) -> None:
        d = self.d
        loc = self.where(e)
        h = e.handle
        if not e.layer:
            self.note(loc, h, "The object has no layer", "put on layer 0", lambda: setattr(d.modify(h), "layer", "0"))
        elif not d.tables["layers"].has(e.layer):
            self.note(loc, h, 'Layer "%s" does not exist' % e.layer, "layer created", lambda n=e.layer: d.table_set("layers", T.new_layer(n)))
        lt = e.linetype
        if lt and lt.lower() not in ("bylayer", "byblock") and not d.tables["linetypes"].has(lt):
            self.note(loc, h, 'Linetype "%s" does not exist' % lt, "set to ByLayer", lambda: setattr(d.modify(h), "linetype", "ByLayer"))
        for kind, attr, table, fallback in STYLE_FIELDS:
            if e.kind == kind:
                val = getattr(e, attr, "")
                if not val or not d.tables[table].has(val):
                    self.note(loc, h, 'Style "%s" does not exist' % val, "set to %s" % fallback, lambda a=attr, f=fallback: setattr(d.modify(h), a, f))
        if e.kind == "insert" and e.block and not d.tables["blocks"].has(e.block):
            self.note(loc, h, 'Block "%s" does not exist' % e.block, "empty block created", lambda n=e.block: d.define_block(n))
        if e.kind == "dimension" and e.associativity:
            bad = [k for k, v in e.associativity.items() if isinstance(v, dict) and v.get("h") not in d.ents]
            if bad:
                def drop(keys=bad):
                    ent = d.modify(h)
                    ent.associativity = {k: v for k, v in ent.associativity.items() if k not in keys}

                self.note(loc, h, "The dimension is associated with an object that is gone", "association removed", drop)
        if e.kind == "viewport" and e.clip and e.clip_source and e.clip_source not in d.ents:
            def unclip():
                ent = d.modify(h)
                ent.clip = None
                ent.clip_source = 0

            self.note(loc, h, "The clipping boundary is gone", "viewport made rectangular", unclip)

    def block_loops(self) -> None:
        d = self.d
        state = {}

        def visit(name, stack):
            low = name.casefold()
            if state.get(low) == 2:
                return
            state[low] = 1
            stack.append(low)
            for e in list(d.entities(block_space(name))):
                if e.kind != "insert" or not e.block:
                    continue
                tgt = e.block.casefold()
                if tgt in stack:
                    self.note("block " + name, e.handle, 'The block contains itself through "%s"' % e.block, "reference removed", lambda h=e.handle: d.erase_entity(h))
                    continue
                if d.tables["blocks"].has(e.block):
                    visit(d.tables["blocks"].get(e.block)["name"], stack)
            stack.pop()
            state[low] = 2

        for rec in list(d.tables["blocks"].values()):
            visit(rec["name"], [])

    def groups(self) -> None:
        d = self.d
        for g in list(d.tables["groups"].values()):
            gone = [m for m in g.get("members", []) if m not in d.ents]
            if gone:
                def trim(n=g["name"], dead=gone):
                    rec = d.modify_record("groups", n)
                    rec["members"] = [m for m in rec["members"] if m not in dead]

                self.note("group " + g["name"], None, "%d member%s no longer exist%s" % (len(gone), "" if len(gone) == 1 else "s", "s" if len(gone) == 1 else ""), "members removed", trim)

    def constraints(self) -> None:
        d = self.d
        if "constraints" not in d.tables:
            return
        for rec in list(d.tables["constraints"].values()):
            refs = []
            for key in ("handles", "entities", "objects", "refs"):
                v = rec.get(key)
                if isinstance(v, list):
                    refs.extend(x for x in v if isinstance(x, int))
            if any(x not in d.ents for x in refs):
                self.note("constraint " + str(rec.get("name", "")), None, "The constraint refers to an object that is gone", "constraint removed", lambda n=rec["name"]: d.table_remove("constraints", n))

    def run(self) -> dict:
        self.standard_tables()
        self.table_refs()
        self.header()
        self.objects()
        self.block_loops()
        self.groups()
        self.constraints()
        return self.result()

    def result(self) -> dict:
        errors = len(self.issues)
        lines = []
        for i in self.issues[:LIST_LIMIT]:
            who = "object %X: " % i["handle"] if i["handle"] else ""
            lines.append("%s: %s%s (%s)" % (i["location"], who, i["message"], i["fix"]))
        if errors > LIST_LIMIT:
            lines.append("... and %d more" % (errors - LIST_LIMIT))
        lines.append("Audit: %d error%s found, %d fixed." % (errors, "" if errors == 1 else "s", self.fixed))
        if errors and not self.fix:
            lines.append("Run AUDIT and answer Yes to fix them.")
        return {"errors": errors, "fixed": self.fixed, "issues": self.issues[:LIST_LIMIT], "lines": lines, "changed": self.fixed > 0}


def run(doc, fix: bool) -> dict:
    return Auditor(doc, fix).run()


def report_path(doc) -> str:
    if not doc.path:
        return ""
    return os.path.splitext(os.path.realpath(doc.path))[0] + ".adt"
