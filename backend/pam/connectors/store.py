"""Connector definitions in the vault: one `connectors/<id>.yaml` per connector (SPEC §8 M16, §7.16).

Behavior:
    Every write holds the vault write lock and ends in exactly one git commit; a write that would not
    change the file's bytes makes no commit. Nothing is deleted: `archive_connector` hides a
    connector instead. A file that fails validation is reported by `scan_connectors`, logged as a
    warning and skipped by everything else.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import yaml
from pydantic import ValidationError

from pam.contracts.common import Slug
from pam.contracts.connector import Connector
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.lock import vault_write_lock
from pam.core.vault import Vault
from pam.sync import git

log = logging.getLogger(__name__)

_SLUG = re.compile(Slug.__metadata__[0].pattern)


class ConnectorNotFound(PamError):
    """No connector (or no tool of that connector) has the requested id or name."""


@dataclass(frozen=True)
class ConnectorEntry:
    """One file in `connectors/`, valid or not.

    Parameters:
        id: The file name without `.yaml`.
        connector: The parsed connector, or `None` when the file is invalid.
        error: Why the file is invalid, or `None`.
    """

    id: str
    connector: Connector | None
    error: str | None = None

    @property
    def valid(self) -> bool:
        return self.connector is not None


def dump_yaml(connector: Connector) -> str:
    """Serialize a connector to the YAML stored in the vault (field order kept, Unicode as is)."""
    return yaml.safe_dump(connector.model_dump(mode="json"), sort_keys=False, allow_unicode=True)


def scan_connectors(vault: Vault) -> list[ConnectorEntry]:
    """Read every connector file, keeping the invalid ones with their error.

    Behavior:
        Files are read in id order. A file is invalid when it is not YAML, does not validate as
        `Connector`, has an unsupported major schema version, or its `id` differs from its file name.
    Returns:
        One entry per `connectors/*.yaml` file, archived ones included.
    Parameters:
        vault: The vault to read.
    """
    if not vault.connectors_dir.is_dir():
        return []
    return [_read_entry(path.stem, path) for path in sorted(vault.connectors_dir.glob("*.yaml"))]


def list_connectors(vault: Vault, include_archived: bool = False) -> list[Connector]:
    """List the valid connectors in id order.

    Behavior:
        Invalid files are logged as warnings and left out. Archived connectors are left out unless
        `include_archived` is true.
    Returns:
        The connectors.
    Parameters:
        vault: The vault to read.
        include_archived: Whether to include archived connectors.
    """
    result = []
    for entry in scan_connectors(vault):
        if entry.connector is None:
            log.warning("skipping invalid connector file connectors/%s.yaml: %s", entry.id, entry.error)
        elif include_archived or not entry.connector.archived:
            result.append(entry.connector)
    return result


def get_connector(vault: Vault, id: str) -> Connector:
    """Load one connector, archived or not.

    Exceptions:
        ConnectorNotFound: `id` is not a slug or has no file.
        PamError: The file is invalid (exit code 2).
    Returns:
        The connector.
    Parameters:
        vault: The vault to read.
        id: Connector id.
    """
    path = vault.connector_path(id) if _SLUG.match(id) else None
    if path is None or not path.is_file():
        raise ConnectorNotFound(f"connector {id!r} not found")
    entry = _read_entry(id, path)
    if entry.connector is None:
        raise PamError(f"connector file connectors/{id}.yaml is invalid: {entry.error}", exit_code=2)
    return entry.connector


def save_connector(vault: Vault, connector: Connector) -> str | None:
    """Create or replace a connector file; one commit `connector: save <id>`.

    Behavior:
        Validates the model again (it may have been built without validation), writes the YAML under
        the vault write lock and commits it. Unchanged bytes make no write and no commit.
    Exceptions:
        PamError: The connector does not validate (exit code 2), or git fails.
        VaultBusy: The vault write lock was not acquired.
    Returns:
        The commit sha, or `None` when nothing changed.
    Parameters:
        vault: The vault to write.
        connector: The connector to store.
    """
    try:
        connector = Connector.model_validate(connector.model_dump())
    except ValidationError as e:
        raise PamError(f"invalid connector: {e}", exit_code=2) from e
    return _write(vault, connector, f"connector: save {connector.id}")


def archive_connector(vault: Vault, id: str) -> str | None:
    """Archive a connector instead of deleting it; one commit `connector: archive <id>`.

    Behavior:
        Sets `archived: true` and `enabled: false`. Archiving an archived, disabled connector makes
        no commit.
    Exceptions:
        ConnectorNotFound: No such connector.
        PamError: The file is invalid (exit code 2), or git fails.
        VaultBusy: The vault write lock was not acquired.
    Returns:
        The commit sha, or `None` when nothing changed.
    Parameters:
        vault: The vault to write.
        id: Connector id.
    """
    connector = get_connector(vault, id).model_copy(update={"archived": True, "enabled": False})
    return _write(vault, connector, f"connector: archive {id}")


def _write(vault: Vault, connector: Connector, message: str) -> str | None:
    path = vault.connector_path(connector.id)
    text = dump_yaml(connector)
    with vault_write_lock(vault):
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return None
        mdio.write_text(path, text)
        return git.commit(vault.root, [path], message)


def _read_entry(id: str, path) -> ConnectorEntry:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return ConnectorEntry(id, None, "not a YAML mapping")
        mdio.check_schema_version(raw.get("schema_version"))
        connector = Connector.model_validate(raw)
    except (OSError, yaml.YAMLError, ValidationError, PamError) as e:
        return ConnectorEntry(id, None, " ".join(str(e).split()))
    if connector.id != id:
        return ConnectorEntry(id, None, f"id {connector.id!r} does not match the file name")
    return ConnectorEntry(id, connector)
