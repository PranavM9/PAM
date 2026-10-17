"""§7.12 Graph — transcribed verbatim from SPEC.md (the §7.12 block is split into reports.py + graph.py)."""

from typing import Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel

class GraphNode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["project", "episode", "fact"]
    label: str
    cluster_id: str | None
    size: float                          # project: #episodes; episode: log(message_count+1)
    created_at: AwareDatetime | None
    path: str | None

class GraphLink(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str
    target: str
    kind: Literal["member", "similar", "derived_from"]
    weight: float = Field(ge=0, le=1)

class GraphData(PamModel):
    agent: str
    nodes: list[GraphNode]
    links: list[GraphLink]
    generated_at: AwareDatetime
