"""`pam` CLI root. T00 creates it; T01 adds auto-discovery of `pam/cli/*_cmd.py` sub-apps."""

import typer

from pam import __version__

app = typer.Typer(name="pam", help="PAM — Portable Agent Memory", no_args_is_help=True)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False, "--version", callback=_version_callback, is_eager=True, help="Print the PAM version and exit."
    ),
) -> None:
    """PAM — Portable Agent Memory."""


if __name__ == "__main__":
    app()
