"""`pam init` and `pam config show|path`: thin CLI wrappers over `pam.core`."""

import json
from pathlib import Path

import typer
from rich.console import Console

from pam.core import config as core_config
from pam.core.vault import Vault, init_vault

out = Console()
err = Console(stderr=True)

config_app = typer.Typer(help="Show the vault configuration (pam.toml).", no_args_is_help=True)


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


def init(
    ctx: typer.Context,
    vault: Path | None = typer.Option(None, "--vault", help="Vault folder (overrides PAM_VAULT)."),
) -> None:
    """Create the vault tree, pam.toml, the git repo, and the default agent; make the initial commit."""
    result = init_vault(vault)
    if _json_mode(ctx):
        typer.echo(json.dumps({
            "root": str(result.root), "created": result.created,
            "commit_sha": result.commit_sha, "files": result.files,
        }, indent=2))
    elif result.created:
        out.print(f"[green]Created[/] vault at {result.root} (commit {result.commit_sha[:7]})")
    else:
        err.print(f"[yellow]Warning:[/] {result.root} is already a PAM vault; nothing to do")


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Print the effective PamConfig (defaults if the vault has no pam.toml)."""
    cfg = core_config.load()
    if _json_mode(ctx):
        typer.echo(cfg.model_dump_json(indent=2))
    else:
        out.print(core_config.dump_toml(cfg), markup=False, highlight=False, end="")


@config_app.command("path")
def config_path(ctx: typer.Context) -> None:
    """Print where the config is loaded from."""
    path = Vault.resolve().config_path
    if _json_mode(ctx):
        typer.echo(json.dumps({"path": str(path), "exists": path.is_file()}))
    else:
        out.print(str(path) if path.is_file() else f"{path} (not found; using defaults)", markup=False)


def register(app: typer.Typer) -> None:
    """Register `init` and the `config` group on the root app.

    Parameters:
        app: The root `pam` Typer app.
    """
    app.command("init")(init)
    app.add_typer(config_app, name="config")
