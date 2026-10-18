"""`pam models list|check`: show the models in `pam.toml` and ping each one (SPEC §8 M12, SETUP §6)."""

from __future__ import annotations

import asyncio
import json

import typer

from pam.core import config
from pam.core.errors import PamError
from pam.core.vault import Vault

app = typer.Typer(help="List and health-check chat models.", no_args_is_help=True)


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


@app.command("list")
def list_cmd(ctx: typer.Context) -> None:
    """List the models declared in `pam.toml`."""
    models = config.load(Vault.resolve().require_initialized()).models
    if _json_mode(ctx):
        typer.echo(json.dumps([m.model_dump(mode="json") for m in models], indent=2))
        return
    if not models:
        typer.echo("No models configured; add [[models]] entries to pam.toml.", err=True)
        return
    for m in models:
        tools = "tools" if m.supports_tools else "-"
        typer.echo(f"{m.id:<60} {tools:<6} {m.label}")


@app.command("check")
def check(ctx: typer.Context) -> None:
    """Ping every model concurrently with a 1-token request; exit 1 if all of them fail."""
    from pam.chat.llm import ping  # lazy: litellm is slow to import

    models = config.load(Vault.resolve().require_initialized()).models
    if not models:
        raise PamError("no models configured; add [[models]] entries to pam.toml")

    async def ping_all():
        return await asyncio.gather(*(ping(m) for m in models))

    results = asyncio.run(ping_all())
    if _json_mode(ctx):
        rows = [{"id": m.id, **r._asdict()} for m, r in zip(models, results)]
        typer.echo(json.dumps(rows, indent=2))
    else:
        for m, r in zip(models, results):
            status = "OK" if r.ok else "FAIL"
            line = f"{status:<5} {r.latency_ms:>6} ms  {m.id}"
            typer.echo(line if r.ok else f"{line}  {r.error}")
    if not any(r.ok for r in results):
        raise typer.Exit(1)
