"""Vault sync: commit and reindex edits made outside PAM, and restore deleted files (SPEC §8 M10).

Behavior:
    `sync` reads `git status`, and on a dirty tree takes the vault write lock, restores deleted
    files from HEAD (§11 item 9), refuses edited episode bodies and invalid frontmatter, commits
    the rest as one `manual: <n> files` commit, and reindexes it. `.pam/` is never looked at.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import BaseModel, ValidationError

from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Fact
from pam.contracts.project import Project
from pam.contracts.reports import SyncReport
from pam.contracts.skill import Skill
from pam.contracts.working import WorkingMemory
from pam.core import mdio
from pam.core.errors import PamError, VaultBusy
from pam.core.ids import sha256_text
from pam.core.lock import vault_write_lock
from pam.core.vault import Vault
from pam.index.indexer import doc_type_of, index_paths
from pam.sync import git

log = logging.getLogger(__name__)

DOC_MODELS: dict[str, type[BaseModel]] = {"fact": Fact, "project": Project, "skill": Skill}
IMMUTABLE_BODY = "episode body changed (body_sha256 mismatch)"


@dataclass
class SyncResult:
    """Outcome of one sync pass, with more detail than the §7.12 `SyncReport`.

    Behavior:
        `dirty_paths` lists every dirty path found. Each one is then committed, restored, or left
        uncommitted as an immutable violation or an invalid file. `busy` means the lock was held
        and nothing was touched.
    """

    dirty_paths: list[str] = field(default_factory=list)
    committed: list[str] = field(default_factory=list)
    restored: list[str] = field(default_factory=list)
    immutable_violations: list[str] = field(default_factory=list)
    invalid: dict[str, str] = field(default_factory=dict)
    reindexed: int = 0
    commit_sha: str | None = None
    busy: bool = False

    @property
    def report(self) -> SyncReport:
        return SyncReport(dirty_paths=self.dirty_paths, reindexed=self.reindexed, commit_sha=self.commit_sha)

    @property
    def problems(self) -> list[str]:
        """One line per path that was restored or left uncommitted."""
        lines = [f"{p}: deleted outside PAM; restored from HEAD" for p in self.restored]
        lines += [f"{p}: {IMMUTABLE_BODY}; not committed" for p in self.immutable_violations]
        lines += [f"{p}: {reason}; not committed" for p, reason in self.invalid.items()]
        return lines


def _head_body(v: Vault, rel: str) -> str | None:
    proc = git.run(v.root, "show", f"HEAD:{rel}", check=False)
    return mdio.split(proc.stdout)[1] if proc.returncode == 0 else None


def _check(v: Vault, rel: str) -> str | None:
    """Return why a changed file may not be committed, or `None` when it may."""
    doc_type = doc_type_of(rel)
    is_working = rel.startswith("working/") and rel.endswith(".md") and rel.count("/") == 1
    if doc_type is None and not is_working:
        return None
    try:
        data, body = mdio.split(v.abs(rel).read_bytes().decode("utf-8"))
        mdio.check_schema_version(data.get("schema_version"))
        if doc_type == "episode":
            fm = EpisodeFrontmatter.model_validate(data)
            # The HEAD comparison also catches a body edit whose `body_sha256` was rewritten to match.
            if sha256_text(body) != fm.body_sha256 or _head_body(v, rel) not in (None, body):
                return IMMUTABLE_BODY
        else:
            (WorkingMemory if is_working else DOC_MODELS[doc_type]).model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        return f"invalid frontmatter ({'.'.join(str(x) for x in first['loc']) or 'frontmatter'}: {first['msg']})"
    except Exception as e:  # noqa: BLE001 - YAML, UTF-8, schema-version, and IO failures all mean "do not commit"
        return f"unreadable ({e})"
    return None


def _apply(v: Vault, entries: list[tuple[str, str]], result: SyncResult) -> None:
    for status, rel in entries:
        if "U" in status or status in ("AA", "DD"):
            result.invalid[rel] = "unmerged git conflict"
        elif "D" in status:
            try:
                git.restore(v.root, rel)
                result.restored.append(rel)
            except PamError as e:
                result.invalid[rel] = f"deleted and cannot be restored ({e})"
        else:
            reason = _check(v, rel)
            if reason == IMMUTABLE_BODY:
                result.immutable_violations.append(rel)
            elif reason:
                result.invalid[rel] = reason
            else:
                result.committed.append(rel)
    if result.committed:
        try:
            result.commit_sha = git.commit(v.root, result.committed, f"manual: {len(result.committed)} files")
        except PamError as e:
            if not str(e).startswith("nothing to commit"):
                raise
            result.committed = []  # only line-ending or stat changes: git sees nothing to record
    touched = result.committed + result.restored
    if touched:
        try:
            result.reindexed = index_paths(v, touched).documents_indexed
        except Exception as e:  # noqa: BLE001 - the commit is done; a stale index is repaired by `pam index`
            log.warning("reindex of %d paths failed (%s); run `pam index` to repair", len(touched), e)


def sync(vault: Vault | str | os.PathLike | None, *, lock_timeout: float = 0.0) -> SyncResult:
    """Bring edits made outside PAM into git and the index.

    Behavior:
        Runs one `git status --porcelain` (`.pam/` excluded); a clean tree returns at once with no
        lock. Otherwise takes the vault write lock and re-reads the status. Deleted files are
        restored from HEAD. A changed episode whose body does not hash to `body_sha256`, or differs
        from the HEAD body, is an immutable violation. Fact, project, skill, and working-memory
        files must validate against their §7 model. Everything else dirty is committed in one
        `manual: <n> files` commit, and the committed and restored paths are reindexed. A held
        lock returns `busy=True` without touching anything. Episode bodies are never rewritten.
    Exceptions:
        VaultNotFound: No vault path is given or configured.
        PamError: The vault is not a git repo or a git command fails.
    Returns:
        The `SyncResult`; its `report` is the §7.12 `SyncReport`.
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
        lock_timeout: Seconds to wait for the write lock before giving up as busy.
    """
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    entries = git.status_porcelain(v.root)
    if not entries:
        return SyncResult()
    try:
        with vault_write_lock(v, timeout=lock_timeout):
            entries = git.status_porcelain(v.root)
            result = SyncResult(dirty_paths=sorted(rel for _, rel in entries))
            _apply(v, entries, result)
            return result
    except VaultBusy:
        return SyncResult(dirty_paths=sorted(rel for _, rel in entries), busy=True)


def sync_once(vault: Vault | str | os.PathLike | None) -> SyncReport:
    """Run one sync pass and return its §7.12 `SyncReport`.

    Behavior:
        Runs `sync(vault)` and logs one warning per restored, refused, or invalid path; a held
        lock is logged at info level and leaves the paths for the next sync. A second call with nothing changed makes no commit and reports
        no dirty paths.
    Exceptions:
        VaultNotFound: No vault path is given or configured.
        PamError: The vault is not a git repo or a git command fails.
    Returns:
        The dirty paths, the number of reindexed documents, and the commit sha (or `None`).
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
    """
    result = sync(vault)
    if result.busy:
        log.info("vault busy: sync skipped; %d dirty paths left for the next sync", len(result.dirty_paths))
    for line in result.problems:
        log.warning(line)
    return result.report


def sync_before_read(vault: Vault | str | os.PathLike | None) -> SyncReport | None:
    """Run `sync_once` before a read without ever failing the read.

    Behavior:
        Any exception from `sync_once` is logged as a warning and swallowed.
    Returns:
        The `SyncReport`, or `None` when the sync failed.
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
    """
    try:
        report = sync_once(vault)
    except Exception as e:  # noqa: BLE001 - a sync failure must not break search
        log.warning("vault sync skipped: %s", e)
        return None
    return report


def watch(
    vault: Vault | str | os.PathLike | None,
    interval: float = 2.0,
    on_result: Callable[[SyncResult], None] | None = None,
    ticks: int | None = None,
) -> None:
    """Run `sync` in a polling loop.

    Behavior:
        Calls `sync` every `interval` seconds and passes each result to `on_result`. A busy vault
        skips that tick. A `PamError` is logged and the loop continues. Stops after `ticks` passes
        when given, otherwise runs until interrupted.
    Parameters:
        vault: Vault or path; `None` resolves `--vault` / `PAM_VAULT`.
        interval: Seconds between passes.
        on_result: Callback for each pass's result.
        ticks: Number of passes, or `None` for no limit.
    """
    n = 0
    while ticks is None or n < ticks:
        try:
            result = sync(vault)
        except PamError as e:
            log.warning("vault sync failed: %s", e)
        else:
            if on_result is not None:
                on_result(result)
        n += 1
        if ticks is None or n < ticks:
            time.sleep(interval)
