"""Read-only access to the derived index and query embedding for retrieval (SPEC §7.8, §8 M6)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

import numpy as np
import sqlite_vec

from pam.contracts.config import PamConfig
from pam.core.errors import PamError
from pam.core.vault import Vault
from pam.index import indexer

BUSY_TIMEOUT_S = 10.0  # same wait as the indexer's connection


def connect(vault: Vault) -> sqlite3.Connection | None:
    """Open the vault index read-only with sqlite-vec loaded.

    Behavior:
        Never creates or changes `.pam/index.db`; a vault that was never indexed has no index.
    Exceptions:
        PamError: This Python cannot load SQLite extensions.
    Returns:
        A read-only connection, or `None` when `index.db` does not exist.
    Parameters:
        vault: Vault whose index is opened.
    """
    if not vault.index_db.is_file():
        return None
    conn = sqlite3.connect(f"{vault.index_db.as_uri()}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_S)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        conn.close()
        raise PamError(f"cannot load sqlite-vec ({exc}); use the uv-managed Python or Docker") from exc
    return conn


def check_model(conn: sqlite3.Connection, cfg: PamConfig) -> None:
    """Refuse an index built with a different embedding model than the config names.

    Behavior:
        Compares `meta.embedding_model` with `embedding.model`; an index without the key passes.
    Exceptions:
        PamError: The models differ (§7.8: the index must be rebuilt).
    Parameters:
        conn: Open index connection.
        cfg: Effective vault configuration.
    """
    row = conn.execute("SELECT value FROM meta WHERE key = 'embedding_model'").fetchone()
    if row and row[0] != cfg.embedding.model:
        raise PamError(
            f"the index was built with {row[0]} but the config says {cfg.embedding.model}; run `pam index --rebuild`"
        )


def embed_query(text: str, cfg: PamConfig) -> np.ndarray:
    """Embed a search query with the same embedder the indexer uses.

    Behavior:
        Goes through `pam.index.indexer.get_embedder`, so queries and documents always share one
        model instance and query prefix.
    Returns:
        One L2-normalized float32 vector.
    Parameters:
        text: Query text without the prefix.
        cfg: Effective vault configuration.
    """
    return indexer.get_embedder(cfg.embedding).embed_query(text)


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
