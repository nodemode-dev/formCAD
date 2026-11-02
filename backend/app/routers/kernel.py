from fastapi import APIRouter

from app.services import kernel

router = APIRouter(tags=["kernel"])


@router.get("/status")
def status() -> dict:
    kernel.probe()
    return kernel.status()


@router.post("/install")
def install() -> dict:
    return kernel.start_install()
