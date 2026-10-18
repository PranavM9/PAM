"""M12 LLM layer and `pam models` tests (SPEC §8 M12, §9.3 T13 part 1).

Behavior:
    No network: `litellm.acompletion` is replaced by fakes that return OpenAI-style chunk dicts
    or raise LiteLLM's own exception classes, and `pam models check` runs with `ping` patched.
"""

from __future__ import annotations

import asyncio
import json

import litellm
import pytest
from typer.testing import CliRunner

from pam.chat import llm
from pam.cli.main import app
from pam.contracts.config import ModelEntry, PamConfig
from pam.core.config import dump_toml
from pam.core.vault import Vault, init_vault, set_vault_override

TOOLS_MODEL = ModelEntry(id="openrouter/acme/tooly:free", label="Tooly", supports_tools=True)
PLAIN_MODEL = ModelEntry(id="anthropic/claude-x", label="Plain")
TOOL_SCHEMA = [{"type": "function", "function": {"name": "search_memory", "parameters": {"type": "object"}}}]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_vault_env(monkeypatch):
    monkeypatch.delenv("PAM_VAULT", raising=False)
    set_vault_override(None)
    yield
    set_vault_override(None)


def _chunk(content=None, tool_calls=None, finish=None, usage=None, choices=True):
    chunk = {"choices": []}
    if choices:
        chunk["choices"] = [{"delta": {"content": content, "tool_calls": tool_calls}, "finish_reason": finish}]
    if usage:
        chunk["usage"] = usage
    return chunk


def _fake_stream(chunks, calls=None):
    async def fake(**kwargs):
        if calls is not None:
            calls.append(kwargs)

        async def gen():
            for c in chunks:
                yield c

        return gen()

    return fake


def _raising(exc):
    async def fake(**kwargs):
        raise exc

    return fake


def _collect(model, messages=None, tools=None):
    async def run():
        return [d async for d in llm.stream_chat(model, messages or [{"role": "user", "content": "hi"}], tools)]

    return asyncio.run(run())


def _vault(tmp_path, models):
    root = tmp_path / "vault"
    init_vault(root)
    vault = Vault(root)
    vault.config_path.write_text(dump_toml(PamConfig(models=models)), encoding="utf-8")
    return vault


# --- resolve_model ------------------------------------------------------------------------------


def test_resolve_model_finds_entry():
    cfg = PamConfig(models=[TOOLS_MODEL, PLAIN_MODEL])
    assert llm.resolve_model(cfg, PLAIN_MODEL.id) is cfg.models[1]


def test_unknown_model_raises():
    cfg = PamConfig(models=[TOOLS_MODEL])
    with pytest.raises(llm.UnknownModel, match="nope/model"):
        llm.resolve_model(cfg, "nope/model")
    with pytest.raises(llm.UnknownModel, match="none"):
        llm.resolve_model(PamConfig(), "nope/model")


# --- stream_chat --------------------------------------------------------------------------------


def test_text_deltas_join(monkeypatch):
    chunks = [_chunk("Hel"), _chunk("lo, "), _chunk("world"), _chunk(finish="stop")]
    monkeypatch.setattr(litellm, "acompletion", _fake_stream(chunks))
    deltas = _collect(PLAIN_MODEL)
    assert "".join(d.text for d in deltas if d.text) == "Hello, world"
    assert deltas[-1].finish_reason == "stop"
    assert all(d.tool_calls is None for d in deltas)


def test_tool_call_fragments_assemble(monkeypatch):
    frag = lambda **kw: [{"index": 0, **kw}]  # noqa: E731
    chunks = [
        _chunk(tool_calls=frag(id="call_1", type="function", function={"name": "search_memory", "arguments": ""})),
        _chunk(tool_calls=frag(function={"arguments": '{"query": "sql'})),
        _chunk(tool_calls=frag(function={"arguments": 'ite", "k": 5}'})),
        _chunk(finish="tool_calls"),
    ]
    monkeypatch.setattr(litellm, "acompletion", _fake_stream(chunks))
    deltas = _collect(TOOLS_MODEL, tools=TOOL_SCHEMA)
    with_calls = [d for d in deltas if d.tool_calls]
    assert len(with_calls) == 1
    (call,) = with_calls[0].tool_calls
    assert call == llm.ToolCall(id="call_1", name="search_memory", arguments={"query": "sqlite", "k": 5})
    assert with_calls[0].finish_reason == "tool_calls"
    assert json.loads(call.as_openai()["function"]["arguments"]) == {"query": "sqlite", "k": 5}


def test_two_parallel_tool_calls_keep_order(monkeypatch):
    chunks = [
        _chunk(tool_calls=[{"index": 1, "id": "b", "function": {"name": "get_episode", "arguments": "{}"}}]),
        _chunk(tool_calls=[{"index": 0, "id": "a", "function": {"name": "search_memory", "arguments": "{}"}}]),
    ]
    monkeypatch.setattr(litellm, "acompletion", _fake_stream(chunks))
    deltas = _collect(TOOLS_MODEL, tools=TOOL_SCHEMA)
    assert [c.id for c in deltas[-1].tool_calls] == ["a", "b"]


def test_invalid_tool_arguments_raise(monkeypatch):
    chunks = [
        _chunk(tool_calls=[{"index": 0, "id": "a", "function": {"name": "x", "arguments": "{oops"}}]),
        _chunk(finish="tool_calls"),
    ]
    monkeypatch.setattr(litellm, "acompletion", _fake_stream(chunks))
    with pytest.raises(llm.LLMError, match="invalid JSON"):
        _collect(TOOLS_MODEL, tools=TOOL_SCHEMA)


def test_usage_from_last_chunk(monkeypatch):
    chunks = [_chunk("ok"), _chunk(finish="stop"), _chunk(choices=False, usage={"prompt_tokens": 12, "completion_tokens": 3})]
    monkeypatch.setattr(litellm, "acompletion", _fake_stream(chunks))
    deltas = _collect(PLAIN_MODEL)
    assert deltas[-1].usage == llm.Usage(prompt_tokens=12, completion_tokens=3)
    assert [d.usage for d in deltas[:-1]] == [None, None]


def test_tools_passed_only_when_supported(monkeypatch):
    calls = []
    monkeypatch.setattr(litellm, "acompletion", _fake_stream([_chunk(finish="stop")], calls))
    _collect(PLAIN_MODEL, tools=TOOL_SCHEMA)
    _collect(TOOLS_MODEL, tools=TOOL_SCHEMA)
    assert "tools" not in calls[0]
    assert calls[1]["tools"] == TOOL_SCHEMA
    assert all(c["stream"] is True and c["timeout"] == llm.REQUEST_TIMEOUT_S for c in calls)
    assert calls[1]["model"] == TOOLS_MODEL.id


def test_keys_and_ollama_base_from_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "an-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama:11434")
    calls = []
    monkeypatch.setattr(litellm, "acompletion", _fake_stream([_chunk(finish="stop")], calls))
    _collect(TOOLS_MODEL)
    _collect(PLAIN_MODEL)
    _collect(ModelEntry(id="ollama/llama3", label="Local"))
    assert calls[0]["api_key"] == "or-key"
    assert calls[1]["api_key"] == "an-key"
    assert calls[2]["api_base"] == "http://ollama:11434" and "api_key" not in calls[2]


def test_rate_limit_is_retryable(monkeypatch):
    err = litellm.RateLimitError(message="slow down", llm_provider="openrouter", model=TOOLS_MODEL.id)
    monkeypatch.setattr(litellm, "acompletion", _raising(err))
    with pytest.raises(llm.LLMError) as info:
        _collect(TOOLS_MODEL)
    assert info.value.retryable is True


def test_auth_error_is_not_retryable(monkeypatch):
    err = litellm.AuthenticationError(message="bad key", llm_provider="anthropic", model=PLAIN_MODEL.id)
    monkeypatch.setattr(litellm, "acompletion", _raising(err))
    with pytest.raises(llm.LLMError) as info:
        _collect(PLAIN_MODEL)
    assert info.value.retryable is False
    assert "bad key" in info.value.message


def test_error_mid_stream_is_mapped(monkeypatch):
    async def fake(**kwargs):
        async def gen():
            yield _chunk("partial")
            raise litellm.Timeout(message="too slow", model=PLAIN_MODEL.id, llm_provider="anthropic")

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake)

    async def run():
        seen = []
        with pytest.raises(llm.LLMError) as info:
            async for d in llm.stream_chat(PLAIN_MODEL, [{"role": "user", "content": "hi"}]):
                seen.append(d.text)
        return seen, info.value

    seen, error = asyncio.run(run())
    assert seen == ["partial"]
    assert error.retryable is True


def test_preamble_constant():
    assert llm.PAM_PREAMBLE.startswith("You are continuing work with a user")
    assert "⚠ conflicting facts" in llm.PAM_PREAMBLE


# --- ping ---------------------------------------------------------------------------------------


def test_ping_ok(monkeypatch):
    calls = []

    async def fake(**kwargs):
        calls.append(kwargs)
        return {"choices": [{"message": {"content": "p"}}]}

    monkeypatch.setattr(litellm, "acompletion", fake)
    result = asyncio.run(llm.ping(PLAIN_MODEL))
    assert result.ok is True and result.error is None
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0
    assert calls[0]["max_tokens"] == llm.PING_MAX_TOKENS
    assert "stream" not in calls[0]


def test_ping_failure(monkeypatch):
    err = litellm.NotFoundError(message="model gone", llm_provider="openrouter", model=TOOLS_MODEL.id)
    monkeypatch.setattr(litellm, "acompletion", _raising(err))
    ok, latency_ms, error = asyncio.run(llm.ping(TOOLS_MODEL))
    assert ok is False and latency_ms >= 0
    assert "model gone" in error


# --- pam models ---------------------------------------------------------------------------------


def test_models_list_json(tmp_path):
    vault = _vault(tmp_path, [TOOLS_MODEL, PLAIN_MODEL])
    res = runner.invoke(app, ["--vault", str(vault.root), "--json", "models", "list"])
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout) == [
        {"id": TOOLS_MODEL.id, "label": "Tooly", "supports_tools": True},
        {"id": PLAIN_MODEL.id, "label": "Plain", "supports_tools": False},
    ]


def test_models_list_text_and_fresh_vault(tmp_path):
    vault = _vault(tmp_path, [TOOLS_MODEL])
    res = runner.invoke(app, ["--vault", str(vault.root), "models", "list"])
    assert res.exit_code == 0 and TOOLS_MODEL.id in res.stdout and "Tooly" in res.stdout

    fresh = tmp_path / "fresh"
    init_vault(fresh)
    res = runner.invoke(app, ["--vault", str(fresh), "models", "list"])
    assert res.exit_code == 0
    res = runner.invoke(app, ["--vault", str(fresh), "--json", "models", "list"])
    assert res.exit_code == 0 and json.loads(res.stdout) == []


def _patch_ping(monkeypatch, outcomes):
    async def fake(model):
        ok = outcomes[model.id]
        return llm.PingResult(ok, 42, None if ok else "boom")

    monkeypatch.setattr(llm, "ping", fake)


@pytest.mark.parametrize(
    ("outcomes", "code"),
    [((True, True), 0), ((True, False), 0), ((False, False), 1)],
)
def test_models_check_exit_codes(tmp_path, monkeypatch, outcomes, code):
    vault = _vault(tmp_path, [TOOLS_MODEL, PLAIN_MODEL])
    _patch_ping(monkeypatch, dict(zip([TOOLS_MODEL.id, PLAIN_MODEL.id], outcomes)))
    res = runner.invoke(app, ["--vault", str(vault.root), "models", "check"])
    assert res.exit_code == code, res.output
    assert res.stdout.count("OK") == sum(outcomes)
    assert res.stdout.count("FAIL") == len(outcomes) - sum(outcomes)


def test_models_check_json(tmp_path, monkeypatch):
    vault = _vault(tmp_path, [TOOLS_MODEL, PLAIN_MODEL])
    _patch_ping(monkeypatch, {TOOLS_MODEL.id: True, PLAIN_MODEL.id: False})
    res = runner.invoke(app, ["--vault", str(vault.root), "--json", "models", "check"])
    assert res.exit_code == 0
    assert json.loads(res.stdout) == [
        {"id": TOOLS_MODEL.id, "ok": True, "latency_ms": 42, "error": None},
        {"id": PLAIN_MODEL.id, "ok": False, "latency_ms": 42, "error": "boom"},
    ]


def test_models_check_without_models_fails(tmp_path):
    fresh = tmp_path / "fresh"
    init_vault(fresh)
    res = runner.invoke(app, ["--vault", str(fresh), "models", "check"])
    assert res.exit_code == 1
