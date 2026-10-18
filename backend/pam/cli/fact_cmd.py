"""`pam fact add|list|show|supersede`: CLI wrappers over `pam.memory.writer` (SPEC §8 M7, SETUP §6)."""

from __future__ import annotations

import json
from uuid import UUID

import typer
from rich.console import Console
from rich.table import Table

from pam.agents.manifest import load_manifest
from pam.agents.permissions import DocRef, can_read
from pam.contracts.fact import Fact
from pam.contracts.writes import AddFactInput, SupersedeFactInput, WriteResult
from pam.core.errors import PamError, PermissionDenied
from pam.core.vault import Vault
from pam.memory import conflicts, writer

fact_app = typer.Typer(help="Add, list, show, and supersede facts.", no_args_is_help=True)
out = Console()
STATUSES = ("active", "conflict")


def json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


def emit_write_result(ctx: typer.Context, result: WriteResult) -> None:
    """Print a `WriteResult` and turn a failure into the matching exit code.

    Behavior:
        `--json` prints the result as JSON (also for failures, followed by the exit code). Otherwise
        a success prints its message with the commit sha, and a failure raises the PAM error:
        exit 3 for `PERMISSION_DENIED`, 4 for a busy vault, 2 for validation, else 1.
    Exceptions:
        PamError: The write failed (`PermissionDenied` and `VaultBusy` for exits 3 and 4).
        typer.Exit: `--json` was given and the write failed.
    Parameters:
        ctx: Typer context, for the global `--json` flag.
        result: The writer's result.
    """
    if json_mode(ctx):
        typer.echo(result.model_dump_json(indent=2))
        if not result.ok:
            raise typer.Exit(writer.failure_exit_code(result))
        return
    writer.raise_for_result(result)
    commit = f"commit {result.commit_sha[:7]}" if result.commit_sha else "no commit (nothing changed)"
    typer.echo(f"{result.message} · {commit}")
    if result.path:
        typer.echo(f"  {result.path}")
    if result.conflict is not None:
        typer.echo(f"Warning: {result.conflict.attribute} is in conflict with {result.conflict.conflict.candidate_value!r}", err=True)


def parse_uuid(value: str, what: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as e:
        raise PamError(f"invalid {what} {value!r}", exit_code=2) from e


def _vault() -> Vault:
    return Vault.resolve().require_initialized()


def _visible(vault: Vault, agent: str):
    """Return a predicate for the facts `agent` may read (`default` reads everything)."""
    try:
        manifest = load_manifest(agent, vault)
    except PamError as e:
        raise PermissionDenied(f"agent {agent!r} is not usable: {e}") from e
    return lambda fact: can_read(manifest, DocRef(doc_id=str(fact.id), doc_type="fact", scope=fact.scope), vault)


def _find(vault: Vault, ref: str, agent: str) -> Fact:
    visible = _visible(vault, agent)
    matches = [f for _, f in conflicts.load_facts(vault) if str(f.id).startswith(ref.lower())]
    if not matches:
        raise PamError(f"fact {ref} not found")
    if len(matches) > 1:
        raise PamError(f"id prefix {ref} is ambiguous ({len(matches)} facts)")
    if not visible(matches[0]):
        raise PermissionDenied(f"agent {agent!r} may not read fact {matches[0].id}")
    return matches[0]


@fact_app.command("add")
def add(
    ctx: typer.Context,
    attribute: str = typer.Option(..., "--attribute", help="Snake-case attribute, e.g. school."),
    value: str = typer.Option(..., "--value", help="The value."),
    category: str = typer.Option(..., "--category", help="identity | education | work | location | preference | tooling | project | relationship | other"),
    cardinality: str = typer.Option("single", "--cardinality", help="single | multi"),
    subject: str = typer.Option("user", "--subject"),
    confidence: float = typer.Option(0.8, "--confidence", min=0.0, max=1.0),
    agent: str = typer.Option("default", "--agent", help="Agent performing the write."),
    shared: bool = typer.Option(True, "--shared/--no-shared", help="Write to shared memory (needs write=shared)."),
    episode: str | None = typer.Option(None, "--episode", metavar="ID", help="Episode the value came from."),
) -> None:
    """Add a fact, bump its confidence, or replace its SINGLE value; one commit."""
    data = AddFactInput.model_validate({
        "subject": subject, "attribute": attribute, "value": value, "category": category,
        "cardinality": cardinality, "confidence": confidence, "shared": shared,
        "episode_id": parse_uuid(episode, "episode id") if episode else None,
    })
    emit_write_result(ctx, writer.add_fact(_vault(), data, agent))


@fact_app.command("list")
def list_cmd(
    ctx: typer.Context,
    scope: str | None = typer.Option(None, "--scope", help="shared or an agent name."),
    status: str | None = typer.Option(None, "--status", help="active | conflict"),
    agent: str = typer.Option("default", "--agent", help="List only what this agent may read."),
) -> None:
    """List facts."""
    if status is not None and status not in STATUSES:
        raise PamError(f"--status must be one of {', '.join(STATUSES)}", exit_code=2)
    vault = _vault()
    visible = _visible(vault, agent)
    rows = [
        f for _, f in conflicts.load_facts(vault, scope)
        if (status is None or f.status.value == status) and visible(f)
    ]
    rows.sort(key=lambda f: (f.scope, f.attribute, f.value.lower()))
    if json_mode(ctx):
        typer.echo(json.dumps([f.model_dump(mode="json") for f in rows], indent=2))
        return
    table = Table("id", "scope", "attribute", "value", "conf", "status")
    table.columns[0].no_wrap = True
    for f in rows:
        table.add_row(str(f.id), f.scope, f.attribute, f.value, f"{f.confidence:.2f}", f.status.value)
    out.print(table)


@fact_app.command("show")
def show(
    ctx: typer.Context,
    fact_id: str = typer.Argument(..., metavar="ID", help="Fact id or a unique prefix."),
    agent: str = typer.Option("default", "--agent", help="Agent reading the fact."),
) -> None:
    """Show one fact with its history and any conflict."""
    fact = _find(_vault(), fact_id, agent)
    if json_mode(ctx):
        typer.echo(fact.model_dump_json(indent=2))
        return
    typer.echo(f"{fact.attribute} = {fact.value}")
    typer.echo(f"  id {fact.id} · scope {fact.scope} · {fact.category.value} · {fact.cardinality.value}")
    typer.echo(f"  status {fact.status.value} · confidence {fact.confidence:.2f} · extractor {fact.extractor.value}")
    typer.echo(f"  source episode {fact.source_episode or '-'} · updated by episode {fact.updated_by_episode or '-'}")
    if fact.conflict is not None:
        typer.echo(f"  conflict: candidate {fact.conflict.candidate_value!r} (episode {fact.conflict.candidate_source_episode or '-'})")
    typer.echo(f"  history ({len(fact.history)}):")
    for entry in fact.history:
        who = f"{entry.changed_by.value}{':' + entry.agent if entry.agent else ''}"
        reason = f" · {entry.reason}" if entry.reason else ""
        typer.echo(f"    {entry.changed_at:%Y-%m-%d %H:%M}Z {entry.value!r} (was) by {who}{reason}")


@fact_app.command("supersede")
def supersede(
    ctx: typer.Context,
    fact_id: str = typer.Argument(..., metavar="ID", help="Fact id or a unique prefix."),
    value: str = typer.Option(..., "--value", help="The confirmed new value."),
    reason: str = typer.Option(..., "--reason", help="Why, e.g. 'user confirmed they transferred to UW'."),
    agent: str = typer.Option("default", "--agent", help="Agent performing the write."),
    episode: str | None = typer.Option(None, "--episode", metavar="ID", help="Episode the new value came from."),
) -> None:
    """Replace a fact's value, clear its conflict, and record why; one commit."""
    vault = _vault()
    fact = _find(vault, fact_id, agent)
    data = SupersedeFactInput(
        fact_id=fact.id, new_value=value, reason=reason,
        episode_id=parse_uuid(episode, "episode id") if episode else None,
    )
    emit_write_result(ctx, writer.supersede_fact(vault, data, agent))


def register(root: typer.Typer) -> None:
    root.add_typer(fact_app, name="fact")
