"""`GET /api/graph`: the project and episode graph (SPEC §7.14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pam.api.deps import get_vault
from pam.cluster.graph import build_graph
from pam.contracts.graph import GraphData
from pam.core.vault import Vault

router = APIRouter(tags=["graph"])


@router.get("/graph", response_model=GraphData)
def get_graph(agent: str = "default", facts: bool = False, vault: Vault = Depends(get_vault)) -> GraphData:
    """Return the graph an agent is allowed to see.

    Exceptions:
        PamError: The agent does not exist (404).
    Returns:
        Nodes and links; fact nodes only when `facts` is true.
    Parameters:
        agent: Agent whose scope filters the graph.
        facts: Include fact nodes.
        vault: The served vault.
    """
    return build_graph(vault, agent, facts)
