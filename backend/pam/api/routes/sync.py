"""`POST /api/sync` and `GET /api/sync/status`: bring outside edits into git and the index (SPEC §7.14)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from pam.contracts.reports import SyncReport
from pam.core.errors import VaultBusy
from pam.core.vault import Vault
from pam.api.deps import get_vault
from pam.sync import git
from pam.sync.watcher import TRANSCRIPT_SUFFIX, sync

router = APIRouter(tags=["sync"])


@router.post("/sync", response_model=SyncReport)
def post_sync(vault: Vault = Depends(get_vault)) -> SyncReport:
    """Run one sync pass.

    Behavior:
        Commits and reindexes files edited outside PAM; a clean vault changes nothing.
    Exceptions:
        VaultBusy: The write lock is held and files are waiting (409).
        PamError: Git fails.
    Returns:
        The dirty paths, the number of reindexed documents and the commit sha.
    Parameters:
        vault: The served vault.
    """
    result = sync(vault)
    if result.busy:
        raise VaultBusy("vault busy: another writer holds the lock; try again shortly")
    return result.report


@router.get("/sync/status", response_model=SyncReport)
def sync_status(vault: Vault = Depends(get_vault)) -> SyncReport:
    """Report what a sync would pick up now, without changing anything.

    Behavior:
        Lists the paths git sees as changed, leaving out unfinished session transcripts. Nothing is
        committed or reindexed, so `reindexed` is 0 and `commit_sha` is `None`.
    Returns:
        The pending paths.
    Parameters:
        vault: The served vault.
    """
    dirty = sorted(
        rel
        for _, rel in git.status_porcelain(vault.root)
        if not (rel.startswith("working/") and rel.endswith(TRANSCRIPT_SUFFIX))
    )
    return SyncReport(dirty_paths=dirty, reindexed=0, commit_sha=None)
