"""Expose hybrid memory retrieval through `pam search`."""

import typer

from pam.contracts.retrieval import SearchQuery
from pam.core.vault import Vault
from pam.retrieve.search import search


def register(app: typer.Typer) -> None:
    """Register the search command.

    Behavior:
        Adds `pam search` to the root CLI.
    Parameters:
        app: Root Typer application.
    """
    app.command("search")(search_command)


def search_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., metavar="Q"),
    agent: str = typer.Option("default", "--agent"),
    k: int = typer.Option(8, "--k", min=1, max=50),
) -> None:
    """Search indexed vault documents and print the response.

    Behavior:
        Prints contract JSON in global JSON mode; otherwise prints each hit and elapsed time.
    Parameters:
        ctx: Click command context.
        query: Search text.
        agent: Agent whose read scope applies.
        k: Maximum hits.
    """
    result = search(Vault.resolve(), SearchQuery(query=query, agent=agent, k=k))
    if (ctx.find_root().obj or {}).get("json"):
        typer.echo(result.model_dump_json(indent=2))
    else:
        for hit in result.hits:
            typer.echo(f"{hit.score:.4f}  {hit.path}\n  {hit.snippet}")
        typer.echo(f"{len(result.hits)} hits · {result.took_ms} ms")
