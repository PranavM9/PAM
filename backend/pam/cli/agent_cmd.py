"""`pam agent create|list|show|set-scope|check`: CLI wrappers over `pam.agents` (SPEC §8 M8, SETUP §6)."""

import json
from typing import get_args
from uuid import UUID

import typer
import yaml

from pam.agents import manifest as agents
from pam.agents.permissions import (
    READ_TOOLS, can_call, can_read, can_write_path, doc_ref_from_path,
)
from pam.contracts.agent import AgentManifest, ReadScope, ToolName
from pam.core.errors import PamError
from pam.core.time import utcnow
from pam.core.vault import Vault

ALL_TOOLS: list[str] = list(get_args(ToolName))

agent_app = typer.Typer(help="Create, inspect, and scope agents.", no_args_is_help=True)


def _json_mode(ctx: typer.Context) -> bool:
    return bool((ctx.find_root().obj or {}).get("json"))


def _split(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_projects(value: str) -> list[UUID]:
    try:
        return [UUID(v) for v in _split(value)]
    except ValueError as e:
        raise PamError(f"invalid project id in {value!r}", exit_code=2) from e


def _parse_tools(value: str) -> list[str]:
    tools = _split(value)
    unknown = [t for t in tools if t not in ALL_TOOLS]
    if unknown:
        raise PamError(f"unknown tool(s): {', '.join(unknown)}", exit_code=2)
    return tools


def _warn_missing_projects(project_ids: list[UUID]) -> None:
    root = Vault.resolve().root
    for pid in project_ids:
        if not any(root.glob(f"memory/*/projects/{pid}.md")):
            typer.echo(f"Warning: project {pid} has no file yet; it adds nothing until it exists", err=True)


def create(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Agent name (lowercase slug)."),
    display_name: str | None = typer.Option(None, "--display-name", help="Defaults to NAME."),
    description: str = typer.Option("", "--description"),
    projects: str = typer.Option("", "--projects", help="Comma-separated project ids the agent may read."),
    write: str = typer.Option("own", "--write", help="none | own | shared"),
    tools: str | None = typer.Option(None, "--tools", help="Comma-separated tools (default: all; read tools with --write none)."),
    model: str | None = typer.Option(None, "--model", help="Default LiteLLM model string."),
    budget: int = typer.Option(2000, "--budget", help="Context token budget."),
) -> None:
    """Create a custom agent with empty persona files; one commit."""
    project_ids = _parse_projects(projects)
    if tools is not None:
        tool_list = _parse_tools(tools)
    else:
        tool_list = [t for t in ALL_TOOLS if write != "none" or t in READ_TOOLS]
    manifest = AgentManifest(
        name=name,
        display_name=display_name or name,
        description=description,
        origin="custom",
        created_at=utcnow(),
        read=ReadScope(project_ids=project_ids),
        write=write,
        tools=tool_list,
        default_model=model,
        token_budget=budget,
    )
    sha = agents.create_agent(manifest)
    _warn_missing_projects(project_ids)
    if _json_mode(ctx):
        typer.echo(manifest.model_dump_json(indent=2))
    else:
        typer.echo(f"Created agent {name} (commit {sha[:7]})")


def list_cmd(ctx: typer.Context) -> None:
    """List all agents."""
    manifests = agents.list_agents()
    if _json_mode(ctx):
        typer.echo(json.dumps([m.model_dump(mode="json") for m in manifests], indent=2))
        return
    for m in manifests:
        read = "all" if m.read.all else f"projects={len(m.read.project_ids)}"
        typer.echo(f"{m.name:<20} write={m.write:<6} read={read:<12} tools={len(m.tools):<3} {m.display_name}")


def show(ctx: typer.Context, name: str = typer.Argument(..., help="Agent name.")) -> None:
    """Show an agent's manifest and rendered persona."""
    manifest = agents.load_manifest(name)
    persona = agents.load_persona(name)
    if _json_mode(ctx):
        typer.echo(json.dumps(
            {"manifest": manifest.model_dump(mode="json"), "persona": persona.model_dump(mode="json")}, indent=2
        ))
        return
    typer.echo(yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False, allow_unicode=True), nl=False)
    typer.echo("\n# identity\n" + (persona.identity or "(empty)"))
    typer.echo("\n# rules")
    typer.echo("\n".join(agents.format_rule(r) for r in persona.rules) or "(empty)")
    typer.echo("\n# style\n" + (persona.style or "(empty)"))


def set_scope(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Agent name."),
    projects: str | None = typer.Option(None, "--projects", help="Replaces the project ids (\"\" clears them)."),
    shared_facts: bool | None = typer.Option(None, "--shared-facts/--no-shared-facts"),
    write: str | None = typer.Option(None, "--write", help="none | own | shared"),
    tools: str | None = typer.Option(None, "--tools", help="Comma-separated tools; replaces the list."),
) -> None:
    """Update an agent's scope, write level, or tools; one commit."""
    project_ids = _parse_projects(projects) if projects is not None else None
    manifest, sha = agents.set_scope(
        name,
        project_ids=project_ids,
        include_shared_facts=shared_facts,
        write=write,
        tools=_parse_tools(tools) if tools is not None else None,
    )
    if project_ids:
        _warn_missing_projects(project_ids)
    if _json_mode(ctx):
        typer.echo(manifest.model_dump_json(indent=2))
    elif sha is None:
        typer.echo(f"No changes for agent {name}")
    else:
        typer.echo(f"Updated agent {name} (commit {sha[:7]})")


def _tool_decision(manifest: AgentManifest, tool: str) -> dict:
    if tool not in ALL_TOOLS:
        return {"allowed": False, "reason": "unknown tool"}
    if can_call(manifest, tool):
        return {"allowed": True, "reason": "in the agent's tools"}
    if tool not in manifest.tools:
        return {"allowed": False, "reason": "not in the agent's tools"}
    return {"allowed": False, "reason": "write tool and write level is none"}


def _path_decisions(manifest: AgentManifest, path: str) -> dict:
    ref = doc_ref_from_path(path)
    if ref is None:
        read = {"allowed": None, "reason": "not a memory document"}
    else:
        ok = can_read(manifest, ref)
        read = {"allowed": ok, "reason": f"{ref.doc_type} in scope {ref.scope}"}
    ok = can_write_path(manifest, path)
    write = {"allowed": ok, "reason": f"write level is {manifest.write}"}
    return {"read": read, "write": write}


def _word(allowed: bool | None) -> str:
    return "n/a" if allowed is None else ("allowed" if allowed else "denied")


def check(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Agent name."),
    tool: str | None = typer.Option(None, "--tool", help="Tool to check."),
    path: str | None = typer.Option(None, "--path", help="Vault-relative path to check."),
) -> None:
    """Show the permission decisions for a tool call or a vault path."""
    if tool is None and path is None:
        raise PamError("give --tool or --path", exit_code=2)
    manifest = agents.load_manifest(name)
    result: dict = {"agent": name}
    if tool is not None:
        result["tool"] = {"name": tool, **_tool_decision(manifest, tool)}
    if path is not None:
        result["path"] = {"path": path, **_path_decisions(manifest, path)}
    if _json_mode(ctx):
        typer.echo(json.dumps(result, indent=2))
        return
    if tool is not None:
        d = result["tool"]
        typer.echo(f"tool {tool}: {_word(d['allowed'])} ({d['reason']})")
    if path is not None:
        for action in ("read", "write"):
            d = result["path"][action]
            typer.echo(f"{action} {path}: {_word(d['allowed'])} ({d['reason']})")


agent_app.command("create")(create)
agent_app.command("list")(list_cmd)
agent_app.command("show")(show)
agent_app.command("set-scope")(set_scope)
agent_app.command("check")(check)


def register(app: typer.Typer) -> None:
    """Register the `agent` command group on the root app.

    Parameters:
        app: Root `pam` Typer app.
    """
    app.add_typer(agent_app, name="agent")
