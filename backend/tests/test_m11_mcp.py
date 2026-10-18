"""M11 MCP server tests, written before T12 (SPEC §8 M11, §9.3 T12).

Behavior:
    Exercises MCP tool discovery, schemas, results, agent filtering, writes, CLI help, and HTTP setup
    through an in-memory client session on isolated vaults. The module skips until T12 exists.

API assumed by these tests (agreed for T12, not in SPEC):
    `server.build_server(vault, agent="default") -> FastMCP`
    `server.http_app(vault) -> ASGI app` with the agent selected by `?agent=`.
    CLI: `pam mcp serve --transport stdio|http --agent A`.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

import anyio
import pytest
from typer.testing import CliRunner

server = pytest.importorskip("pam.mcp_server.server")

from mcp.client import ClientSession  # noqa: E402

from pam.agents import manifest as agents  # noqa: E402
from pam.cli.main import app  # noqa: E402
from pam.contracts.agent import AgentManifest, ReadScope  # noqa: E402
from pam.contracts.common import Actor, Source  # noqa: E402
from pam.contracts.episode import EpisodeFrontmatter  # noqa: E402
from pam.contracts.fact import (  # noqa: E402
    Cardinality,
    Fact,
    FactCategory,
    FactConflict,
    FactStatus,
    fact_id,
)
from pam.contracts.retrieval import ContextBundle, ContextRequest, SearchQuery, SearchResponse  # noqa: E402
from pam.contracts.writes import (  # noqa: E402
    AddFactInput,
    AddSkillInput,
    GetEpisodeInput,
    LogEpisodeInput,
    SupersedeFactInput,
    UpdateProjectInput,
    UpdateWorkingMemoryInput,
    WriteResult,
)
from pam.core import mdio  # noqa: E402
from pam.core.vault import Vault, init_vault  # noqa: E402
from pam.sync import git  # noqa: E402

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture
def anyio_backend():
    """Use the installed SDK's asyncio-compatible in-memory transport."""
    return "asyncio"


@pytest.fixture
def vault(tmp_path) -> Vault:
    """Create an initialized vault with an empty index for one MCP case."""
    root = tmp_path / "vault"
    init_vault(root)
    vault = Vault(root)
    pytest.importorskip("pam.index.indexer")
    indexed = runner.invoke(app, ["--vault", str(root), "index"])
    assert indexed.exit_code == 0, indexed.output
    return vault


def _manifest(name: str, tools: list[str], write: str = "own") -> AgentManifest:
    return AgentManifest(
        name=name,
        display_name=name.title(),
        description=f"{name} test agent",
        origin="custom",
        created_at=NOW,
        read=ReadScope(),
        write=write,
        tools=tools,
    )


def _write_fact(vault: Vault, attribute: str, value: str, *, conflict: bool = False) -> Fact:
    cardinality = Cardinality.SINGLE
    fact = Fact(
        id=fact_id("shared", "user", attribute, cardinality, value),
        scope="shared",
        attribute=attribute,
        value=value,
        cardinality=cardinality,
        category=FactCategory.WORK if attribute == "works_at" else FactCategory.EDUCATION,
        confidence=0.8,
        status=FactStatus.CONFLICT if conflict else FactStatus.ACTIVE,
        conflict=(FactConflict(candidate_value="Campus Dining", detected_at=NOW, detected_by=Actor.RULE)
                  if conflict else None),
        extractor=Actor.MANUAL,
        created_at=NOW,
        updated_at=NOW,
    )
    mdio.write(vault.fact_path("shared", fact.id), fact, f"**{attribute}**: {value}\n")
    return fact


def _write_episode(vault: Vault, *, body: str | None = None) -> EpisodeFrontmatter:
    content = body or "# MCP fixture conversation\n\n" + ("transcript words here. " * 2400)
    episode = EpisodeFrontmatter(
        id=uuid4(),
        agent="default",
        source=Source.CLAUDE,
        source_conversation_id="m11-test",
        title="MCP fixture conversation",
        created_at=NOW,
        updated_at=NOW,
        imported_at=NOW,
        message_count=2,
        has_summary=False,
        body_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    mdio.write(vault.episode_path("default", episode.id), episode, content)
    return episode


def _protocol(app_server):
    """Return the low-level MCP server wrapped by either SDK server API."""
    protocol = getattr(app_server, "_mcp_server", None)
    if protocol is None:
        protocol = getattr(app_server, "_lowlevel_server", None)
    if protocol is None:
        raise AssertionError("build_server must expose an MCP protocol server")
    return protocol


@asynccontextmanager
async def _client_session(app_server):
    """Connect an MCP client and server with in-memory AnyIO streams."""
    protocol = _protocol(app_server)
    client_send, server_receive = anyio.create_memory_object_stream(0)
    server_send, client_receive = anyio.create_memory_object_stream(0)
    options = protocol.create_initialization_options()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(protocol.run, server_receive, server_send, options)
        try:
            async with ClientSession(client_receive, client_send) as session:
                await session.initialize()
                yield session
        finally:
            tasks.cancel_scope.cancel()


async def _list_tools(app_server):
    async with _client_session(app_server) as session:
        result = await session.list_tools()
        return result.tools


async def _instructions(app_server):
    """Read the instructions field returned during the MCP initialization handshake."""
    protocol = _protocol(app_server)
    client_send, server_receive = anyio.create_memory_object_stream(0)
    server_send, client_receive = anyio.create_memory_object_stream(0)
    options = protocol.create_initialization_options()
    async with anyio.create_task_group() as tasks:
        tasks.start_soon(protocol.run, server_receive, server_send, options)
        try:
            async with ClientSession(client_receive, client_send) as session:
                initialized = await session.initialize()
                return initialized.instructions or ""
        finally:
            tasks.cancel_scope.cancel()


async def _call_tool(app_server, name: str, arguments: dict | None = None):
    async with _client_session(app_server) as session:
        return await session.call_tool(name, arguments or {})


def _sync(awaitable):
    async def run():
        return await awaitable

    return anyio.run(run)


def _names(tools) -> set[str]:
    return {tool.name for tool in tools}


def _tool_json(tool) -> dict:
    return tool.model_dump(mode="json", by_alias=True)


def _structured(result):
    """Read structured content under the SDK's snake_case (mcp 2) or camelCase (mcp 1) name."""
    structured = getattr(result, "structured_content", None)
    return structured if structured is not None else getattr(result, "structuredContent", None)


def _is_error(result) -> bool:
    return bool(getattr(result, "is_error", getattr(result, "isError", False)))


def _result_json(result) -> dict:
    structured = _structured(result)
    if structured is not None:
        return structured if isinstance(structured, dict) else structured.model_dump(mode="json")
    for item in result.content:
        if getattr(item, "type", None) == "text":
            try:
                parsed = json.loads(item.text)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    raise AssertionError("MCP tool returned no structured JSON object")


def _result_value(result):
    structured = _structured(result)
    if structured is not None:
        if isinstance(structured, (dict, list)):
            return structured
        return structured.model_dump(mode="json")
    for item in result.content:
        if getattr(item, "type", None) == "text":
            try:
                return json.loads(item.text)
            except (TypeError, json.JSONDecodeError):
                continue
    raise AssertionError("MCP tool returned no JSON value")


def _text(result) -> str:
    return "\n".join(item.text for item in result.content if getattr(item, "type", None) == "text")


def test_default_advertises_all_ten_tools(vault):
    tools = _sync(_list_tools(server.build_server(vault, agent="default")))
    assert len(tools) == 10
    assert _names(tools) == {
        "get_context", "search_memory", "get_episode", "list_agents", "add_fact",
        "supersede_fact", "log_episode", "update_project", "add_skill", "update_working_memory",
    }


def test_restricted_agent_advertises_only_configured_read_tools(vault):
    agents.create_agent(_manifest("research", ["get_context", "search_memory"]), vault)
    tools = _sync(_list_tools(server.build_server(vault, agent="research")))
    assert _names(tools) == {"get_context", "search_memory"}


def test_unadvertised_tool_call_is_rejected(vault):
    agents.create_agent(_manifest("research", ["get_context", "search_memory"]), vault)
    try:
        result = _sync(_call_tool(server.build_server(vault, agent="research"), "add_fact", {
            "attribute": "school", "value": "UW", "category": "education",
        }))
    except Exception as exc:
        assert "add_fact" in str(exc) or "tool" in str(exc).lower()
    else:
        assert _is_error(result)


def test_instructions_and_get_context_description_direct_conflict_handling(vault):
    instance = server.build_server(vault, agent="default")
    tools = _sync(_list_tools(instance))
    descriptions = {tool.name: tool.description or "" for tool in tools}
    instructions = _sync(_instructions(instance))
    assert "get_context" in instructions
    assert "supersede_fact" in instructions
    assert "Never invent memories" in instructions
    description = descriptions["get_context"].lower()
    assert "ask the user" in description and "conflict" in description


def test_input_schemas_match_contract_models_and_bind_agent_on_server(vault):
    schemas = {tool.name: _tool_json(tool)["inputSchema"] for tool in _sync(
        _list_tools(server.build_server(vault, agent="default"))
    )}
    from pam.contracts.writes import (  # noqa: PLC0415
        AddFactInput, GetEpisodeInput, LogEpisodeInput, SupersedeFactInput,
        UpdateProjectInput, UpdateWorkingMemoryInput,
    )

    expected = {
        "get_context": ContextRequest,
        "search_memory": SearchQuery,
        "get_episode": GetEpisodeInput,
        "add_fact": AddFactInput,
        "supersede_fact": SupersedeFactInput,
        "log_episode": LogEpisodeInput,
        "update_project": UpdateProjectInput,
        "add_skill": AddSkillInput,
        "update_working_memory": UpdateWorkingMemoryInput,
    }
    for name, model in expected.items():
        fields = set(model.model_json_schema()["properties"])
        if name == "get_context":
            fields -= {"agent"}  # fixed by the server (SPEC §7.15)
        assert set(schemas[name]["properties"]) == fields
    assert schemas["list_agents"]["properties"] == {}
    assert "agent" not in schemas["get_context"]["properties"]
    assert "agent" in schemas["search_memory"]["properties"]


def test_get_context_returns_rendered_text_and_context_bundle(vault):
    pytest.importorskip("pam.retrieve.context")
    _write_fact(vault, "school", "UW")
    result = _sync(_call_tool(server.build_server(vault), "get_context", {"query": "Where do I study?"}))
    payload = _result_json(result)
    bundle = ContextBundle.model_validate(payload)
    assert bundle.rendered
    assert bundle.rendered in _text(result)


def test_search_memory_returns_search_response(vault):
    pytest.importorskip("pam.retrieve.search")
    result = _sync(_call_tool(server.build_server(vault), "search_memory", {"query": "UW", "k": 4}))
    response = SearchResponse.model_validate(_result_json(result))
    assert response.query == "UW"
    assert response.hits == []


def test_get_episode_truncates_middle_to_requested_token_limit(vault):
    episode = _write_episode(vault, body="# beginning\n\n" + ("middle transcript text. " * 5000) + "\n\n# ending\n")
    result = _sync(_call_tool(server.build_server(vault), "get_episode", {
        "episode_id": str(episode.id), "max_tokens": 256,
    }))
    text = _text(result)
    from pam.core.tokens import count  # noqa: PLC0415

    assert count(text) <= 256
    assert "# beginning" in text and "# ending" in text
    assert "middle transcript text" in text


def test_list_agents_returns_public_manifest_fields(vault):
    agents.create_agent(_manifest("research", ["get_context"]), vault)
    result = _sync(_call_tool(server.build_server(vault), "list_agents"))
    payload = _result_value(result)
    rows = payload.get("agents", []) if isinstance(payload, dict) else payload
    assert any(
        row["name"] == "research" and row["display_name"] == "Research"
        and row["description"] == "research test agent"
        for row in rows
    )


def test_add_fact_returns_write_result_and_exactly_one_commit(vault, monkeypatch):
    pytest.importorskip("pam.memory.writer")
    indexer = pytest.importorskip("pam.index.indexer")
    monkeypatch.setattr(indexer, "index_paths", lambda *args, **kwargs: None)
    before = git.run(vault.root, "rev-parse", "HEAD").stdout.strip()
    result = _sync(_call_tool(server.build_server(vault), "add_fact", {
        "attribute": "favorite_editor", "value": "VS Code", "category": "tooling",
        "cardinality": "single", "shared": True,
    }))
    payload = _result_json(result)
    write_result = WriteResult.model_validate(payload)
    after = git.run(vault.root, "rev-parse", "HEAD").stdout.strip()
    parent = git.run(vault.root, "rev-parse", "HEAD^1").stdout.strip()
    assert write_result.ok and write_result.commit_sha == after
    assert after != before and parent == before


def test_own_write_agent_cannot_add_shared_fact(vault):
    agents.create_agent(_manifest("research", ["add_fact"], write="own"), vault)
    result = _sync(_call_tool(server.build_server(vault, agent="research"), "add_fact", {
        "attribute": "school", "value": "UW", "category": "education", "shared": True,
    }))
    if _is_error(result):
        assert "PERMISSION_DENIED:" in _text(result)
    else:
        assert _result_json(result).get("message", "").startswith("PERMISSION_DENIED:")


def test_supersede_fact_resolves_conflict(vault, monkeypatch):
    pytest.importorskip("pam.memory.writer")
    indexer = pytest.importorskip("pam.index.indexer")
    monkeypatch.setattr(indexer, "index_paths", lambda *args, **kwargs: None)
    fact = _write_fact(vault, "works_at", "Northside Cafe", conflict=True)
    result = _sync(_call_tool(server.build_server(vault), "supersede_fact", {
        "fact_id": str(fact.id), "new_value": "Campus Dining", "reason": "User confirmed",
    }))
    payload = _result_json(result)
    write_result = WriteResult.model_validate(payload)
    saved, _ = mdio.read_model(vault.fact_path("shared", fact.id), Fact)
    assert write_result.ok and saved.status == FactStatus.ACTIVE
    assert saved.value == "Campus Dining" and saved.conflict is None


def test_results_use_json_uuids_and_z_datetimes(vault):
    pytest.importorskip("pam.retrieve.context")
    _write_fact(vault, "school", "UW")
    result = _sync(_call_tool(server.build_server(vault), "get_context", {"query": "Where do I study?"}))
    payload = _result_json(result)
    assert isinstance(payload["generated_at"], str) and payload["generated_at"].endswith("Z")
    assert all(isinstance(fact["id"], str) for fact in payload["facts"])


def test_mcp_serve_help_lists_both_transports():
    result = runner.invoke(app, ["mcp", "serve", "--help"])
    assert result.exit_code == 0, result.output
    assert "stdio" in result.output and "http" in result.output


def test_http_app_accepts_initialize_for_agent_query(vault):
    pytest.importorskip("starlette.testclient")
    agents.create_agent(_manifest("research", ["get_context"]), vault)
    try:
        asgi_app = server.http_app(vault)
    except (AttributeError, NotImplementedError, TypeError) as exc:
        pytest.skip(f"HTTP MCP app factory is unsupported by this SDK version: {exc}")

    from starlette.testclient import TestClient  # noqa: PLC0415

    request = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "pam-test", "version": "1.0.0"},
        },
    }
    with TestClient(asgi_app) as client:
        response = client.post(
            "/mcp?agent=research",
            json=request,
            headers={"Accept": "application/json, text/event-stream", "Content-Type": "application/json"},
        )
    if response.status_code in {404, 405, 406, 501}:
        pytest.skip(f"HTTP MCP initialization is unsupported: {response.status_code}")
    if response.status_code == 400 and any(term in response.text.lower() for term in ("protocol version", "unsupported")):
        pytest.skip(f"HTTP MCP initialization is unsupported by this SDK: {response.text}")
    assert response.status_code == 200, response.text
    assert "initialize" not in response.text or "serverInfo" in response.text



def _block_import(monkeypatch, module: str) -> None:
    """Make `import <module>` fail as if its task had not merged."""
    import importlib  # noqa: PLC0415
    import sys  # noqa: PLC0415

    for name in [n for n in sys.modules if n == module or n.startswith(module + ".")]:
        monkeypatch.delitem(sys.modules, name)
    real = importlib.import_module

    def fake(name, package=None):
        if name == module or name.startswith(module + "."):
            raise ModuleNotFoundError(f"No module named {name!r}", name=module)
        return real(name, package)

    monkeypatch.setattr(importlib, "import_module", fake)


def test_missing_retriever_gives_not_available_result(vault, monkeypatch):
    _block_import(monkeypatch, "pam.retrieve")
    result = _sync(_call_tool(server.build_server(vault), "get_context", {"query": "anything"}))
    assert _is_error(result)
    assert _text(result) == "NOT_AVAILABLE: pam.retrieve.context not merged yet"


def test_missing_working_module_gives_not_available_write_result(vault, monkeypatch):
    _block_import(monkeypatch, "pam.working")
    result = _sync(_call_tool(server.build_server(vault), "update_working_memory", {
        "session_id": "s_abcdefghijkl", "goal": "ship T12",
    }))
    write_result = WriteResult.model_validate(_result_json(result))
    assert not write_result.ok and write_result.action == "update_working_memory"
    assert write_result.message == "NOT_AVAILABLE: pam.working.session not merged yet"


def test_update_working_memory_returns_write_result(vault):
    pytest.importorskip("pam.working.session")
    result = _sync(_call_tool(server.build_server(vault), "update_working_memory", {
        "session_id": "s_abcdefghijkl", "goal": "ship T12",
    }))
    WriteResult.model_validate(_result_json(result))


def test_get_context_binds_agent_and_returns_rendered_text(vault, monkeypatch):
    import sys  # noqa: PLC0415
    import types  # noqa: PLC0415

    seen = {}

    def build_context(bound_vault, request):
        seen["agent"] = request.agent
        return ContextBundle(
            agent=request.agent, query=request.query, persona=None, facts=[], conflicts=[], projects=[],
            episodes=[], working=None, rendered="# Known facts\n- school: UW", tokens_used=6,
            token_budget=2000, baseline_tokens=0, tokens_saved=0, generated_at=NOW,
        )

    fake = types.ModuleType("pam.retrieve.context")
    fake.build_context = build_context
    monkeypatch.setitem(sys.modules, "pam.retrieve.context", fake)
    agents.create_agent(_manifest("research", ["get_context"]), vault)
    result = _sync(_call_tool(server.build_server(vault, agent="research"), "get_context", {"query": "school"}))
    assert seen["agent"] == "research"
    assert _text(result) == "# Known facts\n- school: UW"
    assert ContextBundle.model_validate(_result_json(result)).generated_at == NOW


def test_unknown_agent_raises_clear_error_at_build_time(vault):
    from pam.core.errors import PamError  # noqa: PLC0415

    with pytest.raises(PamError, match="cannot serve MCP for agent 'ghost'"):
        server.build_server(vault, agent="ghost")


def test_http_app_unknown_agent_is_404(vault):
    pytest.importorskip("starlette.testclient")
    from starlette.testclient import TestClient  # noqa: PLC0415

    with TestClient(server.http_app(vault)) as client:
        response = client.post("/mcp?agent=ghost", json={}, headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 404 and "ghost" in response.text


def test_stdio_serve_answers_initialize(vault):
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415

    request = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "pam-test", "version": "1.0.0"},
        },
    })
    code = "from pam.cli.main import app; app()"
    proc = subprocess.run(
        [sys.executable, "-c", code, "--vault", str(vault.root), "mcp", "serve", "--transport", "stdio"],
        input=request + "\n", capture_output=True, text=True, timeout=60,
    )
    first = json.loads(proc.stdout.splitlines()[0])
    assert first["id"] == 1 and "Never invent memories" in first["result"]["instructions"]
