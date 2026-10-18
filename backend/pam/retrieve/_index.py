"""Read indexed chunks and embed retrieval queries (SPEC §7.8, §8 M4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

import numpy as np

from pam.contracts.config import PamConfig
from pam.core.vault import Vault

_embedding_models = {}


def connect(vault: Vault) -> sqlite3.Connection:
    """Open the vault index read-only and load sqlite-vec.

    Behavior:
        Uses T06's database helper when it is available, otherwise opens `.pam/index.db` in
        SQLite read-only mode and loads sqlite-vec for vector queries.
    Exceptions:
        sqlite3.Error: The database or sqlite-vec cannot be opened.
    Returns:
        A read-only SQLite connection.
    Parameters:
        vault: Vault whose index is opened.
    """
    try:
        from pam.index import db  # type: ignore[attr-defined]
    except ImportError:
        db = None
    if db is not None and hasattr(db, "connect"):
        return db.connect(vault)
    path = Path(vault.index_db)
    conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    try:
        import sqlite_vec

        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    return conn


def embed_query(text: str, cfg: PamConfig) -> list[float]:
    """Embed and L2-normalize one prefixed search query.

    Behavior:
        Uses T06's embedder when available, otherwise caches FastEmbed models by name and returns
        a normalized float32 vector.
    Exceptions:
        ImportError: FastEmbed is unavailable.
        ValueError: The embedder returns a zero vector.
    Returns:
        The normalized query vector as Python floats.
    Parameters:
        text: Unprefixed query text.
        cfg: Effective vault configuration.
    """
    try:
        from pam.index import embedder  # type: ignore[attr-defined]
    except ImportError:
        embedder = None
    if embedder is not None and hasattr(embedder, "embed_query"):
        return embedder.embed_query(text, cfg)
    if cfg.embedding.model not in _embedding_models:
        from fastembed import TextEmbedding

        _embedding_models[cfg.embedding.model] = TextEmbedding(cfg.embedding.model)
    raw = next(_embedding_models[cfg.embedding.model].query_embed(cfg.embedding.query_prefix + text))
    vector = np.asarray(raw, dtype=np.float32)
    norm = float(np.linalg.norm(vector))
    if not norm:
        raise ValueError("query embedding is a zero vector")
    return (vector / norm).astype(np.float32).tolist()


def doc_token_counts(conn: sqlite3.Connection, doc_ids: Iterable[str]) -> dict[str, int]:
    """Return indexed full-document token counts for selected IDs.

    Behavior:
        Reads only the §7.8 `documents` table and returns existing IDs.
    Returns:
        A mapping from document ID to full-document token count.
    Parameters:
        conn: Open index connection.
        doc_ids: Document IDs to look up.
    """
    ids = sorted(set(map(str, doc_ids)))
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    return {
        str(row[0]): int(row[1])
        for row in conn.execute(f"SELECT doc_id, token_count FROM documents WHERE doc_id IN ({placeholders})", ids)
    }
