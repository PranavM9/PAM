"""§7.13 Config (stored as vault/pam.toml) — transcribed verbatim from SPEC.md."""

from pydantic import BaseModel, ConfigDict, Field

class _C(BaseModel):
    model_config = ConfigDict(extra="forbid")

class EmbeddingCfg(_C):
    model: str = "BAAI/bge-small-en-v1.5"; dim: int = 384
    query_prefix: str = "Represent this sentence for searching relevant passages: "
class ChunkCfg(_C):
    max_tokens: int = 512; overlap_tokens: int = 64
class RetrievalCfg(_C):
    candidate_k: int = 50; rrf_k: int = 60
    recency_weight: float = 0.2; recency_half_life_days: float = 30
class ContextCfg(_C):
    default_budget: int = 2000; persona_max_tokens: int = 300
    max_facts: int = 12; max_projects: int = 3
class ClusterCfg(_C):
    min_cluster_size: int = 3; assign_threshold: float = 0.70
    similar_link_threshold: float = 0.75; similar_links_per_node: int = 3
    rebuild_match_jaccard: float = 0.5; dormant_after_days: int = 30
class ExtractCfg(_C):
    rule_min_evidence: int = 2; spacy_model: str = "en_core_web_sm"
class ModelEntry(_C):
    id: str                               # LiteLLM model string, e.g. "openrouter/<org>/<model>:free"
    label: str
    supports_tools: bool = False
class PamConfig(_C):
    schema_version: str = "1.0.0"
    embedding: EmbeddingCfg = EmbeddingCfg(); chunking: ChunkCfg = ChunkCfg()
    retrieval: RetrievalCfg = RetrievalCfg(); context: ContextCfg = ContextCfg()
    clustering: ClusterCfg = ClusterCfg(); extraction: ExtractCfg = ExtractCfg()
    models: list[ModelEntry] = Field(default_factory=list)
    sync_interval_seconds: int = 5
    session_idle_minutes: int = 30            # CHG-0026: idle sessions are ended; 0 turns it off
