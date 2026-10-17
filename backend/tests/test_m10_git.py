"""M10 git helper tests (SPEC §8 M10, §9.3 T02).

Behavior:
    Runs `pam.sync.git` against fresh `tmp_path` repos. `GIT_CONFIG_GLOBAL` points at a temp file
    and system config is disabled, so no user identity is configured and the real global config is
    never touched.
"""

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pam.cli.main import app
from pam.core.errors import PamError
from pam.sync import git

SHA = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture(autouse=True)
def isolated_git_config(tmp_path_factory, monkeypatch):
    global_cfg = tmp_path_factory.mktemp("gitcfg") / "gitconfig"
    global_cfg.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_cfg))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for var in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "EMAIL"):
        monkeypatch.delenv(var, raising=False)
    return global_cfg


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()
    git.run(root, "init", "-q", "-b", "main")
    (root / ".gitignore").write_text(".pam/\n", encoding="utf-8")
    return root


def write(root: Path, rel: str, text: str = "x\n") -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_head_sha_is_none_on_empty_repo(repo):
    assert git.head_sha(repo) is None


def test_commit_returns_head_sha_and_pam_author(repo):
    write(repo, "memory/default/facts/a.md")
    sha = git.commit(repo, [".gitignore", "memory/default/facts/a.md"], "pam: add fact")
    assert SHA.match(sha)
    assert sha == git.head_sha(repo)
    log = git.run(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>|%s").stdout.strip()
    assert log == "PAM <pam@local>|PAM <pam@local>|pam: add fact"


def test_commit_accepts_absolute_paths_and_returns_posix_paths(repo):
    p = write(repo, "memory/shared/facts/b.md")
    git.commit(repo, [p], "pam: abs")
    files = git.run(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["memory/shared/facts/b.md"]


def test_commit_only_includes_given_paths(repo):
    git.commit(repo, [write(repo, "a.md")], "first")
    write(repo, "a.md", "changed\n")
    write(repo, "b.md")
    git.run(repo, "add", "b.md")
    git.commit(repo, ["a.md"], "second")
    files = git.run(repo, "show", "--name-only", "--format=", "HEAD").stdout.split()
    assert files == ["a.md"]
    assert ("A ", "b.md") in git.status_porcelain(repo)


def test_commit_with_nothing_to_commit_raises(repo):
    git.commit(repo, [write(repo, "a.md")], "first")
    before = git.head_sha(repo)
    with pytest.raises(PamError, match="nothing to commit"):
        git.commit(repo, ["a.md"], "again")
    assert git.head_sha(repo) == before


@pytest.mark.parametrize("paths", [[], ["../outside.md"]])
def test_commit_rejects_bad_paths(repo, paths):
    with pytest.raises(PamError):
        git.commit(repo, paths, "bad")


def test_commit_rejects_absolute_path_outside_vault(repo, tmp_path):
    with pytest.raises(PamError, match="outside the vault"):
        git.commit(repo, [write(tmp_path, "elsewhere.md")], "bad")


def test_status_porcelain_sees_modified_untracked_and_spaces_and_ignores_pam(repo):
    git.commit(repo, [".gitignore", write(repo, "facts/tracked.md")], "init")
    write(repo, "facts/tracked.md", "edited\n")
    write(repo, "facts/new.md")
    write(repo, "my notes/a file.md")
    write(repo, ".pam/index.db", "derived")
    git.run(repo, "add", "-f", ".pam/index.db")  # force-tracked so status would report it
    status = git.status_porcelain(repo)
    assert (" M", "facts/tracked.md") in status
    assert ("??", "facts/new.md") in status
    assert ("??", "my notes/a file.md") in status
    assert not any(path.startswith(".pam/") for _, path in status)


def test_status_porcelain_reports_rename_target(repo):
    git.commit(repo, [".gitignore", write(repo, "old name.md", "same content\n")], "init")
    git.run(repo, "mv", "old name.md", "new name.md")
    assert git.status_porcelain(repo) == [("R ", "new name.md")]


def test_status_porcelain_clean_repo_is_empty(repo):
    git.commit(repo, [".gitignore"], "init")
    assert git.status_porcelain(repo) == []


def test_restore_brings_back_deleted_file(repo):
    p = write(repo, "memory/default/episodes/e 1.md", "body\n")
    git.commit(repo, [p], "init")
    p.unlink()
    assert ("D", "memory/default/episodes/e 1.md") in [(s.strip(), path) for s, path in git.status_porcelain(repo)]
    git.restore(repo, "memory/default/episodes/e 1.md")
    assert p.read_text(encoding="utf-8") == "body\n"
    assert git.status_porcelain(repo) == [("??", ".gitignore")]


def test_restore_untracked_path_raises_and_keeps_file(repo):
    git.commit(repo, [write(repo, "a.md")], "init")
    p = write(repo, "untracked.md", "keep me\n")
    with pytest.raises(PamError):
        git.restore(repo, "untracked.md")
    assert p.read_text(encoding="utf-8") == "keep me\n"


def test_configure_repo_sets_autocrlf_and_safe_directory_once(repo, isolated_git_config):
    git.configure_repo(repo)
    git.configure_repo(repo)
    assert git.run(repo, "config", "--local", "core.autocrlf").stdout.strip() == "false"
    listed = git.run(repo, "config", "--global", "--get-all", "safe.directory").stdout.splitlines()
    assert listed == [repo.resolve().as_posix()]


def test_run_raises_pam_error_with_git_message(repo):
    with pytest.raises(PamError, match="no-such-subcommand"):
        git.run(repo, "no-such-subcommand")


def test_sync_cli_stub():
    result = CliRunner().invoke(app, ["sync"])
    assert result.exit_code == 0
    assert "not implemented until T09b" in result.output
