"""`/api/connectors`: list, read, save, archive and test-call connectors (SPEC §8 M16 REST, CHG-0027)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends

from pam.api.deps import get_vault
from pam.api.errors import VALIDATION_ERROR, ApiError
from pam.connectors import executor, store
from pam.contracts.connector import Connector, ConnectorResult
from pam.core.vault import Vault

router = APIRouter(tags=["connectors"])


@router.get("/connectors", response_model=list[Connector])
def list_connectors(include_archived: bool = False, vault: Vault = Depends(get_vault)) -> list[Connector]:
    """List the valid connectors in id order; archived ones only with `include_archived=true`."""
    return store.list_connectors(vault, include_archived=include_archived)


@router.get("/connectors/{id}", response_model=Connector)
def get_connector(id: str, vault: Vault = Depends(get_vault)) -> Connector:
    """Return one connector, archived or not (404 if unknown, 400 if its file is invalid)."""
    return store.get_connector(vault, id)


@router.put("/connectors/{id}", response_model=Connector)
def put_connector(id: str, connector: Connector, vault: Vault = Depends(get_vault)) -> Connector:
    """Create or replace a connector; one commit, none if nothing changed.

    Behavior:
        The path id must equal `connector.id`, otherwise 400. A busy vault is 409.
    Returns:
        The stored connector.
    Parameters:
        id: Connector id from the path.
        connector: The connector to store.
    """
    if connector.id != id:
        raise ApiError(400, VALIDATION_ERROR, "connector.id must match the URL")
    store.save_connector(vault, connector)
    return store.get_connector(vault, id)


@router.post("/connectors/{id}/archive", response_model=Connector)
def archive_connector(id: str, vault: Vault = Depends(get_vault)) -> Connector:
    """Archive a connector (`archived: true`, `enabled: false`) instead of deleting it; 404 if unknown."""
    store.archive_connector(vault, id)
    return store.get_connector(vault, id)


@router.post("/connectors/{id}/tools/{tool}/call", response_model=ConnectorResult)
async def call_tool(
    id: str, tool: str, args: dict[str, Any] = Body(default_factory=dict), vault: Vault = Depends(get_vault),
) -> ConnectorResult:
    """Run one connector tool with the posted arguments object.

    Behavior:
        Service and argument problems are an `ok: false` result with status 200; an unknown connector
        or tool is 404.
    Returns:
        The connector result.
    Parameters:
        id: Connector id.
        tool: Tool name.
        args: The arguments object (the request body; empty when there is none).
    """
    return await executor.call(vault, id, tool, args)
