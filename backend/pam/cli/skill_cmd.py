"""`pam skill add|list`: CLI wrappers over `pam.memory.writer.add_skill` (SPEC §8 M7, SETUP §6)."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from pam.agents.manifest import load_manifest
from pam.agents.permissions import DocRef, can_read
from pam.cli.fact_cmd import emit_write_result, json_mode
from pam.contracts.skill import Skill
from pam.contracts.writes import AddSkillInput
from pam.core import mdio
from pam.core.errors import PamError, PermissionDenied
from pam.core.vault import Vault
from pam.memory import writer

skill_app = typer.Typer(help="Add and list skills.", no_args_is_help=True)
out = Console()


def _vault() -> Vault:
    return Vault.resolve().require_initialized()


def _read_steps(source: str) -> str:
    try:
        if source == "-":
            return typer.get_text_stream("stdin").read()
        return Path(source).read_text(encoding="utf-8")
    except OSError as e:
        raise PamError(f"cannot read steps from {source}: {e}") from e


@skill_app.command("add")
def add(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Skill name; the same normalized name updates in place."),
    description: str = typer.Option(..., "--description"),
    steps_file: str = typer.Option(..., "--steps-file", help="Markdown file with the steps ('-' for stdin)."),
    keywords: str = typer.Option("", "--keywords", help="Comma-separated trigger keywords."),
    agent: str = typer.Option("default", "--agent", help="Agent that owns the skill."),
) -> None:
    """Create a skill, or update the one with the same name; one commit."""
    data = AddSkillInput(
        name=name, description=description, steps_markdown=_read_steps(steps_file),
        trigger_keywords=[k.strip() for k in keywords.split(",") if k.strip()],
    )
    emit_write_result(ctx, writer.add_skill(_vault(), data, agent))


@skill_app.command("list")
def list_cmd(
    ctx: typer.Context,
    agent: str = typer.Option("default", "--agent", help="List only the skills this agent may read."),
) -> None:
    """List skills."""
    vault = _vault()
    try:
        manifest = load_manifest(agent, vault)
    except PamError as e:
        raise PermissionDenied(f"agent {agent!r} is not usable: {e}") from e
    rows: list[Skill] = []
    for path in sorted((vault.root / "skills").glob("*/*.md")):
        try:
            skill, _ = mdio.read_model(path, Skill)
        except (PamError, ValidationError, ValueError) as e:
            typer.echo(f"Warning: {path.name}: {e}", err=True)
            continue
        if can_read(manifest, DocRef(doc_id=str(skill.id), doc_type="skill", scope=skill.scope), vault):
            rows.append(skill)
    if json_mode(ctx):
        typer.echo(json.dumps([s.model_dump(mode="json") for s in rows], indent=2))
        return
    table = Table("id", "scope", "name", "keywords", "description")
    table.columns[0].no_wrap = True
    for s in rows:
        table.add_row(str(s.id), s.scope, s.name, ", ".join(s.trigger_keywords), s.description)
    out.print(table)


def register(root: typer.Typer) -> None:
    root.add_typer(skill_app, name="skill")
