"""§7.2 RawConversation (M1 output → M2 input) — transcribed verbatim from SPEC.md."""

from typing import Any, Literal
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Source

class AttachmentRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    kind: Literal["image", "file", "other"]
    mime_type: str | None = None

class RawMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant", "system", "tool"]
    text: str
    created_at: AwareDatetime | None = None
    attachments: list[AttachmentRef] = Field(default_factory=list)

class RawConversation(PamModel):
    source: Source
    source_conversation_id: str = Field(min_length=1)
    title: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    summary: str | None = None          # provider-supplied summary if present, else None
    messages: list[RawMessage]
    source_metadata: dict[str, Any] = Field(default_factory=dict)
