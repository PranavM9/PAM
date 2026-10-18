"""`GET /api/sessions/{id}` and `POST /api/sessions/{id}/end`: working-memory sessions (SPEC §7.14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pam.api.deps import get_vault
from pam.api.errors import CONFLICT, NOT_FOUND, SESSION_ENDED, VALIDATION_ERROR, ApiError
from pam.contracts.working import WorkingMemory
from pam.contracts.writes import WriteResult
from pam.core.vault import Vault
from pam.memory.writer import BUSY_PREFIX
from pam.working import session

router = APIRouter(tags=["sessions"])


@router.get("/sessions/{id}", response_model=WorkingMemory)
def get_session(id: str, vault: Vault = Depends(get_vault)) -> WorkingMemory:  # noqa: A002 - path name fixed by §7.14
    """Return a session with its recent turns.

    Exceptions:
        PamError: The session does not exist (404).
    Returns:
        The working memory.
    Parameters:
        id: Session id (`s_` plus 12 characters).
        vault: The served vault.
    """
    return session.show(vault, id)


@router.post("/sessions/{id}/end", response_model=WriteResult)
def end_session(id: str, vault: Vault = Depends(get_vault)) -> WriteResult:  # noqa: A002 - path name fixed by §7.14
    """Promote a session to an episode and mark it ended.

    Behavior:
        A failed `WriteResult` is turned into an HTTP error: missing session 404, already ended 409
        `SESSION_ENDED`, busy vault or no turns 409, anything else 400.
    Exceptions:
        ApiError: The session cannot be ended.
    Returns:
        The write result of the promoted episode.
    Parameters:
        id: Session id.
        vault: The served vault.
    """
    result = session.end(vault, id)
    if result.ok:
        return result
    text = result.message.lower()
    if "not found" in text:
        raise ApiError(404, NOT_FOUND, result.message)
    if "already ended" in text:
        raise ApiError(409, SESSION_ENDED, result.message)
    if result.message.startswith(BUSY_PREFIX) or "no turns" in text:
        raise ApiError(409, CONFLICT, result.message)
    raise ApiError(400, VALIDATION_ERROR, result.message)
