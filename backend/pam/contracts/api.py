"""§7.14 REST + SSE (M13 ↔ M14) — transcribed verbatim from SPEC.md."""

from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field
from .common import Slug
from .connector import ConnectorCard

class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str | None = None         # None ⇒ new session
    agent: Slug = "default"
    model: str                            # must match a PamConfig.models[].id
    message: str = Field(min_length=1)
    mode: Literal["injection", "tool"] = "injection"

class ContextEvent(BaseModel):
    type: Literal["context"] = "context"
    session_id: str; tokens_used: int; baseline_tokens: int; tokens_saved: int
    doc_ids: list[UUID]; rendered: str
class TokenEvent(BaseModel):
    type: Literal["token"] = "token"; text: str
class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"; name: str; arguments: dict; result_summary: str
    cards: list[ConnectorCard] = []       # CHG-0027: connector display cards; empty for MCP tools
class DoneEvent(BaseModel):
    type: Literal["done"] = "done"; session_id: str; model: str
    prompt_tokens: int | None; completion_tokens: int | None
class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"; message: str; retryable: bool

ChatEvent = Annotated[Union[ContextEvent, TokenEvent, ToolCallEvent, DoneEvent, ErrorEvent],
                      Field(discriminator="type")]
