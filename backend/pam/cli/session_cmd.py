"""`pam session start|record|show|update|list|end`: working-memory sessions (SPEC §8 M9)."""

from __future__ import annotations

import json
from enum import Enum

import typer
from rich.console import Console
from rich.table import Table

from pam.cli.fact_cmd import emit_write_result, json_mode
from pam.contracts.working import WorkingMemory
from pam.contracts.writes import UpdateWorkingMemoryInput
from pam.core import config
from pam.core.vault import Vault
from pam.working import session

app = typer.Typer(help="Working-memory sessions: start, record turns, update, end.", no_args_is_help=True)
out = Console()


class Role(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


def _emit(ctx: typer.Context, memory: WorkingMemory, line: str) -> None:
    if json_mode(ctx):
        typer.echo(memory.model_dump_json(indent=2))
    else:
        typer.echo(line)


def _models(memory: WorkingMemory) -> str:
    return ", ".join(switch.to_model for switch in memory.models_used) or "-"


@app.command("start")
def start_cmd(
    ctx: typer.Context,
    agent: str = typer.Option("default", "--agent", help="Agent that owns the session."),
    model: str = typer.Option(..., "--model", help="Model of the first turn."),
) -> None:
    """Start a session and commit its working file."""
    memory = session.start(Vault.resolve(), agent, model)
    _emit(ctx, memory, f"Started session {memory.session_id} (agent {agent}, model {model})")


@app.command("record")
def record_cmd(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., metavar="ID", help="Session id."),
    role: Role = typer.Option(..., "--role", help="Author of the turn."),
    text: str = typer.Option(..., "--text", help="Message text."),
    model: str = typer.Option(..., "--model", help="Model of this turn."),
) -> None:
    """Record one chat turn (no commit, except when it sets the goal)."""
    memory = session.record_turn(Vault.resolve(), session_id, role.value, text, model)
    _emit(ctx, memory, f"Recorded {role.value} turn on {model} ({len(memory.recent_turns)} recent turns)")


@app.command("show")
def show_cmd(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., metavar="ID", help="Session id."),
) -> None:
    """Print a session: goal, models used, decisions, questions, and recent turns."""
    memory = session.show(Vault.resolve(), session_id)
    if json_mode(ctx):
        typer.echo(memory.model_dump_json(indent=2))
        return
    lines = [
        f"Session {memory.session_id} · agent {memory.agent} · {memory.status}",
        f"Goal: {memory.goal or '-'}",
        f"Models used ({len(memory.models_used)}): {_models(memory)}",
    ]
    lines += [f"Decision: {d}" for d in memory.decisions]
    lines += [f"Open question: {q}" for q in memory.open_questions]
    lines.append(f"Recent turns ({len(memory.recent_turns)}):")
    lines += [f"  {m.role}: {' '.join(m.text.split())[:120]}" for m in memory.recent_turns]
    if memory.promoted_episode_id:
        lines.append(f"Episode: {memory.promoted_episode_id}")
    typer.echo("\n".join(lines))


@app.command("update")
def update_cmd(
    ctx: typer.Context,
    session_id: str = typer.Argument(..., metavar="ID", help="Session id."),
    goal: str | None = typer.Option(None, "--goal", help="New goal."),
    decision: list[str] = typer.Option([], "--decision", help="Decision to append (repeatable)."),
    question: list[str] = typer.Option([], "--question", help="Open question to append (repeatable)."),
    agent: str = typer.Option("default", "--agent", help="Agent named in the commit."),
) -> None:
    """Set the goal and append decisions or open questions (one commit)."""
    data = UpdateWorkingMemoryInput(session_id=session_id, goal=goal, add_decisions=decision, add_open_questions=question)
    emit_write_result(ctx, session.update(Vault.resolve(), data, agent))


@app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List sessions, newest first."""
    sessions = session.list_sessions(Vault.resolve())
    if json_mode(ctx):
        typer.echo(json.dumps([m.model_dump(mode="json") for m in sessions], indent=2))
        return
    table = Table("id", "agent", "status", "started", "models", "goal")
    for m in sessions:
        table.add_row(m.session_id, m.agent, m.status, m.started_at.isoformat(), _models(m), (m.goal or "")[:60])
    out.print(table)


@app.command("end")
def end_cmd(
    ctx: typer.Context,
    session_id: str | None = typer.Argument(None, metavar="ID", help="Session id (omit with --idle)."),
    agent: str | None = typer.Option(None, "--agent", help="Owner of the episode (default: the session's agent)."),
    idle: bool = typer.Option(False, "--idle", help="End every session idle for session_idle_minutes instead of one ID."),
) -> None:
    """Promote the full transcript to an episode and mark the session ended."""
    vault = Vault.resolve()
    if idle:
        results = session.end_idle(vault, config.load(vault).session_idle_minutes * 60)
        if json_mode(ctx):
            typer.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
        else:
            typer.echo(f"Ended {sum(r.ok for r in results)} of {len(results)} idle sessions")
        if any(not r.ok for r in results):
            raise typer.Exit(1)
        return
    if session_id is None:
        raise typer.BadParameter("give a session ID or --idle")
    emit_write_result(ctx, session.end(vault, session_id, agent))


def register(root: typer.Typer) -> None:
    root.add_typer(app, name="session")
