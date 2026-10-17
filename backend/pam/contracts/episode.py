"""§7.3 Episode (M2 output; read by M3–M7) — transcribed verbatim from SPEC.md."""

from uuid import UUID, uuid5
from pydantic import AwareDatetime, Field
from .common import PamModel, Source, Slug, Sha256, PAM_NAMESPACE

def episode_id(source: Source, source_conversation_id: str) -> UUID:
    return uuid5(PAM_NAMESPACE, f"episode:{source.value}:{source_conversation_id}")

class EpisodeFrontmatter(PamModel):
    id: UUID
    agent: Slug = "default"
    source: Source
    source_conversation_id: str
    title: str                          # fallback: "Untitled conversation YYYY-MM-DD"
    created_at: AwareDatetime           # fallback: first message time, else imported_at
    updated_at: AwareDatetime
    imported_at: AwareDatetime
    message_count: int = Field(ge=0)
    has_summary: bool
    body_sha256: Sha256                 # sha256 of the UTF-8 body (everything after frontmatter)
    tags: list[str] = Field(default_factory=list)
    superseded_facts: list[UUID] = Field(default_factory=list)  # backlinks appended by M7
