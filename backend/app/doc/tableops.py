import copy
import math

from app.doc import tablecalc as calc
from app.doc.kinds.table import MAX_COLS, MAX_ROWS, DIRECTIONS, TableObject, new_cell

DEFAULT_COL_METRIC = 40.0
DEFAULT_COL_IMPERIAL = 2.5
FORMAT_KINDS = ("general", "decimal", "percent", "text")
EDGES = ("top", "bottom", "left", "right", "inside_h", "inside_v", "outside", "all")
STYLE_BORDERS = ("top", "inside_h", "bottom", "left", "inside_v", "right")
MAX_CELL_STYLES = 64


class TableError(Exception):
    pass


def style_rec(d, name):
    rec = d.table_get("tablestyles", str(name)) if name else None
    if rec is None:
        rec = d.table_get("tablestyles", "Standard")
    if rec is None:
        vals = d.tables["tablestyles"].values()
        rec = vals[0] if vals else None
    return rec


def cell_style_of(ts, name):
    for cs in (ts or {}).get("cell_styles", []):
        if cs["name"].casefold() == str(name).casefold():
            return cs
    for cs in (ts or {}).get("cell_styles", []):
        if cs["name"] == "Data":
            return cs
    return (ts or {}).get("cell_styles", [None])[0]


def position_style(t, r: int) -> str:
    if t.title and r == 0:
        return "Title"
    if t.header and r == (1 if t.title else 0):
        return "Header"
    return "Data"


def style_name_at(t, r: int, c: int) -> str:
    cell = t.cells[r][c]
    if cell.get("style"):
        return cell["style"]
    if r < len(t.row_styles) and t.row_styles[r]:
        return t.row_styles[r]
    return position_style(t, r)


def effective(d, t, r: int, c: int, anchor=None) -> dict:
    ts = style_rec(d, t.style)
    cell = t.cells[r][c]
    name = style_name_at(t, r, c)
    cs = cell_style_of(ts, name) or {}
    th = cell.get("height")
    if th is None:
        th = cs.get("text_height", 2.5)
        if t.text_height is not None:
            th = float(t.text_height) * (1.4 if name == "Title" else 1.0)
    fmt = cell.get("format") or {}
    return {
        "style": cs.get("name", name),
        "text_style": cs.get("text_style", "Standard"),
        "text_height": float(th) * t.text_scale,
        "text_color": cs.get("text_color", 0),
        "fill": cs.get("fill") if cell.get("fill") is None else (None if cell.get("fill") == "none" else cell.get("fill")),
        "align": int(cell.get("align") or cs.get("alignment", 4)),
        "margin_h": float(cs.get("margin_h", 1.0)) * t.text_scale,
        "margin_v": float(cs.get("margin_v", 1.0)) * t.text_scale,
        "format": fmt.get("kind") or cs.get("format", "general"),
        "precision": int(fmt.get("precision") if fmt.get("precision") is not None else cs.get("precision", 2)),
        "borders": cs.get("borders", {}),
    }


def fmt_of(d, t):
    def fn(r, c):
        e = effective(d, t, r, c)
        return e["format"], e["precision"]

    return fn


def recalc(d, t) -> dict:
    return calc.recalc(t, fmt_of(d, t))


def line_count(text: str) -> int:
    return max(1, len(str(text).replace("\\P", "\n").split("\n")))


def min_row_height(d, t, r: int, cover=None) -> float:
    cover = t.cover() if cover is None else cover
    need = 0.0
    for c in range(t.cols()):
        if (r, c) in cover:
            continue
        cell = t.cells[r][c]
        if cell.get("span", [1, 1])[0] > 1:
            continue
        e = effective(d, t, r, c)
        n = line_count(cell.get("text", "")) if cell.get("text") else 1
        need = max(need, n * e["text_height"] + 2 * e["margin_v"])
    return need


def ensure_heights(d, t) -> None:
    cover = t.cover()
    for r in range(t.rows()):
        t.row_heights[r] = max(float(t.row_heights[r]), min_row_height(d, t, r, cover))


def default_col_width(d) -> float:
    return DEFAULT_COL_METRIC if d.metric else DEFAULT_COL_IMPERIAL


def build(d, style_name: str, data_rows: int, cols: int, position, col_width=None, row_height=None) -> TableObject:
    ts = style_rec(d, style_name)
    if ts is None:
        raise TableError("No table style is defined.")
    if not 1 <= cols <= MAX_COLS:
        raise TableError("Requires an integer between 1 and %d." % MAX_COLS)
    if not 1 <= data_rows <= MAX_ROWS:
        raise TableError("Requires an integer between 1 and %d." % MAX_ROWS)
    title = bool(ts.get("title_row", True))
    header = bool(ts.get("header_row", True))
    rows = data_rows + int(title) + int(header)
    if rows > MAX_ROWS:
        raise TableError("Requires an integer between 1 and %d." % (MAX_ROWS - int(title) - int(header)))
    w = float(col_width) if col_width else default_col_width(d)
    t = TableObject(position=[float(position[0]), float(position[1]), 0.0], style=ts["name"], col_widths=[w] * cols, row_heights=[float(row_height) if row_height else 0.01] * rows, title=title, header=header, cells=[[new_cell() for _ in range(cols)] for _ in range(rows)], row_styles=[""] * rows)
    if title and cols > 1:
        cs = cell_style_of(ts, "Title") or {}
        if cs.get("merge_across", True):
            t.cells[0][0]["span"] = [1, cols]
    ensure_heights(d, t)
    return t


def anchor_of(t, r: int, c: int) -> tuple:
    return t.cover().get((r, c), (r, c))


def _check(t, r, c):
    if not (isinstance(r, int) and isinstance(c, int)) or not (0 <= r < t.rows() and 0 <= c < t.cols()):
        raise TableError("No table cell there.")


def parse_cell_ref(text):
    if isinstance(text, (list, tuple)) and len(text) == 2:
        return int(text[0]), int(text[1])
    ref = calc.parse_ref(str(text))
    if ref is None:
        raise TableError("Invalid cell reference: %s." % text)
    return ref


def set_cell(d, t, r: int, c: int, text, data_type=None, fmt=None) -> dict:
    _check(t, r, c)
    r, c = anchor_of(t, r, c)
    cell = t.cells[r][c]
    s = "" if text is None else str(text)
    if fmt is not None:
        set_format(t, r, c, r, c, fmt.get("kind"), fmt.get("precision"))
    if s.lstrip().startswith("=") and data_type in (None, "formula"):
        if len(s) > 65536:
            raise TableError("The formula is too long.")
        cell["formula"] = s.strip()
        cell["type"] = "formula"
        cell["text"] = ""
        return cell
    cell["formula"] = ""
    cell.pop("value", None)
    eff = effective(d, t, r, c)
    kind = eff["format"]
    if data_type == "text" or kind == "text":
        cell["type"] = "text"
        cell["text"] = s
    elif data_type == "number" or (data_type is None and kind in ("decimal", "percent") and calc.parse_number(s) is not None):
        v = calc.parse_number(s)
        if v is None:
            raise TableError("Requires a number.")
        cell["type"] = "number"
        cell["value"] = v
        cell["text"] = calc.format_value(v, kind if kind != "text" else "general", eff["precision"])
    else:
        cell["type"] = "text"
        cell["text"] = s
    return cell


def set_format(t, r0, c0, r1, c1, kind=None, precision=None) -> int:
    n = 0
    if kind is not None and kind not in FORMAT_KINDS:
        raise TableError("The format must be one of %s." % ", ".join(FORMAT_KINDS))
    if precision is not None and not (isinstance(precision, int) and 0 <= precision <= 8):
        raise TableError("The precision must be 0 to 8.")
    for r in range(min(r0, r1), max(r0, r1) + 1):
        for c in range(min(c0, c1), max(c0, c1) + 1):
            _check(t, r, c)
            f = dict(t.cells[r][c].get("format") or {})
            if kind is not None:
                f["kind"] = kind
            if precision is not None:
                f["precision"] = precision
            t.cells[r][c]["format"] = f or None
            n += 1
    return n


def _shift_map(axis: str, index: int, count: int, deleting: bool):
    def pos(v):
        if deleting:
            if index <= v < index + count:
                return None
            return v - count if v >= index + count else v
        return v + count if v >= index else v

    def fc(r, c):
        if axis == "row":
            nr = pos(r)
            return None if nr is None else (nr, c)
        nc = pos(c)
        return None if nc is None else (r, nc)

    def span(lo, hi):
        if deleting:
            nlo = index if index <= lo < index + count else (lo - count if lo >= index + count else lo)
            nhi = index - 1 if index <= hi < index + count else (hi - count if hi >= index + count else hi)
            return (nlo, nhi) if nlo <= nhi else None
        return (lo + count if lo >= index else lo, hi + count if hi >= index else hi)

    def fr(r0, c0, r1, c1):
        if axis == "row":
            s = span(r0, r1)
            return None if s is None else (s[0], c0, s[1], c1)
        s = span(c0, c1)
        return None if s is None else (r0, s[0], r1, s[1])

    return fc, fr


def _remap_formulas(t, axis, index, count, deleting):
    fc, fr = _shift_map(axis, index, count, deleting)
    for row in t.cells:
        for cell in row:
            if cell.get("formula"):
                cell["formula"] = calc.shift_formula(cell["formula"], fc, fr)


def insert_lines(d, t, axis: str, index: int, count: int = 1) -> None:
    if count < 1:
        raise TableError("Requires a positive count.")
    if axis == "row":
        if t.rows() + count > MAX_ROWS:
            raise TableError("Too many rows.")
        index = max(0, min(index, t.rows()))
    else:
        if t.cols() + count > MAX_COLS:
            raise TableError("Too many columns.")
        index = max(0, min(index, t.cols()))
    _remap_formulas(t, axis, index, count, False)
    if axis == "row":
        for r, row in enumerate(t.cells):
            for cell in row:
                rs = cell.get("span", [1, 1])[0]
                if rs > 1 and r < index < r + rs:
                    cell["span"][0] += count
        ref = t.row_heights[min(max(index - 1, 0), t.rows() - 1)]
        for _ in range(count):
            t.cells.insert(index, [new_cell() for _ in range(t.cols())])
            t.row_heights.insert(index, ref)
            t.row_styles.insert(index, "")
    else:
        for r, row in enumerate(t.cells):
            for c, cell in enumerate(row):
                cs = cell.get("span", [1, 1])[1]
                if cs > 1 and c < index < c + cs:
                    cell["span"][1] += count
        ref = t.col_widths[min(max(index - 1, 0), t.cols() - 1)]
        for _ in range(count):
            for row in t.cells:
                row.insert(index, new_cell())
            t.col_widths.insert(index, ref)
    ensure_heights(d, t)
    recalc(d, t)


def delete_lines(d, t, axis: str, index: int, count: int = 1) -> None:
    n = t.rows() if axis == "row" else t.cols()
    if count < 1 or index < 0 or index + count > n:
        raise TableError("No table %s there." % ("row" if axis == "row" else "column"))
    if count >= n:
        raise TableError("A table keeps at least one row and one column.")
    ax = 0 if axis == "row" else 1
    for r in range(t.rows()):
        for c in range(t.cols()):
            cell = t.cells[r][c]
            sp = cell.get("span", [1, 1])
            if sp[0] == 1 and sp[1] == 1:
                continue
            pos = (r, c)[ax]
            ln = sp[ax]
            lo, hi = pos, pos + ln
            ov = max(0, min(hi, index + count) - max(lo, index))
            if ov == 0:
                continue
            cell["span"][ax] = ln - ov
            if index <= pos < index + count and hi > index + count:
                tr, tc = (index + count, c) if ax == 0 else (r, index + count)
                moved = copy.deepcopy(cell)
                t.cells[tr][tc] = moved
                cell["span"] = [1, 1]
                cell["text"] = ""
                cell["formula"] = ""
    _remap_formulas(t, axis, index, count, True)
    if axis == "row":
        del t.cells[index : index + count]
        del t.row_heights[index : index + count]
        del t.row_styles[index : index + count]
    else:
        for row in t.cells:
            del row[index : index + count]
        del t.col_widths[index : index + count]
    for row in t.cells:
        for cell in row:
            sp = cell.get("span", [1, 1])
            if sp[0] < 1 or sp[1] < 1:
                cell["span"] = [max(sp[0], 1), max(sp[1], 1)]
    recalc(d, t)


def merge(d, t, r0, c0, r1, c1) -> None:
    r0, r1 = min(r0, r1), max(r0, r1)
    c0, c1 = min(c0, c1), max(c0, c1)
    _check(t, r0, c0)
    _check(t, r1, c1)
    if (r1 - r0 + 1) * (c1 - c0 + 1) < 2:
        raise TableError("Merging needs at least two cells.")
    for r in range(t.rows()):
        for c in range(t.cols()):
            rs, cs = t.cells[r][c].get("span", [1, 1])
            if rs == 1 and cs == 1:
                continue
            inside = r0 <= r and r + rs - 1 <= r1 and c0 <= c and c + cs - 1 <= c1
            hit = not (r + rs - 1 < r0 or r > r1 or c + cs - 1 < c0 or c > c1)
            if hit and not inside:
                raise TableError("The range cuts through a merged cell.")
    texts = []
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            cell = t.cells[r][c]
            if cell.get("text") and (r, c) != (r0, c0):
                texts.append(cell["text"])
            if (r, c) != (r0, c0):
                cell["text"] = ""
                cell["formula"] = ""
                cell["span"] = [1, 1]
                cell.pop("value", None)
    anchor = t.cells[r0][c0]
    if not anchor.get("formula"):
        anchor["text"] = " ".join([x for x in [anchor.get("text", "")] + texts if x])
    anchor["span"] = [r1 - r0 + 1, c1 - c0 + 1]
    recalc(d, t)


def unmerge(d, t, r, c) -> None:
    _check(t, r, c)
    ar, ac = anchor_of(t, r, c)
    cell = t.cells[ar][ac]
    if cell.get("span", [1, 1]) == [1, 1]:
        raise TableError("That cell is not merged.")
    cell["span"] = [1, 1]
    recalc(d, t)


def set_style_scope(t, ts, scope: str, name: str, r0=0, c0=0, r1=0, c1=0) -> int:
    real = ""
    if name:
        found = cell_style_of(ts, name)
        if found is None or found["name"].casefold() != str(name).casefold():
            raise TableError("The cell style %s does not exist." % name)
        real = found["name"]
    n = 0
    if scope == "row":
        for r in range(min(r0, r1), max(r0, r1) + 1):
            if not 0 <= r < t.rows():
                raise TableError("No table row there.")
            t.row_styles[r] = real
            n += 1
        return n
    for r in range(min(r0, r1), max(r0, r1) + 1):
        for c in range(min(c0, c1), max(c0, c1) + 1):
            _check(t, r, c)
            t.cells[r][c]["style"] = real
            n += 1
    return n


def set_align(t, r0, c0, r1, c1, align) -> int:
    if align is not None and not (isinstance(align, int) and 1 <= align <= 9):
        raise TableError("The alignment is 1 to 9.")
    n = 0
    for r in range(min(r0, r1), max(r0, r1) + 1):
        for c in range(min(c0, c1), max(c0, c1) + 1):
            _check(t, r, c)
            t.cells[r][c]["align"] = align
            n += 1
    return n


def set_fill(t, r0, c0, r1, c1, color) -> int:
    n = 0
    for r in range(min(r0, r1), max(r0, r1) + 1):
        for c in range(min(c0, c1), max(c0, c1) + 1):
            _check(t, r, c)
            t.cells[r][c]["fill"] = None if color in (None, "") else color
            n += 1
    return n


def set_cell_height(d, t, r0, c0, r1, c1, height) -> int:
    if height is not None and not (isinstance(height, (int, float)) and height > 0):
        raise TableError("The text height must be positive.")
    n = 0
    for r in range(min(r0, r1), max(r0, r1) + 1):
        for c in range(min(c0, c1), max(c0, c1) + 1):
            _check(t, r, c)
            t.cells[r][c]["height"] = None if height is None else float(height)
            n += 1
    ensure_heights(d, t)
    return n


def set_border(t, r0, c0, r1, c1, edge: str, visible=None, color=None, lineweight=None) -> int:
    if edge not in EDGES:
        raise TableError("The border must be one of %s." % ", ".join(EDGES))
    r0, r1 = min(r0, r1), max(r0, r1)
    c0, c1 = min(c0, c1), max(c0, c1)
    _check(t, r0, c0)
    _check(t, r1, c1)
    spec = {}
    if visible is not None:
        spec["visible"] = bool(visible)
    if color is not None:
        spec["color"] = color
    if lineweight is not None:
        spec["lineweight"] = int(lineweight)
    if not spec:
        raise TableError("Give visible, color or lineweight.")
    targets = []
    for r in range(r0, r1 + 1):
        for c in range(c0, c1 + 1):
            sides = []
            if edge in ("top", "outside", "all") and r == r0:
                sides.append("top")
            if edge in ("bottom", "outside", "all") and r == r1:
                sides.append("bottom")
            if edge in ("left", "outside", "all") and c == c0:
                sides.append("left")
            if edge in ("right", "outside", "all") and c == c1:
                sides.append("right")
            if edge in ("inside_h", "all"):
                if r < r1:
                    sides.append("bottom")
                if r > r0:
                    sides.append("top")
            if edge in ("inside_v", "all"):
                if c < c1:
                    sides.append("right")
                if c > c0:
                    sides.append("left")
            for s in sides:
                targets.append((r, c, s))
    for r, c, s in targets:
        cur = dict(t.cells[r][c]["borders"].get(s) or {})
        cur.update(spec)
        t.cells[r][c]["borders"][s] = cur
    return len(targets)


def set_col_width(t, c: int, width) -> None:
    if not (0 <= c < t.cols()):
        raise TableError("No table column there.")
    if not (isinstance(width, (int, float)) and width > 0 and math.isfinite(width)):
        raise TableError("The width must be positive.")
    t.col_widths[c] = float(width)


def set_row_height(d, t, r: int, height) -> None:
    if not (0 <= r < t.rows()):
        raise TableError("No table row there.")
    if not (isinstance(height, (int, float)) and height > 0 and math.isfinite(height)):
        raise TableError("The height must be positive.")
    t.row_heights[r] = max(float(height), min_row_height(d, t, r))


def set_breaks(t, spec: dict) -> int:
    b = dict(t.breaks or {})
    if "enabled" in spec:
        b["enabled"] = bool(spec["enabled"])
    if "direction" in spec:
        if spec["direction"] not in DIRECTIONS:
            raise TableError("The direction must be right, left or down.")
        b["direction"] = spec["direction"]
    for key in ("max_height", "spacing"):
        if key in spec:
            v = float(spec[key])
            if v < 0 or not math.isfinite(v):
                raise TableError("The %s must not be negative." % key.replace("_", " "))
            b[key] = v
    for key in ("repeat_top", "repeat_bottom"):
        if key in spec:
            b[key] = bool(spec[key])
    if "heights" in spec:
        b["heights"] = [float(h) for h in spec["heights"]]
    if "offsets" in spec:
        b["offsets"] = [[float(o[0]), float(o[1])] for o in spec["offsets"]]
    t.breaks = b
    return len(t.parts())


def cell_at(t, p):
    px, py = t.position[0], t.position[1]
    x, y = p[0] - px, p[1] - py
    if t.rotation:
        c, s = math.cos(-t.rotation), math.sin(-t.rotation)
        x, y = x * c - y * s, x * s + y * c
    for part in t.parts():
        lx, ly = x - part["dx"], y - part["dy"]
        if lx < 0 or lx > t.width() or ly > 0:
            continue
        top = 0.0
        for r in part["rows"]:
            h = t.row_heights[r]
            if -ly <= top + h + 1e-12:
                acc = 0.0
                for c in range(t.cols()):
                    if lx <= acc + t.col_widths[c] + 1e-12:
                        return anchor_of(t, r, c)
                    acc += t.col_widths[c]
                return None
            top += h
    return None


def csv_field(text: str, sep: str) -> str:
    if any(ch in text for ch in (sep, '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def export_csv(t, sep: str = ",") -> str:
    if sep not in (",", ";", "\t"):
        raise TableError("The separator must be a comma, semicolon or tab.")
    cover = t.cover()
    lines = []
    for r in range(t.rows()):
        lines.append(sep.join("" if (r, c) in cover else csv_field(t.cells[r][c].get("text", ""), sep) for c in range(t.cols())))
    return "\r\n".join(lines) + "\r\n"


def parse_delimited(text: str, sep: str) -> list:
    rows, row, field, quoted, i = [], [], "", False, 0
    n = len(text)
    while i < n:
        ch = text[i]
        if quoted:
            if ch == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field += '"'
                    i += 1
                else:
                    quoted = False
            else:
                field += ch
        elif ch == '"' and field == "":
            quoted = True
        elif ch == sep:
            row.append(field)
            field = ""
        elif ch in "\r\n":
            if ch == "\r" and i + 1 < n and text[i + 1] == "\n":
                i += 1
            row.append(field)
            rows.append(row)
            row, field = [], ""
        else:
            field += ch
        i += 1
    if field != "" or row:
        row.append(field)
        rows.append(row)
    return rows


def detect_sep(path: str, text: str) -> str:
    low = path.lower()
    if low.endswith((".txt", ".tsv")):
        return "\t"
    first = text.splitlines()[0] if text.splitlines() else ""
    if ";" in first and "," not in first:
        return ";"
    return ","


def fill_from_rows(d, t, rows: list, start_row: int) -> None:
    need = start_row + len(rows)
    width = max([len(r) for r in rows] + [1])
    if need > MAX_ROWS or width > MAX_COLS:
        raise TableError("The data does not fit the table limits.")
    while t.rows() > need:
        t.cells.pop()
        t.row_heights.pop()
        t.row_styles.pop()
    while t.rows() < need:
        t.cells.append([new_cell() for _ in range(t.cols())])
        t.row_heights.append(t.row_heights[-1])
        t.row_styles.append("")
    while t.cols() > width:
        for row in t.cells:
            row.pop()
        t.col_widths.pop()
    while t.cols() < width:
        for row in t.cells:
            row.append(new_cell())
        t.col_widths.append(t.col_widths[-1])
    for r in range(start_row, need):
        data = rows[r - start_row]
        for c in range(t.cols()):
            cell = t.cells[r][c]
            cell["span"] = [1, 1]
            cell["formula"] = ""
            cell["text"] = ""
            cell.pop("value", None)
            if c < len(data):
                set_cell(d, t, r, c, data[c])
    for r in range(t.rows()):
        for c in range(t.cols()):
            sp = t.cells[r][c].get("span", [1, 1])
            if r + sp[0] > t.rows() or c + sp[1] > t.cols():
                t.cells[r][c]["span"] = [min(sp[0], t.rows() - r), min(sp[1], t.cols() - c)]
    ensure_heights(d, t)
    recalc(d, t)


def edge_border(d, t, ts, side: str, pair, fixed: int, cover=None):
    cover = t.cover() if cover is None else cover

    def cell_of(rr, cc):
        return cover.get((rr, cc), (rr, cc))

    def own(cell, s):
        return cell.get("borders", {}).get(s)

    def derived(rr, cc, key):
        cs = cell_style_of(ts, style_name_at(t, rr, cc)) or {}
        b = (cs.get("borders") or {}).get(key) or {"visible": True, "color": 0, "lineweight": -2}
        return b

    if side == "h":
        upper, lower = pair
        c = fixed
        a_up = cell_of(upper, c) if upper is not None else None
        a_lo = cell_of(lower, c) if lower is not None else None
        if a_up is not None and a_lo is not None and a_up == a_lo:
            return None
        if a_lo is not None:
            o = own(t.cells[a_lo[0]][a_lo[1]], "top")
            if o:
                return {**derived(a_lo[0], a_lo[1], "top"), **o}
        if a_up is not None:
            o = own(t.cells[a_up[0]][a_up[1]], "bottom")
            if o:
                return {**derived(a_up[0], a_up[1], "bottom"), **o}
        if a_up is None:
            return derived(a_lo[0], a_lo[1], "top")
        if a_lo is None:
            return derived(a_up[0], a_up[1], "bottom")
        if style_name_at(t, a_up[0], a_up[1]) == style_name_at(t, a_lo[0], a_lo[1]):
            return derived(a_lo[0], a_lo[1], "inside_h")
        lo = derived(a_lo[0], a_lo[1], "top")
        return lo if lo.get("visible", True) else derived(a_up[0], a_up[1], "bottom")
    left, right = pair
    r = fixed
    a_l = cell_of(r, left) if left is not None else None
    a_r = cell_of(r, right) if right is not None else None
    if a_l is not None and a_r is not None and a_l == a_r:
        return None
    if a_r is not None:
        o = own(t.cells[a_r[0]][a_r[1]], "left")
        if o:
            return {**derived(a_r[0], a_r[1], "left"), **o}
    if a_l is not None:
        o = own(t.cells[a_l[0]][a_l[1]], "right")
        if o:
            return {**derived(a_l[0], a_l[1], "right"), **o}
    if a_l is None:
        return derived(a_r[0], a_r[1], "left")
    if a_r is None:
        return derived(a_l[0], a_l[1], "right")
    return derived(a_r[0], a_r[1], "inside_v")


def describe(d, t) -> dict:
    cover = t.cover()
    errors = {}
    cells = []
    for r in range(t.rows()):
        row = []
        for c in range(t.cols()):
            cell = t.cells[r][c]
            e = effective(d, t, r, c)
            txt = cell.get("text", "")
            if cell.get("formula") and txt.startswith("#") and txt in ("#SYNTAX", "#REF", "#CYCLE", "#DIV/0", "#VALUE", "#LIMIT"):
                errors[calc.cell_name(r, c)] = txt
            row.append({"row": r, "col": c, "text": txt, "formula": cell.get("formula", ""), "type": cell.get("type", "text"), "value": cell.get("value"), "span": list(cell.get("span", [1, 1])), "covered": list(cover[(r, c)]) if (r, c) in cover else None, "style": e["style"], "ownStyle": cell.get("style", ""), "align": e["align"], "ownAlign": cell.get("align"), "format": {"kind": e["format"], "precision": e["precision"]}, "ownFormat": cell.get("format"), "fill": e["fill"], "textHeight": e["text_height"], "borders": copy.deepcopy(cell.get("borders", {}))})
        cells.append(row)
    return {"handle": t.handle, "style": t.style, "rows": t.rows(), "cols": t.cols(), "title": t.title, "header": t.header, "position": [t.position[0], t.position[1]], "colWidths": list(t.col_widths), "rowHeights": list(t.row_heights), "rowStyles": list(t.row_styles), "breaks": copy.deepcopy(t.breaks), "parts": len(t.parts()), "link": copy.deepcopy(t.link), "cells": cells, "errors": errors}


def _span(op, t):
    a = parse_cell_ref(op.get("from", [op.get("row", 0), op.get("col", 0)]))
    b = parse_cell_ref(op.get("to", list(a)))
    return a[0], a[1], b[0], b[1]


def apply_op(d, t, op: dict):
    kind = str(op.get("op", "")).lower()
    if kind == "set":
        r, c = parse_cell_ref(op.get("cell") or [op.get("row"), op.get("col")])
        return set_cell(d, t, r, c, op.get("text", op.get("formula", "")), op.get("type"), op.get("format"))
    if kind in ("insertrow", "insertcol", "deleterow", "deletecol"):
        axis = "row" if kind.endswith("row") else "col"
        n = t.rows() if axis == "row" else t.cols()
        idx = op.get("index")
        idx = n if idx is None else int(idx)
        if kind.startswith("insert"):
            return insert_lines(d, t, axis, idx, int(op.get("count", 1)))
        return delete_lines(d, t, axis, idx, int(op.get("count", 1)))
    if kind == "merge":
        return merge(d, t, *_span(op, t))
    if kind == "unmerge":
        r, c = parse_cell_ref(op.get("cell") or [op.get("row"), op.get("col")])
        return unmerge(d, t, r, c)
    if kind == "colwidth":
        return set_col_width(t, int(op["col"]), op["width"])
    if kind == "rowheight":
        return set_row_height(d, t, int(op["row"]), op["height"])
    if kind == "align":
        return set_align(t, *_span(op, t), op.get("align"))
    if kind == "format":
        n = set_format(t, *_span(op, t), op.get("kind"), op.get("precision"))
        _reformat(d, t, *_span(op, t))
        recalc(d, t)
        return n
    if kind == "fill":
        return set_fill(t, *_span(op, t), op.get("color"))
    if kind == "textheight":
        return set_cell_height(d, t, *_span(op, t), op.get("height"))
    if kind == "border":
        return set_border(t, *_span(op, t), str(op.get("edge", "all")), op.get("visible"), op.get("color"), op.get("lineweight"))
    if kind == "cellstyle":
        scope = str(op.get("scope", "cell"))
        ts = style_rec(d, t.style)
        a = _span(op, t) if scope != "row" else (int(op.get("row", op.get("index", 0))), 0, int(op.get("to_row", op.get("row", op.get("index", 0)))), 0)
        n = set_style_scope(t, ts, scope, str(op.get("name", "")), *a)
        ensure_heights(d, t)
        recalc(d, t)
        return n
    if kind == "breaks":
        return set_breaks(t, op)
    if kind == "recalc":
        return recalc(d, t)
    raise TableError("Unknown table operation: %s." % op.get("op"))


def _reformat(d, t, r0, c0, r1, c1):
    for r in range(min(r0, r1), max(r0, r1) + 1):
        for c in range(min(c0, c1), max(c0, c1) + 1):
            cell = t.cells[r][c]
            if cell.get("type") == "number" and cell.get("value") is not None and not cell.get("formula"):
                e = effective(d, t, r, c)
                cell["text"] = calc.format_value(cell["value"], e["format"] if e["format"] != "text" else "general", e["precision"])


def recalc_users(d, style_name: str) -> int:
    n = 0
    for e in d.ents.values():
        if e.kind == "table" and e.style.casefold() == style_name.casefold():
            ent = d.modify(e.handle)
            ensure_heights(d, ent)
            recalc(d, ent)
            n += 1
    return n
