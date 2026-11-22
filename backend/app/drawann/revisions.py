import copy
import datetime

from app.drawann import tabledata, titleblock

KEY = "FC_REVISIONS"
COLUMNS = ("REV", "DESCRIPTION", "DATE", "APPROVED")
TITLE = "REVISIONS"
FIELDS = ("description", "date", "approved")
MAX_ROWS = 200
MAX_TEXT = 200
LETTERS = [c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if c not in "IO"]


class RevisionError(Exception):
    pass


def get(d) -> list:
    saved = d.header.get(KEY)
    return copy.deepcopy(saved) if isinstance(saved, list) else []


def _after(rev: str) -> str:
    if not rev:
        return LETTERS[0]
    digits = [LETTERS.index(c) for c in rev]
    i = len(digits) - 1
    while i >= 0:
        if digits[i] < len(LETTERS) - 1:
            digits[i] += 1
            return "".join(LETTERS[x] for x in digits[: i + 1]) + LETTERS[0] * (len(digits) - i - 1)
        i -= 1
    return LETTERS[0] * (len(digits) + 1)


def _text(v, what) -> str:
    s = "" if v is None else str(v).strip()
    if len(s) > MAX_TEXT:
        raise RevisionError("The %s is longer than %d characters." % (what, MAX_TEXT))
    return s


def _date(v) -> str:
    s = _text(v, "date")
    if not s:
        return datetime.date.today().isoformat()
    return s


def add(d, description="", date=None, approved="", rev=None) -> dict:
    rows = get(d)
    if len(rows) >= MAX_ROWS:
        raise RevisionError("A drawing keeps at most %d revisions." % MAX_ROWS)
    try:
        letter = titleblock.check_rev(rev) if rev else _after(rows[-1]["rev"] if rows else "")
    except titleblock.TitleError as err:
        raise RevisionError(str(err))
    if any(r["rev"] == letter for r in rows):
        raise RevisionError("Revision %s already exists." % letter)
    row = {"rev": letter, "description": _text(description, "description"), "date": _date(date), "approved": _text(approved, "approval")}
    rows.append(row)
    d.set_header(KEY, rows)
    titleblock.put_props(d, {"rev": letter})
    return row


def edit(d, rev, changes: dict) -> dict:
    rows = get(d)
    for row in rows:
        if row["rev"] == str(rev or "").strip().upper():
            for k, v in (changes or {}).items():
                if k not in FIELDS:
                    raise RevisionError("A revision has %s." % ", ".join(FIELDS))
                row[k] = _date(v) if k == "date" else _text(v, k)
            d.set_header(KEY, rows)
            return row
    raise RevisionError("There is no revision %s." % rev)


def remove_last(d) -> dict:
    rows = get(d)
    if not rows:
        raise RevisionError("There is no revision to remove.")
    gone = rows.pop()
    d.set_header(KEY, rows)
    titleblock.put_props(d, {"rev": rows[-1]["rev"] if rows else ""})
    return gone


def fill(d, t, rows, title):
    tabledata.fill_rows(d, t, COLUMNS, [[r["rev"], r["description"], r["date"], r["approved"]] for r in rows], title)


def refresh_all(d) -> int:
    rows = get(d)
    n = 0
    for e in list(d.ents.values()):
        if e.kind == "table" and "revisions" in (e.extra or {}):
            t = d.modify(e.handle)
            fill(d, t, rows, t.extra["revisions"].get("title") or TITLE)
            n += 1
    return n
