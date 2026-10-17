"""M2 normalizer tests (SPEC §8 M2, §9.3 T04).

Behavior:
    Renders hand-built `RawConversation` objects and writes them into fresh `init_vault` vaults.
    `GIT_CONFIG_GLOBAL` points at a temp file so no user git config is read or changed.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid5

import pytest
from typer.testing import CliRunner

from pam.cli.main import app
from pam.contracts.common import PAM_NAMESPACE, Source
from pam.contracts.episode import EpisodeFrontmatter, episode_id
from pam.contracts.raw import AttachmentRef, RawConversation, RawMessage
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.vault import Vault, init_vault
from pam.normalize.render import render
from pam.normalize.writer import write_episodes
from pam.sync import git

FIXTURES = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 10, 1, 18, 4, 11, tzinfo=UTC)
IMPORTED = datetime(2026, 10, 17, 9, 0, 0, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path_factory, monkeypatch):
    cfg = tmp_path_factory.mktemp("gitcfg") / "gitconfig"
    cfg.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    init_vault(tmp_path / "vault")
    return Vault(tmp_path / "vault")


@pytest.fixture
def export(tmp_path: Path) -> Path:
    path = tmp_path / "conversations.json"
    path.write_bytes(b'{"raw": "bytes", "unicode": "\xc3\xa9"}\r\n\x00\xff')
    return path


def conv(cid: str = "c1", **kw) -> RawConversation:
    kw.setdefault("source", Source.CLAUDE)
    kw.setdefault("title", "Plan the trip")
    kw.setdefault("created_at", T0)
    kw.setdefault("updated_at", T0 + timedelta(minutes=5))
    kw.setdefault(
        "messages",
        [
            RawMessage(role="user", text="hello", created_at=T0),
            RawMessage(role="assistant", text="hi there", created_at=T0 + timedelta(seconds=19)),
        ],
    )
    return RawConversation(source_conversation_id=cid, **kw)


def commit_count(vault: Vault) -> int:
    return int(git.run(vault.root, "rev-list", "--count", "HEAD").stdout)


def cli(vault: Vault, *args: str):
    return runner.invoke(app, ["--vault", str(vault.root), *args])


# -- render ----------------------------------------------------------------------------------

def test_grammar_golden():
    raw = conv(
        summary="A short summary.",
        messages=[
            RawMessage(role="user", text="hello", created_at=T0),
            RawMessage(
                role="assistant",
                text="see diagram\n\n```py\nprint(1)\n```",
                created_at=T0 + timedelta(seconds=19),
                attachments=[AttachmentRef(name="diagram.png", kind="image")],
            ),
        ],
    )
    _, body = render(raw, IMPORTED)
    assert body == (
        "# Plan the trip\n"
        "\n"
        "## Summary\n"
        "A short summary.\n"
        "\n"
        "## Transcript\n"
        "\n"
        "### user · 2026-10-01T18:04:11Z\n"
        "hello\n"
        "\n"
        "### assistant · 2026-10-01T18:04:30Z\n"
        "see diagram\n\n```py\nprint(1)\n```\n"
        "[attachment: diagram.png (image)]\n"
    )


@pytest.mark.parametrize("summary,expected", [("text", True), (None, False), ("", False), ("  \n", False)])
def test_summary_present_vs_absent(summary, expected):
    fm, body = render(conv(summary=summary), IMPORTED)
    assert fm.has_summary is expected
    assert ("## Summary" in body) is expected
    assert "## Transcript" in body and "hello" in body


def test_attachment_only_message_and_kinds():
    raw = conv(messages=[RawMessage(
        role="user", text="", created_at=T0,
        attachments=[AttachmentRef(name="a.pdf", kind="file"), AttachmentRef(name="x", kind="other")],
    )])
    fm, body = render(raw, IMPORTED)
    assert body.endswith("### user · 2026-10-01T18:04:11Z\n[attachment: a.pdf (file)]\n[attachment: x (other)]\n")
    assert fm.message_count == 1


def test_unknown_time():
    _, body = render(conv(messages=[RawMessage(role="user", text="hi")]), IMPORTED)
    assert "### user · unknown\nhi\n" in body


def test_title_fallback_and_newline_collapse():
    fm, body = render(conv(title=None), IMPORTED)
    assert fm.title == "Untitled conversation 2026-10-01"
    assert body.startswith("# Untitled conversation 2026-10-01\n")
    assert render(conv(title="  \n "), IMPORTED)[0].title == "Untitled conversation 2026-10-01"
    fm, body = render(conv(title="Two\nlines\r\n  here"), IMPORTED)
    assert fm.title == "Two lines here"
    assert body.startswith("# Two lines here\n")


def test_created_at_fallbacks():
    first = T0 + timedelta(hours=1)
    msgs = [RawMessage(role="user", text="a"), RawMessage(role="user", text="b", created_at=first)]
    fm, _ = render(conv(created_at=None, updated_at=None, messages=msgs), IMPORTED)
    assert fm.created_at == first and fm.updated_at == first
    fm, _ = render(conv(created_at=None, updated_at=None, title=None, messages=[RawMessage(role="user", text="a")]), IMPORTED)
    assert fm.created_at == IMPORTED and fm.title == "Untitled conversation 2026-10-17"


def test_hash_and_identity():
    fm, body = render(conv(), IMPORTED, agent="work")
    assert fm.body_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert fm.id == episode_id(Source.CLAUDE, "c1")
    assert fm.agent == "work" and fm.imported_at == IMPORTED


def test_long_message_kept_intact():
    text = "x" * 150_000
    _, body = render(conv(messages=[RawMessage(role="user", text=text, created_at=T0)]), IMPORTED)
    assert text in body


# -- writer ----------------------------------------------------------------------------------

def test_write_archive_and_single_commit(vault, export):
    before = commit_count(vault)
    report = write_episodes(vault, [conv("a"), conv("b"), conv("c")], Source.CLAUDE, export)
    assert (report.conversations_found, report.episodes_written, report.episodes_skipped_existing) == (3, 3, 0)
    assert commit_count(vault) == before + 1
    assert report.commit_sha == git.head_sha(vault.root)
    assert git.run(vault.root, "log", "-1", "--format=%s").stdout.strip() == "import: claude 3 episodes (conversations.json)"
    assert git.status_porcelain(vault.root) == []
    for cid in "abc":
        fm, body = mdio.read_model(vault.episode_path("default", episode_id(Source.CLAUDE, cid)), EpisodeFrontmatter)
        assert fm.body_sha256 == hashlib.sha256(body.encode()).hexdigest()


def test_archive_is_byte_identical_and_posix(vault, export):
    report = write_episodes(vault, [conv()], Source.CLAUDE, export)
    assert "\\" not in report.archived_path and "\\" not in report.input_path
    parts = report.archived_path.split("/")
    assert parts[:2] == ["imports", "claude"] and len(parts[2]) == 16 and parts[3] == "conversations.json"
    assert (vault.root / report.archived_path).read_bytes() == export.read_bytes()
    assert report.archived_path in git.run(vault.root, "ls-files").stdout.splitlines()


def test_second_run_is_idempotent(vault, export):
    write_episodes(vault, [conv("a"), conv("b")], Source.CLAUDE, export)
    before = commit_count(vault)
    report = write_episodes(vault, [conv("a"), conv("b")], Source.CLAUDE, export)
    assert (report.episodes_written, report.episodes_skipped_existing, report.commit_sha) == (0, 2, None)
    assert report.archived_path == ""
    assert commit_count(vault) == before
    assert len(list((vault.root / "imports" / "claude").iterdir())) == 1


def test_only_new_episodes_are_written(vault, export):
    write_episodes(vault, [conv("a")], Source.CLAUDE, export)
    report = write_episodes(vault, [conv("a"), conv("b")], Source.CLAUDE, export)
    assert (report.episodes_written, report.episodes_skipped_existing) == (1, 1)
    assert git.run(vault.root, "log", "-1", "--format=%s").stdout.strip() == "import: claude 1 episodes (conversations.json)"


def test_update_writes_superseding_version(vault, export):
    write_episodes(vault, [conv("a")], Source.CLAUDE, export)
    old_id = episode_id(Source.CLAUDE, "a")
    newer = conv("a", updated_at=T0 + timedelta(days=1), title="Plan the trip v2")

    skipped = write_episodes(vault, [newer], Source.CLAUDE, export)
    assert skipped.episodes_written == 0 and skipped.episodes_skipped_existing == 1

    before = commit_count(vault)
    report = write_episodes(vault, [newer], Source.CLAUDE, export, update=True)
    assert report.episodes_written == 1 and commit_count(vault) == before + 1
    new_id = uuid5(PAM_NAMESPACE, "episode:claude:a:2026-10-02T18:04:11Z")
    fm, _ = mdio.read_model(vault.episode_path("default", new_id), EpisodeFrontmatter)
    assert fm.tags == [f"supersedes:{old_id}"] and fm.title == "Plan the trip v2"
    assert vault.episode_path("default", old_id).exists()

    again = write_episodes(vault, [newer], Source.CLAUDE, export, update=True)
    assert again.episodes_written == 0 and again.commit_sha is None

    newest = conv("a", updated_at=T0 + timedelta(days=2))
    write_episodes(vault, [newest], Source.CLAUDE, export, update=True)
    third = uuid5(PAM_NAMESPACE, "episode:claude:a:2026-10-03T18:04:11Z")
    fm, _ = mdio.read_model(vault.episode_path("default", third), EpisodeFrontmatter)
    assert fm.tags == [f"supersedes:{new_id}"]


def test_update_ignores_unchanged_or_undated(vault, export):
    write_episodes(vault, [conv("a")], Source.CLAUDE, export)
    same = write_episodes(vault, [conv("a")], Source.CLAUDE, export, update=True)
    assert same.episodes_written == 0
    undated = conv("a", updated_at=None, messages=[RawMessage(role="user", text="x")])
    assert write_episodes(vault, [undated], Source.CLAUDE, export, update=True).episodes_written == 0


def test_dry_run_writes_nothing(vault, export):
    before = commit_count(vault)
    report = write_episodes(vault, [conv("a"), conv("b")], Source.CLAUDE, export, dry_run=True)
    assert report.episodes_written == 2 and report.commit_sha is None
    assert commit_count(vault) == before
    assert git.status_porcelain(vault.root) == []
    assert not (vault.root / "imports" / "claude").exists()
    assert list((vault.root / "memory" / "default" / "episodes").iterdir()) == []


def test_crash_mid_import_commits_nothing_and_next_run_recovers(vault, export):
    def stream():
        yield conv("a")
        yield conv("b")
        raise RuntimeError("boom")

    before = commit_count(vault)
    with pytest.raises(RuntimeError):
        write_episodes(vault, stream(), Source.CLAUDE, export)
    assert commit_count(vault) == before
    assert git.status_porcelain(vault.root) == []
    assert list((vault.root / "memory" / "default" / "episodes").iterdir()) == []
    assert not (vault.root / "imports" / "claude").exists()

    report = write_episodes(vault, [conv("a"), conv("b")], Source.CLAUDE, export)
    assert report.episodes_written == 2 and commit_count(vault) == before + 1


def test_failed_commit_leaves_no_files(vault, export, monkeypatch):
    def broken(*args, **kwargs):
        raise PamError("git exploded")

    monkeypatch.setattr(git, "commit", broken)
    with pytest.raises(PamError):
        write_episodes(vault, [conv("a")], Source.CLAUDE, export)
    assert git.status_porcelain(vault.root) == []


def test_untracked_leftover_is_rewritten_and_committed(vault, export):
    path = vault.episode_path("default", episode_id(Source.CLAUDE, "a"))
    path.write_text("partial", encoding="utf-8")  # as left by a killed process
    report = write_episodes(vault, [conv("a")], Source.CLAUDE, export)
    assert report.episodes_written == 1 and git.status_porcelain(vault.root) == []
    mdio.read_model(path, EpisodeFrontmatter)


def test_crlf_text_still_verifies(vault, export):
    raw = conv("a", messages=[RawMessage(role="user", text="line1\r\nline2", created_at=T0)])
    write_episodes(vault, [raw], Source.CLAUDE, export)
    result = cli(vault, "episode", "verify")
    assert result.exit_code == 0, result.output


def test_agent_scope_and_many_episodes_use_folder_commit(vault, export, monkeypatch):
    import pam.normalize.writer as writer

    monkeypatch.setattr(writer, "MAX_EXPLICIT_COMMIT_PATHS", 2)
    report = write_episodes(vault, [conv(str(i)) for i in range(4)], Source.CLAUDE, export, agent="work")
    assert report.episodes_written == 4 and git.status_porcelain(vault.root) == []
    assert len(list((vault.root / "memory" / "work" / "episodes").iterdir())) == 4


def test_missing_export_and_uninitialized_vault(tmp_path, vault):
    with pytest.raises(PamError):
        write_episodes(vault, [], Source.CLAUDE, tmp_path / "nope.json")
    with pytest.raises(PamError):
        write_episodes(tmp_path / "empty", [], Source.CLAUDE, tmp_path / "nope.json")


# -- CLI -------------------------------------------------------------------------------------

@pytest.mark.parametrize("name,count", [("claude", 9), ("chatgpt", 5), ("gemini", 3)])
def test_cli_import_fixture_end_to_end(vault, name, count):
    fixture = str(FIXTURES / name / "export.zip")
    before = commit_count(vault)
    first = cli(vault, "--json", "import", "run", fixture)
    assert first.exit_code == 0, first.output
    report = json.loads(first.output[first.output.index("{"):])
    assert report["episodes_written"] == count and commit_count(vault) == before + 1
    second = cli(vault, "--json", "import", "run", fixture)
    assert json.loads(second.output[second.output.index("{"):])["episodes_written"] == 0
    assert commit_count(vault) == before + 1
    verify = cli(vault, "episode", "verify")
    assert verify.exit_code == 0 and f"{count} OK, 0 failed" in verify.output


def test_cli_episode_list_show(vault, export):
    write_episodes(vault, [conv("a", title="Alpha")], Source.CLAUDE, export)
    write_episodes(vault, [conv("b", title="Beta", source=Source.CHATGPT)], Source.CHATGPT, export)
    rows = json.loads(cli(vault, "--json", "episode", "list", "--source", "claude").output)
    assert [r["title"] for r in rows] == ["Alpha"]
    assert len(json.loads(cli(vault, "--json", "episode", "list").output)) == 2
    assert len(json.loads(cli(vault, "--json", "episode", "list", "--limit", "1").output)) == 1
    assert json.loads(cli(vault, "--json", "episode", "list", "--agent", "nobody").output) == []

    eid = str(episode_id(Source.CLAUDE, "a"))
    raw = cli(vault, "episode", "show", eid, "--raw")
    assert raw.output == vault.episode_path("default", eid).read_text(encoding="utf-8")
    assert "# Alpha" in raw.output
    assert cli(vault, "episode", "show", eid[:8]).exit_code == 0
    assert cli(vault, "episode", "show", "ffffffff").exit_code == 1


def test_cli_verify_detects_tampered_body(vault, export):
    write_episodes(vault, [conv("a"), conv("b")], Source.CLAUDE, export)
    path = vault.episode_path("default", episode_id(Source.CLAUDE, "a"))
    path.write_text(path.read_text(encoding="utf-8").replace("hello", "HELLO"), encoding="utf-8")
    result = cli(vault, "episode", "verify")
    assert result.exit_code == 1
    assert "1 OK, 1 failed" in result.output and "mismatch" in result.output
