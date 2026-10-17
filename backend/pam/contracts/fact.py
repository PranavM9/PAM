"""§7.4 Fact — transcribed verbatim from SPEC.md."""

import re
from enum import Enum
from uuid import UUID, uuid5
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from .common import PamModel, Actor, SnakeKey, Slug, PAM_NAMESPACE

class FactCategory(str, Enum):
    IDENTITY = "identity"; EDUCATION = "education"; WORK = "work"; LOCATION = "location"
    PREFERENCE = "preference"; TOOLING = "tooling"; PROJECT = "project"
    RELATIONSHIP = "relationship"; OTHER = "other"

class Cardinality(str, Enum):
    SINGLE = "single"   # one value at a time (school, name) → conflicts possible
    MULTI = "multi"     # many values (uses_tool, likes) → values accumulate

class FactStatus(str, Enum):
    ACTIVE = "active"
    CONFLICT = "conflict"

def normalize_value(v: str) -> str:
    return re.sub(r"\s+", " ", v.strip().lower())

def fact_id(scope: str, subject: str, attribute: str, cardinality: Cardinality, value: str) -> UUID:
    key = f"fact:{scope}:{subject}:{attribute}"
    if cardinality is Cardinality.MULTI:
        key += f":{normalize_value(value)}"
    return uuid5(PAM_NAMESPACE, key)

class FactHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str
    changed_at: AwareDatetime
    changed_by: Actor
    agent: Slug | None = None
    episode_id: UUID | None = None
    reason: str | None = None

class FactConflict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_value: str
    candidate_source_episode: UUID | None = None
    detected_at: AwareDatetime
    detected_by: Actor

class Fact(PamModel):
    id: UUID
    scope: str                          # "shared" or an agent Slug
    subject: str = "user"
    attribute: SnakeKey                 # e.g. "school", "works_at", "uses_tool"
    value: str = Field(min_length=1)
    cardinality: Cardinality
    category: FactCategory
    confidence: float = Field(ge=0.0, le=1.0)
    status: FactStatus = FactStatus.ACTIVE
    conflict: FactConflict | None = None
    source_episode: UUID | None = None      # where the CURRENT value came from
    updated_by_episode: UUID | None = None  # episode that last changed it
    extractor: Actor
    pattern_id: str | None = None           # M3 pattern that produced it
    created_at: AwareDatetime
    updated_at: AwareDatetime
    history: list[FactHistoryEntry] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def _conflict_consistency(self):
        if (self.status is FactStatus.CONFLICT) != (self.conflict is not None):
            raise ValueError("status=conflict iff conflict is set")
        return self
