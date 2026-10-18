"""Scope-filtered hybrid retrieval over the vault index (SPEC §7.9, §8 M6)."""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import UTC, datetime

from sqlite_vec import serialize_float32

from pam.agents.manifest import load_manifest
from pam.agents.permissions import visible_doc_filter
from pam.contracts.config import PamConfig, RetrievalCfg
from pam.contracts.retrieval import SearchHit, SearchQuery, SearchResponse
from pam.core.config import load as load_config
from pam.core.vault import Vault
from pam.retrieve import _index

RESTRICTED_OVERFETCH = 3  # §8 M6 step 3: over-fetch x3 when the agent is restricted
MAX_CHUNKS_PER_DOC = 2  # §8 M6 step 6
SNIPPET_CHARS = 500  # §7.9 SearchHit.snippet max_length
_TOKEN = re.compile(r"[\w]+(?:['’][\w]+)*", re.UNICODE)


def rrf_fuse(ranked_lists: list[list[int]], rrf_k: int) -> dict[int, float]:
    """Fuse ranked row IDs with Reciprocal Rank Fusion.

    Behavior:
        Each list adds `1 / (rrf_k + rank)` for every row ID it contains, with 1-based ranks.
    Returns:
        The fused score of every row ID found in any list.
    Parameters:
        ranked_lists: Ranked row IDs from each retrieval method.
        rrf_k: Reciprocal-rank smoothing constant.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, rowid in enumerate(ranked, 1):
            scores[rowid] = scores.get(rowid, 0.0) + 1 / (rrf_k + rank)
    return scores


def recency_multiplier(age_days: float, cfg: RetrievalCfg) -> float:
    """Return the recency boost `1 + recency_weight * 0.5 ** (age_days / half_life)`.

    Returns:
        The multiplier applied to a fused score.
    Parameters:
        age_days: Document age in days.
        cfg: Retrieval configuration (or any object with the same two fields).
    """
    return 1 + cfg.recency_weight * 0.5 ** (age_days / cfg.recency_half_life_days)


def sanitize_fts(query: str) -> str:
    """Turn user text into a safe FTS5 query of quoted terms joined with `OR`.

    Behavior:
        Word tokens are double-quoted (embedded quotes doubled), so FTS operators and punctuation
        lose their meaning. Text without word tokens gives `""`, which matches nothing.
    Returns:
        The FTS5 query string.
    Parameters:
        query: User query.
    """
    terms = _TOKEN.findall(query)
    if not terms:
        return '""'
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def query_terms(text: str) -> list[str]:
    """Return the lowercased word tokens of a text, as `sanitize_fts` sees them."""
    return [term.lower() for term in _TOKEN.findall(text)]


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _vector_ranks(conn: sqlite3.Connection, query: str, cfg: PamConfig, k: int) -> dict[int, int]:
    vector = _index.embed_query(query, cfg)
    rows = conn.execute(
        "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ? ORDER BY distance",
        (serialize_float32(list(map(float, vector))), k),
    ).fetchall()
    return {int(row[0]): rank for rank, row in enumerate(rows, 1)}


def _keyword_ranks(conn: sqlite3.Connection, query: str, k: int) -> dict[int, int]:
    try:
        rows = conn.execute(
            "SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts), rowid LIMIT ?",
            (sanitize_fts(query), k),
        ).fetchall()
    except sqlite3.OperationalError:
        return {}  # §8 M6 Edge cases: an FTS error falls back to vector-only search
    return {int(row[0]): rank for rank, row in enumerate(rows, 1)}


def search(vault: Vault, q: SearchQuery) -> SearchResponse:
    """Run scope-filtered hybrid search: vector + keyword, RRF, recency, dedup.

    Behavior:
        Takes `candidate_k` nearest chunks from `chunks_vec` and the `candidate_k` best BM25
        chunks from `chunks_fts` (x3 for a restricted agent), fuses their ranks with RRF, drops
        chunks outside the agent's `ReadScope`, `doc_types`, or `since`, multiplies by the recency
        boost, and keeps at most two chunks per document, best first, up to `k`. A vault without
        an index or without chunks returns no hits and loads no model. An FTS syntax error falls
        back to vector-only. Read-only: the vault and the index are never changed.
    Exceptions:
        PamError: The agent does not exist, or the index was built with another embedding model.
    Returns:
        The hits and the elapsed milliseconds.
    Parameters:
        vault: Vault to search.
        q: Search request.
    """
    started = time.perf_counter()
    cfg = load_config(vault)
    agent = load_manifest(q.agent, vault)

    def response(hits: list[SearchHit]) -> SearchResponse:
        return SearchResponse(query=q.query, agent=q.agent, hits=hits, took_ms=int((time.perf_counter() - started) * 1000))

    conn = _index.connect(vault)
    if conn is None:
        return response([])
    try:
        _index.check_model(conn, cfg)
        if conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone() is None:
            return response([])
        candidate_k = cfg.retrieval.candidate_k * (1 if agent.read.all else RESTRICTED_OVERFETCH)
        vector_ranks = _vector_ranks(conn, q.query, cfg, candidate_k)
        keyword_ranks = _keyword_ranks(conn, q.query, candidate_k)
        fused = rrf_fuse([list(vector_ranks), list(keyword_ranks)], cfg.retrieval.rrf_k)
        if not fused:
            return response([])

        scope_sql, scope_params = visible_doc_filter(agent, vault, alias="d")
        rowids = sorted(fused)
        sql = (
            "SELECT c.rowid, c.chunk_id, c.doc_id, c.text, d.doc_type, d.scope, d.title, d.path, d.created_at "
            "FROM chunks c JOIN documents d ON d.doc_id = c.doc_id "
            f"WHERE c.rowid IN ({','.join('?' for _ in rowids)}) AND {scope_sql}"
        )
        params: list[object] = [*rowids, *scope_params]
        if q.doc_types:
            sql += f" AND d.doc_type IN ({','.join('?' for _ in q.doc_types)})"
            params.extend(q.doc_types)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    now = datetime.now(UTC)
    hits = []
    for rowid, chunk_id, doc_id, text, doc_type, scope, title, path, created in rows:
        created_at = _parse_time(created)
        if q.since is not None and (created_at is None or created_at < q.since):
            continue
        score = fused[int(rowid)]
        if created_at is not None:
            score *= recency_multiplier(max(0.0, (now - created_at).total_seconds() / 86400), cfg.retrieval)
        hits.append(SearchHit(
            chunk_id=chunk_id, doc_id=doc_id, doc_type=doc_type, scope=scope, title=title,
            snippet=str(text)[:SNIPPET_CHARS], path=path, score=score,
            vector_rank=vector_ranks.get(int(rowid)), keyword_rank=keyword_ranks.get(int(rowid)), created_at=created_at,
        ))
    hits.sort(key=lambda h: (-h.score, h.chunk_id))

    selected: list[SearchHit] = []
    per_doc: dict[str, int] = {}
    for hit in hits:
        key = str(hit.doc_id)
        if per_doc.get(key, 0) >= MAX_CHUNKS_PER_DOC:
            continue
        per_doc[key] = per_doc.get(key, 0) + 1
        selected.append(hit)
        if len(selected) >= q.k:
            break
    return response(selected)
