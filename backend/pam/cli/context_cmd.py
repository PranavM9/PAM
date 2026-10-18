"""`pam context`: the token-budgeted context bundle from the command line (SPEC §8 M6, SETUP §6)."""

from __future__ import annotations

import typer

from pam.contracts.retrieval import ContextRequest
from pam.core.vault import Vault
from pam.retrieve.context import build_context


def context_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., metavar="QUERY"),
    agent: str = typer.Option("default", "--agent", help="Agent whose read scope and persona apply."),
    budget: int | None = typer.Option(None, "--budget", min=256, max=32000,
                                      help="Token budget (default: the agent's token_budget)."),
    session: str | None = typer.Option(None, "--session", help="Working-memory session id."),
    no_persona: bool = typer.Option(False, "--no-persona", help="Leave the persona out."),
) -> None:
    """Print the context bundle for a query: rendered Markdown plus the token line.

    Behavior:
        Prints the `ContextBundle` as JSON with the global `--json`; otherwise `rendered` followed by
        `<used>/<budget> tokens · <saved> saved (baseline <n>)`.
    Exceptions:
        PamError: The agent does not exist, or the index needs `pam index --rebuild` (exit 1).
    Parameters:
        ctx: Typer context with the global options.
        query: User query.
        agent: Agent whose scope applies.
        budget: Token budget.
        session: Working-memory session id.
        no_persona: Leave the persona out.
    """
    req = ContextRequest(query=query, agent=agent, token_budget=budget, session_id=session,
                         include_persona=not no_persona)
    result = build_context(Vault.resolve().require_initialized(), req)
    if (ctx.find_root().obj or {}).get("json"):
        typer.echo(result.model_dump_json(indent=2))
        return
    typer.echo(result.rendered)
    typer.echo(f"{result.tokens_used}/{result.token_budget} tokens · {result.tokens_saved} saved "
               f"(baseline {result.baseline_tokens})")


def register(app: typer.Typer) -> None:
    app.command("context")(context_command)
