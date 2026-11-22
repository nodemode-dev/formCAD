import re
import zipfile
import xml.etree.ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships", "p": "http://schemas.openxmlformats.org/package/2006/relationships"}
MAX_PART = 64 * 1024 * 1024
MAX_CELLS = 200000


class XlsxError(ValueError):
    pass


def _part(z: zipfile.ZipFile, name: str):
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_PART:
        raise XlsxError("A part of the workbook is larger than 64 MB.")
    return ET.fromstring(z.read(info))


def _text(node) -> str:
    return "".join(t.text or "" for t in node.iter("{%s}t" % NS["m"]))


def _col(ref: str, fallback: int) -> int:
    m = re.match(r"[A-Za-z]+", ref)
    if not m:
        return fallback
    n = 0
    for ch in m.group(0).upper():
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def _number(raw: str) -> str:
    try:
        v = float(raw)
    except ValueError:
        return raw
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def sheet_names(path: str) -> list:
    with zipfile.ZipFile(path) as z:
        book = _part(z, "xl/workbook.xml")
        if book is None:
            raise XlsxError("The file is not an Excel workbook.")
        return [s.get("name") for s in book.iterfind("m:sheets/m:sheet", NS)]


def read_rows(path: str, sheet: str = "") -> list:
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError) as err:
        raise XlsxError("The file is not an Excel workbook (%s)." % err)
    with z:
        book = _part(z, "xl/workbook.xml")
        rels = _part(z, "xl/_rels/workbook.xml.rels")
        if book is None or rels is None:
            raise XlsxError("The file is not an Excel workbook.")
        sheets = list(book.iterfind("m:sheets/m:sheet", NS))
        if not sheets:
            raise XlsxError("The workbook has no sheets.")
        chosen = next((s for s in sheets if s.get("name") == sheet), None) if sheet else sheets[0]
        if chosen is None:
            raise XlsxError('The workbook has no sheet named "%s".' % sheet)
        rid = chosen.get("{%s}id" % NS["r"])
        target = next((r.get("Target") for r in rels.iterfind("p:Relationship", NS) if r.get("Id") == rid), None)
        if not target:
            raise XlsxError("The workbook does not say where its sheet is.")
        target = target.lstrip("/")
        name = target if target.startswith("xl/") else "xl/" + target
        strings_root = _part(z, "xl/sharedStrings.xml")
        strings = [_text(si) for si in strings_root.iterfind("m:si", NS)] if strings_root is not None else []
        data = _part(z, name)
        if data is None:
            raise XlsxError("The sheet %s is missing from the workbook." % chosen.get("name"))
        grid = {}
        count = 0
        r = -1
        for row in data.iterfind("m:sheetData/m:row", NS):
            given = row.get("r") or ""
            r = int(given) - 1 if given.isdigit() and int(given) > 0 else r + 1
            col = -1
            for c in row.iterfind("m:c", NS):
                count += 1
                if count > MAX_CELLS:
                    raise XlsxError("The sheet has more than %d cells." % MAX_CELLS)
                col = _col(c.get("r") or "", col + 1)
                kind = c.get("t", "n")
                v = c.find("m:v", NS)
                if kind == "s" and v is not None and v.text is not None and v.text.isdigit() and int(v.text) < len(strings):
                    text = strings[int(v.text)]
                elif kind == "inlineStr":
                    node = c.find("m:is", NS)
                    text = _text(node) if node is not None else ""
                elif kind == "b":
                    text = "TRUE" if (v is not None and v.text == "1") else "FALSE"
                elif v is None or v.text is None:
                    text = ""
                elif kind in ("str", "e"):
                    text = v.text
                else:
                    text = _number(v.text)
                if text:
                    grid.setdefault(r, {})[col] = text
        if not grid:
            return []
        rows = max(grid) + 1
        cols = max(max(cells) for cells in grid.values()) + 1
        if rows * cols > MAX_CELLS:
            raise XlsxError("The used range of the sheet is larger than %d cells." % MAX_CELLS)
        out = [[grid.get(i, {}).get(j, "") for j in range(cols)] for i in range(rows)]
        while out and not any(out[-1]):
            out.pop()
        return out
