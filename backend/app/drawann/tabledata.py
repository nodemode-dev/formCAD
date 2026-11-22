from app.drawann import settings


def fill_rows(d, t, columns, body, title):
    from app.doc import tableops as O

    st = settings.get(d)
    t.text_height = st["bom_text_height"]
    need = len(body) + int(t.title) + int(t.header)
    while len(t.cells) < need:
        t.cells.append([dict(t.cells[-1][c], text="", formula="", span=[1, 1]) for c in range(len(columns))])
        t.row_heights.append(st["bom_row_height"])
        t.row_styles.append("")
    del t.cells[need:], t.row_heights[need:], t.row_styles[need:]
    widths = [max([len(columns[c])] + [len(r[c]) for r in body]) for c in range(len(columns))]
    t.col_widths = [max(12.0, w * st["bom_text_height"] + 4.0) for w in widths]
    r0 = 0
    if t.title:
        O.set_cell(d, t, 0, 0, title)
        r0 = 1
    if t.header:
        for c, name in enumerate(columns):
            O.set_cell(d, t, r0, c, name, "text")
        r0 += 1
    for r, row in enumerate(body):
        for c, v in enumerate(row):
            O.set_cell(d, t, r0 + r, c, v, "text")
    for r in range(len(t.row_heights)):
        t.row_heights[r] = max(t.row_heights[r], st["bom_row_height"])
    O.ensure_heights(d, t)
