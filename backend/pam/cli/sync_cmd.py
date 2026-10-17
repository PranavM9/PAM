"""`pam sync`: placeholder until the vault sync watcher lands in T09b (SPEC §8 M10)."""

import typer

app = typer.Typer(help="Sync manual vault edits into git and the index (T09b).")


@app.callback(invoke_without_command=True)
def sync() -> None:
    """Commit and reindex manual vault edits (not implemented until T09b)."""
    typer.echo("not implemented until T09b")
