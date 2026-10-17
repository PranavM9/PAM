"""Commands for reading provider exports without writing to the vault."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pam.contracts.common import Source
from pam.contracts.raw import RawConversation
from pam.core.vault import Vault
from pam.importers.detect import extract
from pam.normalize.writer import write_episodes

import_app = typer.Typer(help="Import conversations from provider exports.", no_args_is_help=True)
err = Console(stderr=True)


@import_app.command("extract")
def extract_cmd(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Provider export ZIP or JSON file."),
    source: str = typer.Option("auto", "--source", help="auto, claude, chatgpt, or gemini."),
    output: Path | None = typer.Option(None, "--out", help="Write JSONL to this file (default: stdout)."),
) -> None:
    """Parse an export and emit validated RawConversation JSONL."""
    conversations, errors, selected = extract(path, source)
    rows: list[str] = []
    for conversation in conversations:
        # Validate at the serialization boundary so every emitted row is contract-valid.
        rows.append(RawConversation.model_validate(conversation.model_dump()).model_dump_json())
    payload = "\n".join(rows) + ("\n" if rows else "")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        typer.echo(payload, nl=False)
    skipped = sum("skipped" in message for message in errors)
    parse_errors = len(errors) - skipped
    if errors:
        for message in errors:
            err.print(f"[yellow]Warning:[/] {message}")
    err.print(f"{selected} · {len(rows)} conversations · {skipped} skipped · {parse_errors} errors", markup=False)


@import_app.command("run")
def run_cmd(
    ctx: typer.Context,
    path: Path = typer.Argument(..., exists=True, readable=True, help="Provider export ZIP or JSON file."),
    source: str = typer.Option("auto", "--source", help="auto, claude, chatgpt, or gemini."),
    agent: str = typer.Option("default", "--agent", help="Agent scope that owns the episodes."),
    update: bool = typer.Option(False, "--update", help="Write new versions of conversations changed since import."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be written without writing."),
) -> None:
    """Archive an export, write its episodes, and make one commit."""
    vault = Vault.resolve().require_initialized()
    conversations, parse_errors, selected = extract(path, source)
    report = write_episodes(vault, conversations, Source(selected), path, agent, update, dry_run)
    report = report.model_copy(update={"errors": [*parse_errors, *report.errors]})
    if (ctx.find_root().obj or {}).get("json"):
        typer.echo(report.model_dump_json(indent=2))
        return
    verb = "Would write" if dry_run else "Wrote"
    typer.echo(
        f"{verb} {report.episodes_written} episodes ({report.episodes_skipped_existing} already present) "
        f"from {report.conversations_found} conversations"
    )
    if report.commit_sha:
        typer.echo(f"commit {report.commit_sha[:7]} · archived {report.archived_path}")
    for message in report.errors:
        err.print(f"[yellow]Warning:[/] {message}")


def register(app: typer.Typer) -> None:
    app.add_typer(import_app, name="import")
