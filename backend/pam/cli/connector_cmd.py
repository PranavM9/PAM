"""`pam connector list|show|add|archive|call`: CLI wrappers over `pam.connectors` (SPEC §8 M16)."""

import asyncio
import json
from pathlib import Path
from typing import Any

import typer
import yaml
from pydantic import ValidationError

from pam.connectors import executor, store
from pam.contracts.connector import Connector, ConnectorParam
from pam.core.errors import PamError
from pam.core.vault import Vault

TRUE_WORDS = ("true", "1", "yes")
FALSE_WORDS = ("false", "0", "no")

connector_app = typer.Typer(help="Manage connectors (outside HTTP APIs offered to agents as tools).", no_args_is_help=True)


def _json_mode(ctx: typer.Context, local: bool = False) -> bool:
    return local or bool((ctx.find_root().obj or {}).get("json"))


def _vault() -> Vault:
    return Vault.resolve().require_initialized()


def _short(sha: str | None) -> str:
    return f"commit {sha[:7]}" if sha else "unchanged, no commit"


def list_cmd(
    ctx: typer.Context,
    all_: bool = typer.Option(False, "--all", help="Include archived connectors."),
) -> None:
    """List connectors, including invalid files (marked INVALID)."""
    entries = [
        e for e in store.scan_connectors(_vault())
        if all_ or e.connector is None or not e.connector.archived
    ]
    if _json_mode(ctx):
        rows = [
            {"id": e.id, "valid": e.valid, "error": e.error,
             "connector": e.connector.model_dump(mode="json") if e.connector else None}
            for e in entries
        ]
        typer.echo(json.dumps(rows, indent=2))
        return
    if not entries:
        typer.echo("No connectors.")
        return
    for e in entries:
        c = e.connector
        if c is None:
            typer.echo(f"{e.id}  INVALID: {e.error}")
            continue
        state = "archived" if c.archived else ("enabled" if c.enabled else "disabled")
        agents = ", ".join(c.agents) or "none"
        typer.echo(f"{c.id}  {c.name}  {state}  {len(c.tools)} tools  agents: {agents}")


def show(ctx: typer.Context, id: str = typer.Argument(..., help="Connector id.")) -> None:
    """Show one connector as YAML (or JSON with --json)."""
    connector = store.get_connector(_vault(), id)
    if _json_mode(ctx):
        typer.echo(connector.model_dump_json(indent=2))
    else:
        typer.echo(store.dump_yaml(connector), nl=False)


def add(file: Path = typer.Argument(..., exists=True, dir_okay=False, help="Connector YAML file.")) -> None:
    """Validate a connector YAML file and save it to the vault; one commit."""
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
        connector = Connector.model_validate(raw)
    except (yaml.YAMLError, ValidationError) as e:
        raise PamError(f"invalid connector file {file}: {' '.join(str(e).split())}", exit_code=2) from e
    sha = store.save_connector(_vault(), connector)
    typer.echo(f"Saved connector {connector.id} ({_short(sha)}).")


def archive(id: str = typer.Argument(..., help="Connector id.")) -> None:
    """Archive a connector (hidden and disabled; nothing is deleted); one commit."""
    sha = store.archive_connector(_vault(), id)
    typer.echo(f"Archived connector {id} ({_short(sha)}).")


def call(
    ctx: typer.Context,
    id: str = typer.Argument(..., help="Connector id."),
    tool: str = typer.Argument(..., help="Tool name."),
    arg: list[str] = typer.Option([], "--arg", help="Argument as key=value; repeat for more."),
    as_json: bool = typer.Option(False, "--json", help="Print the ConnectorResult as JSON."),
) -> None:
    """Call one connector tool and print status, latency and card titles; exit 1 if it failed."""
    v = _vault()
    connector = store.get_connector(v, id)
    params = {p.name: p for t in connector.tools if t.name == tool for p in t.params}
    args = dict(_parse_arg(a, params) for a in arg)
    result = asyncio.run(executor.call(v, id, tool, args))
    if _json_mode(ctx, as_json):
        typer.echo(result.model_dump_json(indent=2))
    elif result.ok:
        typer.echo(f"ok  HTTP {result.status}  {result.latency_ms} ms  {len(result.cards)} cards")
        for card in result.cards:
            typer.echo(f"- [{card.kind}] {card.title}")
    else:
        status = f"HTTP {result.status}  " if result.status is not None else ""
        typer.echo(f"error  {status}{result.latency_ms} ms  {result.error['code']}: {result.error['message']}")
    if not result.ok:
        raise typer.Exit(1)


def _parse_arg(text: str, params: dict[str, ConnectorParam]) -> tuple[str, Any]:
    """Split `key=value` and convert the value to the parameter's declared type when it parses."""
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise PamError(f"--arg must be key=value, got {text!r}", exit_code=2)
    param = params.get(key)
    if param is None or param.type == "string":
        return key, value
    if param.type == "boolean":
        lowered = value.lower()
        return key, True if lowered in TRUE_WORDS else False if lowered in FALSE_WORDS else value
    try:
        return key, int(value)
    except ValueError:
        try:
            return key, float(value)
        except ValueError:
            return key, value


connector_app.command("list")(list_cmd)
connector_app.command("show")(show)
connector_app.command("add")(add)
connector_app.command("archive")(archive)
connector_app.command("call")(call)


def register(app: typer.Typer) -> None:
    """Register the `connector` command group on the root app.

    Parameters:
        app: Root `pam` Typer app.
    """
    app.add_typer(connector_app, name="connector")
