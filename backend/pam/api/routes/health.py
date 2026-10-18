"""`GET /api/health`: liveness for the compose healthcheck and the frontend (SPEC §7.14, CHG-0017 (M15))."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pam.api.deps import get_vault
from pam.core.vault import Vault

log = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


class Health(BaseModel):
    ok: bool
    vault: str
    index_ok: bool


def _index_ok(vault: Vault) -> bool:
    if not vault.index_db.is_file():
        return False
    from pam.index.indexer import stats  # noqa: PLC0415 - keeps module import light

    try:
        stats(vault)
    except Exception as exc:  # noqa: BLE001 - a broken index must not fail the healthcheck
        log.warning("index check failed: %s", exc)
        return False
    return True


@router.get("/health", response_model=Health)
def health(vault: Vault = Depends(get_vault)) -> Health:
    """Report that the API is up, which vault it serves, and whether the index opens.

    Behavior:
        Always answers `ok: true` while the process runs. `index_ok` is false when the index file
        is missing or cannot be read.
    Returns:
        The health report.
    """
    return Health(ok=True, vault=str(vault.root), index_ok=_index_ok(vault))
