"""M4 indexer tests (SPEC §8 M4, §7.8, §9.3 T06).

Behavior:
    Checks the chunker on hand-written bodies in the §7.3 grammar, then runs the indexer on
    `tmp_path` vaults built from the Claude fixture (`pam init` -> `pam import run`) with a
    deterministic fake embedder: idempotence, rebuild, rowid alignment, unit vectors, document
    vectors, incremental edits and deletions, `index_paths`, the model-mismatch guard, and the CLI.
    One acceptance test uses the real fastembed model.
"""

import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import sqlite_vec
from typer.testing import CliRunner

from pam.cli.main import app
from pam.contracts.common import Actor
from pam.contracts.config import ChunkCfg, EmbeddingCfg
from pam.contracts.fact import Cardinality, Fact, FactCategory, fact_id
from pam.contracts.project import Project
from pam.contracts.reports import IndexReport
from pam.contracts.skill import Skill
from pam.core import mdio, tokens
from pam.core.errors import PamError
from pam.core.vault import Vault, init_vault
from pam.index import chunker, db, embedder, indexer

FIXTURE = Path(__file__).parent / "fixtures" / "claude" / "export.zip"
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
runner = CliRunner()


# --- helpers -------------------------------------------------------------------------------

class FakeEmbedder:
    """Deterministic stand-in for fastembed: a text's sha256 seeds a random unit vector."""

    model_name = "BAAI/bge-small-en-v1.5"
    dim = 384

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        rows = [np.random.default_rng(int(hashlib.sha256(t.encode()).hexdigest()[:16], 16)).standard_normal(384)
                for t in texts]
        return embedder.l2_normalize(np.array(rows).reshape(len(texts), 384))

    def embed_query(self, text):
        return self.embed_documents([text])[0]


@pytest.fixture
def fake(monkeypatch) -> FakeEmbedder:
    fake = FakeEmbedder()
    monkeypatch.setattr(indexer, "get_embedder", lambda cfg: fake)
    return fake


@pytest.fixture(scope="module")
def template(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("m04") / "vault"
    for args in (["init"], ["import", "run", str(FIXTURE)]):
        result = runner.invoke(app, ["--vault", str(root), *args])
        assert result.exit_code == 0, result.output
    return root


@pytest.fixture
def vault(template, tmp_path) -> Vault:
    root = tmp_path / "vault"
    shutil.copytree(template, root)
    return Vault(root)


def _connect(vault: Vault) -> sqlite3.Connection:
    conn = sqlite3.connect(vault.index_db)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    return conn


def _episode_count(vault: Vault) -> int:
    return len(list((vault.root / "memory" / "default" / "episodes").glob("*.md")))


def _write_fact(vault: Vault, value: str = "UW") -> Path:
    fid = fact_id("shared", "user", "school", Cardinality.SINGLE, value)
    path = vault.fact_path("shared", fid)
    fact = Fact(id=fid, scope="shared", attribute="school", value=value, cardinality=Cardinality.SINGLE,
                category=FactCategory.EDUCATION, confidence=0.9, extractor=Actor.MANUAL,
                created_at=NOW, updated_at=NOW)
    mdio.write(path, fact, f"**school**: {value}\n")
    return path


def _write_project_and_skill(vault: Vault) -> tuple[Path, Path]:
    project = Project(id=uuid4(), scope="default", name="Immich photo backup", keywords=["immich", "photo"],
                      origin=Actor.MANUAL, created_at=NOW, updated_at=NOW, last_activity_at=NOW)
    p_path = vault.project_path("default", project.id)
    mdio.write(p_path, project, "## Summary (auto)\nSelf-hosted photo backup.\n\n## Notes\n- private note\n")
    skill = Skill(id=uuid4(), scope="default", name="Restart Immich", description="Restart the stack",
                  created_by=Actor.MANUAL, created_at=NOW, updated_at=NOW)
    s_path = vault.skill_path("default", skill.id)
    mdio.write(s_path, skill, "1. docker compose down\n2. docker compose up -d\n")
    return p_path, s_path


# --- chunker -------------------------------------------------------------------------------

BODY = """# Immich setup

## Summary
Setting up Immich.

## Transcript

### user · 2026-10-01T18:04:11Z
How do I install Immich?

### assistant · 2026-10-01T18:04:30.123456Z
Use docker compose.
[attachment: diagram.png (image)]

### user · unknown
Thanks. ### user · 2026-10-01T18:04:11Z is not a heading here.

### assistant · 2026-10-01T18:05:00Z
You're welcome.
"""


def test_parse_episode_grammar():
    parsed = chunker.parse_episode(BODY)
    assert parsed.title == "Immich setup"
    assert parsed.summary == "Setting up Immich."
    assert [t.role for t in parsed.turns] == ["user", "assistant", "user", "assistant"]
    assert parsed.turns[1].text == "Use docker compose.\n[attachment: diagram.png (image)]"
    assert "is not a heading here" in parsed.turns[2].text


def test_episode_chunks_summary_first_then_pairs_without_times():
    chunks = chunker.episode_chunks(BODY, ChunkCfg())
    assert chunks[0] == "[Immich setup] Summary: Setting up Immich."
    assert chunks[1] == ("[Immich setup] user: How do I install Immich?\n\n"
                         "assistant: Use docker compose.\n[attachment: diagram.png (image)]")
    assert len(chunks) == 3 and all(c.startswith("[Immich setup] ") for c in chunks)
    assert not any("18:04" in c for c in chunks[:2])


def test_episode_without_summary_has_no_summary_chunk():
    body = "# T\n\n## Transcript\n\n### user · unknown\nhi\n\n### assistant · unknown\nhello\n"
    assert chunker.episode_chunks(body, ChunkCfg()) == ["[T] user: hi\n\nassistant: hello"]


def test_leading_assistant_and_consecutive_users_and_other_roles():
    body = ("# T\n\n## Transcript\n\n### assistant · unknown\nWelcome\n\n### user · unknown\nfirst\n\n"
            "### user · unknown\nsecond\n\n### tool · unknown\nresult\n\n### assistant · unknown\nanswer\n")
    assert chunker.episode_chunks(body, ChunkCfg()) == [
        "[T] assistant: Welcome", "[T] user: first", "[T] user: second\n\ntool: result\n\nassistant: answer",
    ]


def test_empty_transcript_gives_title_chunk():
    assert chunker.episode_chunks("# Lonely\n\n## Transcript\n", ChunkCfg()) == ["[Lonely]"]


def test_long_pair_splits_on_paragraphs_with_overlap():
    paragraphs = [f"Paragraph {i}: " + " ".join(f"word{i}x{j}" for j in range(15)) for i in range(30)]
    body = "# Long\n\n## Transcript\n\n### user · unknown\n" + "\n\n".join(paragraphs) + "\n"
    cfg = ChunkCfg(max_tokens=200, overlap_tokens=30)
    chunks = chunker.episode_chunks(body, cfg)
    assert len(chunks) > 3
    assert all(tokens.count(c) <= cfg.max_tokens for c in chunks)
    assert all(c.startswith("[Long] ") for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        head = nxt.removeprefix("[Long] ").split("\n\n")[0]
        assert head in prev  # the next chunk opens with the tail of the previous one


def test_giant_paragraph_is_hard_split():
    text = " ".join(f"tok{i}" for i in range(2000))
    pieces = chunker.split_text(text, 100, 10)
    assert len(pieces) > 10 and all(tokens.count(p) <= 100 for p in pieces)


def test_split_text_keeps_short_text_whole():
    assert chunker.split_text("  short  ", 50, 10) == ["short"]
    assert chunker.split_text("", 50, 10) == []


def test_fact_project_skill_chunks(tmp_path):
    vault = Vault(tmp_path)
    fact = mdio.read_model(_write_fact(vault), Fact)[0]
    assert chunker.fact_chunk(fact) == "user school: UW"
    p_path, s_path = _write_project_and_skill(vault)
    project, p_body = mdio.read_model(p_path, Project)
    assert chunker.project_chunk(project, p_body) == "Immich photo backup\nimmich, photo\nSelf-hosted photo backup."
    skill, s_body = mdio.read_model(s_path, Skill)
    assert chunker.skill_chunk(skill, s_body) == (
        "Restart Immich\nRestart the stack\n1. docker compose down\n2. docker compose up -d")
    long_skill = chunker.skill_chunk(skill, "step " * 1000)
    assert tokens.count(long_skill) <= chunker.SKILL_STEPS_TOKENS + 20


# --- embedder wrapper ----------------------------------------------------------------------

def test_embedder_prefixes_queries_batches_and_normalizes(monkeypatch):
    seen = {}

    class Model:
        def embed(self, texts, batch_size):
            seen["texts"], seen["batch_size"] = texts, batch_size
            return [np.full(384, 3.0) for _ in texts]

    emb = embedder.Embedder(EmbeddingCfg())
    monkeypatch.setattr(emb, "_load", lambda: Model())
    vector = emb.embed_query("photo backup")
    assert seen["texts"] == [EmbeddingCfg().query_prefix + "photo backup"]
    assert seen["batch_size"] == 64
    assert vector.dtype == np.float32 and abs(np.linalg.norm(vector) - 1) < 1e-5
    emb.embed_documents(["doc"])
    assert seen["texts"] == ["doc"]
    assert emb.embed_documents([]).shape == (0, 384)


def test_get_embedder_is_shared_per_model():
    assert embedder.get_embedder(EmbeddingCfg()) is embedder.get_embedder(EmbeddingCfg())


# --- indexer -------------------------------------------------------------------------------

def test_first_run_indexes_every_document_type(vault, fake):
    _write_fact(vault)
    _write_project_and_skill(vault)
    report = indexer.index_vault(vault)
    episodes = _episode_count(vault)
    assert report.documents_indexed == episodes + 3
    assert report.documents_unchanged == 0 and report.documents_removed_from_index == 0
    with _connect(vault) as conn:
        types = dict(conn.execute("SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type"))
        assert types == {"episode": episodes, "fact": 1, "project": 1, "skill": 1}
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == report.chunks_written
        fact_row = conn.execute("SELECT scope, title, path FROM documents WHERE doc_type='fact'").fetchone()
        assert fact_row[0] == "shared" and fact_row[1] == "school: UW" and fact_row[2].startswith("memory/shared/facts/")


def test_second_run_is_idempotent_and_skips_the_model(vault, fake):
    first = indexer.index_vault(vault)
    fake.calls.clear()
    second = indexer.index_vault(vault)
    assert second.documents_indexed == 0 and second.chunks_written == 0
    assert second.documents_unchanged == first.documents_indexed
    assert fake.calls == []


def test_rebuild_produces_identical_chunks(vault, fake):
    indexer.index_vault(vault)
    with _connect(vault) as conn:
        before = conn.execute("SELECT chunk_id, text FROM chunks ORDER BY chunk_id").fetchall()
    report = indexer.index_vault(vault, rebuild=True)
    with _connect(vault) as conn:
        after = conn.execute("SELECT chunk_id, text FROM chunks ORDER BY chunk_id").fetchall()
    assert before == after and report.chunks_written == len(after)


def test_rowids_match_and_vectors_are_unit_length(vault, fake):
    _write_fact(vault)
    indexer.index_vault(vault)
    with _connect(vault) as conn:
        chunk_ids = [r for (r,) in conn.execute("SELECT rowid FROM chunks ORDER BY rowid")]
        assert chunk_ids == [r for (r,) in conn.execute("SELECT rowid FROM chunks_fts ORDER BY rowid")]
        assert chunk_ids == [r for (r,) in conn.execute("SELECT rowid FROM chunks_vec ORDER BY rowid")]
        for (blob,) in conn.execute("SELECT embedding FROM chunks_vec"):
            assert abs(np.linalg.norm(np.frombuffer(blob, dtype=np.float32)) - 1) < 1e-5
        hit = conn.execute(
            "SELECT c.text FROM chunks_fts f JOIN chunks c ON c.rowid = f.rowid WHERE chunks_fts MATCH 'immich'"
        ).fetchall()
        assert hit and all("immich" in t.lower() for (t,) in hit)
        assert conn.execute("SELECT text FROM chunks WHERE chunk_id LIKE '%:0' AND doc_id IN "
                            "(SELECT doc_id FROM documents WHERE doc_type='fact')").fetchone() == ("user school: UW",)


def test_doc_vectors_are_normalized_means_for_episodes_only(vault, fake):
    _write_fact(vault)
    indexer.index_vault(vault)
    with _connect(vault) as conn:
        rows = conn.execute("SELECT doc_id, embedding FROM doc_vectors").fetchall()
        assert len(rows) == _episode_count(vault)
        doc_id, blob = rows[0]
        chunks = [np.frombuffer(b, dtype=np.float32) for (b,) in conn.execute(
            "SELECT v.embedding FROM chunks c JOIN chunks_vec v ON v.rowid = c.rowid WHERE c.doc_id = ?", (doc_id,))]
        expected = embedder.l2_normalize(np.mean(chunks, axis=0))
        assert np.allclose(np.frombuffer(blob, dtype=np.float32), expected, atol=1e-5)


def test_episode_token_count_is_the_full_body(vault, fake):
    indexer.index_vault(vault)
    path = next((vault.root / "memory" / "default" / "episodes").glob("*.md"))
    _, body = mdio.read(path)
    with _connect(vault) as conn:
        assert conn.execute("SELECT token_count FROM documents WHERE path = ?",
                            (vault.rel(path),)).fetchone() == (tokens.count(body),)


def test_edited_fact_is_reindexed_alone(vault, fake):
    path = _write_fact(vault)
    indexer.index_vault(vault)
    fact, body = mdio.read_model(path, Fact)
    mdio.write(path, fact.model_copy(update={"value": "Zanzibar Polytechnic"}), body)
    report = indexer.index_vault(vault)
    assert report.documents_indexed == 1 and report.chunks_written == 1
    with _connect(vault) as conn:
        assert conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'zanzibar'").fetchone()[0] == 1
        assert conn.execute("SELECT c.text FROM chunks c JOIN documents d USING (doc_id) WHERE d.doc_type='fact'"
                            ).fetchall() == [("user school: Zanzibar Polytechnic",)]
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == \
               conn.execute("SELECT COUNT(*) FROM chunks_vec").fetchone()[0]


def test_deleted_file_leaves_the_index_but_vault_is_untouched(vault, fake):
    path = _write_fact(vault)
    indexer.index_vault(vault)
    path.unlink()
    files_before = sorted(p for p in vault.root.rglob("*") if ".pam" not in p.parts and ".git" not in p.parts)
    report = indexer.index_vault(vault)
    assert report.documents_removed_from_index == 1
    assert files_before == sorted(p for p in vault.root.rglob("*") if ".pam" not in p.parts and ".git" not in p.parts)
    with _connect(vault) as conn:
        assert conn.execute("SELECT COUNT(*) FROM documents WHERE doc_type='fact'").fetchone() == (0,)
        orphans = conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id NOT IN (SELECT doc_id FROM documents)")
        assert orphans.fetchone() == (0,)
        assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == \
               conn.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]


def test_index_paths_touches_only_the_given_files(vault, fake):
    indexer.index_vault(vault)
    fact_path = _write_fact(vault)
    p_path, _ = _write_project_and_skill(vault)
    report = indexer.index_paths(vault, [fact_path, "pam.toml", "agent/default/rules.md"])
    assert report.documents_indexed == 1 and report.documents_unchanged == 0
    report = indexer.index_paths(vault, [vault.rel(p_path)])  # vault-relative also works
    assert report.documents_indexed == 1
    fact_path.unlink()
    assert indexer.index_paths(vault, [fact_path]).documents_removed_from_index == 1
    with _connect(vault) as conn:
        assert dict(conn.execute("SELECT doc_type, COUNT(*) FROM documents GROUP BY doc_type")) == {
            "episode": _episode_count(vault), "project": 1}


def test_model_mismatch_requires_rebuild(vault, fake):
    indexer.index_vault(vault)
    toml = vault.config_path.read_text(encoding="utf-8")
    vault.config_path.write_text(toml.replace('model = "BAAI/bge-small-en-v1.5"', 'model = "other/model"'),
                                 encoding="utf-8")
    with pytest.raises(PamError, match="--rebuild"):
        indexer.index_vault(vault)
    report = indexer.index_vault(vault, rebuild=True)
    assert report.embedding_model == "other/model" and report.documents_indexed == _episode_count(vault)
    with _connect(vault) as conn:
        assert db.get_meta(conn)["embedding_model"] == "other/model"


def test_meta_keys_are_written(vault, fake):
    indexer.index_vault(vault)
    with _connect(vault) as conn:
        meta = db.get_meta(conn)
    assert set(meta) == {"schema_version", "embedding_model", "embedding_dim", "index_version", "last_indexed_commit"}
    assert meta["embedding_dim"] == "384" and len(meta["last_indexed_commit"]) == 40


def test_empty_vault_indexes_nothing_without_loading_a_model(tmp_path, monkeypatch):
    init_vault(tmp_path / "v")
    monkeypatch.setattr(indexer, "get_embedder", lambda cfg: pytest.fail("model must not load"))
    report = indexer.index_vault(tmp_path / "v")
    assert (report.documents_indexed, report.chunks_written, report.documents_unchanged) == (0, 0, 0)
    assert indexer.stats(tmp_path / "v")["documents"] == 0


def test_invalid_file_is_skipped_with_a_warning(vault, fake):
    bad = vault.root / "memory" / "shared" / "facts" / "broken.md"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("---\nvalue: 1\n---\nbroken\n", encoding="utf-8")
    with pytest.warns(UserWarning, match="broken.md was not indexed"):
        report = indexer.index_vault(vault)
    assert report.documents_indexed == _episode_count(vault)


def test_copied_file_with_the_same_id_is_skipped(vault, fake):
    path = _write_fact(vault)
    indexer.index_vault(vault)
    shutil.copy(path, path.with_name("copy.md"))
    with pytest.warns(UserWarning, match="already belongs to"):
        report = indexer.index_vault(vault)
    assert report.documents_indexed == 0


def test_dim_other_than_384_is_refused(vault, fake):
    toml = vault.config_path.read_text(encoding="utf-8")
    vault.config_path.write_text(toml.replace("dim = 384", "dim = 768"), encoding="utf-8")
    with pytest.raises(PamError, match="384"):
        indexer.index_vault(vault)


# --- CLI -----------------------------------------------------------------------------------

def test_cli_index_json_and_stats(vault, fake):
    _write_fact(vault)
    result = runner.invoke(app, ["--vault", str(vault.root), "--json", "index"])
    assert result.exit_code == 0, result.output
    report = IndexReport.model_validate(json.loads(result.output))
    assert report.documents_indexed == _episode_count(vault) + 1

    result = runner.invoke(app, ["--vault", str(vault.root), "index"])
    assert result.exit_code == 0, result.output
    assert f"Indexed 0 documents ({report.documents_indexed} unchanged, 0 removed)" in result.output

    result = runner.invoke(app, ["--vault", str(vault.root), "--json", "index", "stats"])
    data = json.loads(result.output)
    assert data["types"]["episode"]["documents"] == _episode_count(vault)
    assert data["types"]["fact"] == {"documents": 1, "chunks": 1}
    assert data["chunks"] == report.chunks_written and data["embedding_model"] == "BAAI/bge-small-en-v1.5"

    result = runner.invoke(app, ["--vault", str(vault.root), "index", "stats"])
    assert result.exit_code == 0 and "episode" in result.output and "fact" in result.output


def test_cli_rebuild_with_paths_is_an_error(vault, fake):
    result = runner.invoke(app, ["--vault", str(vault.root), "index", "--rebuild", "pam.toml"])
    assert result.exit_code == 1


def test_cli_model_mismatch_exits_1(vault, fake):
    indexer.index_vault(vault)
    toml = vault.config_path.read_text(encoding="utf-8")
    vault.config_path.write_text(toml.replace('model = "BAAI/bge-small-en-v1.5"', 'model = "other/model"'),
                                 encoding="utf-8")
    result = runner.invoke(app, ["--vault", str(vault.root), "index"])
    assert result.exit_code == 1


# --- acceptance with the real model --------------------------------------------------------

def test_acceptance_real_model_idempotent_and_rebuild_stable(vault):
    first = indexer.index_vault(vault)
    assert first.documents_indexed == _episode_count(vault) and first.chunks_written > 0
    second = indexer.index_vault(vault)
    assert second.documents_unchanged == first.documents_indexed and second.documents_indexed == 0
    rebuilt = indexer.index_vault(vault, rebuild=True)
    assert rebuilt.chunks_written == first.chunks_written
    query = embedder.get_embedder(EmbeddingCfg()).embed_query("backing up photos with Immich")
    with _connect(vault) as conn:
        rowid = conn.execute("SELECT rowid FROM chunks_vec WHERE embedding MATCH ? AND k = 1",
                             (sqlite_vec.serialize_float32(query),)).fetchone()[0]
        title = conn.execute("SELECT d.title FROM chunks c JOIN documents d USING (doc_id) WHERE c.rowid = ?",
                             (rowid,)).fetchone()[0]
    assert "immich" in title.lower()
