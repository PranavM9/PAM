"""§7.10 Working memory — transcribed verbatim from SPEC.md."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Slug
from .raw import RawMessage

class ModelSwitch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    at: AwareDatetime
    from_model: str | None
    to_model: str

class WorkingMemory(PamModel):
    session_id: str = Field(pattern=r"^s_[0-9a-z]{12}$")
    agent: Slug
    status: Literal["active", "ended"] = "active"
    started_at: AwareDatetime
    updated_at: AwareDatetime
    models_used: list[ModelSwitch] = Field(default_factory=list)
    goal: str | None = None                 # default: first user message (truncated 200 chars)
    decisions: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    recent_turns: list[RawMessage] = Field(default_factory=list, max_length=8)
    promoted_episode_id: UUID | None = None
