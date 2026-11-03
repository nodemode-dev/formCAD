from fastapi import APIRouter, HTTPException

from app.vault import session
from app.vault.base import VaultError

router = APIRouter(tags=["vault"])


@router.get("/{doc_id}/vault")
def vault_status(doc_id: str) -> dict:
    try:
        return session.status_of(doc_id)
    except VaultError as err:
        raise HTTPException(err.status, err.message)
