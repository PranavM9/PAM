"""`pam sync`: commit and reindex edits made outside PAM, once or in a polling loop (SPEC §8 M10)."""

from __future__ import annotations

import typer

from pam.core.errors import VaultBusy
from pam.core.vault import Vault
from pam.sync.watcher import SyncResult, sync, watch

app = typer.Typer(help="Sync edits made outside PAM into git and the index.")


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


def _print(result: SyncResult, json_out: bool) -> None:
    if json_out:
        typer.echo(result.report.model_dump_json())
        return
    for line in result.problems:
        typer.echo(f"Warning: {line}", err=True)
    if result.busy:
        typer.echo(f"Vault busy; skipped ({len(result.dirty_paths)} dirty paths left for the next sync)")
    elif result.commit_sha:
        typer.echo(f"Committed {len(result.committed)} files ({result.reindexed} reindexed)")
        for path in result.committed:
            typer.echo(f"    {path}")
        typer.echo(f"commit {result.commit_sha}")
    elif not result.dirty_paths:
        typer.echo("Vault is clean; nothing to sync")
    else:
        typer.echo("Nothing committed")


@app.callback(invoke_without_command=True)
def sync_command(
    ctx: typer.Context,
    watch_mode: bool = typer.Option(False, "--watch", help="Keep syncing every --interval seconds until Ctrl-C."),
    interval: float = typer.Option(2.0, "--interval", min=0.1, help="Seconds between passes with --watch."),
) -> None:
    """Commit and reindex manual vault edits; restore deleted files from git.

    Behavior:
        One pass prints what was committed, restored, or refused (edited episode bodies, invalid
        frontmatter); with the global `--json` it prints the `SyncReport`. `--watch` repeats the
        pass and prints only passes that found dirty paths (one JSON line each with `--json`).
    Exceptions:
        VaultBusy: Another writer holds the lock (exit 4; `--json` prints the report first).
        PamError: The vault is not a git repo or git fails (exit 1).
    Parameters:
        ctx: Typer context with the global options.
        watch_mode: Poll instead of running once.
        interval: Seconds between passes.
    """
    vault = Vault.resolve().require_initialized()
    json_out = _json_mode(ctx)
    if watch_mode:
        def on_result(result: SyncResult) -> None:
            if result.dirty_paths:
                _print(result, json_out)

        try:
            watch(vault, interval, on_result=on_result)
        except KeyboardInterrupt:
            pass
        return
    result = sync(vault)
    if result.busy:
        if json_out:
            _print(result, json_out)
            raise typer.Exit(VaultBusy.exit_code)
        raise VaultBusy(f"vault busy: another writer holds {vault.lock_path}; nothing synced")
    _print(result, json_out)
