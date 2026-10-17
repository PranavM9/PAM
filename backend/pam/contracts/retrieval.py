"""§7.9 Retrieval — transcribed verbatim from SPEC.md."""

from typing import Literal
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from .common import PamModel, Slug, Source, VaultPath
from .fact import Fact
from .agent import Persona
from .working import WorkingMemory

DocType = Literal["episode", "fact", "project", "skill"]

class SearchQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    agent: Slug = "default"
    k: int = Field(default=8, ge=1, le=50)
    doc_types: list[DocType] | None = None
    since: AwareDatetime | None = None

class SearchHit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chunk_id: str
    doc_id: UUID
    doc_type: DocType
    scope: str
    title: str | None
    snippet: str = Field(max_length=500)
    path: VaultPath
    score: float                         # final fused score (higher = better)
    vector_rank: int | None              # 1-based; None if not in vector candidates
    keyword_rank: int | None             # 1-based; None if not in FTS candidates
    created_at: AwareDatetime | None

class SearchResponse(PamModel):
    query: str
    agent: Slug
    hits: list[SearchHit]
    took_ms: int

class ContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1)
    agent: Slug = "default"
    session_id: str | None = None
    token_budget: int | None = Field(default=None, ge=256, le=32000)  # None ⇒ agent default
    include_persona: bool = True

class ProjectBrief(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    name: str
    keywords: list[str]
    status: Literal["active", "dormant"]
    last_activity_at: AwareDatetime
    summary: str

class EpisodeSnippet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: UUID
    title: str
    source: Source
    created_at: AwareDatetime
    text: str
    chunk_ids: list[str]

class ContextBundle(PamModel):
    agent: Slug
    query: str
    persona: Persona | None
    facts: list[Fact]
    conflicts: list[Fact]                # status == conflict; always included when relevant
    projects: list[ProjectBrief]
    episodes: list[EpisodeSnippet]
    working: WorkingMemory | None
    rendered: str                        # markdown block ready to inject into a system prompt
    tokens_used: int                     # tiktoken cl100k_base count of `rendered`
    token_budget: int
    baseline_tokens: int                 # full transcripts of every episode a snippet came from
    tokens_saved: int                    # max(0, baseline_tokens - tokens_used)
    tokenizer: Literal["cl100k_base"] = "cl100k_base"
    generated_at: AwareDatetime
