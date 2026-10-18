"""`pam cluster [--rebuild] [--agent A]`: CLI over `pam.cluster.cluster` (SPEC §8 M5, SETUP §6)."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager

import typer

from pam.cluster.cluster import run_cluster
from pam.core.vault import Vault


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


@contextmanager
def _warnings_to_stderr() -> Iterator[None]:
    """Print each distinct warning raised inside the block once on stderr as `Warning: <message>`."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield
        finally:
            for message in dict.fromkeys(str(w.message) for w in caught):
                typer.echo(f"Warning: {message}", err=True)


def cluster_command(
    ctx: typer.Context,
    rebuild: bool = typer.Option(False, "--rebuild", help="Re-cluster every episode; ids kept on >= 50% overlap."),
    agent: str = typer.Option("default", "--agent", help="Agent whose memory scope is clustered."),
) -> None:
    """Assign new episodes to projects (or re-cluster) and commit the project files once."""
    vault = Vault.resolve().require_initialized()
    with _warnings_to_stderr():
        report = run_cluster(vault, agent=agent, rebuild=rebuild)
    if _json_mode(ctx):
        typer.echo(report.model_dump_json(indent=2))
        return
    typer.echo(
        f"cluster ({report.mode}): +{report.projects_created} created, ~{report.projects_updated} updated, "
        f"{report.episodes_assigned} episodes assigned, {report.episodes_unassigned} unassigned"
    )
    if report.commit_sha:
        typer.echo(f"commit {report.commit_sha[:7]} · {report.duration_ms / 1000:.1f}s")
    else:
        typer.echo("No changes")


def register(root: typer.Typer) -> None:
    root.command("cluster")(cluster_command)
