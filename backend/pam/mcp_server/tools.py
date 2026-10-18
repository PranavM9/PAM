"""MCP tool implementations for one bound agent (SPEC §8 M11, §7.15).

Behavior:
    Each tool validates its arguments with the §7.9 / §7.11 contract model, calls the core module,
    and returns a `CallToolResult` carrying `model_dump(mode="json")` as structured content plus one
    text block. Modules owned by later tasks (`pam.retrieve`, `pam.working`) are imported inside the
    tool, so the server builds and advertises all ten tools before they merge; a call then returns a
    `NOT_AVAILABLE: <module> not merged yet` result instead of raising.
"""

from __future__ import annotations

import importlib
import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType
from typing import Annotated, Any
from uuid import UUID

import anyio.to_thread
from mcp_types import CallToolResult, TextContent
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from pam.agents import manifest as agents
from pam.agents.permissions import WRITE_TOOLS, DocRef, can_read
from pam.contracts.retrieval import ContextRequest, SearchQuery
from pam.contracts.writes import (
    AddFactInput,
    AddSkillInput,
    GetEpisodeInput,
    LogEpisodeInput,
    SupersedeFactInput,
    UpdateProjectInput,
    UpdateWorkingMemoryInput,
    WriteResult,
)
from pam.core import mdio, tokens
from pam.core.errors import PamError, PermissionDenied
from pam.core.vault import Vault

DENIED = "PERMISSION_DENIED:"
NOT_AVAILABLE = "NOT_AVAILABLE:"
_TRUNCATION_MARK = "\n\n[... middle of the transcript truncated to fit max_tokens ...]\n\n"


class NotAvailable(Exception):
    """A module owned by a task that has not merged yet cannot be imported."""

    def __init__(self, module: str) -> None:
        super().__init__(f"{NOT_AVAILABLE} {module} not merged yet")


@dataclass(frozen=True)
class Binding:
    """The vault and the agent one server instance is bound to."""

    vault: Vault
    agent: str


def _deps(module: str, attribute: str | None = None) -> Any:
    """Import a module (or one of its attributes) that a later task provides.

    Behavior:
        Only a missing `module` itself, or one of its parent packages, counts as unavailable. An
        import error raised from inside an existing module is a real bug and propagates.
    Exceptions:
        NotAvailable: The module or the attribute does not exist yet.
    Returns:
        The module, or the named attribute of it.
    Parameters:
        module: Dotted module name.
        attribute: Optional attribute to fetch from the module.
    """
    try:
        loaded: ModuleType = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name and (module == exc.name or module.startswith(exc.name + ".")):
            raise NotAvailable(module) from exc
        raise
    if attribute is None:
        return loaded
    try:
        return getattr(loaded, attribute)
    except AttributeError as exc:
        raise NotAvailable(f"{module}.{attribute}") from exc


def _result(payload: dict[str, Any], text: str | None = None, *, is_error: bool = False) -> CallToolResult:
    body = json.dumps(payload, ensure_ascii=False, indent=2) if text is None else text
    return CallToolResult(
        content=[TextContent(type="text", text=body)], structured_content=payload, is_error=is_error
    )


def _write_result(result: WriteResult) -> CallToolResult:
    payload = result.model_dump(mode="json")
    return _result(payload, is_error=not result.ok)


def _failure(message: str) -> CallToolResult:
    return _result({"ok": False, "message": message}, message, is_error=True)


def _truncate_middle(text: str, max_tokens: int) -> str:
    """Cut the middle out of a text so the result fits `max_tokens`, keeping both ends."""
    if tokens.count(text) <= max_tokens:
        return text

    def joined(keep: int) -> str:
        return text[:keep] + _TRUNCATION_MARK + (text[-keep:] if keep else "")

    low, high = 0, len(text) // 2
    while low < high:
        mid = (low + high + 1) // 2
        if tokens.count(joined(mid)) <= max_tokens:
            low = mid
        else:
            high = mid - 1
    return joined(low)


def _find_episode(vault: Vault, episode_id: UUID) -> tuple[str, Any] | None:
    for path in sorted((vault.root / "memory").glob(f"*/episodes/{episode_id}.md")):
        return path.parent.parent.name, path
    return None


# -- tool handlers: (binding, validated arguments) -> CallToolResult ---------------------------


def _get_context(bound: Binding, args: dict[str, Any]) -> CallToolResult:
    request = ContextRequest.model_validate({**args, "agent": bound.agent})
    build_context = _deps("pam.retrieve.context", "build_context")
    bundle = build_context(bound.vault, request)
    return _result(bundle.model_dump(mode="json"), bundle.rendered)


def _search_memory(bound: Binding, args: dict[str, Any]) -> CallToolResult:
    query = SearchQuery.model_validate({**args, "agent": bound.agent})
    search = _deps("pam.retrieve.search", "search")
    return _result(search(bound.vault, query).model_dump(mode="json"))


def _get_episode(bound: Binding, args: dict[str, Any]) -> CallToolResult:
    data = GetEpisodeInput.model_validate(args)
    manifest = agents.load_manifest(bound.agent, bound.vault)
    found = _find_episode(bound.vault, data.episode_id)
    if found is None:
        return _failure(f"episode {data.episode_id} not found")
    scope, path = found
    if not can_read(manifest, DocRef(str(data.episode_id), "episode", scope), bound.vault):
        return _failure(f"{DENIED} agent {bound.agent!r} may not read episode {data.episode_id}")
    frontmatter, body = mdio.read(path)
    text = _truncate_middle(body, data.max_tokens)
    payload = {
        "episode_id": str(data.episode_id),
        "title": frontmatter.get("title"),
        "truncated": text != body,
        "markdown": text,
    }
    return _result(payload, text)


def _list_agents(bound: Binding, args: dict[str, Any]) -> CallToolResult:
    rows = [
        {"name": m.name, "display_name": m.display_name, "description": m.description}
        for m in agents.list_agents(bound.vault)
    ]
    return _result({"agents": rows})


def _writer_tool(action: str, model: type[BaseModel]) -> Callable[[Binding, dict[str, Any]], CallToolResult]:
    def handler(bound: Binding, args: dict[str, Any]) -> CallToolResult:
        data = model.model_validate(args)
        write = _deps("pam.memory.writer", action)
        return _write_result(write(bound.vault, data, agent=bound.agent))

    return handler


def _update_working_memory(bound: Binding, args: dict[str, Any]) -> CallToolResult:
    data = UpdateWorkingMemoryInput.model_validate(args)
    update = _deps("pam.working.session", "update_working_memory")
    result = update(bound.vault, data, agent=bound.agent)
    return _write_result(result if isinstance(result, WriteResult) else WriteResult.model_validate(result))


# -- registration ------------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One advertised tool: its contract model, description, and handler."""

    name: str
    description: str
    model: type[BaseModel] | None
    handler: Callable[[Binding, dict[str, Any]], CallToolResult]
    hidden_fields: frozenset[str] = frozenset()


TOOL_SPECS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "get_context",
            "Get the persona, facts, projects and past conversations relevant to a query. "
            "If get_context returns conflicting facts, ask the user which is correct, "
            "then call supersede_fact.",
            ContextRequest, _get_context, frozenset({"agent"}),
        ),
        ToolSpec("search_memory", "Search the memory index for relevant chunks.", SearchQuery, _search_memory),
        ToolSpec(
            "get_episode", "Read one episode's Markdown, truncated from the middle to max_tokens.",
            GetEpisodeInput, _get_episode,
        ),
        ToolSpec("list_agents", "List the agents in this vault.", None, _list_agents),
        ToolSpec(
            "add_fact", "Record a fact about the user; a different value for the same slot overwrites it.",
            AddFactInput, _writer_tool("add_fact", AddFactInput),
        ),
        ToolSpec(
            "supersede_fact", "Replace a fact's value by id after the user confirms, clearing any conflict.",
            SupersedeFactInput, _writer_tool("supersede_fact", SupersedeFactInput),
        ),
        ToolSpec(
            "log_episode", "Store a conversation as a new episode.",
            LogEpisodeInput, _writer_tool("log_episode", LogEpisodeInput),
        ),
        ToolSpec(
            "update_project", "Create a project, or add a note, episodes or a status to one.",
            UpdateProjectInput, _writer_tool("update_project", UpdateProjectInput),
        ),
        ToolSpec(
            "add_skill", "Create a skill, or update the skill with the same name.",
            AddSkillInput, _writer_tool("add_skill", AddSkillInput),
        ),
        ToolSpec(
            "update_working_memory", "Set the goal and append decisions or open questions of a session.",
            UpdateWorkingMemoryInput, _update_working_memory,
        ),
    )
}


def _signature(spec: ToolSpec) -> inspect.Signature:
    """Build the keyword-only signature whose pydantic model matches the contract model's fields."""
    params = []
    fields = spec.model.model_fields if spec.model else {}
    for name, field in fields.items():
        if name in spec.hidden_fields:
            continue
        annotation = Annotated[(field.annotation, *field.metadata)] if field.metadata else field.annotation
        if field.is_required():
            default = inspect.Parameter.empty
        else:
            default = field.get_default(call_default_factory=True)
            if default is PydanticUndefined:  # pragma: no cover - defensive
                default = None
        params.append(
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, default=default, annotation=annotation)
        )
    return inspect.Signature(params, return_annotation=CallToolResult)


def make_tool(spec: ToolSpec, bound: Binding) -> Callable[..., Any]:
    """Wrap a handler as an async tool function with the contract model's parameters.

    Behavior:
        The handler runs in a worker thread because the core calls block on git, sqlite and the
        vault lock. Failures a handler raises as `PamError` come back as error results, never as
        exceptions.
    Returns:
        A callable ready for `MCPServer.add_tool`.
    Parameters:
        spec: The tool definition.
        bound: The vault and agent the tool acts for.
    """

    async def tool(**kwargs: Any) -> CallToolResult:
        def run() -> CallToolResult:
            try:
                return spec.handler(bound, kwargs)
            except NotAvailable as exc:
                return _unavailable(spec, exc)
            except PermissionDenied as exc:
                return _failure(f"{DENIED} {exc}")
            except PamError as exc:
                return _failure(str(exc))

        return await anyio.to_thread.run_sync(run)

    tool.__name__ = spec.name
    tool.__doc__ = spec.description
    tool.__signature__ = _signature(spec)  # type: ignore[attr-defined]
    return tool


def _unavailable(spec: ToolSpec, exc: NotAvailable) -> CallToolResult:
    message = str(exc)
    if spec.name in WRITE_TOOLS:
        return _write_result(WriteResult(ok=False, action=spec.name, message=message))
    return _failure(message)
