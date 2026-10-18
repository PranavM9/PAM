"""`GET /api/models` and `POST /api/chat`: model list and the SSE chat stream (SPEC §7.14, CHG-0018 (M12))."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from sse_starlette import EventSourceResponse

from pam.api.deps import get_vault
from pam.api.errors import INTERNAL_ERROR, ApiError
from pam.contracts.api import ChatRequest, ErrorEvent
from pam.contracts.config import ModelEntry
from pam.core import config
from pam.core.vault import Vault

router = APIRouter(tags=["chat"])

_END = object()
_QUEUE_SIZE = 64


@router.get("/models", response_model=list[ModelEntry])
def get_models(vault: Vault = Depends(get_vault)) -> list[ModelEntry]:
    """List the models configured in `pam.toml`."""
    return config.load(vault).models


def _frame(event) -> dict:
    return {"event": event.type, "data": event.model_dump_json()}


async def _pump(vault: Vault, req: ChatRequest, mcp_url: str | None, queue: asyncio.Queue) -> None:
    """Run `run_turn` to the end in one task and put its events (or its exception) on `queue`.

    Behavior:
        `run_turn` opens MCP sessions with task-bound cancel scopes, so the whole generator must
        be consumed by a single task; the route and the response only read the queue.
    """
    from pam.chat.orchestrator import run_turn  # noqa: PLC0415 - litellm is slow to import

    try:
        async for event in run_turn(vault, req, mcp_url=mcp_url):
            await queue.put(event)
    except Exception as exc:  # noqa: BLE001 - delivered to the route, which maps it
        await queue.put(exc)
    finally:
        await queue.put(_END)


async def _stream(queue: asyncio.Queue, first, task: asyncio.Task) -> AsyncIterator[dict]:
    terminal = first.type in ("done", "error")
    try:
        yield _frame(first)
        while (item := await queue.get()) is not _END:
            if isinstance(item, Exception):
                item = ErrorEvent(message=f"{type(item).__name__}: {item}", retryable=False)
            terminal = terminal or item.type in ("done", "error")
            yield _frame(item)
        if not terminal:
            yield _frame(ErrorEvent(message="chat ended without a result", retryable=True))
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@router.post("/chat")
async def chat(req: ChatRequest, request: Request, vault: Vault = Depends(get_vault)) -> EventSourceResponse:
    """Stream one chat turn as server-sent events.

    Behavior:
        Each frame is `event: <type>` and `data: <ChatEvent JSON>`. The first event is `context`
        and the last is exactly one `done` or `error`. Failures that `run_turn` raises before its
        first event (unknown model 400, unknown session or agent 404, ended session or busy vault
        409) are returned as normal HTTP errors, because no stream has started yet.
    Exceptions:
        PamError: Raised by `run_turn` before the first event; mapped to 400, 404 or 409.
        ApiError: The turn produced no events (500).
    Returns:
        The event stream.
    Parameters:
        req: The chat request.
        request: The HTTP request (gives the app's MCP URL).
        vault: The served vault.
    """
    queue: asyncio.Queue = asyncio.Queue(_QUEUE_SIZE)
    task = asyncio.create_task(_pump(vault, req, request.app.state.mcp_url, queue))
    first = await queue.get()
    if isinstance(first, Exception) or first is _END:
        await task
        if isinstance(first, Exception):
            raise first
        raise ApiError(500, INTERNAL_ERROR, "chat produced no events")
    return EventSourceResponse(_stream(queue, first, task), sep="\n")
