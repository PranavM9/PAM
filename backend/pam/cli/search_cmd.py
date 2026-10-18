"""`pam search`: hybrid memory search from the command line (SPEC §8 M6, SETUP §6)."""

from __future__ import annotations

from datetime import UTC, datetime

import typer

from pam.contracts.retrieval import SearchQuery
from pam.core.vault import Vault
from pam.retrieve.search import search

DOC_TYPES = ("episode", "fact", "project", "skill")
SNIPPET_PREVIEW = 160


def _doc_types(value: str | None) -> list[str] | None:
    if not value:
        return None
    types = [t.strip() for t in value.split(",") if t.strip()]
    unknown = [t for t in types if t not in DOC_TYPES]
    if unknown:
        raise typer.BadParameter(f"unknown type {', '.join(unknown)}; use {', '.join(DOC_TYPES)}")
    return types


def _since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise typer.BadParameter("use a date like 2026-09-01 or an ISO-8601 time") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def search_command(
    ctx: typer.Context,
    query: str = typer.Argument(..., metavar="QUERY"),
    agent: str = typer.Option("default", "--agent", help="Agent whose read scope applies."),
    k: int = typer.Option(8, "--k", "-k", min=1, max=50, help="Maximum hits."),
    doc_type: str | None = typer.Option(None, "--type", help="Comma-separated: episode,fact,project,skill."),
    since: str | None = typer.Option(None, "--since", help="Only documents created on or after this date."),
) -> None:
    """Hybrid search over the vault; shows score, vector rank, and keyword rank.

    Behavior:
        Prints the `SearchResponse` as JSON with the global `--json`; otherwise one block per hit
        (score, ranks, type, title, path, and a one-line snippet) and a summary line.
    Exceptions:
        typer.BadParameter: `--type` or `--since` is invalid (exit 2).
        PamError: The agent does not exist, or the index needs `pam index --rebuild` (exit 1).
    Parameters:
        ctx: Typer context with the global options.
        query: Search text.
        agent: Agent whose read scope applies.
        k: Maximum hits.
        doc_type: Comma-separated document types.
        since: Earliest creation date.
    """
    q = SearchQuery(query=query, agent=agent, k=k, doc_types=_doc_types(doc_type), since=_since(since))
    result = search(Vault.resolve().require_initialized(), q)
    if (ctx.find_root().obj or {}).get("json"):
        typer.echo(result.model_dump_json(indent=2))
        return
    for hit in result.hits:
        ranks = f"vector {hit.vector_rank or '-'}, keyword {hit.keyword_rank or '-'}"
        typer.echo(f"{hit.score:.4f}  ({ranks})  {hit.doc_type}  {hit.title or ''}")
        typer.echo(f"    {hit.path}")
        typer.echo(f"    {' '.join(hit.snippet.split())[:SNIPPET_PREVIEW]}")
    typer.echo(f"{len(result.hits)} hits · {result.took_ms} ms")


def register(app: typer.Typer) -> None:
    app.command("search")(search_command)
