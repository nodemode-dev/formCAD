from typing import Optional

from fastapi import APIRouter, HTTPException

from app.routers.part import _read
from app.weld import cutlist, records, shapes

router = APIRouter(tags=["weldment"])


def wrap(fn):
    try:
        return fn()
    except (cutlist.CutError, shapes.ShapeError) as err:
        raise HTTPException(400, str(err))


def members_of(d) -> list:
    return records.rows(d, "member")


def parts_of(d) -> list:
    return [r for r in records.rows(d) if r.get("kind") in ("end_cap", "gusset")]


@router.get("/{doc_id}/weld")
def overview(doc_id: str, tolerance: Optional[float] = None) -> dict:
    return _read(doc_id, lambda doc: wrap(lambda: {"frames": records.active_ids(doc.drawing), "members": members_of(doc.drawing), "parts": parts_of(doc.drawing), "cutlist": cutlist.build(doc.drawing, tolerance)}))


@router.get("/{doc_id}/weld/members")
def members(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"members": members_of(doc.drawing)})


@router.get("/{doc_id}/weld/cutlist")
def get_cutlist(doc_id: str, tolerance: Optional[float] = None) -> dict:
    return _read(doc_id, lambda doc: wrap(lambda: cutlist.build(doc.drawing, tolerance)))


@router.get("/{doc_id}/weld/cutlist/csv")
def get_cutlist_csv(doc_id: str, tolerance: Optional[float] = None) -> dict:
    return _read(doc_id, lambda doc: wrap(lambda: {"csv": cutlist.csv_text(doc.drawing, tolerance)}))


@router.get("/{doc_id}/weld/shapes")
def get_shapes(doc_id: str) -> dict:
    return _read(doc_id, lambda doc: {"shapes": shapes.listing()})


LIBRARY_SHAPES = {
    "rect_tube": ("rect_tube", {"b": "w", "h": "h", "t": "t", "outer_r": "r"}),
    "round_tube": ("round_tube", {"od": "d", "t": "t"}),
    "flat_bar": ("flat_bar", {"b": "w", "t": "t"}),
    "angle": ("angle", {"a": "a", "b": "b", "t": "t"}),
}


@router.get("/{doc_id}/weld/library-profile")
def library_profile(doc_id: str, family: str, row: str) -> dict:
    from app.param import units as U
    from app.toolbox import library

    def go(doc):
        try:
            kind, params = library.resolve(family, row)
        except library.LibraryError as err:
            raise HTTPException(400, str(err))
        if kind not in LIBRARY_SHAPES:
            raise HTTPException(400, "The family kind %s has no weld profile; use %s." % (kind, ", ".join(LIBRARY_SHAPES)))
        shape, names = LIBRARY_SHAPES[kind]
        mm = U.mm_per_unit(doc.drawing)
        spec = {"shape": shape}
        for src, dst in names.items():
            if params.get(src) is not None:
                spec[dst] = round(float(params[src]) / mm, 6)
        shapes.regions_of(spec, mm)
        return {"profile": spec, "source": "%s / %s" % (family, row)}

    return _read(doc_id, lambda doc: wrap(lambda: go(doc)))
