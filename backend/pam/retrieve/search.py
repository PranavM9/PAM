"""Scope-filtered hybrid retrieval over the vault index."""

from __future__ import annotations

import re
import sqlite3
import time
from datetime import UTC, datetime

from pam.agents.manifest import load_manifest
from pam.agents.permissions import visible_doc_filter
from pam.contracts.retrieval import SearchHit, SearchQuery, SearchResponse
from pam.core.config import load as load_config
from pam.core.vault import Vault
from pam.retrieve import _index

_TOKEN = re.compile(r"[\w]+(?:['’][\w]+)*", re.UNICODE)


def rrf_fuse(ranked_lists: list[list[int]], rrf_k: int) -> dict[int, float]:
    """Fuse ranked row IDs using reciprocal rank contributions.

    Behavior:
        Ranks are one-based positions in each input list.
    Returns:
        A score for every row ID in any list.
    Parameters:
        ranked_lists: Ranked row IDs from retrieval methods.
        rrf_k: Reciprocal-rank smoothing constant.
    """
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, rowid in enumerate(ranked, 1):
            scores[rowid] = scores.get(rowid, 0.0) + 1 / (rrf_k + rank)
    return scores


def recency_multiplier(age_days: float, cfg) -> float:
    """Return the configured exponential recency boost.

    Behavior:
        Applies the half-life decay in `RetrievalCfg` without changing the configured age.
    Returns:
        The multiplier applied to the fused score.
    Parameters:
        age_days: Document age in days.
        cfg: Retrieval configuration or a compatible test object.
    """
    return 1 + cfg.recency_weight * 0.5 ** (age_days / cfg.recency_half_life_days)


def sanitize_fts(query: str) -> str:
    """Quote each searchable token and join terms with FTS `OR`.

    Behavior:
        Embedded double quotes are escaped. Punctuation and operators are treated as separators.
        An empty query emits an impossible phrase, avoiding a syntax error.
    Returns:
        A safe FTS5 query.
    Parameters:
        query: User query.
    """
    terms = _TOKEN.findall(query)
    if not terms:
        return '""'
    return " OR ".join('"' + term.replace('"', '""') + '"' for term in terms)


def _vector_bytes(vector: list[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(vector)


def search(vault: Vault, q: SearchQuery) -> SearchResponse:
    """Run scope-filtered vector and keyword search.

    Behavior:
        Queries both index tables, fuses candidate ranks, applies permission and query filters,
        boosts recent documents, and returns at most two chunks per document.
    Returns:
        Ranked search hits and elapsed milliseconds.
    Parameters:
        vault: Vault to search.
        q: Search request.
    """
    started = time.perf_counter()
    cfg = load_config(vault)
    try:
        conn = _index.connect(vault)
    except (sqlite3.Error, OSError, ImportError):
        return SearchResponse(query=q.query, agent=q.agent, hits=[], took_ms=int((time.perf_counter() - started) * 1000))
    try:
        agent = load_manifest(q.agent, vault)
        scope_sql, scope_params = visible_doc_filter(agent, vault, alias="d")
        restricted = not agent.read.all
        candidate_k = cfg.retrieval.candidate_k * (3 if restricted else 1)
        vector_ranks: dict[int, int] = {}
        keyword_ranks: dict[int, int] = {}
        try:
            query_vector = _index.embed_query(q.query, cfg)
            rows = conn.execute(
                "SELECT rowid, distance FROM chunks_vec WHERE embedding MATCH ? AND k = ?",
                (_vector_bytes(query_vector), candidate_k),
            ).fetchall()
            vector_ranks = {int(row[0]): rank for rank, row in enumerate(rows, 1)}
        except (sqlite3.Error, ImportError, ValueError):
            vector_ranks = {}
        try:
            rows = conn.execute(
                "SELECT rowid, bm25(chunks_fts) FROM chunks_fts WHERE chunks_fts MATCH ? "
                "ORDER BY bm25(chunks_fts) LIMIT ?",
                (sanitize_fts(q.query), candidate_k),
            ).fetchall()
            keyword_ranks = {int(row[0]): rank for rank, row in enumerate(rows, 1)}
        except sqlite3.OperationalError:
            keyword_ranks = {}
        fused = rrf_fuse([list(vector_ranks), list(keyword_ranks)], cfg.retrieval.rrf_k)
        if not fused:
            return SearchResponse(query=q.query, agent=q.agent, hits=[], took_ms=int((time.perf_counter() - started) * 1000))
        rowids = sorted(fused)
        placeholders = ",".join("?" for _ in rowids)
        sql = (
            "SELECT c.rowid, c.chunk_id, c.doc_id, c.text, d.doc_type, d.scope, d.title, d.path, d.created_at "
            "FROM chunks c JOIN documents d ON d.doc_id=c.doc_id "
            f"WHERE c.rowid IN ({placeholders}) AND {scope_sql}"
        )
        params: list[object] = list(rowids) + list(scope_params)
        if q.doc_types:
            sql += " AND d.doc_type IN (" + ",".join("?" for _ in q.doc_types) + ")"
            params.extend(q.doc_types)
        if q.since is not None:
            sql += " AND d.created_at >= ?"
            params.append(q.since.astimezone(UTC).isoformat().replace("+00:00", "Z"))
        records = conn.execute(sql, params).fetchall()
        hits = []
        now = datetime.now(UTC)
        for row in records:
            rowid = int(row[0])
            created_at = datetime.fromisoformat(row[8].replace("Z", "+00:00")) if row[8] else None
            score = fused[rowid]
            if created_at:
                score *= recency_multiplier((now - created_at).total_seconds() / 86400, cfg.retrieval)
            hits.append(SearchHit(
                chunk_id=row[1], doc_id=row[2], doc_type=row[4], scope=row[5], title=row[6],
                snippet=str(row[3])[:500], path=row[7], score=score,
                vector_rank=vector_ranks.get(rowid), keyword_rank=keyword_ranks.get(rowid), created_at=created_at,
            ))
        hits.sort(key=lambda h: (-h.score, str(h.doc_id), h.chunk_id))
        selected, counts = [], {}
        for hit in hits:
            if counts.get(str(hit.doc_id), 0) >= 2:
                continue
            selected.append(hit)
            counts[str(hit.doc_id)] = counts.get(str(hit.doc_id), 0) + 1
            if len(selected) >= q.k:
                break
        return SearchResponse(query=q.query, agent=q.agent, hits=selected, took_ms=int((time.perf_counter() - started) * 1000))
    finally:
        conn.close()
