from fastapi import APIRouter

from app.solid import holes

router = APIRouter(tags=["holes"])


@router.get("/table")
def table() -> dict:
    return holes.dialog_data()
