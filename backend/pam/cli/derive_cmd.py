"""`pam derive`, `pam patterns list|test`, and `pam persona show`: CLI over `pam.extract` (SPEC §8 M3, SETUP §3)."""

from __future__ import annotations

import json
import shlex
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict

import typer
from rich.console import Console
from rich.table import Table

from pam.agents.manifest import load_persona
from pam.core.vault import Vault
from pam.extract import patterns as pat
from pam.extract.derive import derive
from pam.extract.facts import scan_text
from pam.extract.rules import extract_rules

patterns_app = typer.Typer(help="Inspect the fact extraction patterns.", no_args_is_help=True)
persona_app = typer.Typer(help="Show agent personas.", no_args_is_help=True)
out = Console()


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


@contextmanager
def _warnings_to_stderr() -> Iterator[None]:
    """Print warnings raised inside the block as plain `Warning:` lines on stderr.

    Behavior:
        Each distinct message is printed once when the block exits, also when it raises, without
        the source path and code line that Python's default handler adds. Stdout stays clean for
        `--json`.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            for message in dict.fromkeys(str(w.message) for w in caught):
                typer.echo(f"Warning: {message}", err=True)


def _count(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def derive_command(
    ctx: typer.Context,
    episode: str | None = typer.Option(None, "--episode", metavar="ID", help="Only this episode (id or unique prefix)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would change without writing."),
) -> None:
    """Extract facts and rules, render the default persona, and commit the result once."""
    with _warnings_to_stderr():
        report = derive(episode=episode, dry_run=dry_run)
    if _json_mode(ctx):
        typer.echo(report.model_dump_json(indent=2))
        return
    facts_part = (
        f"{_count(report.facts_created, 'new fact')} ({report.facts_updated} updated, "
        f"{_count(report.conflicts_flagged, 'conflict')})"
    )
    rules_part = _count(report.rules_derived, "derived rule")
    if dry_run:
        typer.echo(f"Would derive {facts_part}; the default persona would have {rules_part} (dry run, nothing written)")
    elif report.commit_sha is None:
        typer.echo(f"No changes; the default persona has {rules_part}")
    else:
        root = shlex.quote(str(Vault.resolve().root))
        typer.echo(f"Derived {facts_part}; the default persona has {rules_part}")
        typer.echo(f"commit {report.commit_sha[:7]} · {report.duration_ms / 1000:.1f}s")
        typer.echo(f"See the persona:   pam --vault {root} persona show")
        typer.echo(f"See what changed:  git -C {root} show --stat {report.commit_sha[:7]}")


@patterns_app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """Show every extraction pattern."""
    if _json_mode(ctx):
        typer.echo(json.dumps(pat.PATTERNS, indent=2))
        return
    table = Table("id", "attribute", "category", "cardinality", "conf", "ner", "regex")
    for p in pat.PATTERNS:
        table.add_row(
            p["id"], p["attribute"], p["category"], p["cardinality"], f"{p['confidence']:.2f}",
            p.get("ner_filter", ""), p["regex"],
        )
    out.print(table)


@patterns_app.command("test")
def test_cmd(
    ctx: typer.Context,
    sentence: str = typer.Argument(..., metavar="SENTENCE", help="Text to match as a user message."),
) -> None:
    """Show which patterns fire on a sentence, and why other matches were skipped."""
    with _warnings_to_stderr():
        candidates = scan_text(sentence, "user")
        rules = extract_rules(sentence, "user")
    if _json_mode(ctx):
        typer.echo(json.dumps({"facts": [asdict(c) for c in candidates], "rules": rules}, indent=2))
        return
    for c in candidates:
        line = f'{c.attribute} = "{c.value}"  (pattern: {c.pattern_id}, conf {c.confidence:.2f})'
        typer.echo(line if c.skipped is None else f"skipped ({c.skipped}): {line}")
    for rule in rules:
        typer.echo(f"rule: {rule}")
    if not candidates and not rules:
        typer.echo("no pattern matched")


@persona_app.command("show")
def show_cmd(
    ctx: typer.Context,
    agent: str = typer.Option("default", "--agent", help="Agent whose persona to print."),
) -> None:
    """Print an agent's persona: identity, rules, and style (Derived, then Custom)."""
    persona = load_persona(agent, Vault.resolve().require_initialized())
    if _json_mode(ctx):
        typer.echo(persona.model_dump_json(indent=2))
        return
    typer.echo("# Identity\n" + (persona.identity or "(empty)"))
    typer.echo("\n# Rules\n" + ("\n".join(f"- {r.text}" for r in persona.rules) or "(none)"))
    typer.echo("\n# Style\n" + (persona.style or "(empty)"))


def register(root: typer.Typer) -> None:
    root.command("derive")(derive_command)
    root.add_typer(patterns_app, name="patterns")
    root.add_typer(persona_app, name="persona")
