import datetime
import math

from app.doc import blockdefs, layouts
from app.doc.entities import AttDef, Line, LwPolyline

KEY = "FC_DOCPROPS"
BLOCK = "TITLEBLOCK"

FIELDS = (
    ("OWNER", "owner", "Legal owner"),
    ("IDNO", "idno", "Identification number"),
    ("REV", "rev", "Revision index"),
    ("DATE", "date", "Date of issue"),
    ("SHEET", "sheet", "Sheet number"),
    ("SHEETS", "sheets", "Number of sheets"),
    ("TITLE", "title", "Title"),
    ("SUBTITLE", "subtitle", "Supplementary title"),
    ("DEPT", "dept", "Responsible department"),
    ("TECHREF", "techref", "Technical reference"),
    ("APPROVED", "approved", "Approval person"),
    ("DRAWN", "drawn", "Creator"),
    ("DOCTYPE", "doctype", "Document type"),
    ("STATUS", "status", "Document status"),
    ("SCALE", "scale", "Scale"),
    ("PAPER", "paper", "Paper size"),
)
PROP_KEYS = ("title", "subtitle", "drawn", "date", "owner", "idno", "rev", "approved", "dept", "techref", "doctype", "status", "language")
STATUS_TERMS = ("In preparation", "Under approval", "Released", "Withdrawn")


class TitleError(Exception):
    pass


def check_rev(value) -> str:
    s = str(value or "").strip().upper()
    if not s:
        return ""
    if not s.isalpha() or any(c in "IO" for c in s):
        raise TitleError("Revision letters run A to Z without I and O.")
    return s


DOC_KEY = {"drawn": "author", "rev": "revision"}


def props(d) -> dict:
    from app.assembly import props as dp

    raw = dp.get(d)
    return {k: raw.get(DOC_KEY.get(k, k), "") for k in PROP_KEYS}


def put_props(d, changes: dict) -> dict:
    from app.assembly import props as dp

    out = {}
    for k, v in (changes or {}).items():
        if k not in PROP_KEYS:
            raise TitleError("Unknown property %s; use %s." % (k, ", ".join(PROP_KEYS)))
        v = "" if v is None else str(v)
        if k == "rev":
            v = check_rev(v)
        if k == "status" and v and v not in STATUS_TERMS:
            raise TitleError("Status is one of: %s." % ", ".join(STATUS_TERMS))
        out[DOC_KEY.get(k, k)] = v
    try:
        dp.put(d, out)
    except dp.PropError as err:
        raise TitleError(str(err))
    return props(d)


def build_block(d, name=BLOCK, width=180.0, height=40.0):
    ents = []
    ents.append(LwPolyline.from_points([(0, 0), (width, 0), (width, height), (0, height)], closed=True))
    for y in (10.0, 20.0, 30.0):
        ents.append(Line(start=[0.0, y, 0.0], end=[width, y, 0.0]))
    for x in (40.0, 80.0, 130.0, 160.0):
        ents.append(Line(start=[x, 0.0, 0.0], end=[x, height, 0.0]))
    cols = {"OWNER": (2, 31), "IDNO": (2, 21), "REV": (2, 11), "DATE": (2, 1), "SHEET": (42, 1), "SHEETS": (42, 11), "TITLE": (82, 31), "SUBTITLE": (82, 21), "DEPT": (82, 11), "TECHREF": (82, 1), "APPROVED": (132, 31), "DRAWN": (132, 21), "DOCTYPE": (132, 11), "STATUS": (132, 1), "SCALE": (162, 21), "PAPER": (162, 11)}
    for tag, _k, prompt in FIELDS:
        x, y = cols[tag]
        ents.append(AttDef(position=[float(x), float(y) + 2.5, 0.0], tag=tag, prompt=prompt, default="", height=2.5))
    blockdefs.define(d, name, ents, [0.0, 0.0, 0.0], description="Drawing title block with owner, number, revision, date, sheet, title, scale and paper fields")
    return blockdefs.lookup(d, name)


def tags_of(d, name=BLOCK) -> list:
    return [c.tag for c in blockdefs.children(d, name) if c.kind == "attdef"]


def paper_name(d, layout) -> str:
    try:
        ps = layouts.page_setup(d, layout)
        return " ".join(str(ps.get("paper", "")).split(" (")[0].split())
    except Exception:
        return ""


def sheet_numbers(d, layout) -> tuple:
    names = [n for n in layouts.names(d) if any(True for _ in d.entities("layout:" + n))]
    if layout not in names:
        names.append(layout)
    return names.index(layout) + 1, len(names)


def values_for(d, layout, scale_text="", doc_title="") -> dict:
    p = props(d)
    n, m = sheet_numbers(d, layout)
    date = p["date"] or datetime.date.today().isoformat()
    return {
        "OWNER": p["owner"], "IDNO": p["idno"], "REV": p["rev"], "DATE": date, "SHEET": str(n), "SHEETS": str(m),
        "TITLE": p["title"] or doc_title, "SUBTITLE": p["subtitle"], "DEPT": p["dept"], "TECHREF": p["techref"],
        "APPROVED": p["approved"], "DRAWN": p["drawn"], "DOCTYPE": p["doctype"], "STATUS": p["status"],
        "SCALE": scale_text, "PAPER": paper_name(d, layout),
    }
