"""§7.7 Agent & Persona — transcribed verbatim from SPEC.md."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from .common import PamModel, Slug, RESERVED_SCOPES

ToolName = Literal[
    "get_context", "search_memory", "get_episode", "list_agents",
    "add_fact", "supersede_fact", "log_episode", "update_project",
    "add_skill", "update_working_memory",
]
READ_TOOLS = {"get_context", "search_memory", "get_episode", "list_agents"}

class ReadScope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: bool = False                       # True ⇒ every scope (default agent)
    project_ids: list[UUID] = Field(default_factory=list)   # episodes/projects visible
    include_shared_facts: bool = True
    include_own_memory: bool = True         # memory/<self>/**
    include_skills_from: list[Slug] = Field(default_factory=list)

class AgentManifest(PamModel):
    name: Slug
    display_name: str
    description: str = ""
    origin: Literal["derived", "custom"]
    created_at: AwareDatetime
    read: ReadScope
    write: Literal["none", "own", "shared"] = "own"   # shared ⇒ own + memory/shared
    tools: list[ToolName]
    default_model: str | None = None        # LiteLLM model string
    token_budget: int = Field(default=2000, ge=256, le=32000)

    @field_validator("name")
    @classmethod
    def _not_reserved(cls, v: str) -> str:
        if v in RESERVED_SCOPES:
            raise ValueError("reserved name")
        return v

class PersonaRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str                                 # "r_" + first 8 hex of sha256(normalized text)
    text: str
    origin: Literal["derived", "manual"]
    evidence_count: int = Field(ge=0)
    evidence_episodes: list[UUID] = Field(default_factory=list, max_length=5)

class Persona(BaseModel):
    model_config = ConfigDict(extra="forbid")
    agent: Slug
    identity: str                           # rendered markdown
    rules: list[PersonaRule]
    style: str                              # rendered markdown
