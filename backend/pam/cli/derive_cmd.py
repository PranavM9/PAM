"""`pam derive`, `pam patterns list|test`, and `pam persona show`: CLI over `pam.extract` (SPEC §8 M3, SETUP §3)."""

from __future__ import annotations

import json
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


def derive_command(
    ctx: typer.Context,
    episode: str | None = typer.Option(None, "--episode", metavar="ID", help="Only this episode (id or unique prefix)."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would change without writing."),
) -> None:
    """Extract facts and rules, render the default persona, and commit the result once."""
    report = derive(episode=episode, dry_run=dry_run)
    if _json_mode(ctx):
        typer.echo(report.model_dump_json(indent=2))
        return
    commit = report.commit_sha[:7] if report.commit_sha else "none"
    suffix = " (dry run)" if dry_run else ""
    typer.echo(
        f"derive: +{report.facts_created} ~{report.facts_updated} !{report.conflicts_flagged}; "
        f"{report.rules_derived} rules; commit {commit}; {report.duration_ms} ms{suffix}"
    )


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
