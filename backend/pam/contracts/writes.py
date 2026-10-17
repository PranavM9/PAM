"""§7.11 Writes (MCP tool inputs + result) — transcribed verbatim from SPEC.md."""

from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from .common import PamModel, SnakeKey
from .fact import Cardinality, FactCategory, Fact
from .raw import RawMessage

class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")

class AddFactInput(_In):
    subject: str = "user"
    attribute: SnakeKey
    value: str = Field(min_length=1)
    category: FactCategory
    cardinality: Cardinality = Cardinality.SINGLE
    confidence: float = Field(default=0.8, ge=0, le=1)
    shared: bool = True                  # write to memory/shared (needs write="shared")
    episode_id: UUID | None = None

class SupersedeFactInput(_In):
    fact_id: UUID
    new_value: str = Field(min_length=1)
    reason: str = Field(min_length=1)    # e.g. "user confirmed they transferred to UW"
    episode_id: UUID | None = None

class LogEpisodeInput(_In):
    title: str
    messages: list[RawMessage] = Field(min_length=1)
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)

class UpdateProjectInput(_In):
    project_id: UUID | None = None       # None ⇒ create new project (name required)
    name: str | None = None
    note: str | None = None              # appended to ## Notes
    add_episode_ids: list[UUID] = Field(default_factory=list)
    status: str | None = Field(default=None, pattern=r"^(active|dormant)$")

class AddSkillInput(_In):
    name: str
    description: str
    steps_markdown: str
    trigger_keywords: list[str] = Field(default_factory=list)

class UpdateWorkingMemoryInput(_In):
    session_id: str
    goal: str | None = None
    add_decisions: list[str] = Field(default_factory=list)
    add_open_questions: list[str] = Field(default_factory=list)

class GetEpisodeInput(_In):
    episode_id: UUID
    max_tokens: int = Field(default=4000, ge=256, le=32000)   # transcript truncated from the middle

class WriteResult(PamModel):
    ok: bool
    action: str                          # "add_fact" | "supersede_fact" | …
    doc_id: UUID | None = None
    path: str | None = None
    commit_sha: str | None = None
    conflict: Fact | None = None         # set if the write revealed a conflict
    message: str
