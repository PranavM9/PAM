"""PAM-02 T1 repo check: `mock/tmobile/`, `.pm/` and `research/` are gone (PAM-02.md A1).

Behavior:
    Verifies the R1 paths are absent from both the worktree and `git ls-files`, that
    `docker-compose.yml` carries no `tmobile-mock` service (and, where the `docker` CLI is
    available, that `docker compose config` agrees), that `CLAUDE.md` no longer points at
    `.pm/`, and that no tracked file outside `SPEC.md` and `frontend/src/` (T2 scope) still
    mentions `tmobile`, `.pm/` or `research/TODO`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
THIS_FILE = Path(__file__).resolve().relative_to(REPO_ROOT).as_posix()

R1_REMOVED_PATHS = ("mock/tmobile", ".pm", "research")


def _git_ls_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines()


def test_removed_paths_absent_from_worktree():
    for rel in R1_REMOVED_PATHS:
        assert not (REPO_ROOT / rel).exists(), f"{rel} still exists on disk"


def test_removed_paths_absent_from_git_ls_files():
    tracked = _git_ls_files()
    for rel in R1_REMOVED_PATHS:
        prefix = f"{rel}/"
        offenders = [p for p in tracked if p == rel or p.startswith(prefix)]
        assert offenders == [], f"git still tracks {rel}: {offenders}"


def test_docker_compose_yaml_has_no_tmobile_mock_service():
    doc = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    services = doc.get("services", {})
    assert "tmobile-mock" not in services
    for name, service in services.items():
        depends_on = service.get("depends_on") or {}
        assert "tmobile-mock" not in depends_on, f"{name} still depends_on tmobile-mock"


def test_docker_compose_config_has_no_tmobile_mock_service():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not available in this environment")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        pytest.skip("docker compose plugin not available in this environment")
    result = subprocess.run(
        ["docker", "compose", "config"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "tmobile-mock" not in result.stdout


def test_claude_md_has_no_pm_reference():
    text = (REPO_ROOT / "CLAUDE.md").read_text()
    assert ".pm/" not in text
    assert "briefs.md" not in text
    assert "SPEC.md" in text
    assert "PAM-02.md" in text


def test_no_stray_references_outside_t2_scope():
    tracked = _git_ls_files()
    needles = ("tmobile", ".pm/", "research/todo")
    offenders: dict[str, list[str]] = {}
    for rel in tracked:
        if rel in ("SPEC.md", THIS_FILE) or rel.startswith("frontend/src/"):
            continue
        path = REPO_ROOT / rel
        try:
            text = path.read_text(errors="ignore").lower()
        except (UnicodeDecodeError, OSError):
            continue
        hits = [n for n in needles if n in text]
        if hits:
            offenders[rel] = hits
    assert offenders == {}
