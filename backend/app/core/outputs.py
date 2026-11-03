import os


class OutputRefused(Exception):
    pass


def _class_of(head: bytes) -> str:
    if head[:2] == b"PK":
        return "zip"
    if head[:2] == b"AC":
        return "dwg"
    if head[:5] == b"%PDF-":
        return "pdf"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if b"\x00" in head:
        return "binary"
    return "text"


EXPECT = {".fcad": ("zip",), ".dwg": ("dwg",), ".pdf": ("pdf",), ".png": ("png",), ".dwt": ("text", "dwg", "zip"), ".dxf": ("text", "binary"), ".stl": ("text", "binary"), ".3dm": ("text", "binary"), ".3mf": ("zip",), ".zip": ("zip",), ".glb": ("binary",), ".gltf": ("text", "binary"), ".ply": ("text", "binary"), ".mp4": ("binary",), ".webm": ("text", "binary")}


def checked(path: str, allowed: tuple, default: str = "") -> str:
    raw = os.path.expanduser(str(path or "").strip())
    if not raw or "\x00" in raw:
        raise OutputRefused("An output file name is required.")
    full = os.path.abspath(raw)
    if os.path.isdir(full):
        raise OutputRefused("An output file name is required.")
    ext = os.path.splitext(full)[1].lower()
    if not ext and default:
        full += default
        ext = default
    if ext not in allowed:
        raise OutputRefused("That file type is not written here. Use one of: %s." % ", ".join(allowed))
    if not os.path.isdir(os.path.dirname(full)):
        raise OutputRefused("The folder %s does not exist." % os.path.dirname(full))
    if os.path.lexists(full):
        real = os.path.realpath(full)
        if not os.path.isfile(real):
            raise OutputRefused("That name is not a regular file.")
        try:
            with open(real, "rb") as fh:
                head = fh.read(16)
        except OSError:
            raise OutputRefused("The existing file cannot be read, so it is not replaced.")
        if head:
            want = EXPECT.get(ext, ("text",))
            if _class_of(head) not in want:
                raise OutputRefused("%s already exists and is a different kind of file; it is not replaced." % os.path.basename(full))
    return full
