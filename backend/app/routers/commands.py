from fastapi import APIRouter

from app.cmd import registry

router = APIRouter(tags=["commands"])


@router.get("")
def catalogue() -> dict:
    return {"commands": registry.catalogue()}


@router.get("/suggest")
def suggest(prefix: str = "", limit: int = 8) -> dict:
    return {"items": registry.suggest(prefix, max(1, min(limit, 50)))}
