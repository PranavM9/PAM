"""Fast M6 retrieval checks backed by a small deterministic §7.8 SQLite index."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import struct
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlite_vec
from typer.testing import CliRunner

from pam.agents import manifest as agents
from pam.cli.main import app
from pam.contracts.agent import AgentManifest, ReadScope
from pam.contracts.common import Actor
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Cardinality, Fact, FactCategory, FactConflict, FactStatus, fact_id
from pam.contracts.project import Project
from pam.contracts.retrieval import ContextBundle, ContextRequest, SearchQuery, SearchResponse
from pam.core import mdio, tokens
from pam.core.vault import Vault, init_vault
from pam.retrieve import _index, context, search

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
runner = CliRunner()


def _fake_vector(text: str) -> list[float]:
    seed = hashlib.sha256(text.encode()).digest()
    vals = [((seed[i % len(seed)] / 127.5) - 1.0) for i in range(384)]
    norm = math.sqrt(sum(v * v for v in vals))
    return [v / norm for v in vals]


def _pack(vector: list[float]) -> bytes:
    return struct.pack("<384f", *vector)


@pytest.fixture()
def stub_vault(tmp_path, monkeypatch) -> Vault:
    root = tmp_path / "vault"
    init_vault(root)
    vault = Vault(root)
    result = runner.invoke(app, ["--vault", str(root), "import", "run", str(FIXTURES / "claude" / "export.zip")])
    assert result.exit_code == 0, result.output
    episodes = []
    for path in sorted((root / "memory/default/episodes").glob("*.md")):
        episode, body = mdio.read_model(path, EpisodeFrontmatter)
        episodes.append((episode, body, path))
    assert episodes
    target_episode_id = episodes[0][0].id
    conn = sqlite3.connect(vault.index_db)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.executescript("""
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE documents (doc_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL, scope TEXT NOT NULL,
          path TEXT NOT NULL UNIQUE, title TEXT, created_at TEXT, content_sha256 TEXT NOT NULL,
          token_count INTEGER NOT NULL, indexed_at TEXT NOT NULL);
        CREATE TABLE chunks (rowid INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE,
          doc_id TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL, token_count INTEGER NOT NULL);
        CREATE VIRTUAL TABLE chunks_fts USING fts5(text, tokenize='porter unicode61');
        CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[384]);
        CREATE TABLE doc_vectors (doc_id TEXT PRIMARY KEY, embedding BLOB NOT NULL);
        CREATE TABLE project_centroids (project_id TEXT PRIMARY KEY, embedding BLOB NOT NULL, updated_at TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO meta VALUES ('embedding_model','fake')")
    rowid = 1
    for episode, body, path in episodes:
        doc_id = str(episode.id)
        conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)", (
            doc_id, "episode", episode.agent, vault.rel(path), episode.title, episode.created_at.isoformat(),
            hashlib.sha256(body.encode()).hexdigest(), tokens.count(body), NOW.isoformat(),
        ))
        turns = re.split(r"(?=^### )", body, flags=re.MULTILINE)
        turns = [turn.strip() for turn in turns if turn.startswith("### ")]
        if not turns:
            turns = [body]
        chunks = [turns[i] + ("\n\n" + turns[i + 1] if i + 1 < len(turns) else "")
                  for i in range(0, len(turns), 2)]
        for ordinal, turn_pair in enumerate(chunks):
            chunk_id = f"{doc_id}:{ordinal}"
            marker = " quartzretrievalkey" if episode.id == target_episode_id and ordinal == 0 else ""
            text = f"[{episode.title}] {turn_pair}{marker}"
            conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (rowid, chunk_id, doc_id, ordinal, text, tokens.count(text)))
            conn.execute("INSERT INTO chunks_fts(rowid,text) VALUES (?,?)", (rowid, text))
            conn.execute("INSERT INTO chunks_vec(rowid,embedding) VALUES (?,?)", (rowid, _pack(_fake_vector(text))))
            rowid += 1

    chosen = next((episode for episode, _, _ in episodes if "immich" in episode.title.lower()), episodes[0][0])
    project_id = uuid4()
    project = Project(id=project_id, scope="default", name="Fixture project", keywords=["fixture"],
                      episode_ids=[chosen.id], origin=Actor.MANUAL, created_at=NOW,
                      updated_at=NOW, last_activity_at=NOW)
    project_path = vault.project_path("default", project_id)
    mdio.write(project_path, project, "## Summary (auto)\nFixture project notes.\n")
    conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)", (
        str(project_id), "project", "default", vault.rel(project_path), project.name, NOW.isoformat(),
        hashlib.sha256(b"project").hexdigest(), tokens.count("Fixture project notes."), NOW.isoformat(),
    ))
    work_id = fact_id("shared", "user", "works_at", Cardinality.SINGLE, "Cafe")
    fact = Fact(id=work_id, scope="shared", attribute="works_at", value="Cafe", cardinality=Cardinality.SINGLE,
                category=FactCategory.WORK, confidence=0.8, status=FactStatus.CONFLICT,
                conflict=FactConflict(candidate_value="Library", detected_at=NOW, detected_by=Actor.MANUAL),
                extractor=Actor.MANUAL, created_at=NOW, updated_at=NOW)
    fact_path = vault.fact_path("shared", work_id)
    mdio.write(fact_path, fact, "**works_at**: Cafe\n")
    # Index the manually written fact as an ordinary one-chunk document.
    text = "user works_at: Cafe Library"
    conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)", (
        str(work_id), "fact", "shared", vault.rel(fact_path), None, NOW.isoformat(),
        hashlib.sha256(text.encode()).hexdigest(), tokens.count(text), NOW.isoformat(),
    ))
    conn.execute("INSERT INTO chunks VALUES (?,?,?,?,?,?)", (rowid, f"{work_id}:0", str(work_id), 0, text, tokens.count(text)))
    conn.execute("INSERT INTO chunks_fts(rowid,text) VALUES (?,?)", (rowid, text))
    conn.execute("INSERT INTO chunks_vec(rowid,embedding) VALUES (?,?)", (rowid, _pack(_fake_vector(text))))
    manifest = AgentManifest(name="research", display_name="Research", origin="custom", created_at=NOW,
                             read=ReadScope(project_ids=[project_id], include_shared_facts=True), write="own",
                             tools=["get_context", "search_memory", "get_episode", "list_agents"])
    agents.create_agent(manifest, vault)
    conn.commit()
    conn.close()
    monkeypatch.setattr(_index, "embed_query", lambda text, cfg: _fake_vector(text))
    return vault


def test_stub_search_returns_scoped_shaped_hits(stub_vault):
    result = search.search(stub_vault, SearchQuery(query="quartzretrievalkey", k=3))
    assert result.hits
    assert all(len(hit.snippet) <= 500 and "\\" not in hit.path for hit in result.hits)
    conn = sqlite3.connect(stub_vault.index_db)
    try:
        target = conn.execute("SELECT doc_id FROM chunks WHERE text LIKE '%quartzretrievalkey%'").fetchone()[0]
    finally:
        conn.close()
    assert any(str(hit.doc_id) == target for hit in result.hits[:3])
    assert all(hit.doc_type == "episode" for hit in search.search(stub_vault, SearchQuery(query="Immich", doc_types=["episode"])).hits)


def test_stub_scope_and_operator_fallback(stub_vault, monkeypatch):
    scoped = search.search(stub_vault, SearchQuery(query='"(immich OR visa)* -x', agent="research", k=20))
    assert all(hit.doc_type == "episode" or hit.doc_type == "fact" and hit.scope == "shared" or hit.scope == "default" for hit in scoped.hits)
    original_connect = _index.connect

    class FtsErrorConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=()):
            if "FROM chunks_fts" in sql:
                raise sqlite3.OperationalError("simulated FTS parse issue")
            return self.conn.execute(sql, params)

        def close(self):
            self.conn.close()

    monkeypatch.setattr(_index, "connect", lambda vault: FtsErrorConnection(original_connect(vault)))
    result = search.search(stub_vault, SearchQuery(query='"(Immich OR Tailscale)* -visa'))
    assert result.query == '"(Immich OR Tailscale)* -visa'
    assert all(hit.vector_rank is not None and hit.keyword_rank is None for hit in result.hits)


@pytest.mark.parametrize("budget", [256, 800, 2000])
def test_stub_context_budget_headings_conflict_and_savings(stub_vault, budget):
    bundle = context.build_context(stub_vault, ContextRequest(query="Where do I work? Immich", token_budget=budget))
    assert bundle.tokens_used <= budget == bundle.token_budget
    assert bundle.tokens_used == tokens.count(bundle.rendered)
    headings = ["# Agent persona", "# Known facts", "# ⚠ Conflicting facts — ask the user", "# Working memory", "# Relevant projects", "# Relevant past conversations"]
    assert [bundle.rendered.index(h) for h in headings] == sorted(bundle.rendered.index(h) for h in headings)
    assert any(f.attribute == "works_at" for f in bundle.conflicts)
    assert bundle.tokens_saved == max(0, bundle.baseline_tokens - bundle.tokens_used)


def test_stub_context_is_repeatable_and_empty_index_is_persona_only(stub_vault, tmp_path):
    req = ContextRequest(query="Immich", token_budget=2000)
    one, two = context.build_context(stub_vault, req), context.build_context(stub_vault, req)
    a, b = one.model_dump(mode="json"), two.model_dump(mode="json")
    a.pop("generated_at"); b.pop("generated_at")
    assert a == b
    empty = Vault(tmp_path / "empty")
    init_vault(empty.root)
    bundle = context.build_context(empty, ContextRequest(query="anything", token_budget=800))
    assert not bundle.facts and not bundle.episodes and bundle.persona is not None


def test_stub_cli_json(stub_vault):
    result = runner.invoke(app, ["--vault", str(stub_vault.root), "--json", "search", "Immich"])
    assert result.exit_code == 0, result.output
    SearchResponse.model_validate(json.loads(result.output))
    result = runner.invoke(app, ["--vault", str(stub_vault.root), "--json", "context", "Immich", "--budget", "800"])
    assert result.exit_code == 0, result.output
    ContextBundle.model_validate(json.loads(result.output))
