"""M13 REST API: extra route and error-mapping tests written during T14 (SPEC §7.14, CHG-0022).

Behavior:
    Covers what `test_m13_api.py` does not: import validation and failed jobs, unknown agents and
    sessions, the 409 and 500 mappings, persona Custom sections, tool-mode chat and the SSE
    terminal-event promise. Fixtures and helpers come from `test_m13_api.py`.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from pam.api.app import create_app
from pam.contracts.reports import JobStatus

from .test_m13_api import (  # noqa: F401 - fixtures are used by name
    CHATGPT_EXPORT,
    _error,
    _events,
    _install_fake_llm,
    _make_agent,
    client,
    vault,
)


def _wait(client: TestClient, job: JobStatus) -> JobStatus:
    deadline = time.monotonic() + 30
    while job.stage not in {"done", "error"} and time.monotonic() < deadline:
        time.sleep(0.05)
        job = JobStatus.model_validate(client.get(f"/api/imports/{job.job_id}").json())
    return job


def _manifest(name: str) -> dict:
    return {
        "name": name, "display_name": name.title(), "description": "", "origin": "custom",
        "created_at": datetime.now(UTC).isoformat(), "read": {"all": False}, "write": "own",
        "tools": ["get_context"], "token_budget": 2000,
    }


def _chat(client: TestClient, **body) -> list[tuple[str, dict]]:
    response = client.post("/api/chat", json={"model": "test/model", "message": "hello", **body})
    assert response.status_code == 200, response.text
    return _events(response.text)


def _assert_one_terminal(events: list[tuple[str, dict]]) -> None:
    names = [name for name, _ in events]
    assert names[0] == "context"
    assert names[-1] in {"done", "error"}
    assert sum(name in {"done", "error"} for name in names) == 1


# -- imports ------------------------------------------------------------------------------------


def test_import_rejects_unknown_source_and_agent(client):
    files = {"file": ("export.zip", CHATGPT_EXPORT.read_bytes(), "application/zip")}
    _error(client.post("/api/imports", files=files, data={"source": "bing"}), 400)
    _error(client.post("/api/imports", files=files, data={"agent": "nobody"}), 404)


def test_import_rejects_empty_upload(client):
    _error(client.post("/api/imports", files={"file": ("export.zip", b"", "application/zip")}), 400)


def test_import_job_with_unreadable_export_ends_in_error_stage(client):
    response = client.post("/api/imports", files={"file": ("export.zip", b"not a zip", "application/zip")})
    job = _wait(client, JobStatus.model_validate(response.json()))
    assert job.stage == "error"
    assert job.error
    assert job.report is None


def test_import_archives_under_the_basename_only(client):
    data = CHATGPT_EXPORT.read_bytes()
    response = client.post("/api/imports", files={"file": ("../../evil.zip", data, "application/zip")})
    job = _wait(client, JobStatus.model_validate(response.json()))
    assert job.stage == "done", job.error
    assert job.report.archived_path.endswith("/evil.zip")
    assert ".." not in job.report.archived_path


# -- scope and paths ----------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/vault/tree", "/api/graph"])
def test_unknown_agent_is_404(client, path):
    _error(client.get(path, params={"agent": "nobody"}), 404)


def test_invalid_agent_name_is_400(client):
    _error(client.get("/api/graph", params={"agent": "Bad Name!"}), 400)


@pytest.mark.parametrize("path", [".git/config", "pam.toml", "memory/../pam.toml", "agent/default/.hidden.md"])
def test_vault_file_only_serves_visible_markdown(client, path):
    assert client.get("/api/vault/file", params={"path": path}).status_code == 400


def test_vault_file_reads_persona_without_frontmatter(client):
    payload = client.get("/api/vault/file", params={"path": "agent/default/identity.md"}).json()
    assert payload["frontmatter"] == {}
    assert "## Custom" in payload["body"]


def test_restricted_agent_tree_hides_other_scopes(client, vault):
    _make_agent(vault, "narrow", include_shared_facts=False)
    paths = client.get("/api/vault/tree", params={"agent": "narrow"}).json()["paths"]
    assert paths
    assert all(p.startswith(("agent/narrow/", "memory/narrow/")) for p in paths)


# -- error shapes -------------------------------------------------------------------------------


def test_unknown_route_and_bad_body_use_the_error_shape(client):
    _error(client.get("/api/nope"), 404)
    error = _error(client.post("/api/search", json={}), 400)
    assert "query" in error["message"]


def test_unexpected_exception_is_a_generic_500(vault, monkeypatch):
    from pam.api.routes import sync as sync_routes  # noqa: PLC0415

    def boom(_):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(sync_routes, "sync", boom)
    quiet = TestClient(create_app(vault.root), raise_server_exceptions=False)
    response = quiet.post("/api/sync")
    assert _error(response, 500)["code"] == "INTERNAL_ERROR"
    assert "secret detail" not in response.text


# -- agents -------------------------------------------------------------------------------------


def test_agent_custom_sections_round_trip_and_derived_is_kept(client, vault):
    body = {"manifest": _manifest("writer"), "identity_custom": "Writes docs.", "rules_custom": "- Be brief\n",
            "style_custom": "Plain."}
    assert client.post("/api/agents", json=body).status_code == 201
    persona = client.get("/api/agents/writer").json()["persona"]
    assert persona["identity"].split("## Custom", 1)[1].endswith("Writes docs.\n")
    assert [r["text"] for r in persona["rules"] if r["origin"] == "manual"] == ["Be brief"]
    derived = vault.persona_path("writer", "identity").read_text(encoding="utf-8").split("## Custom", 1)[0]

    body["identity_custom"] = "Writes release notes."
    assert client.put("/api/agents/writer", json=body).status_code == 200
    text = vault.persona_path("writer", "identity").read_text(encoding="utf-8")
    assert text.split("## Custom", 1)[0] == derived
    assert text.rstrip().endswith("Writes release notes.")


def test_agent_update_without_changes_makes_no_commit(client, vault):
    from pam.sync import git  # noqa: PLC0415

    body = {"manifest": _manifest("same"), "identity_custom": "", "rules_custom": "", "style_custom": ""}
    assert client.post("/api/agents", json=body).status_code == 201
    head = git.head_sha(vault.root)
    assert client.put("/api/agents/same", json=body).status_code == 200
    assert git.head_sha(vault.root) == head


def test_agent_write_errors(client):
    body = {"manifest": _manifest("dup"), "identity_custom": "", "rules_custom": "", "style_custom": ""}
    assert client.post("/api/agents", json=body).status_code == 201
    _error(client.post("/api/agents", json=body), 409)
    _error(client.put("/api/agents/other", json=body), 400)
    _error(client.put("/api/agents/ghost", json={**body, "manifest": _manifest("ghost")}), 404)
    _error(client.get("/api/agents/ghost"), 404)


# -- sessions and chat --------------------------------------------------------------------------


def test_chat_continues_a_session_and_end_is_not_repeatable(client, monkeypatch):
    _install_fake_llm(monkeypatch, "one")
    first = _chat(client)
    _assert_one_terminal(first)
    session_id = first[-1][1]["session_id"]
    _install_fake_llm(monkeypatch, "two")
    second = _chat(client, session_id=session_id, message="and then?")
    _assert_one_terminal(second)
    assert second[-1][1]["session_id"] == session_id
    turns = client.get(f"/api/sessions/{session_id}").json()["recent_turns"]
    assert [t["role"] for t in turns] == ["user", "assistant", "user", "assistant"]
    assert client.post(f"/api/sessions/{session_id}/end").status_code == 200
    assert _error(client.post(f"/api/sessions/{session_id}/end"), 409)["code"] == "SESSION_ENDED"
    ended = client.post("/api/chat", json={"model": "test/model", "message": "hi", "session_id": session_id})
    assert _error(ended, 409)["code"] == "SESSION_ENDED"


def test_unknown_session_is_404(client):
    _error(client.get("/api/sessions/s_missing00000"), 404)
    _error(client.post("/api/sessions/s_missing00000/end"), 404)
    unknown = client.post("/api/chat", json={"model": "test/model", "message": "hi", "session_id": "s_missing00000"})
    _error(unknown, 404)


def test_chat_agent_mismatch_is_400(client, vault, monkeypatch):
    _install_fake_llm(monkeypatch, "ok")
    session_id = _chat(client)[-1][1]["session_id"]
    _make_agent(vault, "other")
    mismatch = client.post(
        "/api/chat", json={"model": "test/model", "message": "hi", "session_id": session_id, "agent": "other"}
    )
    _error(mismatch, 400)


def test_chat_tool_mode_streams_and_ends_with_done(client, monkeypatch):
    _install_fake_llm(monkeypatch, "tools ready")
    events = _chat(client, mode="tool")
    _assert_one_terminal(events)
    assert events[-1][0] == "done"
    assert "".join(p["text"] for n, p in events if n == "token") == "tools ready"


def test_chat_validation_errors_are_400(client):
    _error(client.post("/api/chat", json={"model": "test/model", "message": ""}), 400)
    _error(client.post("/api/chat", json={"model": "test/model", "message": "x", "mode": "bogus"}), 400)


def test_chat_provider_failure_after_context_is_a_stream_error(client, monkeypatch):
    from pam.chat.llm import LLMError  # noqa: PLC0415

    _install_fake_llm(monkeypatch, "partial ", LLMError("bad key", retryable=False))
    events = _chat(client)
    _assert_one_terminal(events)
    assert events[-1][0] == "error"
    assert events[-1][1]["retryable"] is False


# -- sync ---------------------------------------------------------------------------------------


def test_sync_commits_outside_edits_and_status_reports_pending(client, vault):
    (vault.root / "outside-edit.md").write_text("edited outside PAM\n", encoding="utf-8")
    assert client.get("/api/sync/status").json()["dirty_paths"] == ["outside-edit.md"]
    report = client.post("/api/sync").json()
    assert report["dirty_paths"] == ["outside-edit.md"]
    assert report["commit_sha"]
    assert client.get("/api/sync/status").json()["dirty_paths"] == []


def test_health_index_ok_follows_the_index_file(client, vault):
    assert client.get("/api/health").json()["index_ok"] is True
    vault.index_db.unlink()
    assert client.get("/api/health").json()["index_ok"] is False
