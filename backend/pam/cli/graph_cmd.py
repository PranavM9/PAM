"""`pam graph export [--agent A] [--facts] [--out FILE]`: CLI over `pam.cluster.graph` (SPEC §8 M5, SETUP §6)."""

from __future__ import annotations

import warnings
from pathlib import Path

import typer

from pam.cluster.graph import build_graph
from pam.core.errors import PamError
from pam.core.vault import Vault

graph_app = typer.Typer(help="Export the project / episode graph.", no_args_is_help=True)


@graph_app.command("export")
def export(
    agent: str = typer.Option("default", "--agent", help="Agent whose read scope filters the graph."),
    facts: bool = typer.Option(False, "--facts", help="Include fact nodes and derived_from links."),
    out: Path | None = typer.Option(None, "--out", help="Write GraphData JSON here (default: stdout)."),
) -> None:
    """Write the agent's `GraphData` as JSON; `--out` creates missing parent folders."""
    vault = Vault.resolve().require_initialized()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        graph = build_graph(vault, agent=agent, facts=facts)
    for message in dict.fromkeys(str(w.message) for w in caught):
        typer.echo(f"Warning: {message}", err=True)
    text = graph.model_dump_json(indent=2)
    if out is None:
        typer.echo(text)
        return
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        raise PamError(f"cannot write {out}: {exc.strerror or exc}") from exc
    counts = {t: sum(n.type == t for n in graph.nodes) for t in ("project", "episode", "fact")}
    typer.echo(
        f"{out}: {counts['project']} projects, {counts['episode']} episodes, {counts['fact']} facts, "
        f"{len(graph.links)} links",
        err=True,
    )


def register(root: typer.Typer) -> None:
    root.add_typer(graph_app, name="graph")
