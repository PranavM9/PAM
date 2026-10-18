"""`pam chat`: one streamed chat turn with memory, printing the session id for follow-ups (SPEC §8 M12, SETUP §6)."""

from __future__ import annotations

import asyncio
import json
import logging

import typer

from pam.core.vault import Vault


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


def chat(
    ctx: typer.Context,
    message: str = typer.Argument(..., help="The user message."),
    model: str = typer.Option(..., "--model", help="A model id listed by `pam models list`."),
    session_id: str | None = typer.Option(None, "--session", help="Continue this session."),
    agent: str | None = typer.Option(None, "--agent", help="Agent to chat as (default: the session's, else default)."),
    mode: str = typer.Option("injection", "--mode", help="injection | tool"),
    show_context: bool = typer.Option(False, "--show-context", help="Print the injected context block."),
) -> None:
    """Run one chat turn and stream the reply.

    Behavior:
        Text mode prints `session <id> · context <n> tok (saved <m>)`, the streamed reply, one
        tool line per tool call, and the session id again for follow-ups; `--json` prints
        every `ChatEvent` as one JSON line. An `ErrorEvent` exits 1; an unknown model, an invalid
        request or an agent mismatch exits 2.
    """
    from pam.chat.orchestrator import run_turn  # lazy: litellm is slow to import
    from pam.contracts.api import ChatRequest, ContextEvent, ErrorEvent, TokenEvent, ToolCallEvent

    req = ChatRequest(
        session_id=session_id, agent=agent or "default", model=model, message=message, mode=mode
    )
    vault = Vault.resolve().require_initialized()
    as_json = _json_mode(ctx)
    # LiteLLM logs every call at INFO to stdout, which would mix into the reply and the NDJSON.
    for name in ("LiteLLM", "mcp"):
        logging.getLogger(name).setLevel(logging.WARNING)

    async def consume() -> bool:
        failed, mid_line, sid = False, False, None
        async for event in run_turn(vault, req):
            failed = failed or isinstance(event, ErrorEvent)
            if as_json:
                typer.echo(event.model_dump_json())
            elif isinstance(event, ContextEvent):
                sid = event.session_id
                typer.echo(
                    f"session {sid} · context {event.tokens_used:,} tok (saved {event.tokens_saved:,})"
                )
                if show_context:
                    typer.echo(event.rendered.rstrip("\n"))
            elif isinstance(event, TokenEvent):
                typer.echo(event.text, nl=False)
                mid_line = not event.text.endswith("\n")
            elif isinstance(event, ToolCallEvent):
                if mid_line:
                    typer.echo()
                args = json.dumps(event.arguments, ensure_ascii=False)
                typer.echo(f"[tool] {event.name}({args}) -> {event.result_summary}")
                mid_line = False
            elif isinstance(event, ErrorEvent):
                if mid_line:
                    typer.echo()
                hint = " (retryable)" if event.retryable else ""
                typer.echo(f"error: {event.message}{hint}", err=True)
                mid_line = False
            elif mid_line:  # DoneEvent ends the streamed line
                typer.echo()
        if sid and not as_json:
            typer.echo(f"session {sid} (continue with --session {sid})")
        return failed

    if asyncio.run(consume()):
        raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Add `pam chat` to the root CLI.

    Parameters:
        app: The root Typer app.
    """
    app.command("chat")(chat)
