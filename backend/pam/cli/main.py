"""`pam` CLI root: global options, error-to-exit-code mapping, and command auto-discovery.

Behavior:
    Imports every `pam/cli/*_cmd.py` module in alphabetical order and registers its commands, so
    later tasks never edit this file. A module registers in one of two ways:

        def register(app: typer.Typer) -> None:      # preferred: any mix of commands and groups
            app.command("foo")(foo)
            app.add_typer(foo_app, name="foo")

        app = typer.Typer()                          # fallback: mounted as `pam <name>`, where
                                                     # `<name>_cmd.py` is the module name

    Global options land in `ctx.find_root().obj` (`json`, `verbose`); `--vault` sets the core
    vault override. A `*_cmd.py` module must not import this module (circular import).
"""

import importlib
import pkgutil
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError
from typer._click.exceptions import ClickException  # typer >= 0.26 vendors click; stock click's class is not caught
from typer.core import TyperGroup

import pam.cli
from pam import __version__
from pam.core.errors import PamError
from pam.core.vault import set_vault_override


class _CliError(ClickException):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class PamGroup(TyperGroup):
    """Root command group that maps PAM errors to SETUP §5 exit codes.

    Behavior:
        A `PamError` exits with its `exit_code`; a pydantic `ValidationError` exits with `2`. Both
        print a one-line error instead of a traceback.
    """

    def invoke(self, ctx: typer.Context) -> Any:
        try:
            return super().invoke(ctx)
        except PamError as e:
            raise _CliError(str(e), e.exit_code) from e
        except ValidationError as e:
            raise _CliError(f"validation error: {e}", 2) from e


app = typer.Typer(name="pam", help="PAM — Portable Agent Memory", no_args_is_help=True, cls=PamGroup)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    vault: Path | None = typer.Option(None, "--vault", help="Vault folder (overrides PAM_VAULT)."),
    json_out: bool = typer.Option(False, "--json", help="Print contract models as JSON."),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="More output."),
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Print the PAM version and exit."
    ),
) -> None:
    """PAM — Portable Agent Memory."""
    set_vault_override(vault)
    ctx.ensure_object(dict)
    ctx.obj.update(json=json_out, verbose=verbose)


def _discover(root: typer.Typer) -> None:
    for info in sorted(pkgutil.iter_modules(pam.cli.__path__), key=lambda m: m.name):
        if not info.name.endswith("_cmd"):
            continue
        module = importlib.import_module(f"pam.cli.{info.name}")
        register = getattr(module, "register", None)
        sub_app = getattr(module, "app", None)
        if callable(register):
            register(root)
        elif isinstance(sub_app, typer.Typer):
            root.add_typer(sub_app, name=info.name.removesuffix("_cmd"))


_discover(app)

if __name__ == "__main__":
    app()
