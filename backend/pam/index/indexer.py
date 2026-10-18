"""Keep `.pam/index.db` in sync with the vault: chunk, embed, and store documents (SPEC §8 M4)."""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
import warnings
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pydantic import ValidationError
from sqlite_vec import serialize_float32

from pam.contracts.common import SCHEMA_VERSION
from pam.contracts.config import PamConfig
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Fact
from pam.contracts.project import Project
from pam.contracts.reports import IndexReport
from pam.contracts.skill import Skill
from pam.core import config, mdio, tokens
from pam.core.errors import PamError
from pam.core.time import iso_z, utcnow
from pam.core.vault import Vault
from pam.index import chunker, db
from pam.index.embedder import Embedder, get_embedder, l2_normalize
from pam.sync import git

MEMORY_FOLDERS = {"episodes": "episode", "facts": "fact", "projects": "project"}
DOC_GLOBS = ("memory/*/episodes/*.md", "memory/*/facts/*.md", "memory/*/projects/*.md", "skills/*/*.md")
DOC_TYPES = ("episode", "fact", "project", "skill")


@dataclass
class _Doc:
    doc_id: str
    doc_type: str
    scope: str
    path: str
    title: str
    created_at: str
    content_sha256: str
    token_count: int
    chunks: list[str]


def doc_type_of(rel_path: str) -> str | None:
    """Classify a vault-relative path as an indexable document.

    Behavior:
        `memory/<scope>/episodes|facts|projects/<id>.md` and `skills/<scope>/<id>.md` are documents;
        everything else (personas, imports, working memory, `pam.toml`) is not.
    Returns:
        `episode`, `fact`, `project`, `skill`, or `None`.
    Parameters:
        rel_path: Vault-relative POSIX path.
    """
    parts = rel_path.split("/")
    if not parts[-1].endswith(".md"):
        return None
    if len(parts) == 4 and parts[0] == "memory":
        return MEMORY_FOLDERS.get(parts[2])
    if len(parts) == 3 and parts[0] == "skills":
        return "skill"
    return None


def _scan(vault: Vault) -> list[str]:
    found = {p.relative_to(vault.root).as_posix() for g in DOC_GLOBS for p in vault.root.glob(g) if p.is_file()}
    return sorted(found)


def _rel(vault: Vault, path: str | os.PathLike) -> str | None:
    try:
        return vault.rel(path)
    except ValueError:
        return None


def _load(rel: str, raw: bytes, sha: str, cfg: PamConfig) -> _Doc:
    data, body = mdio.split(raw.decode("utf-8"))
    mdio.check_schema_version(data.get("schema_version"))
    doc_type = doc_type_of(rel)
    if doc_type == "episode":
        ep = EpisodeFrontmatter.model_validate(data)
        model, scope, title, chunks = ep, ep.agent, ep.title, chunker.episode_chunks(body, cfg.chunking)
    elif doc_type == "fact":
        fact = Fact.model_validate(data)
        model, scope, title, chunks = fact, fact.scope, f"{fact.attribute}: {fact.value}", [chunker.fact_chunk(fact)]
    elif doc_type == "project":
        project = Project.model_validate(data)
        model, scope, title, chunks = project, project.scope, project.name, [chunker.project_chunk(project, body)]
    else:
        skill = Skill.model_validate(data)
        model, scope, title, chunks = skill, skill.scope, skill.name, [chunker.skill_chunk(skill, body)]
    return _Doc(
        doc_id=str(model.id), doc_type=doc_type, scope=scope, path=rel, title=title,
        created_at=iso_z(model.created_at), content_sha256=sha, token_count=tokens.count(body), chunks=chunks,
    )


def _reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        first = exc.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or "frontmatter"
        more = exc.error_count() - 1
        return f"{field}: {first['msg']}" + (f" (and {more} more)" if more else "")
    return str(exc).splitlines()[0] if str(exc) else type(exc).__name__


def _delete_doc(conn: sqlite3.Connection, doc_id: str) -> None:
    rowids = [(r,) for (r,) in conn.execute("SELECT rowid FROM chunks WHERE doc_id = ?", (doc_id,))]
    conn.executemany("DELETE FROM chunks_fts WHERE rowid = ?", rowids)
    conn.executemany("DELETE FROM chunks_vec WHERE rowid = ?", rowids)
    conn.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM doc_vectors WHERE doc_id = ?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))


def _insert_doc(conn: sqlite3.Connection, doc: _Doc, vectors: np.ndarray, indexed_at: str) -> None:
    conn.execute(
        "INSERT INTO documents (doc_id, doc_type, scope, path, title, created_at, content_sha256, token_count,"
        " indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (doc.doc_id, doc.doc_type, doc.scope, doc.path, doc.title, doc.created_at, doc.content_sha256,
         doc.token_count, indexed_at),
    )
    for ordinal, (text, vector) in enumerate(zip(doc.chunks, vectors, strict=True)):
        rowid = conn.execute(
            "INSERT INTO chunks (chunk_id, doc_id, ordinal, text, token_count) VALUES (?, ?, ?, ?, ?)",
            (f"{doc.doc_id}:{ordinal}", doc.doc_id, ordinal, text, tokens.count(text)),
        ).lastrowid
        conn.execute("INSERT INTO chunks_fts (rowid, text) VALUES (?, ?)", (rowid, text))
        conn.execute("INSERT INTO chunks_vec (rowid, embedding) VALUES (?, ?)", (rowid, serialize_float32(vector)))
    if doc.doc_type == "episode" and len(vectors):
        mean = l2_normalize(vectors.mean(axis=0))
        conn.execute("INSERT INTO doc_vectors (doc_id, embedding) VALUES (?, ?)", (doc.doc_id, serialize_float32(mean)))


def index_vault(
    vault: Vault | str | os.PathLike | None = None,
    *,
    rebuild: bool = False,
    paths: Iterable[str | os.PathLike] | None = None,
    embedder: Embedder | None = None,
) -> IndexReport:
    """Bring the index up to date with the vault's episodes, facts, projects, and skills.

    Behavior:
        Hashes each document file (frontmatter and body). An unchanged hash is skipped; a changed
        or new file has its rows deleted from `chunks`, `chunks_fts`, `chunks_vec`, `doc_vectors`,
        and `documents` and re-inserted with one shared `rowid` per chunk. Without `paths`, the
        whole vault is scanned and documents whose files are gone are removed from the index. With
        `paths` (absolute, or relative to the vault root), only those files are handled: a missing
        file is removed from the index and a non-document path is ignored. A file that fails to
        parse is skipped with a warning, and its old rows are removed. `rebuild` deletes the
        database first; it is needed after a `[chunking]` change, because unchanged files keep
        their old chunks. The model loads only when there is something to embed. Takes no vault lock
        and never writes vault files, so M7 and M10 can call it while holding the lock. Writes
        `meta` (`schema_version`, `embedding_model`, `embedding_dim`, `index_version`,
        `last_indexed_commit`) in the same transaction.
    Exceptions:
        VaultNotFound: The vault is not initialized.
        PamError: `embedding.dim` is not 384, the stored `embedding_model` differs from the config
            without `rebuild`, or sqlite-vec cannot be loaded.
    Returns:
        The `IndexReport` for this run.
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
        rebuild: Delete and rebuild the whole index.
        paths: Only index these files.
        embedder: Embedder to use; defaults to the shared one for the config.
    """
    started = time.perf_counter()
    vault = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).require_initialized()
    cfg = config.load(vault)
    model = cfg.embedding.model
    if cfg.embedding.dim != db.VECTOR_DIM:
        raise PamError(f"embedding.dim is {cfg.embedding.dim}, but the index schema stores {db.VECTOR_DIM}-dim vectors")
    if rebuild:
        db.delete_index(vault)

    conn = db.connect(vault)
    try:
        stored = db.get_meta(conn).get("embedding_model")
        if stored and stored != model:
            raise PamError(f"the index was built with {stored} but the config says {model}; run `pam index --rebuild`")
        known = {path: (doc_id, sha) for doc_id, path, sha in
                 conn.execute("SELECT doc_id, path, content_sha256 FROM documents")}

        if paths is None:
            targets = _scan(vault)
            removed = sorted(set(known) - set(targets))
        else:
            targets, removed = [], []
            for p in paths:
                rel = _rel(vault, p)
                if rel is None or doc_type_of(rel) is None:
                    continue
                if vault.abs(rel).is_file():
                    targets.append(rel)
                elif rel in known:
                    removed.append(rel)
            targets = sorted(set(targets))

        unchanged, changed = 0, []
        for rel in targets:
            raw = vault.abs(rel).read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if rel in known and known[rel][1] == sha:
                unchanged += 1
                continue
            try:
                changed.append(_load(rel, raw, sha, cfg))
            except (PamError, ValidationError, ValueError) as exc:
                warnings.warn(f"{rel} was not indexed: {_reason(exc)}", stacklevel=2)
                if rel in known:
                    removed.append(rel)

        # A document id may live at one path only; a second file claiming it (a copy) is skipped.
        gone = set(removed)
        owners = {doc_id: path for path, (doc_id, _) in known.items() if path not in gone}
        accepted: list[_Doc] = []
        for doc in changed:
            owner = owners.get(doc.doc_id)
            if owner is not None and owner != doc.path and vault.abs(owner).is_file():
                warnings.warn(f"{doc.path} was not indexed: id {doc.doc_id} already belongs to {owner}", stacklevel=2)
                continue
            owners[doc.doc_id] = doc.path
            accepted.append(doc)

        texts = [text for doc in accepted for text in doc.chunks]
        vectors = (embedder or get_embedder(cfg.embedding)).embed_documents(texts) if texts else np.zeros((0, 0))

        indexed_at = iso_z(utcnow())
        with conn:
            for rel in removed:
                _delete_doc(conn, known[rel][0])
            offset = 0
            for doc in accepted:
                if doc.path in known:
                    _delete_doc(conn, known[doc.path][0])
                _delete_doc(conn, doc.doc_id)
                _insert_doc(conn, doc, vectors[offset:offset + len(doc.chunks)], indexed_at)
                offset += len(doc.chunks)
            db.set_meta(conn, {
                "schema_version": SCHEMA_VERSION,
                "embedding_model": model,
                "embedding_dim": str(cfg.embedding.dim),
                "index_version": db.INDEX_VERSION,
                "last_indexed_commit": git.head_sha(vault.root) or "",
            })
    finally:
        conn.close()

    return IndexReport(
        documents_indexed=len(accepted),
        documents_unchanged=unchanged,
        documents_removed_from_index=len(removed),
        chunks_written=len(texts),
        embedding_model=model,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def index_paths(
    vault: Vault | str | os.PathLike | None,
    paths: Iterable[str | os.PathLike],
    embedder: Embedder | None = None,
) -> IndexReport:
    """Re-index only the given files, for writers (M7) and `pam sync` (M10).

    Behavior:
        Same as `index_vault(vault, paths=paths)`: changed files are re-indexed, deleted files are
        removed from the index, and non-document paths are ignored. Takes no vault lock.
    Exceptions:
        VaultNotFound: The vault is not initialized.
        PamError: The configured model differs from the index (run `pam index --rebuild`).
    Returns:
        The `IndexReport` for these paths.
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
        paths: Absolute or vault-relative paths of the files that changed.
        embedder: Embedder to use; defaults to the shared one for the config.
    """
    return index_vault(vault, paths=list(paths), embedder=embedder)


def stats(vault: Vault | str | os.PathLike | None = None) -> dict:
    """Summarize the index without changing it.

    Behavior:
        Reads document and chunk counts per `doc_type`, the `meta` values, and the size of the
        database files. A vault that was never indexed reports zeros and no model.
    Exceptions:
        VaultNotFound: The vault is not initialized.
    Returns:
        A dict with `types` (`{doc_type: {"documents": n, "chunks": n}}`), `documents`, `chunks`,
        `embedding_model`, `embedding_dim`, `last_indexed_commit`, and `db_bytes`.
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
    """
    vault = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).require_initialized()
    types = {t: {"documents": 0, "chunks": 0} for t in DOC_TYPES}
    meta: dict[str, str] = {}
    if vault.index_db.is_file():
        conn = db.connect(vault)
        try:
            meta = db.get_meta(conn)
            for doc_type, n in conn.execute("SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type"):
                types[doc_type]["documents"] = n
            for doc_type, n in conn.execute(
                "SELECT d.doc_type, COUNT(*) FROM chunks c JOIN documents d USING (doc_id) GROUP BY d.doc_type"
            ):
                types[doc_type]["chunks"] = n
        finally:
            conn.close()
    db_bytes = sum(p.stat().st_size for p in (Path(f"{vault.index_db}{s}") for s in ("", "-wal")) if p.is_file())
    return {
        "types": types,
        "documents": sum(t["documents"] for t in types.values()),
        "chunks": sum(t["chunks"] for t in types.values()),
        "embedding_model": meta.get("embedding_model"),
        "embedding_dim": int(meta["embedding_dim"]) if "embedding_dim" in meta else None,
        "last_indexed_commit": meta.get("last_indexed_commit") or None,
        "db_bytes": db_bytes,
    }
