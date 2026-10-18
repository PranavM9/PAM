"""Settings routes: model list, health check and provider keys (CHG-0023).

Behavior:
    Covers `PUT /models`, `POST /models/check` and `GET|PUT /settings/keys`, and the promise that a
    key never reaches git, API responses, error messages or logs. No network: LiteLLM is patched.
    Fixtures and helpers come from `test_m13_api.py`.
"""

from __future__ import annotations

import logging
import os
import subprocess

import pytest

from pam.chat import keystore, llm
from pam.core import config
from pam.sync import git

from .test_m13_api import _error, client, vault  # noqa: F401 - fixtures are used by name

SECRET = "sk-test-SECRET123"
NEW_MODELS = [
    {"id": "openrouter/org/free-model:free", "label": "Free", "supports_tools": True},
    {"id": "ollama/llama3", "label": "Llama", "supports_tools": False},
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (*keystore.ENV_VARS.values(), "PAM_VAULT"):
        monkeypatch.delenv(name, raising=False)
    yield
    keystore.bind(None)


def _commit_count(vault) -> int:
    out = subprocess.run(
        ["git", "-C", str(vault.root), "rev-list", "--count", "HEAD"], capture_output=True, text=True, check=True
    )
    return int(out.stdout.strip())


def _row(client, provider: str) -> dict:
    return next(r for r in client.get("/api/settings/keys").json() if r["provider"] == provider)


# -- models -------------------------------------------------------------------------------------


def test_put_models_round_trips_with_one_commit(client, vault):
    before = _commit_count(vault)
    response = client.put("/api/models", json=NEW_MODELS)
    assert response.status_code == 200, response.text
    assert response.json() == NEW_MODELS
    assert client.get("/api/models").json() == NEW_MODELS
    assert [m.id for m in config.load(vault).models] == [m["id"] for m in NEW_MODELS]
    assert _commit_count(vault) == before + 1


def test_put_same_models_makes_no_commit(client, vault):
    client.put("/api/models", json=NEW_MODELS)
    before = _commit_count(vault)
    assert client.put("/api/models", json=NEW_MODELS).status_code == 200
    assert _commit_count(vault) == before


def test_put_empty_list_clears_models(client):
    assert client.put("/api/models", json=[]).json() == []
    assert client.get("/api/models").json() == []


@pytest.mark.parametrize(
    "body",
    [
        [{"id": "a/b", "label": "A"}, {"id": "a/b", "label": "Again"}],
        [{"id": "  ", "label": "Blank id"}],
        [{"id": "a/b", "label": ""}],
        [{"id": "a/b"}],
    ],
)
def test_put_models_rejects_invalid_lists(client, vault, body):
    before = _commit_count(vault)
    assert _error(client.put("/api/models", json=body), 400)["code"] == "VALIDATION_ERROR"
    assert _commit_count(vault) == before


def test_put_models_trims_whitespace(client):
    saved = client.put("/api/models", json=[{"id": " a/b ", "label": " Label "}]).json()
    assert saved == [{"id": "a/b", "label": "Label", "supports_tools": False}]


def test_put_models_while_vault_locked_is_409(client, vault):
    from pam.core.lock import vault_write_lock  # noqa: PLC0415

    with vault_write_lock(vault):
        assert _error(client.put("/api/models", json=NEW_MODELS), 409)["code"] == "CONFLICT"


# -- model check --------------------------------------------------------------------------------


def _patch_ping(monkeypatch, failing=()):
    async def fake(model):
        error = "AuthenticationError: bad key" if model.id in failing else None
        return llm.PingResult(error is None, 7, error)

    monkeypatch.setattr(llm, "ping", fake)


def test_check_all_models(client, monkeypatch):
    client.put("/api/models", json=NEW_MODELS)
    _patch_ping(monkeypatch, failing={"ollama/llama3"})
    rows = client.post("/api/models/check", json={}).json()
    assert rows == [
        {"id": "openrouter/org/free-model:free", "ok": True, "latency_ms": 7, "error": None},
        {"id": "ollama/llama3", "ok": False, "latency_ms": 7, "error": "AuthenticationError: bad key"},
    ]


def test_check_one_model_and_no_body(client, monkeypatch):
    client.put("/api/models", json=NEW_MODELS)
    _patch_ping(monkeypatch)
    assert [r["id"] for r in client.post("/api/models/check", json={"id": "ollama/llama3"}).json()] == ["ollama/llama3"]
    assert len(client.post("/api/models/check").json()) == 2


def test_check_unknown_model_is_400_and_empty_list_is_empty(client, monkeypatch):
    _patch_ping(monkeypatch)
    _error(client.post("/api/models/check", json={"id": "nope/none"}), 400)
    client.put("/api/models", json=[])
    assert client.post("/api/models/check", json={}).json() == []


# -- keys ---------------------------------------------------------------------------------------


def test_key_status_shows_set_and_last4_only(client, vault, caplog):
    caplog.set_level(logging.DEBUG)
    assert _row(client, "anthropic") == {
        "provider": "anthropic", "is_set": False, "last4": None, "source": "none", "value": None,
    }
    response = client.put("/api/settings/keys", json={"provider": "anthropic", "value": SECRET})
    assert response.status_code == 200
    assert response.json() == {
        "provider": "anthropic", "is_set": True, "last4": "T123", "source": "settings", "value": None,
    }
    listing = client.get("/api/settings/keys")
    for text in (response.text, listing.text, caplog.text):
        assert SECRET not in text
    assert _row(client, "anthropic")["last4"] == SECRET[-4:]


def test_key_is_stored_untracked_and_private(client, vault):
    client.put("/api/settings/keys", json={"provider": "openrouter", "value": SECRET})
    path = keystore.store_path(vault)
    assert path.is_file()
    tracked = subprocess.run(["git", "-C", str(vault.root), "ls-files"], capture_output=True, text=True).stdout
    assert ".pam" not in tracked and "secrets.json" not in tracked
    ignored = subprocess.run(["git", "-C", str(vault.root), "check-ignore", "-q", ".pam/secrets.json"])
    assert ignored.returncode == 0
    history = subprocess.run(["git", "-C", str(vault.root), "log", "-p", "--all"], capture_output=True, text=True).stdout
    assert SECRET not in history
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600


def test_clear_key(client):
    client.put("/api/settings/keys", json={"provider": "anthropic", "value": SECRET})
    cleared = client.put("/api/settings/keys", json={"provider": "anthropic", "value": None}).json()
    assert cleared["is_set"] is False and cleared["source"] == "none"
    assert _row(client, "anthropic")["is_set"] is False


def test_settings_value_wins_over_env_and_clearing_falls_back(client, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key-ABCDEFGH1234")
    assert _row(client, "anthropic")["source"] == "env"
    assert _row(client, "anthropic")["last4"] == "1234"
    client.put("/api/settings/keys", json={"provider": "anthropic", "value": SECRET})
    assert _row(client, "anthropic")["source"] == "settings"
    assert keystore.lookup("anthropic") == (SECRET, "settings")
    client.put("/api/settings/keys", json={"provider": "anthropic", "value": None})
    assert keystore.lookup("anthropic") == ("env-key-ABCDEFGH1234", "env")


def test_short_key_shows_no_last4(client):
    client.put("/api/settings/keys", json={"provider": "anthropic", "value": "short"})
    assert _row(client, "anthropic")["is_set"] is True
    assert _row(client, "anthropic")["last4"] == ""


def test_ollama_url_is_shown_and_validated(client):
    saved = client.put("/api/settings/keys", json={"provider": "ollama", "value": "http://ollama:11434"}).json()
    assert saved["value"] == "http://ollama:11434" and saved["last4"] is None
    _error(client.put("/api/settings/keys", json={"provider": "ollama", "value": "ollama:11434"}), 400)


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "anthropic", "value": ""},
        {"provider": "anthropic", "value": f"{SECRET} {SECRET}"},
        {"provider": "anthropic", "value": SECRET * 100},
        {"provider": "bing", "value": SECRET},
    ],
)
def test_invalid_key_updates_are_400_and_never_echo_the_value(client, body):
    response = client.put("/api/settings/keys", json=body)
    assert _error(response, 400)["code"] == "VALIDATION_ERROR"
    assert SECRET not in response.text


def test_corrupt_store_error_does_not_quote_the_file(client, vault):
    keystore.store_path(vault).parent.mkdir(exist_ok=True)
    keystore.store_path(vault).write_text(f'{{"anthropic": "{SECRET}"', encoding="utf-8")
    response = client.get("/api/settings/keys")
    assert response.status_code >= 400
    assert SECRET not in response.text


# -- the key reaches the provider call and never leaks back ---------------------------------------


def test_stored_key_is_passed_to_litellm_at_call_time(client, vault, monkeypatch):
    import litellm  # noqa: PLC0415

    seen: list[dict] = []

    async def fake(**kwargs):
        seen.append(kwargs)

    monkeypatch.setattr(litellm, "acompletion", fake)
    model = config.load(vault).models[0].model_copy(update={"id": "openrouter/org/m:free"})
    client.put("/api/settings/keys", json={"provider": "openrouter", "value": SECRET})
    import asyncio  # noqa: PLC0415

    assert asyncio.run(llm.ping(model)).ok
    assert seen[-1]["api_key"] == SECRET
    client.put("/api/settings/keys", json={"provider": "openrouter", "value": None})
    asyncio.run(llm.ping(model))
    assert "api_key" not in seen[-1]


def test_provider_errors_mask_the_key(client, vault, monkeypatch, caplog):
    import asyncio  # noqa: PLC0415

    import litellm  # noqa: PLC0415

    async def fail(**kwargs):
        raise litellm.AuthenticationError(f"invalid x-api-key {kwargs['api_key']}", "anthropic", "m")

    monkeypatch.setattr(litellm, "acompletion", fail)
    client.put("/api/settings/keys", json={"provider": "anthropic", "value": SECRET})
    client.put("/api/models", json=[{"id": "anthropic/claude-x", "label": "X"}])
    caplog.set_level(logging.DEBUG)
    response = client.post("/api/models/check", json={})
    row = response.json()[0]
    assert row["ok"] is False and "***" in row["error"]
    assert SECRET not in response.text and SECRET not in caplog.text
