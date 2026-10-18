"""Connection and `meta` helpers for the derived index `.pam/index.db` (SPEC §7.8, §8 M4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import sqlite_vec

from pam.core.errors import PamError
from pam.core.vault import Vault

SCHEMA_SQL = Path(__file__).with_name("schema.sql")
VECTOR_DIM = 384  # fixed by `chunks_vec ... float[384]` in schema.sql
INDEX_VERSION = "1"
BUSY_TIMEOUT_S = 10.0  # same wait as `vault_write_lock`


def connect(vault: Vault) -> sqlite3.Connection:
    """Open the index database with sqlite-vec loaded and the §7.8 schema applied.

    Behavior:
        Creates `.pam/` and the database when missing, loads the sqlite-vec extension, switches to
        WAL so readers are not blocked by an indexing run, and runs `schema.sql` (idempotent).
    Exceptions:
        PamError: This Python cannot load SQLite extensions.
    Returns:
        An open connection; the caller closes it.
    Parameters:
        vault: The vault whose index to open.
    """
    vault.index_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(vault.index_db, timeout=BUSY_TIMEOUT_S)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except (AttributeError, sqlite3.OperationalError) as exc:
        conn.close()
        raise PamError(f"cannot load sqlite-vec ({exc}); use the uv-managed Python or Docker") from exc
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    return conn


def delete_index(vault: Vault) -> None:
    """Delete the index database and its WAL files.

    Behavior:
        Used by `--rebuild`; the index is derived, so nothing in the vault is lost. Missing files
        are ignored.
    Parameters:
        vault: The vault whose index to delete.
    """
    for suffix in ("", "-wal", "-shm"):
        Path(f"{vault.index_db}{suffix}").unlink(missing_ok=True)


def get_meta(conn: sqlite3.Connection) -> dict[str, str]:
    """Read the `meta` table.

    Returns:
        Every stored key and value.
    Parameters:
        conn: An open index connection.
    """
    return dict(conn.execute("SELECT key, value FROM meta").fetchall())


def set_meta(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    """Insert or replace `meta` keys.

    Behavior:
        Runs inside the caller's transaction.
    Parameters:
        conn: An open index connection.
        values: Keys and values to store.
    """
    conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", list(values.items()))
