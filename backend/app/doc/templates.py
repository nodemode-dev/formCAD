from app.doc import tables as T
from app.doc.model import Drawing

KINDS = ("drawing", "part", "assembly", "surface", "form", "graph", "ecad")

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
    "ecad": {"label": "Electronics design", "kind": "ecad", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Board"},
    "metric": {"label": "Millimetres", "kind": "drawing", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Drawing"},
    "iso": {"label": "Millimetres", "kind": "drawing", "metric": True, "limits": (420.0, 297.0), "sheet": A3, "prefix": "Drawing"},
    "imperial": {"label": "Inches", "kind": "drawing", "metric": False, "limits": (12.0, 9.0), "sheet": (279.4, 215.9), "prefix": "Drawing"},
    "inch": {"label": "Inches", "kind": "drawing", "metric": False, "limits": (12.0, 9.0), "sheet": (279.4, 215.9), "prefix": "Drawing"},
}


def lookup(template: str):
    return TEMPLATES.get((template or "").strip().lower())


FILE_EXT = (".fcad", ".dwt", ".dxf")


def folder() -> str:
    import os

    from app.core import config

    path = os.path.join(str(config.data_dir()), "templates")
    os.makedirs(path, mode=0o700, exist_ok=True)
    return path


def file_for(ref: str):
    import os

    r = os.path.expanduser((ref or "").strip())
    if not r or r == ".":
        return None
    candidates = [r] if os.path.dirname(r) else [os.path.join(folder(), r)]
    if not os.path.dirname(r):
        candidates.append(r)
    for base in candidates:
        for path in ([base] if os.path.splitext(base)[1].lower() in FILE_EXT else [base + e for e in FILE_EXT]):
            if os.path.isfile(path):
                return os.path.realpath(path)
    return None


def load_file(ref: str):
    import os

    path = file_for(ref)
    if path is None:
        return None
    ext = os.path.splitext(path)[1].lower()
    if ext == ".fcad":
        from app.doc import container

        try:
            drawing, manifest = container.load(path)
        except container.ContainerError as err:
            raise ValueError(err.message)
        kind = manifest.get("kind")
        return drawing, (kind if kind in KINDS else "drawing"), path
    from app.interchange import files
    from app.interchange.errors import InterchangeError

    try:
        drawing = files.read_any(path)[0]
    except InterchangeError as err:
        raise ValueError(str(err))
    return drawing, "drawing", path


def listing() -> list:
    import os

    out = [{"name": k, "label": v["label"], "kind": v["kind"], "source": "built-in"} for k, v in TEMPLATES.items()]
    try:
        for n in sorted(os.listdir(folder())):
            if os.path.splitext(n)[1].lower() in FILE_EXT:
                out.append({"name": n, "label": os.path.splitext(n)[0], "kind": "drawing", "source": "file", "path": os.path.join(folder(), n)})
    except OSError:
        pass
    return out


def apply(drawing: Drawing, spec: dict) -> None:
    drawing.header["LIMMIN"] = [0.0, 0.0]
    drawing.header["LIMMAX"] = [float(spec["limits"][0]), float(spec["limits"][1])]
    width, height = spec["sheet"]
    for order, name in ((1, "Layout1"), (2, "Layout2")):
        rec = T.new_layout(name, order, bool(spec["metric"]))
        rec["page_setup"]["width"] = float(width)
        rec["page_setup"]["height"] = float(height)
        drawing.tables["layouts"].put(rec)
