"""LLM provider layer for the chat orchestrator: model lookup, streaming, and health pings (SPEC §8 M12).

Behavior:
    Wraps `litellm.acompletion` so `anthropic/…`, `openrouter/…` and `ollama/…` models share one
    streaming API. Keys come from the environment (`ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY`;
    `OLLAMA_BASE_URL` as `api_base`). Provider failures surface as `LLMError` with a `retryable`
    flag. LiteLLM's model cost map is read from the installed package instead of fetched at import.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, NamedTuple

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import httpx  # noqa: E402
import litellm  # noqa: E402
import openai  # noqa: E402

from pam.contracts.config import ModelEntry, PamConfig  # noqa: E402
from pam.core.errors import PamError  # noqa: E402

litellm.suppress_debug_info = True

PAM_PREAMBLE = (
    "You are continuing work with a user whose long-term memory is provided below. Treat it as "
    "reliable background, cite it naturally, and ask the user about any ⚠ conflicting facts."
)

REQUEST_TIMEOUT_S = 120.0
PING_TIMEOUT_S = 30.0
PING_MAX_TOKENS = 1
PING_PROMPT = "ping"

_API_KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY"}
_OLLAMA_PREFIXES = ("ollama", "ollama_chat")
_OLLAMA_BASE_ENV = "OLLAMA_BASE_URL"

_HTTP_TOO_MANY_REQUESTS = 429
_HTTP_SERVER_ERROR = 500
_RETRYABLE_ERRORS = (
    litellm.RateLimitError,
    litellm.Timeout,
    litellm.APIConnectionError,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
    asyncio.TimeoutError,
    httpx.TransportError,
)
_FATAL_ERRORS = (
    litellm.AuthenticationError,
    litellm.PermissionDeniedError,
    litellm.NotFoundError,
    litellm.BadRequestError,
)


class UnknownModel(PamError):
    """A model id is not listed in `pam.toml` `[[models]]` (the API maps it to 400)."""

    exit_code = 2


class LLMError(PamError):
    """A provider call failed.

    Behavior:
        `retryable` is true for rate limits, timeouts, connection errors and 5xx responses, and
        false for auth, permission, not-found and bad-request errors.
    Parameters:
        message: Human-readable error message.
        retryable: Whether the same request may succeed later.
    """

    def __init__(self, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ToolCall:
    """One complete tool call assembled from streamed fragments."""

    id: str
    name: str
    arguments: dict[str, Any]

    def as_openai(self) -> dict[str, Any]:
        """Render the call as an OpenAI `tool_calls` entry for an assistant message.

        Returns:
            `{"id", "type": "function", "function": {"name", "arguments": <json str>}}`.
        """
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": json.dumps(self.arguments)},
        }


@dataclass(frozen=True)
class Usage:
    """Token counts reported by the provider; either may be missing."""

    prompt_tokens: int | None
    completion_tokens: int | None


@dataclass(frozen=True)
class LLMDelta:
    """One step of a streamed completion.

    Behavior:
        `text` is a token fragment. `tool_calls` holds every complete call of the response and is
        set once, on the delta that carries `finish_reason` (or on a final delta if the stream
        ends without one). `usage` is set when the provider reports it, usually last.
    """

    text: str | None = None
    tool_calls: list[ToolCall] | None = None
    finish_reason: str | None = None
    usage: Usage | None = None


class PingResult(NamedTuple):
    """Outcome of `ping`: success flag, round-trip time, and the error message on failure."""

    ok: bool
    latency_ms: int
    error: str | None


def resolve_model(cfg: PamConfig, model_id: str) -> ModelEntry:
    """Look up a model by its LiteLLM id in the vault configuration.

    Exceptions:
        UnknownModel: `model_id` is not in `cfg.models`.
    Returns:
        The matching `ModelEntry`.
    Parameters:
        cfg: The vault's `PamConfig`.
        model_id: A `PamConfig.models[].id`, e.g. `"openrouter/<org>/<model>:free"`.
    """
    for entry in cfg.models:
        if entry.id == model_id:
            return entry
    known = ", ".join(m.id for m in cfg.models) or "none; add [[models]] to pam.toml"
    raise UnknownModel(f"unknown model {model_id!r} (configured: {known})")


async def stream_chat(
    model: ModelEntry, messages: list[dict], tools: list[dict] | None = None
) -> AsyncIterator[LLMDelta]:
    """Stream one completion as `LLMDelta`s.

    Behavior:
        Calls `litellm.acompletion(stream=True)` with usage reporting on. `tools` are passed only
        when `model.supports_tools`. Tool-call fragments are merged by their `index` and their
        JSON arguments parsed once the response finishes.
    Exceptions:
        LLMError: The provider call fails, or a tool call carries arguments that are not a JSON object.
    Returns:
        An async iterator of deltas.
    Parameters:
        model: The model to call.
        messages: OpenAI-style chat messages, system prompt included.
        tools: OpenAI tool schemas, ignored for models without tool support.
    """
    kwargs = _provider_kwargs(model)
    if tools and model.supports_tools:
        kwargs["tools"] = tools
    fragments: dict[int, dict[str, str]] = {}
    tools_sent = False
    try:
        stream = await litellm.acompletion(
            model=model.id,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            timeout=REQUEST_TIMEOUT_S,
            drop_params=True,
            **kwargs,
        )
        async for chunk in stream:
            text, finish_reason = None, None
            for choice in _get(chunk, "choices") or []:
                delta = _get(choice, "delta")
                text = _get(delta, "content") or text
                for frag in _get(delta, "tool_calls") or []:
                    _merge_fragment(fragments, frag)
                finish_reason = _get(choice, "finish_reason") or finish_reason
            usage = _usage(_get(chunk, "usage"))
            calls = None
            if finish_reason and not tools_sent:
                calls, tools_sent = _assemble(fragments), True
            if text or calls or finish_reason or usage:
                yield LLMDelta(text=text, tool_calls=calls, finish_reason=finish_reason, usage=usage)
    except LLMError:
        raise
    except (*_RETRYABLE_ERRORS, *_FATAL_ERRORS, openai.APIError) as e:
        raise _to_llm_error(e) from e
    if fragments and not tools_sent:
        yield LLMDelta(tool_calls=_assemble(fragments))


async def ping(model: ModelEntry) -> PingResult:
    """Send a one-token request to check that a model answers.

    Behavior:
        Any failure, provider or otherwise, is reported in the result rather than raised.
    Returns:
        `(ok, latency_ms, error)`; `error` is `None` on success.
    Parameters:
        model: The model to ping.
    """
    start = time.perf_counter()
    try:
        await litellm.acompletion(
            model=model.id,
            messages=[{"role": "user", "content": PING_PROMPT}],
            max_tokens=PING_MAX_TOKENS,
            timeout=PING_TIMEOUT_S,
            **_provider_kwargs(model),
        )
        error = None
    except Exception as e:  # noqa: BLE001 - a health check reports every failure
        error = _to_llm_error(e).message
    return PingResult(error is None, round((time.perf_counter() - start) * 1000), error)


def _provider_kwargs(model: ModelEntry) -> dict[str, Any]:
    provider = model.id.split("/", 1)[0]
    kwargs: dict[str, Any] = {}
    if key := os.environ.get(_API_KEY_ENV.get(provider, "")):
        kwargs["api_key"] = key
    if provider in _OLLAMA_PREFIXES and (base := os.environ.get(_OLLAMA_BASE_ENV)):
        kwargs["api_base"] = base
    return kwargs


def _to_llm_error(e: BaseException) -> LLMError:
    if isinstance(e, LLMError):
        return e
    message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
    if isinstance(e, _FATAL_ERRORS):
        return LLMError(message, retryable=False)
    if isinstance(e, _RETRYABLE_ERRORS):
        return LLMError(message, retryable=True)
    status = getattr(e, "status_code", None)
    if isinstance(status, int):
        return LLMError(message, retryable=status == _HTTP_TOO_MANY_REQUESTS or status >= _HTTP_SERVER_ERROR)
    return LLMError(message, retryable=False)


def _get(obj: Any, key: str) -> Any:
    """Read a field from a LiteLLM response object or a plain dict."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _merge_fragment(fragments: dict[int, dict[str, str]], frag: Any) -> None:
    index = _get(frag, "index") or 0
    slot = fragments.setdefault(index, {"id": "", "name": "", "arguments": ""})
    if call_id := _get(frag, "id"):
        slot["id"] = call_id
    fn = _get(frag, "function")
    if name := _get(fn, "name"):
        slot["name"] = name
    slot["arguments"] += _get(fn, "arguments") or ""


def _assemble(fragments: dict[int, dict[str, str]]) -> list[ToolCall] | None:
    calls = []
    for index in sorted(fragments):
        slot = fragments[index]
        try:
            arguments = json.loads(slot["arguments"]) if slot["arguments"].strip() else {}
        except json.JSONDecodeError as e:
            raise LLMError(f"tool call {slot['name']!r} has invalid JSON arguments: {e}", retryable=True) from e
        if not isinstance(arguments, dict):
            raise LLMError(f"tool call {slot['name']!r} arguments are not a JSON object", retryable=True)
        calls.append(ToolCall(id=slot["id"] or f"call_{index}", name=slot["name"], arguments=arguments))
    return calls or None


def _usage(raw: Any) -> Usage | None:
    if raw is None:
        return None
    prompt, completion = _get(raw, "prompt_tokens"), _get(raw, "completion_tokens")
    if prompt is None and completion is None:
        return None
    return Usage(prompt_tokens=prompt, completion_tokens=completion)
