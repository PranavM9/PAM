"""Load and serialize `vault/pam.toml` (`PamConfig`, §7.13)."""

from __future__ import annotations

import os
import tomllib

import tomli_w

from pam.contracts.config import PamConfig
from pam.core.errors import PamError
from pam.core.mdio import check_schema_version
from pam.core.vault import Vault


def load(vault: Vault | str | os.PathLike | None = None) -> PamConfig:
    """Load the vault's effective configuration.

    Behavior:
        Returns the built-in defaults when `pam.toml` does not exist.
    Exceptions:
        VaultNotFound: No vault path is given or configured.
        PamError: `pam.toml` is not valid TOML (exit code 2).
        SchemaVersionError: The major `schema_version` is unknown.
        pydantic.ValidationError: The file does not match `PamConfig`.
    Returns:
        The validated configuration.
    Parameters:
        vault: A `Vault`, a vault path, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    if not v.config_path.is_file():
        return PamConfig()
    try:
        data = tomllib.loads(v.config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise PamError(f"invalid TOML in {v.config_path}: {e}", exit_code=2) from e
    check_schema_version(data.get("schema_version"))
    return PamConfig.model_validate(data)


def dump_toml(cfg: PamConfig) -> str:
    """Serialize a configuration as `pam.toml` text.

    Returns:
        The TOML text.
    Parameters:
        cfg: Configuration to serialize.
    """
    return tomli_w.dumps(cfg.model_dump(mode="json", exclude_none=True))
