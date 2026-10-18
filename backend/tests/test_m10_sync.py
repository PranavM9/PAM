"""M10 vault sync tests (SPEC §8 M10, §9.3 T09b, §11 item 9).

Behavior:
    Runs `pam.sync.watcher` against fresh `tmp_path` vaults made by `init_vault`. Facts and episodes
    are written through M7 (committed and indexed with the offline embedder from `conftest.py`),
    then edited by hand. `GIT_CONFIG_GLOBAL` points at a temp file, so the real git config is never
    touched.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pam.cli.main import app
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Cardinality, Fact, FactCategory, fact_id
from pam.contracts.raw import RawMessage
from pam.contracts.reports import SyncReport
from pam.contracts.retrieval import SearchQuery, SearchResponse
from pam.contracts.writes import AddFactInput, LogEpisodeInput
from pam.core import mdio
from pam.core.ids import sha256_text
from pam.core.lock import vault_write_lock
from pam.core.time import utcnow
from pam.core.vault import Vault, init_vault
from pam.memory import writer
from pam.retrieve.search import search
from pam.sync import git, watcher

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path_factory, monkeypatch):
    global_cfg = tmp_path_factory.mktemp("gitcfg") / "gitconfig"
    global_cfg.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    init_vault(root)
    return Vault(root)


@pytest.fixture
def index_spy(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real = watcher.index_paths

    def spy(v, paths, *args, **kwargs):
        calls.append(list(paths))
        return real(v, paths, *args, **kwargs)

    monkeypatch.setattr(watcher, "index_paths", spy)
    return calls


def _commits(vault: Vault) -> int:
    return int(git.run(vault.root, "rev-list", "--count", "HEAD").stdout.strip())


def _last_message(vault: Vault) -> str:
    return git.run(vault.root, "log", "-1", "--format=%s").stdout.strip()


def _add_fact(vault: Vault, value: str = "UW") -> str:
    result = writer.add_fact(vault, AddFactInput(attribute="school", value=value, category="education"))
    assert result.ok and result.path, result.message
    return result.path


def _edit_fact(vault: Vault, rel: str, new_value: str) -> None:
    path = vault.abs(rel)
    fact, body = mdio.read_model(path, Fact)
    mdio.write(path, fact.model_copy(update={"value": new_value}), body.replace(fact.value, new_value))


def _log_episode(vault: Vault) -> str:
    data = LogEpisodeInput(title="Sync test", messages=[RawMessage(role="user", text="Plain message for sync.")])
    result = writer.log_episode(vault, data)
    assert result.ok and result.path, result.message
    return result.path


def test_clean_vault_is_a_no_op(vault, index_spy):
    before = _commits(vault)
    report = watcher.sync_once(vault)
    assert report == SyncReport(dirty_paths=[], reindexed=0, commit_sha=None)
    assert _commits(vault) == before
    assert index_spy == []


def test_edited_fact_makes_one_commit_and_reindexes_that_path(vault, index_spy):
    rel = _add_fact(vault)
    before = _commits(vault)
    _edit_fact(vault, rel, "Stanford")
    report = watcher.sync_once(vault)
    assert report.commit_sha == git.head_sha(vault.root)
    assert report.dirty_paths == [rel]
    assert report.reindexed == 1
    assert _commits(vault) == before + 1
    assert _last_message(vault) == "manual: 1 files"
    assert index_spy == [[rel]]
    assert git.status_porcelain(vault.root) == []


def test_second_call_is_a_no_op(vault, index_spy):
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Stanford")
    assert watcher.sync_once(vault).commit_sha
    after_first = _commits(vault)
    report = watcher.sync_once(vault)
    assert report == SyncReport(dirty_paths=[], reindexed=0, commit_sha=None)
    assert _commits(vault) == after_first
    assert len(index_spy) == 1


def test_untracked_fact_file_is_committed(vault, index_spy):
    now = utcnow()
    fid = fact_id("shared", "user", "pet", Cardinality.SINGLE, "Quokka")
    fact = Fact(id=fid, scope="shared", attribute="pet", value="Quokka", cardinality=Cardinality.SINGLE,
                category=FactCategory.OTHER, confidence=0.9, extractor="manual", created_at=now, updated_at=now)
    path = vault.fact_path("shared", fid)
    mdio.write(path, fact, "**pet**: Quokka\n")
    rel = vault.rel(path)
    report = watcher.sync_once(vault)
    assert report.commit_sha and report.dirty_paths == [rel]
    assert rel in git.run(vault.root, "ls-files").stdout.splitlines()
    assert index_spy == [[rel]]


def test_several_edits_share_one_commit(vault):
    rel = _add_fact(vault)
    before = _commits(vault)
    _edit_fact(vault, rel, "Stanford")
    identity = vault.persona_path("default", "identity")
    identity.write_text(identity.read_text(encoding="utf-8") + "- Likes quokkas.\n", encoding="utf-8")
    result = watcher.sync(vault)
    assert sorted(result.committed) == sorted([rel, vault.rel(identity)])
    assert _commits(vault) == before + 1
    assert _last_message(vault) == "manual: 2 files"


def test_deleted_file_is_restored_and_reported(vault, index_spy, caplog):
    rel = _add_fact(vault)
    original = vault.abs(rel).read_bytes()
    before = _commits(vault)
    vault.abs(rel).unlink()
    with caplog.at_level(logging.WARNING, logger="pam.sync.watcher"):
        report = watcher.sync_once(vault)
    assert vault.abs(rel).read_bytes() == original
    assert report.dirty_paths == [rel]
    assert report.commit_sha is None
    assert _commits(vault) == before
    assert git.status_porcelain(vault.root) == []
    assert any(rel in r.getMessage() and "restored" in r.getMessage() for r in caplog.records)


def test_deleted_file_shows_in_sync_result(vault):
    identity = vault.persona_path("default", "identity")
    identity.unlink()
    result = watcher.sync(vault)
    assert result.restored == [vault.rel(identity)]
    assert identity.exists()


def test_pam_folder_is_ignored(vault, index_spy):
    vault.pam_dir.mkdir(exist_ok=True)
    (vault.pam_dir / "scratch.txt").write_text("derived\n", encoding="utf-8")
    (vault.pam_dir / "index.db").write_bytes(b"not really a db")
    before = _commits(vault)
    report = watcher.sync_once(vault)
    assert report.dirty_paths == [] and report.commit_sha is None
    assert _commits(vault) == before
    assert (vault.pam_dir / "scratch.txt").read_text(encoding="utf-8") == "derived\n"
    assert index_spy == []


def test_session_transcript_is_skipped(vault, index_spy):
    transcript = vault.root / "working" / "s_abc123def456.transcript.jsonl"
    transcript.write_text('{"role": "user", "text": "hi"}\n', encoding="utf-8")
    rel = vault.rel(transcript)
    before = _commits(vault)
    result = runner.invoke(app, ["--vault", str(vault.root), "--json", "sync"])
    assert result.exit_code == 0, result.output
    assert SyncReport.model_validate_json(result.stdout) == SyncReport(dirty_paths=[], reindexed=0, commit_sha=None)
    assert _commits(vault) == before
    assert rel not in git.run(vault.root, "ls-files").stdout.splitlines()
    assert ("??", rel) in git.status_porcelain(vault.root)
    assert index_spy == []


def test_edited_episode_body_is_reported_not_committed(vault, caplog):
    rel = _log_episode(vault)
    path = vault.abs(rel)
    edited = path.read_text(encoding="utf-8") + "\nA line added by hand.\n"
    path.write_text(edited, encoding="utf-8")
    before = _commits(vault)
    with caplog.at_level(logging.WARNING, logger="pam.sync.watcher"):
        report = watcher.sync_once(vault)
    assert report.commit_sha is None
    assert report.dirty_paths == [rel]
    assert _commits(vault) == before
    assert path.read_text(encoding="utf-8") == edited  # reported, never rewritten
    assert any("body_sha256" in r.getMessage() and rel in r.getMessage() for r in caplog.records)
    assert watcher.sync(vault).immutable_violations == [rel]


def test_episode_body_edit_with_rewritten_hash_is_refused(vault):
    rel = _log_episode(vault)
    path = vault.abs(rel)
    fm, body = mdio.read_model(path, EpisodeFrontmatter)
    forged = body + "\nForged line.\n"
    mdio.write(path, fm.model_copy(update={"body_sha256": sha256_text(forged)}), forged)
    result = watcher.sync(vault)
    assert result.immutable_violations == [rel]
    assert result.commit_sha is None


def test_episode_frontmatter_edit_is_committed(vault):
    rel = _log_episode(vault)
    path = vault.abs(rel)
    fm, body = mdio.read_model(path, EpisodeFrontmatter)
    mdio.write(path, fm.model_copy(update={"tags": [*fm.tags, "hand-tagged"]}), body)
    result = watcher.sync(vault)
    assert result.committed == [rel]
    assert result.commit_sha
    assert result.immutable_violations == []


def test_invalid_fact_frontmatter_is_not_committed(vault):
    bad = vault.memory_dir("shared") / "facts" / "broken.md"
    bad.write_text("---\nattribute: school\n---\nno value\n", encoding="utf-8")
    rel = vault.rel(bad)
    result = watcher.sync(vault)
    assert rel in result.invalid
    assert result.commit_sha is None
    assert ("??", rel) in git.status_porcelain(vault.root)


def test_held_lock_reports_busy_without_crashing(vault, index_spy):
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Stanford")
    before = _commits(vault)
    with vault_write_lock(vault):
        result = watcher.sync(vault)
        report = watcher.sync_once(vault)
        cli = runner.invoke(app, ["--vault", str(vault.root), "sync"])
    assert result.busy and result.commit_sha is None
    assert result.dirty_paths == [rel]
    assert report.commit_sha is None
    assert cli.exit_code == 4
    assert "vault busy" in cli.output
    assert _commits(vault) == before
    assert index_spy == []
    assert watcher.sync_once(vault).commit_sha  # the next sync after release picks the edit up


def test_search_still_works_when_sync_raises(vault, monkeypatch):
    _add_fact(vault)

    def boom(_vault):
        raise RuntimeError("sync exploded")

    monkeypatch.setattr(watcher, "sync_once", boom)
    response = search(vault, SearchQuery(query="school UW", agent="default"))
    assert isinstance(response, SearchResponse)


def test_search_survives_a_vault_without_git(tmp_path):
    assert watcher.sync_before_read(tmp_path) is None


def test_search_finds_hand_edited_fact(vault):
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Quokkaville Institute")
    before = _commits(vault)
    response = search(vault, SearchQuery(query="Quokkaville", agent="default"))
    assert _commits(vault) == before + 1
    assert any(hit.path == rel for hit in response.hits)


def test_cli_json_validates_as_sync_report(vault):
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Stanford")
    result = runner.invoke(app, ["--vault", str(vault.root), "--json", "sync"])
    assert result.exit_code == 0, result.output
    report = SyncReport.model_validate_json(result.stdout)
    assert report.commit_sha == git.head_sha(vault.root)
    assert report.dirty_paths == [rel]


def test_cli_text_output(vault):
    clean = runner.invoke(app, ["--vault", str(vault.root), "sync"])
    assert clean.exit_code == 0 and "clean" in clean.output
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Stanford")
    synced = runner.invoke(app, ["--vault", str(vault.root), "sync"])
    assert synced.exit_code == 0
    assert rel in synced.output and git.head_sha(vault.root) in synced.output


def test_cli_on_a_fresh_vault_commits_hand_edit_once(vault):
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Stanford")
    before = _commits(vault)
    assert runner.invoke(app, ["--vault", str(vault.root), "sync"]).exit_code == 0
    assert runner.invoke(app, ["--vault", str(vault.root), "sync"]).exit_code == 0
    assert _commits(vault) == before + 1


def test_watch_polls_and_stops_after_ticks(vault):
    rel = _add_fact(vault)
    _edit_fact(vault, rel, "Stanford")
    results: list[watcher.SyncResult] = []
    watcher.watch(vault, 0, on_result=results.append, ticks=2)
    assert len(results) == 2
    assert results[0].committed == [rel] and results[0].commit_sha
    assert results[1].dirty_paths == [] and results[1].commit_sha is None


def test_restored_episode_is_not_rewritten_beyond_head(vault):
    rel = _log_episode(vault)
    committed = subprocess.run(
        ["git", "-C", str(vault.root), "show", f"HEAD:{rel}"], capture_output=True, check=True
    ).stdout
    vault.abs(rel).unlink()
    watcher.sync(vault)
    assert vault.abs(rel).read_bytes() == committed
