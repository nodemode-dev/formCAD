from app.doc import tables as T
from app.doc.model import Drawing

KINDS = ("drawing", "part", "assembly", "surface", "form", "graph")

A3 = (420.0, 297.0)
A4 = (297.0, 210.0)
ANSI_B = (431.8, 279.4)

TEMPLATES = {
    "drawing-mm-a3": {"label": "2D drawing, millimetres, A3", "kind": "drawing", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Drawing"},
    "drawing-inch-ansi-b": {"label": "2D drawing, inches, ANSI B", "kind": "drawing", "metric": False, "limits": (17.0, 11.0), "sheet": ANSI_B, "prefix": "Drawing"},
    "drawing-sheet": {"label": "Drawing sheet, millimetres, A4", "kind": "drawing", "metric": True, "limits": (297.0, 210.0), "sheet": A4, "prefix": "Sheet"},
    "part": {"label": "Part", "kind": "part", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Part"},
    "assembly": {"label": "Assembly", "kind": "assembly", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Assembly"},
    "surface": {"label": "Surface", "kind": "surface", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Surface"},
    "form": {"label": "Form", "kind": "form", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Form"},
    "graph": {"label": "Graph", "kind": "graph", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Graph"},
    "metric": {"label": "Millimetres", "kind": "drawing", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Drawing"},
    "iso": {"label": "Millimetres", "kind": "drawing", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Drawing"},
    "imperial": {"label": "Inches", "kind": "drawing", "metric": False, "limits": (12.0, 9.0), "sheet": (279.4, 215.9), "prefix": "Drawing"},
    "inch": {"label": "Inches", "kind": "drawing", "metric": False, "limits": (12.0, 9.0), "sheet": (279.4, 215.9), "prefix": "Drawing"},
}


def lookup(template: str):
    return TEMPLATES.get((template or "").strip().lower())


def apply(drawing: Drawing, spec: dict) -> None:
    drawing.header["LIMMIN"] = [0.0, 0.0]
    drawing.header["LIMMAX"] = [float(spec["limits"][0]), float(spec["limits"][1])]
    width, height = spec["sheet"]
    for order, name in ((1, "Layout1"), (2, "Layout2")):
        rec = T.new_layout(name, order, bool(spec["metric"]))
        rec["page_setup"]["width"] = float(width)
        rec["page_setup"]["height"] = float(height)
        drawing.tables["layouts"].put(rec)
