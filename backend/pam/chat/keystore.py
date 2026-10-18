"""Provider key store for chat: the settings file under `vault/.pam/` and its environment fallback (CHG-0023).

Behavior:
    Holds the Anthropic and OpenRouter API keys and the Ollama base URL that the Settings page
    writes. The file `vault/.pam/secrets.json` lives in the gitignored `.pam/` folder, so it is never
    committed. A stored value wins over the environment variable of the same provider. Keys are
    write-only: nothing here returns a key to the API, only whether one is set and its last 4 characters.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, get_args

from pam.core.errors import PamError
from pam.core.vault import Vault

Provider = Literal["anthropic", "openrouter", "ollama"]
Source = Literal["settings", "env", "none"]

PROVIDERS: tuple[str, ...] = get_args(Provider)
ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_BASE_URL",
}
STORE_FILE = "secrets.json"
STORE_MODE = 0o600
REDACTED = "***"
# A shorter secret would reveal most of itself through its last four characters.
LAST4_MIN_LENGTH = 12
SECRET_PROVIDERS = ("anthropic", "openrouter")

_bound: Vault | None = None


def bind(vault: Vault | None) -> None:
    """Remember the vault whose store the LLM layer reads (the API sets it when the app is created).

    Parameters:
        vault: The served vault, or `None` to resolve from `--vault` / `PAM_VAULT` again.
    """
    global _bound
    _bound = vault


def store_path(vault: Vault) -> Path:
    """Return the path of the settings file inside `vault`."""
    return vault.pam_dir / STORE_FILE


def read_store(vault: Vault) -> dict[str, str]:
    """Read the stored values, or an empty dict when the file does not exist.

    Exceptions:
        PamError: The file is not a JSON object of strings. The message never contains its content.
    Returns:
        A mapping from provider to stored value.
    Parameters:
        vault: The vault that owns the store.
    """
    return {k: v for k, v in _read_all(vault).items() if k in PROVIDERS and v}


def _read_all(vault: Vault) -> dict[str, str]:
    """Read every entry of the store, provider or not (`{}` when the file does not exist)."""
    path = store_path(vault)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise PamError(f"unreadable settings store {path.name}: {type(e).__name__}") from None
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise PamError(f"unreadable settings store {path.name}: not an object of strings")
    return data


def set_value(vault: Vault, provider: str, value: str | None) -> None:
    """Store or clear one provider's value.

    Behavior:
        Writes atomically through a temp file created with mode 0600 (POSIX), then replaces the
        store. `None` removes the provider's entry. No git commit is made: the file is gitignored.
    Exceptions:
        PamError: The provider is unknown, or the existing store is unreadable.
        OSError: The file cannot be written.
    Parameters:
        vault: The vault that owns the store.
        provider: One of `PROVIDERS`.
        value: The key or URL, or `None` to clear it.
    """
    if provider not in PROVIDERS:
        raise PamError(f"unknown provider {provider!r}", exit_code=2)
    data = read_store(vault)
    if value is None:
        data.pop(provider, None)
    else:
        data[provider] = value
    path = store_path(vault)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, STORE_MODE)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    if os.name == "posix":
        path.chmod(STORE_MODE)


def lookup(provider: str, vault: Vault | None = None) -> tuple[str | None, Source]:
    """Find the value to use for a provider and where it came from.

    Behavior:
        The settings store wins over the environment variable. With no `vault`, the bound vault is
        used, then `--vault` / `PAM_VAULT`; when none resolves, only the environment is consulted.
    Exceptions:
        PamError: The settings store is unreadable.
    Returns:
        `(value, source)`; `(None, "none")` when neither is set.
    Parameters:
        provider: One of `PROVIDERS`.
        vault: The vault to read, or `None` for the current one.
    """
    v = vault or _current_vault()
    if v is not None and (stored := read_store(v).get(provider)):
        return stored, "settings"
    if env := os.environ.get(ENV_VARS.get(provider, "")):
        return env, "env"
    return None, "none"


def lookup_secret(name: str, vault: Vault | None = None) -> str | None:
    """Find a secret by its own name, such as a connector's `auth.env_var` (CHG-0027).

    Behavior:
        The settings store entry `name` wins over the environment variable `name`. Vault
        resolution is the same as in `lookup`.
    Exceptions:
        PamError: The settings store is unreadable.
    Returns:
        The secret, or `None` when neither is set.
    Parameters:
        name: The secret's name, used as both the store key and the environment variable.
        vault: The vault to read, or `None` for the current one.
    """
    v = vault or _current_vault()
    if v is not None and (stored := _read_all(v).get(name)):
        return stored
    return os.environ.get(name) or None


def last4(value: str) -> str:
    """Return the last 4 characters of a key, or an empty string when the key is too short to show any."""
    return value[-4:] if len(value) >= LAST4_MIN_LENGTH else ""


def status(vault: Vault) -> list[dict]:
    """Describe every provider's value without exposing a key.

    Behavior:
        Anthropic and OpenRouter rows carry `is_set`, `last4` and `source` only. The Ollama row also
        carries `value`, because a base URL is not a secret.
    Exceptions:
        PamError: The settings store is unreadable.
    Returns:
        One dict per provider: `{provider, is_set, last4, source, value}`.
    Parameters:
        vault: The vault that owns the store.
    """
    rows = []
    for provider in PROVIDERS:
        value, source = lookup(provider, vault)
        secret = provider in SECRET_PROVIDERS
        rows.append({
            "provider": provider,
            "is_set": value is not None,
            "last4": last4(value) if value and secret else None,
            "source": source,
            "value": value if value and not secret else None,
        })
    return rows


def redact(text: str) -> str:
    """Replace every known key (store and environment) in `text` with `***`.

    Behavior:
        Never raises: an unreadable store only means its values cannot be masked.
    Returns:
        The text without any configured key.
    Parameters:
        text: Text that may quote a key, such as a provider error message.
    """
    for provider in SECRET_PROVIDERS:
        candidates = [os.environ.get(ENV_VARS[provider])]
        try:
            candidates.append(lookup(provider)[0])
        except PamError:
            pass
        for secret in candidates:
            if secret:
                text = text.replace(secret, REDACTED)
    return text


def _current_vault() -> Vault | None:
    if _bound is not None:
        return _bound
    try:
        return Vault.resolve()
    except PamError:
        return None
