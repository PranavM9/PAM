"""`POST /api/search` and `POST /api/context`: retrieval endpoints (SPEC §7.14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pam.api.deps import get_vault
from pam.contracts.retrieval import ContextBundle, ContextRequest, SearchQuery, SearchResponse
from pam.core.vault import Vault

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def post_search(query: SearchQuery, vault: Vault = Depends(get_vault)) -> SearchResponse:
    """Run a hybrid search within the agent's read scope.

    Exceptions:
        PamError: The agent does not exist (404) or the index cannot be read.
    Returns:
        The ranked hits.
    Parameters:
        query: The search request.
        vault: The served vault.
    """
    from pam.retrieve.search import search  # noqa: PLC0415 - the embedder import is slow

    return search(vault, query)


@router.post("/context", response_model=ContextBundle)
def post_context(request: ContextRequest, vault: Vault = Depends(get_vault)) -> ContextBundle:
    """Build the context bundle an agent would receive for a query.

    Exceptions:
        PamError: The agent does not exist (404) or the index cannot be read.
    Returns:
        The bundle, within the requested token budget.
    Parameters:
        request: The context request.
        vault: The served vault.
    """
    from pam.retrieve.context import build_context  # noqa: PLC0415

    return build_context(vault, request)
