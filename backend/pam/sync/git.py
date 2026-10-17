"""Git helper for vault writers: commit, status, restore, and init-time repo config (SPEC §8 M10).

Behavior:
    Runs the `git` CLI through `subprocess` against the vault repo. Every command passes
    `safe.directory=<vault>` on the command line, so it works on Docker bind mounts, and commits pass
    `user.name`/`user.email`, so no global git identity is needed. Paths sent to git are
    vault-relative POSIX.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path, PurePosixPath

from pam.core.errors import PamError

GIT_AUTHOR_NAME = "PAM"
GIT_AUTHOR_EMAIL = "pam@local"
DERIVED_DIR = ".pam/"


def _root(vault: str | os.PathLike) -> Path:
    return Path(vault).resolve()


def run(
    vault: str | os.PathLike, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run one git command inside the vault repo.

    Behavior:
        Runs `git -C <vault> -c safe.directory=<vault> -c core.quotePath=false <args>` with UTF-8
        output. Stdout is returned unstripped, so porcelain output keeps its leading spaces.
    Exceptions:
        PamError: `git` is not on PATH, or the command exits non-zero while `check` is true.
    Returns:
        The completed process with `stdout` and `stderr` as text.
    Parameters:
        vault: Vault root folder.
        args: Git subcommand and its arguments.
        check: Raise on a non-zero exit code.
    """
    root = _root(vault)
    cmd = ["git", "-C", str(root), "-c", f"safe.directory={root.as_posix()}", "-c", "core.quotePath=false", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    except FileNotFoundError as e:
        raise PamError("git is not installed or not on PATH") from e
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip()
        raise PamError(f"git {' '.join(args)} failed: {detail}")
    return proc


def configure_repo(vault: str | os.PathLike) -> None:
    """Apply the init-time git config to the vault repo.

    Behavior:
        Sets `core.autocrlf=false` in the repo config. Adds the vault path to the global
        `safe.directory` list unless it or `*` is already listed, because git ignores
        `safe.directory` in repo config. Safe to call repeatedly.
    Exceptions:
        PamError: The folder is not a git repo or a git command fails.
    Parameters:
        vault: Vault root folder (already `git init`-ed).
    """
    root = _root(vault)
    run(root, "config", "core.autocrlf", "false")
    listed = run(root, "config", "--global", "--get-all", "safe.directory", check=False).stdout.splitlines()
    if root.as_posix() not in listed and "*" not in listed:
        run(root, "config", "--global", "--add", "safe.directory", root.as_posix())


def _rel(root: Path, path: str | os.PathLike) -> str:
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(root)
        except ValueError as e:
            raise PamError(f"{path} is outside the vault {root}") from e
    rel = PurePosixPath(p.as_posix())
    if rel.is_absolute() or ".." in rel.parts or str(rel) in ("", "."):
        raise PamError(f"{path} is not a file path inside the vault")
    return str(rel)


def commit(vault: str | os.PathLike, paths: list[str | os.PathLike], message: str) -> str:
    """Stage the given paths and record them as one commit by `PAM <pam@local>`.

    Behavior:
        Runs `git add -- <paths>`, then `git commit -m <message> --author "PAM <pam@local>" -- <paths>`,
        so other staged changes stay out of the commit. Absolute paths must lie inside the vault.
    Exceptions:
        PamError: `paths` is empty, a path is outside the vault, nothing changed in `paths`, or git fails.
    Returns:
        The 40-character sha of the new commit.
    Parameters:
        vault: Vault root folder.
        paths: Files to commit, absolute or vault-relative.
        message: Commit message.
    """
    root = _root(vault)
    if not paths:
        raise PamError("commit needs at least one path")
    rels = [_rel(root, p) for p in paths]
    run(root, "add", "--", *rels)
    if run(root, "diff", "--cached", "--quiet", "--", *rels, check=False).returncode == 0:
        raise PamError(f"nothing to commit for {', '.join(rels)}")
    run(
        root,
        "-c", f"user.name={GIT_AUTHOR_NAME}",
        "-c", f"user.email={GIT_AUTHOR_EMAIL}",
        "commit", "-q", "-m", message,
        "--author", f"{GIT_AUTHOR_NAME} <{GIT_AUTHOR_EMAIL}>",
        "--", *rels,
    )
    return run(root, "rev-parse", "HEAD").stdout.strip()


def status_porcelain(vault: str | os.PathLike) -> list[tuple[str, str]]:
    """List the dirty paths in the vault, excluding the derived `.pam/` folder.

    Behavior:
        Parses `git status --porcelain -z --untracked-files=all`. Each entry is the two-letter `XY`
        code (`" M"`, `"??"`, `"D "`, …) and the vault-relative POSIX path. Renames and copies report
        the new path.
    Exceptions:
        PamError: The folder is not a git repo or git fails.
    Returns:
        `(status, path)` pairs in git's order.
    Parameters:
        vault: Vault root folder.
    """
    out = run(vault, "status", "--porcelain", "-z", "--untracked-files=all").stdout
    fields = out.split("\0")
    entries: list[tuple[str, str]] = []
    i = 0
    while i < len(fields):
        field = fields[i]
        i += 1
        if not field:
            continue
        status, path = field[:2], field[3:]
        if status[0] in "RC":
            i += 1  # the next field is the rename/copy source path
        if not path.startswith(DERIVED_DIR):
            entries.append((status, path))
    return entries


def restore(vault: str | os.PathLike, path: str | os.PathLike) -> None:
    """Restore one tracked file from HEAD.

    Behavior:
        Runs `git checkout HEAD -- <path>`, which rewrites the file and its index entry from HEAD.
        It never deletes anything; a path not in HEAD is an error.
    Exceptions:
        PamError: The path is outside the vault, is not in HEAD, or git fails.
    Parameters:
        vault: Vault root folder.
        path: File to restore, absolute or vault-relative.
    """
    root = _root(vault)
    run(root, "checkout", "HEAD", "--", _rel(root, path))


def head_sha(vault: str | os.PathLike) -> str | None:
    """Return the sha of the current HEAD commit.

    Behavior:
        Runs `git rev-parse --verify -q HEAD`.
    Exceptions:
        PamError: git is not on PATH.
    Returns:
        The 40-character sha, or `None` before the first commit or outside a repo.
    Parameters:
        vault: Vault root folder.
    """
    proc = run(vault, "rev-parse", "--verify", "-q", "HEAD", check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None
