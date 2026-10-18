"""MCP client for the chat orchestrator: PAM's own tools, in-process or over streamable HTTP (SPEC §8 M12).

Behavior:
    `open_session` connects to the M11 server bound to one agent and yields the SDK `ClientSession`.
    Without a URL the server is built in-process with `build_server` (CLI, tests), so `pam chat`
    needs no running server; with a URL (the API's own `/mcp`) it connects over streamable HTTP
    with `?agent=<agent>`. The helpers below adapt a session to what the orchestrator needs.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from mcp import Client
from mcp.client.session import ClientSession
from mcp.shared.exceptions import MCPError

from pam.contracts.retrieval import ContextBundle
from pam.core.errors import PamError
from pam.core.vault import Vault
from pam.mcp_server.server import build_server


class McpToolError(PamError):
    """A PAM MCP tool could not be reached or returned an error.

    Parameters:
        message: Human-readable error message.
        retryable: Whether the same call may succeed later (a connection failure, not a tool error).
    """

    def __init__(self, message: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class ToolOutcome:
    """Result of one tool call: its text blocks joined, its structured content, and the error flag."""

    text: str
    structured: dict[str, Any] | None
    is_error: bool


@asynccontextmanager
async def open_session(
    vault: Vault | str | os.PathLike | None, agent: str, url: str | None = None
) -> AsyncIterator[ClientSession]:
    """Open an MCP client session bound to one agent.

    Behavior:
        Without `url`, builds the agent's server in-process and connects through the SDK's
        in-process transport. With `url`, connects over streamable HTTP to `<url>?agent=<agent>`.
        Any failure while connecting is reported as a retryable `McpToolError`. An error raised
        inside the caller's block propagates unwrapped, not as the client task group's
        `ExceptionGroup`.
    Exceptions:
        PamError: The agent does not exist (in-process only).
        McpToolError: The session could not be opened.
    Returns:
        An async context manager yielding an initialized `ClientSession`.
    Parameters:
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        agent: Agent every tool call acts for.
        url: The `/mcp` endpoint, or `None` for an in-process server.
    """
    target: Any = build_server(vault, agent) if url is None else f"{url}?{urlencode({'agent': agent})}"
    try:
        async with AsyncExitStack() as stack:
            try:
                client = await stack.enter_async_context(Client(target))
            except Exception as e:  # noqa: BLE001 - any transport failure means the tools are unreachable
                raise McpToolError(f"cannot open MCP session: {type(e).__name__}: {e}", retryable=True) from e
            yield client.session
    except BaseExceptionGroup as group:
        # The client's task group wraps errors raised in the caller's block; re-raise a lone one as is.
        leaves = _leaves(group)
        if len(leaves) == 1 and isinstance(leaves[0], Exception):
            raise leaves[0] from None
        raise


def _leaves(group: BaseExceptionGroup) -> list[BaseException]:
    found: list[BaseException] = []
    for exc in group.exceptions:
        found.extend(_leaves(exc) if isinstance(exc, BaseExceptionGroup) else [exc])
    return found


async def openai_tools(session: ClientSession) -> list[dict[str, Any]]:
    """List the session's tools as OpenAI function-tool schemas.

    Returns:
        `[{"type": "function", "function": {"name", "description", "parameters"}}]`, one per tool
        the bound agent may call.
    Parameters:
        session: An open MCP session.
    """
    listed = await session.list_tools()
    return [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description or "", "parameters": t.input_schema},
        }
        for t in listed.tools
    ]


async def call_tool(session: ClientSession, name: str, arguments: dict[str, Any]) -> ToolOutcome:
    """Call one tool.

    Behavior:
        A protocol-level failure (for example a tool the agent may not call) is returned as an
        error outcome, so a model's bad call never ends the turn.
    Returns:
        The tool's outcome.
    Parameters:
        session: An open MCP session.
        name: Tool name.
        arguments: Tool arguments.
    """
    try:
        result = await session.call_tool(name, arguments)
    except MCPError as e:
        return ToolOutcome(text=str(e), structured=None, is_error=True)
    text = "\n".join(item.text for item in result.content if getattr(item, "type", None) == "text")
    structured = result.structured_content if isinstance(result.structured_content, dict) else None
    return ToolOutcome(text=text, structured=structured, is_error=bool(result.is_error))


async def get_context(session: ClientSession, query: str, session_id: str | None) -> ContextBundle:
    """Call `get_context` and parse its structured result.

    Exceptions:
        McpToolError: The tool returned an error (e.g. not advertised for the agent).
    Returns:
        The context bundle.
    Parameters:
        session: An open MCP session.
        query: The user's message.
        session_id: Chat session whose working memory the bundle includes.
    """
    outcome = await call_tool(session, "get_context", {"query": query, "session_id": session_id})
    if outcome.is_error or outcome.structured is None:
        raise McpToolError(f"get_context failed: {outcome.text or 'no structured result'}")
    return ContextBundle.model_validate(outcome.structured)
