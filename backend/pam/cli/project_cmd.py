"""`pam project create|note|add-episodes`: CLI wrappers over `pam.memory.writer.update_project` (SPEC §8 M7)."""

from __future__ import annotations

from uuid import UUID

import typer

from pam.cli.fact_cmd import emit_write_result, parse_uuid
from pam.contracts.writes import UpdateProjectInput
from pam.core.errors import PamError
from pam.core.vault import Vault
from pam.memory import writer

project_app = typer.Typer(help="Create projects and add notes or episodes.", no_args_is_help=True)


def _vault() -> Vault:
    return Vault.resolve().require_initialized()


def _resolve_project(vault: Vault, ref: str) -> UUID:
    if not ref.strip():
        raise PamError("project id must not be empty")
    ids = sorted({p.stem for p in vault.root.glob("memory/*/projects/*.md") if p.stem.startswith(ref.lower())})
    if not ids:
        raise PamError(f"project {ref} not found")
    if len(ids) > 1:
        raise PamError(f"id prefix {ref} is ambiguous ({len(ids)} projects)")
    return UUID(ids[0])


@project_app.command("create")
def create(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Project name."),
    note: str | None = typer.Option(None, "--note", help="First note for ## Notes."),
    episodes: list[str] = typer.Option([], "--episode", metavar="ID", help="Episode to add (repeatable)."),
    agent: str = typer.Option("default", "--agent", help="Agent that owns the project."),
    session: str | None = typer.Option(None, "--session", help="Working-memory session id."),
) -> None:
    """Create a project (origin agent); one commit."""
    data = UpdateProjectInput(
        name=name, note=note, add_episode_ids=[parse_uuid(e, "episode id") for e in episodes]
    )
    emit_write_result(ctx, writer.update_project(_vault(), data, agent, session))


@project_app.command("note")
def note(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., metavar="ID", help="Project id or a unique prefix."),
    text: str = typer.Argument(..., metavar="TEXT", help="Note to append to ## Notes."),
    agent: str = typer.Option("default", "--agent", help="Agent writing the note."),
    session: str | None = typer.Option(None, "--session", help="Working-memory session id."),
) -> None:
    """Append one note bullet to a project; one commit."""
    vault = _vault()
    data = UpdateProjectInput(project_id=_resolve_project(vault, project_id), note=text)
    emit_write_result(ctx, writer.update_project(vault, data, agent, session))


@project_app.command("add-episodes")
def add_episodes(
    ctx: typer.Context,
    project_id: str = typer.Argument(..., metavar="ID", help="Project id or a unique prefix."),
    episodes: list[str] = typer.Argument(..., metavar="EP_ID...", help="Episode ids to add."),
    agent: str = typer.Option("default", "--agent", help="Agent performing the write."),
    session: str | None = typer.Option(None, "--session", help="Working-memory session id."),
) -> None:
    """Add episodes to a project; one commit."""
    vault = _vault()
    data = UpdateProjectInput(
        project_id=_resolve_project(vault, project_id),
        add_episode_ids=[parse_uuid(e, "episode id") for e in episodes],
    )
    emit_write_result(ctx, writer.update_project(vault, data, agent, session))


def register(root: typer.Typer) -> None:
    root.add_typer(project_app, name="project")
