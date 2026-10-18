"""Expose budgeted context assembly through `pam context`."""

import typer

from pam.contracts.retrieval import ContextRequest
from pam.core.vault import Vault
from pam.retrieve.context import build_context


def register(app: typer.Typer) -> None:
    """Register the context command.

    Behavior:
        Adds `pam context` to the root CLI.
    Parameters:
        app: Root Typer application.
    """
    app.command("context")(context_command)


def context_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., metavar="Q"),
    budget: int | None = typer.Option(None, "--budget", min=256, max=32000),
    agent: str = typer.Option("default", "--agent"),
    session: str | None = typer.Option(None, "--session"),
) -> None:
    """Assemble and print query context.

    Behavior:
        Prints contract JSON in global JSON mode; otherwise prints rendered Markdown and token use.
    Parameters:
        ctx: Click command context.
        query: User query.
        budget: Optional context token budget.
        agent: Agent whose read scope applies.
        session: Optional working-memory session id.
    """
    result = build_context(Vault.resolve(), ContextRequest(query=query, agent=agent, token_budget=budget, session_id=session))
    if (ctx.find_root().obj or {}).get("json"):
        typer.echo(result.model_dump_json(indent=2))
    else:
        typer.echo(result.rendered)
        typer.echo(f"{result.tokens_used}/{result.token_budget} tokens · {result.tokens_saved} saved")
