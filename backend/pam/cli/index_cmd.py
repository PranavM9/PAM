"""`pam index [PATHS...] [--rebuild]` and `pam index stats`: CLI over `pam.index` (SPEC §8 M4, SETUP §6)."""

from __future__ import annotations

import json
import warnings
from collections.abc import Iterator
from contextlib import contextmanager

import typer

from pam.core.errors import PamError
from pam.core.vault import Vault
from pam.index.indexer import index_vault, stats


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


@contextmanager
def _warnings_to_stderr() -> Iterator[None]:
    """Print each distinct warning raised inside the block once on stderr as `Warning: <message>`."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            for message in dict.fromkeys(str(w.message) for w in caught):
                typer.echo(f"Warning: {message}", err=True)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _print_stats(ctx: typer.Context, vault: Vault) -> None:
    data = stats(vault)
    if _json_mode(ctx):
        typer.echo(json.dumps(data, indent=2))
        return
    typer.echo(f"{'type':<10}{'documents':>10}{'chunks':>10}")
    for doc_type, counts in data["types"].items():
        typer.echo(f"{doc_type:<10}{counts['documents']:>10}{counts['chunks']:>10}")
    typer.echo(f"{'total':<10}{data['documents']:>10}{data['chunks']:>10}")
    model = data["embedding_model"] or "(not indexed yet)"
    dim = f" ({data['embedding_dim']} dims)" if data["embedding_dim"] else ""
    typer.echo(f"model {model}{dim} · db {data['db_bytes'] / 1_048_576:.1f} MB · "
               f"last commit {(data['last_indexed_commit'] or '-')[:7]}")


def index_command(
    ctx: typer.Context,
    paths: list[str] | None = typer.Argument(
        None, metavar="[PATHS]...", help="Only these files (absolute or vault-relative). `stats` shows index counts.",
    ),
    rebuild: bool = typer.Option(
        False, "--rebuild",
        help="Delete the index and rebuild it from the vault. Needed after changing the embedding or chunking "
             "settings in pam.toml.",
    ),
) -> None:
    """Index the vault for search (incremental), or show counts with `pam index stats`."""
    vault = Vault.resolve().require_initialized()
    if paths == ["stats"]:
        _print_stats(ctx, vault)
        return
    if paths and rebuild:
        raise PamError("--rebuild always indexes the whole vault; leave out the paths")
    with _warnings_to_stderr():
        report = index_vault(vault, rebuild=rebuild, paths=paths or None)
    if _json_mode(ctx):
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(
        f"Indexed {_count(report.documents_indexed, 'document')} ({report.documents_unchanged} unchanged, "
        f"{report.documents_removed_from_index} removed); {_count(report.chunks_written, 'chunk')} "
        f"with {report.embedding_model} in {report.duration_ms / 1000:.1f}s"
    )


def register(app: typer.Typer) -> None:
    app.command("index")(index_command)
