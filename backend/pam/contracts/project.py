"""§7.5 Project — transcribed verbatim from SPEC.md."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, Field
from .common import PamModel, Actor, Slug

class Project(PamModel):
    id: UUID                            # uuid4 at creation; stable thereafter
    scope: Slug
    name: str                           # from c-TF-IDF keywords / titles (M5) or set by agent/user
    keywords: list[str] = Field(default_factory=list, max_length=10)
    episode_ids: list[UUID] = Field(default_factory=list)
    origin: Actor                       # cluster | agent | manual
    status: Literal["active", "dormant"] = "active"   # dormant if no activity for N days
    created_at: AwareDatetime
    updated_at: AwareDatetime
    last_activity_at: AwareDatetime
