import sys
from pathlib import Path

from fastapi import APIRouter

from app.core import config
from app.services import kernel

router = APIRouter(tags=["system"])

KINDS = {
    ".fcad": "project",
    ".dxf": "dxf",
    ".dwg": "dwg",
    ".step": "step",
    ".stp": "step",
    ".iges": "iges",
    ".igs": "iges",
    ".3dm": "3dm",
    ".stl": "stl",
    ".3mf": "3mf",
    ".obj": "obj",
    ".svg": "svg",
    ".pdf": "pdf",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}
MAX_ITEMS = 500
MAX_DEPTH = 4


@router.get("/health")
def health() -> dict:
    return {"ok": True, "version": config.VERSION}


@router.get("/capabilities")
def capabilities() -> dict:
    return {
        "version": config.VERSION,
        "platform": sys.platform,
        "dataDir": str(config.data_dir()),
        "dataDirSource": config.data_dir_source(),
        "kernel": kernel.describe(),
        "desktop": config.is_desktop(),
    }


def listing(folder: Path, kinds: set[str] | None = None, limit: int = MAX_ITEMS) -> list[dict]:
    items: list[dict] = []
    base = folder.resolve()

    def walk(current: Path, depth: int) -> None:
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                if depth < MAX_DEPTH:
                    walk(entry, depth + 1)
                continue
            kind = KINDS.get(entry.suffix.lower())
            if kind is None or (kinds is not None and kind not in kinds):
                continue
            try:
                info = entry.stat()
            except OSError:
                continue
            items.append({"name": entry.name, "path": str(entry), "size": info.st_size, "modified": info.st_mtime, "kind": kind})

    walk(base, 0)
    items.sort(key=lambda item: item["modified"], reverse=True)
    return items[:limit]


@router.get("/recent")
def recent() -> dict:
    return {"items": listing(config.projects_dir(), {"project"}, 24)}


@router.get("/library")
def library() -> dict:
    return {"items": listing(config.projects_dir())}


@router.get("/outputs")
def outputs() -> dict:
    return {"items": listing(config.outputs_dir())}
