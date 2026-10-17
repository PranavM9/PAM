"""The single vault write lock at `vault/.pam/write.lock`."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from filelock import FileLock, Timeout

from pam.core.errors import VaultBusy
from pam.core.vault import Vault


@contextmanager
def vault_write_lock(vault: Vault | str | os.PathLike | None = None, timeout: float = 10.0) -> Iterator[None]:
    """Hold the vault write lock for the duration of a `with` block.

    Behavior:
        Every vault writer holds this lock until its git commit, so only one writer runs at a time.
        Creates `.pam/` if it is missing.
    Exceptions:
        VaultBusy: The lock is not acquired within `timeout` seconds.
        VaultNotFound: No vault path is given or configured.
    Parameters:
        vault: A `Vault`, a vault path, or `None` to resolve from `--vault` / `PAM_VAULT`.
        timeout: Seconds to wait for the lock.
    """
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    v.pam_dir.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(v.lock_path), timeout=timeout)
    try:
        lock.acquire()
    except Timeout as e:
        raise VaultBusy(f"vault is busy: {v.lock_path} is held by another writer") from e
    try:
        yield
    finally:
        lock.release()
