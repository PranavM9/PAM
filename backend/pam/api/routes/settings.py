"""`PUT /api/models`, `POST /api/models/check` and `/api/settings/keys`: manage models and provider keys (CHG-0023)."""

from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pam.api.deps import get_vault
from pam.api.errors import VALIDATION_ERROR, ApiError
from pam.chat import keystore
from pam.chat.llm import resolve_model
from pam.contracts.config import ModelEntry
from pam.core import config
from pam.core.lock import vault_write_lock
from pam.core.mdio import write_text
from pam.core.vault import Vault
from pam.sync import git

router = APIRouter(tags=["settings"])

MAX_VALUE_LENGTH = 512
URL_SCHEMES = ("http://", "https://")


class CheckRequest(BaseModel):
    """Body of `POST /models/check`: one model id, or none to check every configured model."""

    id: str | None = None


class CheckResult(BaseModel):
    """Health of one model: whether a 1-token request succeeded, how long it took, and the error if not."""

    id: str
    ok: bool
    latency_ms: int
    error: str | None = None


class KeyStatus(BaseModel):
    """What the UI may know about a provider value: set or not, last 4 characters, and where it came from.

    `value` is filled only for the Ollama base URL, which is not a secret.
    """

    provider: Literal["anthropic", "openrouter", "ollama"]
    is_set: bool
    last4: str | None = None
    source: Literal["settings", "env", "none"]
    value: str | None = None


class KeyUpdate(BaseModel):
    """Body of `PUT /settings/keys`: the provider and its new value, or `null` to clear it."""

    provider: Literal["anthropic", "openrouter", "ollama"]
    value: str | None = None


@router.put("/models", response_model=list[ModelEntry])
def put_models(entries: list[ModelEntry], vault: Vault = Depends(get_vault)) -> list[ModelEntry]:
    """Replace the model list in `pam.toml`.

    Behavior:
        Ids and labels are trimmed and must be non-empty; ids must be unique. Nothing is sent to a
        provider (use `POST /models/check`). The write holds the vault lock and ends in one commit;
        an unchanged list writes and commits nothing.
    Exceptions:
        ApiError: An id or label is empty, or an id repeats (400 `VALIDATION_ERROR`).
        VaultBusy: Another writer holds the lock (409).
    Returns:
        The saved models.
    Parameters:
        entries: The new list.
        vault: The served vault.
    """
    models = [m.model_copy(update={"id": m.id.strip(), "label": m.label.strip()}) for m in entries]
    seen: set[str] = set()
    for m in models:
        if not m.id or not m.label:
            raise ApiError(400, VALIDATION_ERROR, "every model needs a non-empty id and label")
        if m.id in seen:
            raise ApiError(400, VALIDATION_ERROR, f"duplicate model id {m.id!r}")
        seen.add(m.id)
    with vault_write_lock(vault):
        cfg = config.load(vault)
        if cfg.models != models:
            write_text(vault.config_path, config.dump_toml(cfg.model_copy(update={"models": models})))
            git.commit(vault.root, [vault.config_path], "pam: update models")
    return models


@router.post("/models/check", response_model=list[CheckResult])
async def check_models(body: CheckRequest | None = None, vault: Vault = Depends(get_vault)) -> list[CheckResult]:
    """Ping the configured models with a 1-token request, as `pam models check` does.

    Behavior:
        Pings run concurrently. A failing model is reported in its row, not raised.
    Exceptions:
        UnknownModel: `id` is not configured (400).
    Returns:
        One result per checked model, in configuration order; empty when none are configured.
    Parameters:
        body: Optional `{id}` to check a single model.
        vault: The served vault.
    """
    from pam.chat.llm import ping  # noqa: PLC0415 - litellm is slow to import

    cfg = config.load(vault)
    wanted = body.id if body else None
    models = [resolve_model(cfg, wanted)] if wanted else cfg.models
    results = await asyncio.gather(*(ping(m) for m in models))
    return [CheckResult(id=m.id, ok=r.ok, latency_ms=r.latency_ms, error=r.error) for m, r in zip(models, results)]


@router.get("/settings/keys", response_model=list[KeyStatus])
def get_keys(vault: Vault = Depends(get_vault)) -> list[KeyStatus]:
    """Report whether each provider value is set, never the key itself.

    Returns:
        One row per provider with `is_set`, `last4` and `source`.
    Parameters:
        vault: The served vault.
    """
    return [KeyStatus(**row) for row in keystore.status(vault)]


@router.put("/settings/keys", response_model=KeyStatus)
def put_key(body: KeyUpdate, vault: Vault = Depends(get_vault)) -> KeyStatus:
    """Set or clear one provider value in the settings store.

    Behavior:
        The value is trimmed. A key may not contain whitespace or exceed 512 characters; the Ollama
        value must be an `http://` or `https://` URL. Error messages never quote the value. The
        write makes no git commit.
    Exceptions:
        ApiError: The value is empty, malformed or too long (400 `VALIDATION_ERROR`).
    Returns:
        The provider's new status; the value is not echoed.
    Parameters:
        body: Provider and value (`null` clears).
        vault: The served vault.
    """
    value = body.value.strip() if body.value is not None else None
    if value is not None:
        if not value:
            raise ApiError(400, VALIDATION_ERROR, "value is empty; send null to clear it")
        if len(value) > MAX_VALUE_LENGTH:
            raise ApiError(400, VALIDATION_ERROR, f"value is longer than {MAX_VALUE_LENGTH} characters")
        if body.provider == "ollama":
            if not value.startswith(URL_SCHEMES):
                raise ApiError(400, VALIDATION_ERROR, "the Ollama base URL must start with http:// or https://")
        elif any(c.isspace() for c in value):
            raise ApiError(400, VALIDATION_ERROR, "a key cannot contain whitespace")
    keystore.set_value(vault, body.provider, value)
    row = next(r for r in keystore.status(vault) if r["provider"] == body.provider)
    return KeyStatus(**row)
