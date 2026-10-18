"""Chat orchestrator: one chat turn with any model, memory injected or exposed as tools (SPEC §8 M12).

Behavior:
    `run_turn` records the user turn in working memory (M9), gets context through PAM's own MCP
    tools (M11), streams the model's reply as `ChatEvent`s, and records the assistant turn. Request
    problems (unknown model, session or agent; a busy vault) raise before the first event. Once the
    turn has started, the first event is always `context` and the last is exactly one `done` or
    `error` (§7.14).
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from mcp.client.session import ClientSession

from pam.agents.manifest import load_persona
from pam.chat import mcp_client
from pam.chat.llm import MEMORY_GUIDE, PAM_PREAMBLE, LLMError, ToolCall, resolve_model, stream_chat
from pam.chat.mcp_client import McpToolError, open_session
from pam.contracts.api import ChatEvent, ChatRequest, ContextEvent, DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent
from pam.contracts.config import ModelEntry
from pam.contracts.retrieval import ContextBundle
from pam.contracts.working import WorkingMemory
from pam.core import config, tokens
from pam.core.errors import PamError, VaultBusy
from pam.core.vault import Vault
from pam.retrieve.render import persona_section
from pam.working import session

MAX_TOOL_ROUNDS = 5
TOOL_SUMMARY_CHARS = 200
DEFAULT_AGENT = "default"

NO_TOOLS_NOTE = (
    "You have no tools in this chat, so you cannot save or change memory. Never claim to have "
    "remembered, saved or updated anything; if the user asks, say so and suggest a model with tool support."
)


class ToolRoundLimit(PamError):
    """The model still asked for tools after `MAX_TOOL_ROUNDS` rounds of tool calls."""


class ToolsUnsupported(PamError):
    """Tool mode was requested for a model whose `ModelEntry.supports_tools` is false."""


@dataclass
class _Reply:
    """Text, tool calls and usage gathered from the completions of one turn."""

    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


async def run_turn(
    vault: Vault | str | os.PathLike | None, req: ChatRequest, *, mcp_url: str | None = None
) -> AsyncIterator[ChatEvent]:
    """Run one chat turn and stream its events.

    Behavior:
        Starts a session when `req.session_id` is `None`; otherwise continues it, using the
        session's agent when `req.agent` is `"default"`. Records the user turn (a new model adds a
        `ModelSwitch`), then: injection mode emits a `ContextEvent` from MCP `get_context` and
        sends `PAM_PREAMBLE`, a tools note and the rendered bundle as the system prompt. A model with
        `supports_tools` also gets the agent's MCP tools in injection mode (same loop and cap as tool
        mode), so memory writes work by default; a model without them is told it cannot save memory
        (CHG-0024). Tool mode emits a
        persona-only `ContextEvent`, fails for a model without `supports_tools`, and otherwise lets
        the model call the agent's MCP tools for at most `MAX_TOOL_ROUNDS` rounds. History is the
        session's `recent_turns` before the current message. Tokens stream as `TokenEvent`s; a
        non-empty reply is recorded with its model and a `DoneEvent` closes the turn. Any failure
        after the user turn is recorded ends the turn with one `ErrorEvent` (preceded by an empty
        `ContextEvent` if none was sent), and no assistant turn is recorded.
    Exceptions:
        UnknownModel: `req.model` is not in `pam.toml` (nothing is written).
        PamError: The session does not exist or has ended, `req.agent` differs from the session's
            agent (exit 2), or the agent does not exist.
        VaultBusy: The vault write lock was not acquired for the user turn.
    Returns:
        An async iterator of `ContextEvent`, then `TokenEvent`/`ToolCallEvent`, then one `DoneEvent`
        or `ErrorEvent`.
    Parameters:
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        req: The chat request.
        mcp_url: The `/mcp` endpoint to use, or `None` for an in-process MCP server.
    """
    v = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).require_initialized()
    model = resolve_model(config.load(v), req.model)
    memory = await asyncio.to_thread(_open_session, v, req)
    sid, agent = memory.session_id, memory.agent
    memory = await asyncio.to_thread(session.record_turn, v, sid, "user", req.message, model.id)
    turns = [*_history(memory), {"role": "user", "content": req.message}]

    reply, context_sent = _Reply(), False
    try:
        if req.mode == "tool":
            rendered = persona_section(await asyncio.to_thread(load_persona, agent, v))
            context_sent = True
            yield ContextEvent(
                session_id=sid, tokens_used=tokens.count(rendered), baseline_tokens=0, tokens_saved=0,
                doc_ids=[], rendered=rendered,
            )
            if not model.supports_tools:
                raise ToolsUnsupported(f"model {model.id} does not support tools; use --mode injection")
            system = "\n\n".join((PAM_PREAMBLE, MEMORY_GUIDE, rendered))
            async with open_session(v, agent, mcp_url) as mcp:
                async for event in _tool_loop(model, [_system(system), *turns], mcp, reply):
                    yield event
        else:
            async with open_session(v, agent, mcp_url) as mcp:
                bundle = await mcp_client.get_context(mcp, req.message, sid)
                context_sent = True
                yield _context_event(sid, bundle)
                note = MEMORY_GUIDE if model.supports_tools else NO_TOOLS_NOTE
                messages = [_system(f"{PAM_PREAMBLE}\n\n{note}\n\n{bundle.rendered}"), *turns]
                if model.supports_tools:
                    events = _tool_loop(model, messages, mcp, reply)
                else:
                    events = _stream(model, messages, None, reply)
                async for event in events:
                    yield event
        if reply.text:
            await asyncio.to_thread(session.record_turn, v, sid, "assistant", reply.text, model.id)
    except Exception as e:  # noqa: BLE001 - every failure after the turn starts ends the stream with one error
        if not context_sent:
            yield ContextEvent(
                session_id=sid, tokens_used=0, baseline_tokens=0, tokens_saved=0, doc_ids=[], rendered=""
            )
        yield _error_event(e)
        return
    yield DoneEvent(
        session_id=sid, model=model.id,
        prompt_tokens=reply.prompt_tokens, completion_tokens=reply.completion_tokens,
    )


def _open_session(v: Vault, req: ChatRequest) -> WorkingMemory:
    if req.session_id is None:
        return session.start(v, req.agent, req.model)
    memory = session.show(v, req.session_id)
    if req.agent not in (DEFAULT_AGENT, memory.agent):
        raise PamError(
            f"session {memory.session_id} belongs to agent {memory.agent!r}, not {req.agent!r}", exit_code=2
        )
    return memory


def _history(memory: WorkingMemory) -> list[dict[str, str]]:
    """Return the session's recent user and assistant turns, without the current (last) one."""
    return [
        {"role": t.role, "content": t.text}
        for t in memory.recent_turns[:-1]
        if t.role in ("user", "assistant")
    ]


def _system(text: str) -> dict[str, str]:
    return {"role": "system", "content": text}


def _context_event(sid: str, bundle: ContextBundle) -> ContextEvent:
    ids: list[UUID] = [
        *(f.id for f in bundle.facts), *(f.id for f in bundle.conflicts),
        *(p.id for p in bundle.projects), *(e.episode_id for e in bundle.episodes),
    ]
    return ContextEvent(
        session_id=sid, tokens_used=bundle.tokens_used, baseline_tokens=bundle.baseline_tokens,
        tokens_saved=bundle.tokens_saved, doc_ids=list(dict.fromkeys(ids)), rendered=bundle.rendered,
    )


def _error_event(e: Exception) -> ErrorEvent:
    """Map a failure to the terminal event: provider and MCP errors keep their flag, a busy vault is retryable."""
    if isinstance(e, (LLMError, McpToolError)):
        return ErrorEvent(message=e.message, retryable=e.retryable)
    if isinstance(e, PamError):
        return ErrorEvent(message=str(e), retryable=isinstance(e, VaultBusy))
    return ErrorEvent(message=f"{type(e).__name__}: {e}" if str(e) else type(e).__name__, retryable=False)


async def _stream(
    model: ModelEntry, messages: list[dict], tools: list[dict] | None, reply: _Reply
) -> AsyncIterator[TokenEvent]:
    """Stream one completion as `TokenEvent`s, adding its text, calls and usage to `reply`.

    Behavior:
        `reply.calls` is replaced by this completion's tool calls; usage is summed over completions.
    Exceptions:
        LLMError: The provider call fails.
    """
    reply.calls = []
    async for delta in stream_chat(model, messages, tools):
        if delta.text:
            reply.text += delta.text
            yield TokenEvent(text=delta.text)
        if delta.tool_calls:
            reply.calls = list(delta.tool_calls)
        if delta.usage:
            reply.prompt_tokens = _add(reply.prompt_tokens, delta.usage.prompt_tokens)
            reply.completion_tokens = _add(reply.completion_tokens, delta.usage.completion_tokens)


async def _tool_loop(
    model: ModelEntry, messages: list[dict], mcp: ClientSession, reply: _Reply
) -> AsyncIterator[TokenEvent | ToolCallEvent]:
    """Let the model call MCP tools until it answers, for at most `MAX_TOOL_ROUNDS` rounds.

    Behavior:
        Each completion with tool calls appends the assistant message and one `tool` message per
        call (matched by `tool_call_id`) and emits a `ToolCallEvent` per call; a failing tool is an
        error result for the model, not a failed turn. The model reads the results of the last
        allowed round; asking for more tools after that fails the turn.
    Exceptions:
        LLMError: A provider call fails.
        ToolRoundLimit: The model asks for tools after `MAX_TOOL_ROUNDS` rounds.
    """
    tools = await mcp_client.openai_tools(mcp)
    for round_no in range(MAX_TOOL_ROUNDS + 1):
        text_before = len(reply.text)
        async for event in _stream(model, messages, tools, reply):
            yield event
        if not reply.calls:
            return
        if round_no == MAX_TOOL_ROUNDS:
            raise ToolRoundLimit(f"tool round limit ({MAX_TOOL_ROUNDS}) reached")
        messages.append({
            "role": "assistant", "content": reply.text[text_before:] or None,
            "tool_calls": [c.as_openai() for c in reply.calls],
        })
        for call in reply.calls:
            outcome = await mcp_client.call_tool(mcp, call.name, call.arguments)
            summary = _summary(outcome.text, outcome.is_error)
            yield ToolCallEvent(name=call.name, arguments=call.arguments, result_summary=summary)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": outcome.text})


def _summary(text: str, is_error: bool) -> str:
    flat = " ".join(text.split())
    if is_error:
        flat = f"ERROR: {flat}"
    return flat[:TOOL_SUMMARY_CHARS]


def _add(total: int | None, value: Any) -> int | None:
    if value is None:
        return total
    return (total or 0) + int(value)
