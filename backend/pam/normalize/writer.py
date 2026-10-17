"""Write episodes and archive the raw export in one commit (SPEC §8 M2)."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Iterable
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid5

from pydantic import ValidationError

from pam.contracts.common import PAM_NAMESPACE, Slug, Source
from pam.contracts.episode import EpisodeFrontmatter, episode_id
from pam.contracts.raw import RawConversation
from pam.contracts.reports import ImportReport
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.lock import vault_write_lock
from pam.core.time import iso_z, utcnow
from pam.core.vault import Vault
from pam.normalize.render import render
from pam.sync import git

# Above this many paths, commit whole folders so the git command line stays within the OS limit.
MAX_EXPLICIT_COMMIT_PATHS = 1000


def _untracked_episodes(vault: Vault, agent: str) -> set[str]:
    prefix = vault.rel(vault.memory_dir(agent) / "episodes") + "/"
    return {path for status, path in git.status_porcelain(vault.root) if status == "??" and path.startswith(prefix)}


def _latest_versions(
    vault: Vault, agent: str, pending: set[str], errors: list[str]
) -> dict[tuple[str, str], tuple[datetime, UUID]]:
    latest: dict[tuple[str, str], tuple[datetime, UUID]] = {}
    folder = vault.memory_dir(agent) / "episodes"
    for path in sorted(folder.glob("*.md")) if folder.is_dir() else []:
        if vault.rel(path) in pending:
            continue
        try:
            fm, _ = mdio.read_model(path, EpisodeFrontmatter)
        except (PamError, ValidationError, OSError, ValueError) as e:
            errors.append(f"{path.name}: unreadable episode skipped for --update: {e}")
            continue
        key = (fm.source.value, fm.source_conversation_id)
        if key not in latest or fm.updated_at > latest[key][0]:
            latest[key] = (fm.updated_at, fm.id)
    return latest


def _archive_dir(vault: Vault, source: Source, now: datetime, filename: str) -> Path:
    # Archives are never modified, so a same-second collision moves to the next free second.
    while True:
        folder = vault.import_dir(source.value, now)
        if not (folder / filename).exists():
            return folder
        now += timedelta(seconds=1)


def _commit_paths(vault: Vault, archive: Path, agent: str, written: list[Path]) -> list[Path]:
    if len(written) < MAX_EXPLICIT_COMMIT_PATHS:
        return [archive, *written]
    return [archive.parent, vault.memory_dir(agent) / "episodes"]


def write_episodes(
    vault: Vault | str | os.PathLike,
    raws: Iterable[RawConversation],
    source: Source | str,
    original_file: str | os.PathLike,
    agent: Slug = "default",
    update: bool = False,
    dry_run: bool = False,
) -> ImportReport:
    """Archive a raw export and write one episode per new conversation in a single commit.

    Behavior:
        Holds the vault write lock for the whole run. The first time an episode needs writing, the
        export is copied byte-for-byte to `imports/<source>/<YYYYMMDDTHHMMSSZ>/<filename>`. Episodes
        whose id already exists are skipped. With `update`, a conversation whose `updated_at` is newer
        than its newest stored version gets a new episode with id
        `uuid5(PAM_NAMESPACE, "episode:<source>:<id>:<updated_at>")` and the tag `supersedes:<old_id>`.
        Everything is committed once as `import: <source> <n> episodes (<file>)`. When nothing is new
        there is no archive and no commit, and `archived_path` is empty. On any failure the files
        written in this run are removed and nothing is committed. Episode files left untracked by an
        earlier crash count as not yet written and are rewritten. With `dry_run`, nothing is written.
    Exceptions:
        VaultNotFound: The vault is not initialized.
        VaultBusy: The write lock is held by another writer.
        PamError: The original file is missing or git fails.
    Returns:
        The `ImportReport`; `errors` holds only this writer's own warnings.
    Parameters:
        vault: Vault or vault path.
        raws: Parsed conversations, consumed once.
        source: Provider the conversations came from.
        original_file: The export file to archive.
        agent: Agent scope that owns the episodes.
        update: Write newer versions of changed conversations.
        dry_run: Count what would be written without touching the vault.
    """
    started = time.perf_counter()
    v = (vault if isinstance(vault, Vault) else Vault(vault)).require_initialized()
    src = Source(source)
    original = Path(original_file)
    if not original.is_file():
        raise PamError(f"import file not found: {original}")

    errors: list[str] = []
    found = written = skipped = 0
    created: list[Path] = []
    episode_files: list[Path] = []
    archive_dir: Path | None = None
    imported_at = utcnow()

    def finish(archived: str, sha: str | None) -> ImportReport:
        return ImportReport(
            source=src,
            input_path=original.as_posix(),
            archived_path=archived,
            conversations_found=found,
            episodes_written=written,
            episodes_skipped_existing=skipped,
            errors=errors,
            commit_sha=sha,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    with vault_write_lock(v):
        pending = _untracked_episodes(v, agent)
        latest = _latest_versions(v, agent, pending, errors) if update else {}
        seen: set[UUID] = set()
        try:
            for raw in raws:
                found += 1
                key = (src.value, raw.source_conversation_id)
                new_id = episode_id(src, raw.source_conversation_id)
                supersedes: UUID | None = None
                if v.episode_path(agent, new_id).exists() and v.rel(v.episode_path(agent, new_id)) not in pending:
                    prior = latest.get(key)
                    if not (update and raw.updated_at and prior and raw.updated_at > prior[0]):
                        skipped += 1
                        continue
                    supersedes = prior[1]
                    new_id = uuid5(PAM_NAMESPACE, f"episode:{src.value}:{raw.source_conversation_id}:{iso_z(raw.updated_at)}")
                if new_id in seen or (supersedes and v.episode_path(agent, new_id).exists()):
                    skipped += 1
                    continue
                seen.add(new_id)
                path = v.episode_path(agent, new_id)
                if not dry_run:
                    if archive_dir is None:
                        archive_dir = _archive_dir(v, src, imported_at, original.name)
                        archive_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(original, archive_dir / original.name)
                    frontmatter, body = render(raw, imported_at, agent)
                    frontmatter = frontmatter.model_copy(update={"id": new_id})
                    if supersedes:
                        frontmatter.tags.append(f"supersedes:{supersedes}")
                    created.append(path)
                    mdio.write(path, frontmatter, body)
                    episode_files.append(path)
                written += 1

            if dry_run:
                planned = v.rel(_archive_dir(v, src, imported_at, original.name) / original.name) if written else ""
                return finish(planned, None)
            if archive_dir is None:
                return finish("", None)
            archive = archive_dir / original.name
            sha = git.commit(
                v.root,
                _commit_paths(v, archive, agent, episode_files),
                f"import: {src.value} {written} episodes ({original.name})",
            )
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            if archive_dir is not None:
                shutil.rmtree(archive_dir, ignore_errors=True)
                try:
                    archive_dir.parent.rmdir()
                except OSError:
                    pass  # other imports of this source exist
            raise
    return finish(v.rel(archive), sha)
