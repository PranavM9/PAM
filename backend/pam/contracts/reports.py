"""§7.12 Reports — transcribed verbatim from SPEC.md (the §7.12 block is split into reports.py + graph.py)."""

from typing import Literal
from pydantic import Field
from .common import PamModel, Source

class ImportReport(PamModel):
    source: Source
    input_path: str
    archived_path: str                   # imports/<source>/<ts>/<file>
    conversations_found: int
    episodes_written: int
    episodes_skipped_existing: int
    errors: list[str] = Field(default_factory=list)
    commit_sha: str | None
    duration_ms: int

class DeriveReport(PamModel):
    facts_created: int; facts_updated: int; conflicts_flagged: int
    rules_derived: int; commit_sha: str | None; duration_ms: int

class IndexReport(PamModel):
    documents_indexed: int; documents_unchanged: int; documents_removed_from_index: int
    chunks_written: int; embedding_model: str; duration_ms: int

class ClusterReport(PamModel):
    mode: Literal["incremental", "rebuild"]
    projects_created: int; projects_updated: int; episodes_assigned: int; episodes_unassigned: int
    commit_sha: str | None; duration_ms: int

class SyncReport(PamModel):
    dirty_paths: list[str]; reindexed: int; commit_sha: str | None

class JobStatus(PamModel):               # async import job (API)
    job_id: str
    stage: Literal["queued", "extract", "normalize", "derive", "index", "cluster", "done", "error"]
    progress: float = Field(ge=0, le=1)
    report: ImportReport | None = None
    error: str | None = None
