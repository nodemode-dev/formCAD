import os
import shutil

from app.interchange import dwg, dxf_read, dxf_write
from app.interchange.errors import InterchangeError, Report

_done = False


def read_dxf_drawing(path: str, report: Report | None = None):
    drawing, rep = dxf_read.read_file(path, report=report or Report())
    from app.doc.kinds import blockcache

    blockcache.refresh_all(drawing)
    return drawing


def read_dwg_drawing(path: str, report: Report | None = None):
    produced, work = dwg.dwg_to_dxf(path)
    try:
        return read_dxf_drawing(produced, report)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def write_dxf_hook(drawing, path, precision=16):
    dxf_write.write_file(drawing, path, None, Report(), precision)


def write_dwg_hook(drawing, path, precision=16):
    import tempfile

    with tempfile.TemporaryDirectory(prefix="fcdwgw_") as tmp:
        mid = os.path.join(tmp, "tmp.dxf")
        rep = Report()
        dxf_write.write_file(drawing, mid, "R2018", rep, precision)
        dwg.dxf_to_dwg(mid, path, "R2018")


def _xref_wrap(fn):
    def run(path):
        from app.doc.xref import XrefError

        try:
            return fn(path)
        except InterchangeError as err:
            raise XrefError(str(err))

    return run


def install() -> None:
    global _done
    if _done:
        return
    _done = True
    from app.doc import blockio, xref

    blockio.DXF_WRITER = write_dxf_hook
    blockio.DWG_WRITER = write_dwg_hook
    for ext, fn in ((".dxf", read_dxf_drawing), (".dwg", read_dwg_drawing)):
        blockio.register_reader(ext, fn)
        xref.register_reader(ext, _xref_wrap(fn))
