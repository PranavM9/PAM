"""§7.6 Skill — transcribed verbatim from SPEC.md."""

from uuid import UUID
from pydantic import AwareDatetime, Field
from .common import PamModel, Actor, Slug

class Skill(PamModel):
    id: UUID                            # uuid4
    scope: Slug
    name: str
    description: str
    trigger_keywords: list[str] = Field(default_factory=list)
    source_episodes: list[UUID] = Field(default_factory=list)
    created_by: Actor                   # agent | manual (rule-based skill mining is a stretch goal)
    created_at: AwareDatetime
    updated_at: AwareDatetime
