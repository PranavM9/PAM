"""M13 REST API tests, written before T14 (SPEC §7.14, §8 M13, §9.3 T14).

Behavior:
    Exercises the REST endpoints, import jobs, SSE stream, error mapping, and MCP mount.
    The module skips until `pam.api.app` exists; endpoint tests also skip until their
    backing modules exist.

Pinned API:
    `pam.api.app.create_app(vault_path) -> FastAPI`
    `POST /api/chat` emits `ChatEvent` SSE frames, starting with `context` and ending
    with exactly one `done` or `error` event.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

app_mod = pytest.importorskip("pam.api.app")

from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from pam.cli.main import app as cli_app  # noqa: E402
from pam.core.vault import Vault, init_vault  # noqa: E402

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_EXPORT = FIXTURES / "claude" / "export.zip"
CHATGPT_EXPORT = FIXTURES / "chatgpt" / "export.zip"


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """Create a temporary vault populated with the Claude fixture, derived and indexed.

    Setup added for B-03: the `test/model` entry (committed) and the derive and index steps that the
    search, context, graph and chat tests rely on.
    """
    from pam.contracts.config import ModelEntry  # noqa: PLC0415
    from pam.core import config  # noqa: PLC0415
    from pam.sync import git  # noqa: PLC0415

    root = tmp_path / "vault"
    init_vault(root)
    for args in (["import", "run", str(CLAUDE_EXPORT)], ["derive"], ["index"]):
        result = runner.invoke(cli_app, ["--vault", str(root), *args])
        assert result.exit_code == 0, result.output
    created = Vault(root)
    cfg = config.load(created)
    cfg = cfg.model_copy(update={"models": [ModelEntry(id="test/model", label="Test model", supports_tools=True)]})
    created.config_path.write_text(config.dump_toml(cfg), encoding="utf-8")
    git.commit(root, [created.config_path], "test: add test/model")
    return created


def _make_agent(vault: Vault, name: str, **read) -> None:
    """Create an agent with a restricted read scope (setup for the scope and permission tests)."""
    from pam.agents.manifest import create_agent  # noqa: PLC0415
    from pam.contracts.agent import AgentManifest, ReadScope  # noqa: PLC0415

    manifest = AgentManifest(
        name=name, display_name=name.title(), origin="custom", created_at=datetime.now(UTC),
        read=ReadScope(all=False, **read), write="own", tools=["get_context"],
    )
    create_agent(manifest, vault)


def _install_fake_llm(monkeypatch, *steps) -> None:
    """Replace the provider call: text steps stream as tokens, an exception step is raised."""
    from pam.chat import llm, orchestrator  # noqa: PLC0415

    async def fake(model, messages, tools=None):
        for step in steps:
            if isinstance(step, Exception):
                raise step
            yield llm.LLMDelta(text=step)
        yield llm.LLMDelta(finish_reason="stop")

    monkeypatch.setattr(orchestrator, "stream_chat", fake)


@pytest.fixture
def client(vault: Vault):
    """Create a test client for an initialized fixture vault."""
    return TestClient(app_mod.create_app(vault.root))


def _error(response, status: int) -> dict:
    assert response.status_code == status
    payload = response.json()
    assert set(payload) == {"error"}
    assert set(payload["error"]) == {"code", "message"}
    assert isinstance(payload["error"]["code"], str)
    assert isinstance(payload["error"]["message"], str)
    return payload["error"]


def _events(body: str) -> list[tuple[str, dict]]:
    events = []
    for frame in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
        events.append((fields["event"], json.loads(fields["data"])))
    return events


def test_health_reports_vault_and_index_status(client, vault):
    response = client.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["vault"] == str(vault.root)
    assert isinstance(payload["index_ok"], bool)


def test_import_job_runs_to_completion(client):
    response = client.post(
        "/api/imports",
        files={"file": ("export.zip", CHATGPT_EXPORT.read_bytes(), "application/zip")},
    )
    assert response.status_code in (200, 202)
    from pam.contracts.reports import JobStatus  # noqa: PLC0415

    status = JobStatus.model_validate(response.json())
    assert status.stage in {"queued", "extract", "normalize", "derive", "index", "cluster", "done"}
    seen_progress = status.progress
    deadline = time.monotonic() + 30
    while status.stage not in {"done", "error"} and time.monotonic() < deadline:
        time.sleep(0.05)
        poll = client.get(f"/api/imports/{status.job_id}")
        assert poll.status_code == 200
        status = JobStatus.model_validate(poll.json())
        assert status.progress >= seen_progress
        assert 0 <= status.progress <= 1
        seen_progress = status.progress
    assert status.stage == "done", status.error
    assert status.report is not None
    assert status.report.episodes_written == 5


def test_unknown_import_job_returns_404_error(client):
    _error(client.get("/api/imports/unknown-job-id"), 404)


def test_vault_tree_returns_posix_paths(client):
    payload = client.get("/api/vault/tree").json()
    assert isinstance(payload["paths"], list)
    assert payload["paths"]
    assert all(isinstance(path, str) and "\\" not in path for path in payload["paths"])


def test_vault_tree_respects_agent_scope(client, vault):
    pytest.importorskip("pam.agents.permissions")
    _make_agent(vault, "research")
    response = client.get("/api/vault/tree", params={"agent": "research"})
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert all("memory/default/" not in path for path in paths)


def test_vault_file_returns_frontmatter_and_body(client, vault):
    paths = list((vault.root / "memory" / "default" / "episodes").glob("*.md"))  # §6 layout; was episodes/default
    assert paths
    relative = paths[0].relative_to(vault.root).as_posix()
    response = client.get("/api/vault/file", params={"path": relative})
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == relative
    assert isinstance(payload["frontmatter"], dict)
    assert isinstance(payload["body"], str)


@pytest.mark.parametrize("path", ["../x", "../../.env", "C:\\Windows\\win.ini", "/etc/passwd"])
def test_vault_file_rejects_paths_outside_vault(client, path):
    response = client.get("/api/vault/file", params={"path": path})
    assert response.status_code in (400, 404)
    assert "root:" not in response.text


def test_search_returns_contract_response(client):
    pytest.importorskip("pam.retrieve.search")
    from pam.contracts.retrieval import SearchResponse  # noqa: PLC0415

    response = client.post("/api/search", json={"query": "work"})
    assert response.status_code == 200
    result = SearchResponse.model_validate(response.json())
    assert result.query == "work"


def test_search_rejects_invalid_query_with_error_shape(client):
    pytest.importorskip("pam.retrieve.search")
    _error(client.post("/api/search", json={"query": "work", "k": 0}), 400)


def test_context_returns_contract_and_honors_budget(client):
    pytest.importorskip("pam.retrieve.context")
    from pam.contracts.retrieval import ContextBundle  # noqa: PLC0415

    response = client.post("/api/context", json={"query": "What am I working on?", "token_budget": 512})
    assert response.status_code == 200
    bundle = ContextBundle.model_validate(response.json())
    assert bundle.tokens_used <= bundle.token_budget <= 512


def test_graph_links_reference_existing_nodes(client):
    pytest.importorskip("pam.cluster.graph")
    from pam.contracts.graph import GraphData  # noqa: PLC0415

    response = client.get("/api/graph", params={"agent": "default"})
    assert response.status_code == 200
    graph = GraphData.model_validate(response.json())
    node_ids = {node.id for node in graph.nodes}
    assert all(link.source in node_ids and link.target in node_ids for link in graph.links)


def test_graph_facts_query_includes_fact_nodes(client):
    pytest.importorskip("pam.cluster.graph")
    with_facts = client.get("/api/graph", params={"agent": "default", "facts": "true"})
    without_facts = client.get("/api/graph", params={"agent": "default", "facts": "false"})
    assert with_facts.status_code == without_facts.status_code == 200
    assert any(node["type"] == "fact" for node in with_facts.json()["nodes"])
    assert not any(node["type"] == "fact" for node in without_facts.json()["nodes"])


def test_agent_list_and_detail(client):
    pytest.importorskip("pam.agents.manifest")
    listed = client.get("/api/agents")
    assert listed.status_code == 200
    assert any(item["name"] == "default" for item in listed.json())
    detail = client.get("/api/agents/default")
    assert detail.status_code == 200
    assert detail.json()["manifest"]["name"] == "default"
    assert {"identity", "rules", "style"} <= set(detail.json()["persona"])


def test_agent_create_update_and_reserved_name(client):
    pytest.importorskip("pam.agents.manifest")
    manifest = {
        "name": "research",
        "display_name": "Research",
        "description": "Research agent",
        "origin": "custom",
        "created_at": datetime.now(UTC).isoformat(),
        "read": {"all": False},
        "write": "own",
        "tools": ["get_context"],
        "token_budget": 2000,
    }
    create = client.post("/api/agents", json={
        "manifest": manifest,
        "identity_custom": "Research identity",
        "rules_custom": "Research rules",
        "style_custom": "Research style",
    })
    assert create.status_code in (200, 201)
    assert create.json()["name"] == "research"
    update = client.put("/api/agents/research", json={
        "manifest": {**manifest, "description": "Updated research agent"},
        "identity_custom": "Updated identity",
        "rules_custom": "Updated rules",
        "style_custom": "Updated style",
    })
    assert update.status_code == 200
    assert update.json()["description"] == "Updated research agent"
    invalid = client.post("/api/agents", json={
        "manifest": {**manifest, "name": "shared"},
        "identity_custom": "",
        "rules_custom": "",
        "style_custom": "",
    })
    assert invalid.status_code == 400


def test_models_returns_configured_entries(client, vault):
    from pam.contracts.config import ModelEntry  # noqa: PLC0415

    models = client.get("/api/models")
    assert models.status_code == 200
    assert all(ModelEntry.model_validate(item) for item in models.json())


def test_chat_sse_event_order_and_token_content(client, monkeypatch):
    pytest.importorskip("pam.chat.orchestrator")
    from pam.contracts.api import ChatRequest  # noqa: PLC0415

    _install_fake_llm(monkeypatch, "fake ", "response")
    assert ChatRequest.model_validate({"model": "test/model", "message": "hello"})
    response = client.post("/api/chat", json={"model": "test/model", "message": "hello"})
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    events = _events(response.text)
    assert events[0][0] == "context"
    terminal = [i for i, (name, _) in enumerate(events) if name in {"done", "error"}]
    assert len(terminal) == 1 and terminal[0] == len(events) - 1
    assert "".join(payload["text"] for name, payload in events if name == "token") == "fake response"


def test_chat_unknown_model_is_rejected_before_stream(client):
    pytest.importorskip("pam.chat.orchestrator")
    _error(client.post("/api/chat", json={"model": "unknown/model", "message": "hello"}), 400)


def test_chat_provider_rate_limit_ends_with_retryable_error(client, monkeypatch):
    pytest.importorskip("pam.chat.orchestrator")
    from pam.chat.llm import LLMError  # noqa: PLC0415

    _install_fake_llm(monkeypatch, LLMError("RateLimitError: slow down", retryable=True))
    response = client.post("/api/chat", json={"model": "test/model", "message": "hello"})
    assert response.status_code == 200
    events = _events(response.text)
    assert events[0][0] == "context"
    assert events[-1][0] == "error"
    assert events[-1][1]["retryable"] is True


def test_session_get_and_end_return_contracts(client, vault, monkeypatch):
    pytest.importorskip("pam.working.session")
    from pam.contracts.working import WorkingMemory  # noqa: PLC0415
    from pam.contracts.writes import WriteResult  # noqa: PLC0415
    from pam.working import session  # noqa: PLC0415

    session_id = "s_0123456789ab"
    monkeypatch.setattr(session, "_new_id", lambda: session_id)
    session.start(vault, "default", "test/model")
    session.record_turn(vault, session_id, "user", "hello", "test/model")
    current = client.get(f"/api/sessions/{session_id}")
    assert current.status_code == 200
    WorkingMemory.model_validate(current.json())
    ended = client.post(f"/api/sessions/{session_id}/end")
    assert ended.status_code == 200
    result = WriteResult.model_validate(ended.json())
    assert result.ok and result.doc_id is not None


def test_sync_post_and_status_return_contracts(client):
    pytest.importorskip("pam.sync.watcher")
    from pam.contracts.reports import SyncReport  # noqa: PLC0415

    response = client.post("/api/sync")
    assert response.status_code == 200
    SyncReport.model_validate(response.json())
    status = client.get("/api/sync/status")
    assert status.status_code == 200
    SyncReport.model_validate(status.json())


@pytest.mark.parametrize(("module", "status"), [
    ("pam.agents.permissions", 403),
    ("pam.core.errors", 409),
    ("pam.core.errors", 404),
])
def test_permission_busy_and_missing_errors_have_standard_shape(client, vault, module, status):
    pytest.importorskip(module)
    if status == 403:
        _make_agent(vault, "restricted", include_shared_facts=False)
        response = client.get("/api/vault/file", params={"path": "memory/shared/facts/denied.md", "agent": "restricted"})
    elif status == 409:
        from pam.core.lock import vault_write_lock  # noqa: PLC0415

        (vault.root / "outside-edit.md").write_text("edited outside PAM\n", encoding="utf-8")
        with vault_write_lock(vault, timeout=0):
            response = client.post("/api/sync")
    else:
        response = client.get("/api/vault/file", params={"path": "episodes/default/missing.md"})
    _error(response, status)


def test_cors_preflight_allows_frontend_origin(client):
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_openapi_lists_every_rest_endpoint(client):
    paths = client.get("/openapi.json").json()["paths"]
    expected = {
        "/api/health", "/api/imports", "/api/imports/{job_id}", "/api/vault/tree",
        "/api/vault/file", "/api/search", "/api/context", "/api/graph", "/api/agents",
        "/api/agents/{name}", "/api/models", "/api/chat", "/api/sessions/{id}",
        "/api/sessions/{id}/end", "/api/sync", "/api/sync/status",
    }
    assert expected <= set(paths)
    assert client.get("/docs").status_code == 200


def test_mcp_is_mounted_on_app(client):
    response = client.get("/mcp")
    assert response.status_code != 404



def test_idle_sweep_ends_session_and_creates_episode(client, vault, monkeypatch):
    from datetime import timedelta  # noqa: PLC0415

    from pam.core import config  # noqa: PLC0415
    from pam.working import session  # noqa: PLC0415

    cfg = config.load(vault).model_copy(update={"session_idle_minutes": 1})
    vault.config_path.write_text(config.dump_toml(cfg), encoding="utf-8")
    sid = session.start(vault, "default", "test/model").session_id
    session.record_turn(vault, sid, "user", "hello", "test/model")
    assert app_mod.end_idle_once(vault) == 0
    real = session.utcnow
    monkeypatch.setattr(session, "utcnow", lambda: real() + timedelta(minutes=5))
    assert app_mod.end_idle_once(vault) == 1
    body = client.get(f"/api/sessions/{sid}").json()
    assert body["status"] == "ended" and body["promoted_episode_id"]


def test_sweeper_runs_with_app_lifespan(vault, monkeypatch):
    import threading  # noqa: PLC0415

    ran = threading.Event()
    monkeypatch.setattr(app_mod, "end_idle_once", lambda root: ran.set() or 0)
    with TestClient(app_mod.create_app(vault.root)):
        assert ran.wait(5)
