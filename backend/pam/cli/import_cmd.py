"""Commands for reading provider exports without writing to the vault."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from pam.contracts.raw import RawConversation
from pam.importers.detect import extract

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


def register(app: typer.Typer) -> None:
    app.add_typer(import_app, name="import")
