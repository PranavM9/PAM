"""`pam episode list|show|verify`: read-only views over the vault's episode files."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from pam.cli.fact_cmd import emit_write_result
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.raw import RawMessage
from pam.contracts.writes import LogEpisodeInput
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.ids import sha256_text
from pam.core.vault import Vault
from pam.memory import writer

app = typer.Typer(help="Inspect and verify imported episodes.", no_args_is_help=True)
out = Console()
err = Console(stderr=True)


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


def _episode_files(vault: Vault, agent: str | None = None) -> list[Path]:
    if agent:
        folders = [vault.memory_dir(agent) / "episodes"]
    else:
        base = vault.root / "memory"
        folders = [d / "episodes" for d in sorted(base.iterdir())] if base.is_dir() else []
    return sorted(p for folder in folders if folder.is_dir() for p in folder.glob("*.md"))


def _find(vault: Vault, episode_id: str) -> Path:
    matches = [p for p in _episode_files(vault) if p.stem.startswith(episode_id.lower())]
    if not matches:
        raise PamError(f"no episode with id {episode_id}")
    if len(matches) > 1:
        raise PamError(f"id prefix {episode_id} is ambiguous ({len(matches)} episodes)")
    return matches[0]


@app.command("list")
def list_cmd(
    ctx: typer.Context,
    agent: str | None = typer.Option(None, "--agent", help="Only this agent's episodes."),
    source: str | None = typer.Option(None, "--source", help="Only this source (claude, chatgpt, ...)."),
    limit: int = typer.Option(20, "--limit", min=1, help="Maximum rows."),
) -> None:
    """List episodes, newest first."""
    vault = Vault.resolve().require_initialized()
    rows: list[EpisodeFrontmatter] = []
    for path in _episode_files(vault, agent):
        try:
            fm, _ = mdio.read_model(path, EpisodeFrontmatter)
        except (PamError, ValidationError, ValueError) as e:
            err.print(f"[yellow]Warning:[/] {path.name}: {e}", markup=True)
            continue
        if source is None or fm.source.value == source:
            rows.append(fm)
    rows.sort(key=lambda fm: fm.created_at, reverse=True)
    rows = rows[:limit]
    if _json_mode(ctx):
        typer.echo(json.dumps([fm.model_dump(mode="json") for fm in rows], indent=2))
        return
    table = Table("id", "date", "source", "title", "msgs")
    for fm in rows:
        table.add_row(str(fm.id), fm.created_at.date().isoformat(), fm.source.value, fm.title, str(fm.message_count))
    out.print(table)


@app.command("show")
def show_cmd(
    episode_id: str = typer.Argument(..., metavar="ID", help="Episode id or a unique prefix."),
    raw: bool = typer.Option(False, "--raw", help="Print the file exactly as stored."),
) -> None:
    """Print one episode, rendered or raw."""
    vault = Vault.resolve().require_initialized()
    path = _find(vault, episode_id)
    if raw:
        typer.echo(path.read_bytes().decode("utf-8"), nl=False)
        return
    fm, body = mdio.read_model(path, EpisodeFrontmatter)
    out.print(f"[bold]{fm.title}[/]\n{fm.source.value} · {fm.agent} · {fm.message_count} messages · {fm.id}", markup=True)
    out.print(Markdown(body))


@app.command("verify")
def verify_cmd(ctx: typer.Context) -> None:
    """Re-hash every episode body against `body_sha256`; exit 1 on any mismatch."""
    vault = Vault.resolve().require_initialized()
    ok = 0
    bad: list[str] = []
    for path in _episode_files(vault):
        try:
            fm, body = mdio.read_model(path, EpisodeFrontmatter)
        except (PamError, ValidationError, ValueError) as e:
            bad.append(f"{path.stem}: unreadable ({e})")
            continue
        if sha256_text(body) == fm.body_sha256:
            ok += 1
        else:
            bad.append(f"{path.stem}: body_sha256 mismatch")
    if _json_mode(ctx):
        typer.echo(json.dumps({"ok": ok, "failed": bad}, indent=2))
    else:
        for line in bad:
            err.print(f"FAIL {line}", markup=False)
        out.print(f"{ok} OK, {len(bad)} failed", markup=False)
    if bad:
        raise typer.Exit(1)


def _read_messages(source: str) -> list[RawMessage]:
    try:
        text = typer.get_text_stream("stdin").read() if source == "-" else Path(source).read_text(encoding="utf-8")
    except OSError as e:
        raise PamError(f"cannot read messages from {source}: {e}") from e
    messages = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            messages.append(RawMessage.model_validate_json(line))
        except ValidationError as e:
            raise PamError(f"{source}:{number}: not a valid message: {e}", exit_code=2) from e
    return messages


@app.command("log")
def log_cmd(
    ctx: typer.Context,
    title: str = typer.Option(..., "--title", help="Episode title."),
    messages: str = typer.Option(..., "--messages", help="JSONL of messages {role, text, created_at?} ('-' for stdin)."),
    summary: str | None = typer.Option(None, "--summary", help="Episode summary."),
    tags: str = typer.Option("", "--tags", help="Comma-separated tags."),
    agent: str = typer.Option("default", "--agent", help="Agent that owns the episode."),
    session: str | None = typer.Option(None, "--session", help="Working-memory session id."),
) -> None:
    """Log a conversation as an episode, mine it for facts, and commit once."""
    data = LogEpisodeInput(
        title=title, messages=_read_messages(messages), summary=summary,
        tags=[t.strip() for t in tags.split(",") if t.strip()],
    )
    emit_write_result(ctx, writer.log_episode(Vault.resolve().require_initialized(), data, agent, session))


def register(root: typer.Typer) -> None:
    root.add_typer(app, name="episode")
