"""M12 chat orchestrator, MCP client and `pam chat` tests (SPEC §8 M12, §7.14, §9.3 T13 rest).

Behavior:
    No network: `orchestrator.stream_chat` is replaced by a scripted fake that records every call.
    The MCP server is the real M11 server, built in-process. Most cases run on an empty `tmp_path`
    vault with a fake `build_context`; the fixture cases import and index the Claude export with
    the offline embedder from `conftest.py` and use the real retriever. Sessions are real M9 sessions.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import subprocess
import typing
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import TypeAdapter
from typer.testing import CliRunner

from pam.agents import manifest as agents
from pam.chat import llm, mcp_client, orchestrator
from pam.chat.mcp_client import McpToolError, open_session
from pam.cli.main import app
from pam.contracts.agent import AgentManifest, ReadScope
from pam.contracts.api import (
    ChatEvent,
    ChatRequest,
    ContextEvent,
    DoneEvent,
    ErrorEvent,
    TokenEvent,
    ToolCallEvent,
)
from pam.contracts.common import Source
from pam.contracts.config import ModelEntry, PamConfig
from pam.contracts.fact import Cardinality, Fact, FactCategory, FactStatus, fact_id
from pam.contracts.retrieval import ContextBundle, EpisodeSnippet, ProjectBrief
from pam.core import tokens
from pam.core.config import dump_toml
from pam.core.errors import PamError, VaultBusy
from pam.core.vault import Vault, init_vault, set_vault_override
from pam.working import session

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
CLAUDE = Path(__file__).parent / "fixtures" / "claude" / "export.zip"
MODEL_A = ModelEntry(id="openrouter/acme/alpha:free", label="Alpha")
MODEL_B = ModelEntry(id="anthropic/claude-x", label="Bravo")
TOOLS_MODEL = ModelEntry(id="openrouter/acme/tooly:free", label="Tooly", supports_tools=True)
RENDERED = "# Agent persona\n\n# Known facts\n- works_at: Acme\n"
ALL_TOOLS = {
    "get_context", "search_memory", "get_episode", "list_agents", "add_fact",
    "supersede_fact", "log_episode", "update_project", "add_skill", "update_working_memory",
}

runner = CliRunner()
EVENTS = TypeAdapter(ChatEvent)


@pytest.fixture(autouse=True)
def _clean_vault_env(monkeypatch):
    monkeypatch.delenv("PAM_VAULT", raising=False)
    set_vault_override(None)
    yield
    set_vault_override(None)


def _init(root: Path) -> Vault:
    init_vault(root)
    v = Vault(root)
    v.config_path.write_text(dump_toml(PamConfig(models=[MODEL_A, MODEL_B, TOOLS_MODEL])), encoding="utf-8")
    return v


@pytest.fixture
def vault(tmp_path) -> Vault:
    """Create an empty vault with three models configured (one supports tools)."""
    return _init(tmp_path / "vault")


@pytest.fixture
def fixture_vault(tmp_path) -> Vault:
    """Create a vault with the Claude export imported and indexed (offline embedder)."""
    v = _init(tmp_path / "vault")
    for args in (["import", "run", str(CLAUDE)], ["index"]):
        result = runner.invoke(app, ["--vault", str(v.root), *args])
        assert result.exit_code == 0, result.output
    return v


# --- fakes -------------------------------------------------------------------------------------


def _fact(attribute: str, value: str) -> Fact:
    return Fact(
        id=fact_id("shared", "user", attribute, Cardinality.SINGLE, value), scope="shared",
        attribute=attribute, value=value, cardinality=Cardinality.SINGLE, category=FactCategory.WORK,
        confidence=0.8, status=FactStatus.ACTIVE, extractor="manual", created_at=NOW, updated_at=NOW,
    )


FACT = _fact("works_at", "Acme")
PROJECT = ProjectBrief(
    id=uuid4(), name="RAG pipeline", keywords=["rag"], status="active", last_activity_at=NOW, summary="s",
)
SNIPPET = EpisodeSnippet(
    episode_id=uuid4(), title="Chunking", source=Source.CLAUDE, created_at=NOW, text="t", chunk_ids=["c1"],
)


@pytest.fixture
def context_calls(monkeypatch):
    """Replace `build_context` with a fixed bundle and record every request it receives."""
    from pam.retrieve import context as context_module

    calls = []

    def build_context(bound_vault, request):
        calls.append(request)
        return ContextBundle(
            agent=request.agent, query=request.query, persona=None, facts=[FACT], conflicts=[FACT],
            projects=[PROJECT], episodes=[SNIPPET], working=None, rendered=RENDERED, tokens_used=17,
            token_budget=2000, baseline_tokens=500, tokens_saved=483, generated_at=NOW,
        )

    monkeypatch.setattr(context_module, "build_context", build_context)
    return calls


class ScriptedLLM:
    """Stand-in for `stream_chat`: one scripted list of deltas (or exceptions) per call."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.calls: list[dict] = []

    async def __call__(self, model, messages, tools=None):
        self.calls.append({"model": model.id, "messages": copy.deepcopy(messages), "tools": tools})
        script = self.rounds.pop(0) if self.rounds else [llm.LLMDelta(text="ok", finish_reason="stop")]
        for item in script:
            if isinstance(item, BaseException):
                raise item
            yield item


@pytest.fixture
def fake_llm(monkeypatch):
    """Install a `ScriptedLLM` as `orchestrator.stream_chat`; call it with the rounds to script."""

    def install(*rounds) -> ScriptedLLM:
        fake = ScriptedLLM(*rounds)
        monkeypatch.setattr(orchestrator, "stream_chat", fake)
        return fake

    return install


def _text(*parts, usage=None):
    deltas = [llm.LLMDelta(text=p) for p in parts]
    deltas.append(llm.LLMDelta(finish_reason="stop", usage=usage))
    return deltas


def _tool_round(*calls, text=None):
    deltas = [llm.LLMDelta(text=text)] if text else []
    deltas.append(llm.LLMDelta(tool_calls=list(calls), finish_reason="tool_calls"))
    return deltas


def _run(req: ChatRequest, vault: Vault, **kwargs) -> list:
    async def collect():
        return [e async for e in orchestrator.run_turn(vault, req, **kwargs)]

    return asyncio.run(collect())


def _req(message="where did I leave off?", model=MODEL_A.id, **kwargs) -> ChatRequest:
    return ChatRequest(message=message, model=model, **kwargs)


def _types(events) -> list[str]:
    return [e.type for e in events]


def _assert_stream_shape(events) -> None:
    """§7.14: the first event is `context`; exactly one `done` or `error`, and it is last."""
    assert events[0].type == "context"
    terminal = [i for i, e in enumerate(events) if e.type in ("done", "error")]
    assert terminal == [len(events) - 1]


def _transcript(vault: Vault, sid: str) -> list[dict]:
    path = session.transcript_path(vault, sid)
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _commit_count(vault: Vault) -> int:
    out = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=vault.root, capture_output=True, text=True)
    return int(out.stdout.strip())


def _manifest(name: str, tools: list[str]) -> AgentManifest:
    return AgentManifest(
        name=name, display_name=name.title(), description=f"{name} test agent", origin="custom",
        created_at=NOW, read=ReadScope(), write="own", tools=tools,
    )


# --- injection mode ----------------------------------------------------------------------------


def test_injection_event_order_and_prompt(vault, context_calls, fake_llm):
    fake = fake_llm(_text("You were ", "wiring RAG.", usage=llm.Usage(120, 7)))
    events = _run(_req(), vault)
    assert _types(events) == ["context", "token", "token", "done"]
    assert "".join(e.text for e in events if isinstance(e, TokenEvent)) == "You were wiring RAG."
    messages = fake.calls[0]["messages"]
    assert messages[0] == {"role": "system", "content": f"{llm.PAM_PREAMBLE}\n\n{RENDERED}"}
    assert messages[-1] == {"role": "user", "content": "where did I leave off?"}
    assert len(messages) == 2  # a new session has no history
    assert fake.calls[0]["tools"] is None
    done = events[-1]
    assert (done.model, done.prompt_tokens, done.completion_tokens) == (MODEL_A.id, 120, 7)


def test_context_event_carries_bundle_numbers_and_unique_doc_ids(vault, context_calls, fake_llm):
    fake_llm(_text("hi"))
    context = _run(_req(), vault)[0]
    assert isinstance(context, ContextEvent)
    assert (context.tokens_used, context.baseline_tokens, context.tokens_saved) == (17, 500, 483)
    assert context.rendered == RENDERED
    assert context.doc_ids == [FACT.id, PROJECT.id, SNIPPET.episode_id]  # fact in facts and conflicts: once


def test_get_context_receives_message_session_and_agent(vault, context_calls, fake_llm):
    fake_llm(_text("hi"))
    events = _run(_req(message="status of RAG?"), vault)
    request = context_calls[0]
    assert (request.query, request.session_id, request.agent) == ("status of RAG?", events[0].session_id, "default")


def test_done_without_provider_usage_has_none(vault, context_calls, fake_llm):
    fake_llm(_text("hi"))
    done = _run(_req(), vault)[-1]
    assert isinstance(done, DoneEvent)
    assert done.prompt_tokens is None and done.completion_tokens is None


def test_new_session_records_user_and_assistant_turns(vault, context_calls, fake_llm):
    fake_llm(_text("Answer ", "text."))
    events = _run(_req(message="Plan the  RAG\nwork"), vault)
    sid = events[0].session_id
    assert all(getattr(e, "session_id", sid) == sid for e in events)
    turns = _transcript(vault, sid)
    assert [(t["role"], t["text"], t["model"]) for t in turns] == [
        ("user", "Plan the  RAG\nwork", MODEL_A.id), ("assistant", "Answer text.", MODEL_A.id),
    ]
    assert session.show(vault, sid).goal == "Plan the RAG work"


def test_hot_swap_follow_up_sees_previous_model_turn(vault, context_calls, fake_llm):
    fake = fake_llm(_text("Use pgvector."), _text("As I said, pgvector."))
    first = _run(_req(message="Which vector store?"), vault)
    sid = first[0].session_id
    second = _run(_req(message="Why that one?", model=MODEL_B.id, session_id=sid), vault)
    assert second[-1].model == MODEL_B.id and second[0].session_id == sid
    messages = fake.calls[1]["messages"]
    assert messages[1:] == [
        {"role": "user", "content": "Which vector store?"},
        {"role": "assistant", "content": "Use pgvector."},
        {"role": "user", "content": "Why that one?"},
    ]
    used = session.show(vault, sid).models_used
    assert [m.to_model for m in used] == [MODEL_A.id, MODEL_B.id]


def test_history_is_recent_turns_without_the_current_one(vault, context_calls, fake_llm):
    fake = fake_llm(*[_text(f"reply {i}") for i in range(6)])
    sid = _run(_req(message="turn 0"), vault)[0].session_id
    for i in range(1, 6):
        _run(_req(message=f"turn {i}", session_id=sid), vault)
    messages = fake.calls[-1]["messages"]
    history = messages[1:-1]
    assert len(history) == 7  # 8 recent turns minus the current user turn
    assert history[0] == {"role": "assistant", "content": "reply 1"}
    assert history[-1] == {"role": "assistant", "content": "reply 4"}
    assert messages[-1] == {"role": "user", "content": "turn 5"}


def test_empty_reply_is_not_recorded(vault, context_calls, fake_llm):
    fake_llm([llm.LLMDelta(finish_reason="stop", usage=llm.Usage(5, 0))])
    events = _run(_req(), vault)
    assert _types(events) == ["context", "done"]
    assert [t["role"] for t in _transcript(vault, events[0].session_id)] == ["user"]


def test_real_get_context_on_an_empty_vault(vault, fake_llm):
    fake = fake_llm(_text("hi"))
    context = _run(_req(), vault)[0]
    assert context.rendered.startswith("# Agent persona")
    assert context.doc_ids == []
    assert context.rendered in fake.calls[0]["messages"][0]["content"]


# --- with the Claude fixture imported and indexed ----------------------------------------------


def test_fixture_context_matches_the_bundle_and_prompt(fixture_vault, fake_llm):
    fake = fake_llm(_text("You were setting up Immich."))
    events = _run(_req(message="Immich photo backup"), fixture_vault)
    _assert_stream_shape(events)
    context = events[0]
    assert context.doc_ids, "the indexed Claude export should contribute documents"
    assert 0 < context.tokens_used <= 2000  # the default agent's token budget
    assert context.tokens_saved == max(0, context.baseline_tokens - context.tokens_used)
    system = fake.calls[0]["messages"][0]["content"]
    assert system.startswith(llm.PAM_PREAMBLE) and context.rendered in system
    assert "Immich" in context.rendered


def test_fixture_hot_swap_carries_the_first_turn(fixture_vault, fake_llm):
    fake = fake_llm(_text("Immich runs on the NAS."), _text("Yes, the NAS from before."))
    sid = _run(_req(message="Immich photo backup"), fixture_vault)[0].session_id
    second = _run(_req(message="where was it running?", model=MODEL_B.id, session_id=sid), fixture_vault)
    _assert_stream_shape(second)
    assert {"role": "assistant", "content": "Immich runs on the NAS."} in fake.calls[1]["messages"]
    assert len(session.show(fixture_vault, sid).models_used) == 2


def test_fixture_tool_mode_calls_get_context(fixture_vault, fake_llm):
    call = llm.ToolCall(id="c1", name="get_context", arguments={"query": "Immich photo backup"})
    fake = fake_llm(_tool_round(call), _text("You use Immich."))
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), fixture_vault)
    assert _types(events) == ["context", "tool_call", "token", "done"]
    assert events[1].name == "get_context" and len(events[1].result_summary) <= orchestrator.TOOL_SUMMARY_CHARS
    tool_message = fake.calls[1]["messages"][-1]
    assert tool_message["tool_call_id"] == "c1" and "Immich" in tool_message["content"]


# --- tool mode ---------------------------------------------------------------------------------


def test_tool_mode_round_trip(vault, context_calls, fake_llm):
    call = llm.ToolCall(id="c1", name="list_agents", arguments={})
    fake = fake_llm(_tool_round(call), _text("You have one agent."))
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), vault)
    assert _types(events) == ["context", "tool_call", "token", "done"]
    assert context_calls == []  # tool mode does not inject get_context

    context = events[0]
    assert context.rendered.startswith("# Agent persona")
    assert context.tokens_used == tokens.count(context.rendered)
    assert (context.baseline_tokens, context.tokens_saved, context.doc_ids) == (0, 0, [])

    tool_event = events[1]
    assert (tool_event.name, tool_event.arguments) == ("list_agents", {})
    assert "default" in tool_event.result_summary

    first = fake.calls[0]
    assert {t["function"]["name"] for t in first["tools"]} == ALL_TOOLS
    system = first["messages"][0]["content"]
    assert system.startswith(llm.PAM_PREAMBLE) and "get_context" in system and context.rendered in system
    follow = fake.calls[1]["messages"]
    assert follow[-2] == {"role": "assistant", "content": None, "tool_calls": [call.as_openai()]}
    assert follow[-1]["role"] == "tool" and follow[-1]["tool_call_id"] == "c1"
    assert "default" in follow[-1]["content"]


def test_tool_text_across_rounds_is_recorded_and_usage_summed(vault, fake_llm):
    call = llm.ToolCall(id="c1", name="list_agents", arguments={})
    first = _tool_round(call, text="Let me check. ")
    first[-1] = llm.LLMDelta(tool_calls=[call], finish_reason="tool_calls", usage=llm.Usage(10, 2))
    fake = fake_llm(first, _text("One agent.", usage=llm.Usage(30, 3)))
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), vault)
    assert fake.calls[1]["messages"][-2]["content"] == "Let me check. "
    done = events[-1]
    assert (done.prompt_tokens, done.completion_tokens) == (40, 5)
    assert _transcript(vault, done.session_id)[-1]["text"] == "Let me check. One agent."


def test_two_tool_calls_in_one_round_keep_order(vault, fake_llm):
    calls = [llm.ToolCall("a", "list_agents", {}), llm.ToolCall("b", "list_agents", {})]
    fake = fake_llm(_tool_round(*calls), _text("done"))
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), vault)
    assert _types(events) == ["context", "tool_call", "tool_call", "token", "done"]
    follow = fake.calls[1]["messages"]
    assert [m["tool_call_id"] for m in follow if m["role"] == "tool"] == ["a", "b"]


def test_tool_call_not_allowed_for_agent_is_an_error_result(vault, fake_llm):
    agents.create_agent(_manifest("research", ["list_agents"]), vault)
    call = llm.ToolCall(id="c1", name="add_fact", arguments={"attribute": "x", "value": "y"})
    fake = fake_llm(_tool_round(call), _text("Could not save it."))
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool", agent="research"), vault)
    assert {t["function"]["name"] for t in fake.calls[0]["tools"]} == {"list_agents"}
    tool_event = next(e for e in events if isinstance(e, ToolCallEvent))
    assert tool_event.result_summary.startswith("ERROR:")
    assert events[-1].type == "done"


def test_model_may_answer_after_the_last_allowed_round(vault, fake_llm):
    call = llm.ToolCall(id="c", name="list_agents", arguments={})
    rounds = [_tool_round(call) for _ in range(orchestrator.MAX_TOOL_ROUNDS)]
    fake = fake_llm(*rounds, _text("Final answer."))
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), vault)
    assert len(fake.calls) == orchestrator.MAX_TOOL_ROUNDS + 1
    assert all(c["tools"] for c in fake.calls)
    assert _types(events).count("tool_call") == orchestrator.MAX_TOOL_ROUNDS
    assert events[-2].text == "Final answer." and events[-1].type == "done"


def test_endless_tool_loop_stops_with_an_error_at_the_cap(vault, fake_llm):
    call = llm.ToolCall(id="c", name="list_agents", arguments={})
    fake = fake_llm(*[_tool_round(call) for _ in range(orchestrator.MAX_TOOL_ROUNDS + 3)])
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), vault)
    _assert_stream_shape(events)
    assert len(fake.calls) == orchestrator.MAX_TOOL_ROUNDS + 1
    assert _types(events).count("tool_call") == orchestrator.MAX_TOOL_ROUNDS
    error = events[-1]
    assert isinstance(error, ErrorEvent) and error.retryable is False
    assert f"tool round limit ({orchestrator.MAX_TOOL_ROUNDS})" in error.message
    assert [t["role"] for t in _transcript(vault, events[0].session_id)] == ["user"]


def test_tool_mode_without_tool_support_is_an_error(vault, context_calls, fake_llm):
    fake = fake_llm(_text("hi"))
    events = _run(_req(model=MODEL_A.id, mode="tool"), vault)
    assert _types(events) == ["context", "error"]
    assert events[0].rendered.startswith("# Agent persona")
    assert events[1].retryable is False and "does not support tools" in events[1].message
    assert fake.calls == [] and context_calls == []


def test_summary_collapses_whitespace_and_truncates():
    text = "a  b\n\nc " + "x" * 500
    summary = orchestrator._summary(text, is_error=False)
    assert summary.startswith("a b c x") and len(summary) == orchestrator.TOOL_SUMMARY_CHARS
    assert orchestrator._summary("bad", is_error=True) == "ERROR: bad"


# --- errors ------------------------------------------------------------------------------------


def test_unknown_model_raises_before_anything_is_written(vault, fake_llm):
    fake = fake_llm()
    before = _commit_count(vault)
    with pytest.raises(llm.UnknownModel) as exc:
        _run(_req(model="openrouter/nope"), vault)
    assert exc.value.exit_code == 2
    assert _commit_count(vault) == before
    assert not list((vault.root / "working").glob("s_*"))
    assert fake.calls == []


@pytest.mark.parametrize("retryable", [True, False])
def test_llm_error_mid_stream_is_the_last_event(vault, context_calls, fake_llm, retryable):
    fake_llm([llm.LLMDelta(text="par"), llm.LLMError("RateLimitError: slow down", retryable=retryable)])
    events = _run(_req(), vault)
    assert _types(events) == ["context", "token", "error"]
    assert events[-1].retryable is retryable and "slow down" in events[-1].message
    assert [t["role"] for t in _transcript(vault, events[0].session_id)] == ["user"]


def test_unexpected_exception_is_a_non_retryable_error(vault, context_calls, fake_llm):
    fake_llm([RuntimeError("boom")])
    events = _run(_req(), vault)
    _assert_stream_shape(events)
    assert events[-1] == ErrorEvent(message="RuntimeError: boom", retryable=False)


def test_llm_error_in_tool_round_is_an_error_event(vault, fake_llm):
    call = llm.ToolCall(id="c", name="list_agents", arguments={})
    fake_llm(_tool_round(call), [llm.LLMError("APIConnectionError", retryable=True)])
    events = _run(_req(model=TOOLS_MODEL.id, mode="tool"), vault)
    assert _types(events) == ["context", "tool_call", "error"]
    assert events[-1].retryable is True


def test_unknown_session_raises(vault, fake_llm):
    fake_llm()
    with pytest.raises(PamError):
        _run(_req(session_id="s_000000000000"), vault)


def test_ended_session_raises(vault, context_calls, fake_llm, monkeypatch):
    from pam.index import indexer

    monkeypatch.setattr(indexer, "index_paths", lambda *args, **kwargs: None)
    fake_llm(_text("hi"))
    sid = _run(_req(), vault)[0].session_id
    assert session.end(vault, sid).ok
    with pytest.raises(PamError, match="ended"):
        _run(_req(session_id=sid), vault)


def test_other_agent_on_a_session_is_rejected(vault, context_calls, fake_llm):
    agents.create_agent(_manifest("research", ["get_context"]), vault)
    agents.create_agent(_manifest("writer", ["get_context"]), vault)
    fake_llm(_text("hi"))
    sid = _run(_req(agent="research"), vault)[0].session_id
    with pytest.raises(PamError) as exc:
        _run(_req(agent="writer", session_id=sid), vault)
    assert exc.value.exit_code == 2


def test_default_agent_request_adopts_the_session_agent(vault, context_calls, fake_llm):
    agents.create_agent(_manifest("research", ["get_context"]), vault)
    fake_llm(_text("a"), _text("b"))
    sid = _run(_req(agent="research"), vault)[0].session_id
    _run(_req(session_id=sid), vault)
    assert [r.agent for r in context_calls] == ["research", "research"]


def test_missing_get_context_tool_still_starts_with_context(vault, fake_llm):
    agents.create_agent(_manifest("research", ["list_agents"]), vault)
    fake = fake_llm()
    events = _run(_req(agent="research"), vault)
    assert _types(events) == ["context", "error"]
    assert events[0].rendered == "" and events[0].session_id.startswith("s_")
    assert "get_context" in events[1].message and events[1].retryable is False
    assert fake.calls == []


def test_vault_busy_when_recording_the_reply_is_retryable(vault, context_calls, fake_llm, monkeypatch):
    real = session.record_turn

    def record_turn(v, sid, role, text, model):
        if role == "assistant":
            raise VaultBusy("vault is locked")
        return real(v, sid, role, text, model)

    monkeypatch.setattr(session, "record_turn", record_turn)
    fake_llm(_text("hi"))
    events = _run(_req(), vault)
    assert _types(events) == ["context", "token", "error"]
    assert events[-1].retryable is True


def test_unreachable_mcp_url_is_retryable(vault, fake_llm):
    fake_llm()
    events = _run(_req(), vault, mcp_url="http://127.0.0.1:9/mcp")
    assert _types(events) == ["context", "error"]
    assert events[1].retryable is True and "MCP" in events[1].message


# --- MCP client --------------------------------------------------------------------------------


def _with_session(vault, agent, use):
    async def run():
        async with open_session(vault, agent) as mcp:
            return await use(mcp)

    return asyncio.run(run())


def test_open_session_yields_a_client_session(vault):
    from mcp.client.session import ClientSession

    kind = _with_session(vault, "default", lambda mcp: asyncio.sleep(0, result=type(mcp)))
    assert issubclass(kind, ClientSession)


def test_openai_tool_schemas(vault):
    tools = _with_session(vault, "default", mcp_client.openai_tools)
    assert {t["function"]["name"] for t in tools} == ALL_TOOLS
    for tool in tools:
        assert tool["type"] == "function" and tool["function"]["description"]
        assert tool["function"]["parameters"]["type"] == "object"
    get_context = next(t for t in tools if t["function"]["name"] == "get_context")
    params = get_context["function"]["parameters"]
    assert "agent" not in params["properties"] and params["required"] == ["query"]


def test_restricted_agent_lists_only_its_tools(vault):
    agents.create_agent(_manifest("research", ["get_context", "search_memory"]), vault)
    tools = _with_session(vault, "research", mcp_client.openai_tools)
    assert {t["function"]["name"] for t in tools} == {"get_context", "search_memory"}


def test_get_context_parses_the_bundle(vault, context_calls):
    bundle = _with_session(vault, "default", lambda mcp: mcp_client.get_context(mcp, "q", None))
    assert isinstance(bundle, ContextBundle) and bundle.rendered == RENDERED


def test_get_context_error_raises_tool_error(vault):
    agents.create_agent(_manifest("research", ["list_agents"]), vault)
    with pytest.raises(McpToolError, match="get_context"):
        _with_session(vault, "research", lambda mcp: mcp_client.get_context(mcp, "q", None))


def test_call_tool_returns_text_and_structured_content(vault):
    outcome = _with_session(vault, "default", lambda mcp: mcp_client.call_tool(mcp, "list_agents", {}))
    assert outcome.is_error is False
    assert outcome.structured["agents"][0]["name"] == "default"
    assert "default" in outcome.text


def test_open_session_unknown_agent_raises(vault):
    with pytest.raises(PamError, match="ghost"):
        _with_session(vault, "ghost", mcp_client.openai_tools)


# --- CLI ---------------------------------------------------------------------------------------


def _chat(vault, *args, json_mode=False):
    base = ["--vault", str(vault.root)] + (["--json"] if json_mode else [])
    return runner.invoke(app, [*base, "chat", *args])


def test_cli_text_output(vault, context_calls, fake_llm):
    fake_llm(_text("You were ", "wiring RAG."))
    res = _chat(vault, "where did I leave off?", "--model", MODEL_A.id)
    assert res.exit_code == 0, res.output
    lines = res.stdout.splitlines()
    sid = lines[0].split()[1]
    assert lines[0] == f"session {sid} · context 17 tok (saved 483)"
    assert lines[1] == "You were wiring RAG."
    assert lines[2] == f"session {sid} (continue with --session {sid})"
    assert RENDERED.strip() not in res.stdout


def test_cli_quiets_provider_info_logs(vault, context_calls, fake_llm, monkeypatch):
    for name in ("LiteLLM", "mcp"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.INFO)
    fake_llm(_text("hi"))
    assert _chat(vault, "q", "--model", MODEL_A.id).exit_code == 0
    assert logging.getLogger("LiteLLM").level >= logging.WARNING
    assert logging.getLogger("mcp").level >= logging.WARNING


def test_cli_show_context(vault, context_calls, fake_llm):
    fake_llm(_text("hi"))
    res = _chat(vault, "q", "--model", MODEL_A.id, "--show-context")
    assert res.exit_code == 0, res.output
    assert RENDERED.strip() in res.stdout


def test_cli_json_is_one_valid_event_per_line(vault, context_calls, fake_llm):
    fake_llm(_text("a", "b"))
    res = _chat(vault, "q", "--model", MODEL_A.id, json_mode=True)
    assert res.exit_code == 0, res.output
    events = [EVENTS.validate_json(line) for line in res.stdout.splitlines()]
    assert _types(events) == ["context", "token", "token", "done"]


def test_cli_tool_lines(vault, fake_llm):
    fake_llm(_tool_round(llm.ToolCall("c1", "list_agents", {}), text="Checking."), _text("One."))
    res = _chat(vault, "q", "--model", TOOLS_MODEL.id, "--mode", "tool")
    assert res.exit_code == 0, res.output
    lines = res.stdout.splitlines()
    assert lines[1] == "Checking."
    assert lines[2].startswith("[tool] list_agents({}) -> ")
    assert lines[3] == "One."


def test_cli_error_event_exits_1(vault, context_calls, fake_llm):
    fake_llm([llm.LLMError("RateLimitError: slow down", retryable=True)])
    res = _chat(vault, "q", "--model", MODEL_A.id)
    assert res.exit_code == 1
    assert "error: RateLimitError: slow down (retryable)" in res.stderr
    assert "(continue with --session" in res.stdout.splitlines()[-1]


def test_cli_error_event_json_exits_1(vault, context_calls, fake_llm):
    fake_llm([llm.LLMError("AuthenticationError", retryable=False)])
    res = _chat(vault, "q", "--model", MODEL_A.id, json_mode=True)
    assert res.exit_code == 1
    last = EVENTS.validate_json(res.stdout.splitlines()[-1])
    assert isinstance(last, ErrorEvent) and last.retryable is False


def test_cli_unknown_model_exits_2_on_a_fresh_vault(tmp_path):
    root = tmp_path / "fresh"
    init_vault(root)
    res = runner.invoke(app, ["--vault", str(root), "chat", "q", "--model", MODEL_A.id])
    assert res.exit_code == 2
    assert "unknown model" in res.output


def test_cli_invalid_mode_exits_2(vault):
    res = _chat(vault, "q", "--model", MODEL_A.id, "--mode", "telepathy")
    assert res.exit_code == 2


def test_cli_follow_up_with_session(vault, context_calls, fake_llm):
    fake = fake_llm(_text("Use pgvector."), _text("Because of SQL."))
    first = _chat(vault, "Which store?", "--model", MODEL_A.id)
    sid = first.stdout.split()[1]
    second = _chat(vault, "Why?", "--model", MODEL_B.id, "--session", sid)
    assert second.exit_code == 0, second.output
    assert second.stdout.split()[1] == sid
    assert {"role": "assistant", "content": "Use pgvector."} in fake.calls[1]["messages"]


def test_cli_agent_mismatch_exits_2(vault, context_calls, fake_llm):
    agents.create_agent(_manifest("research", ["get_context"]), vault)
    agents.create_agent(_manifest("writer", ["get_context"]), vault)
    fake_llm(_text("hi"))
    first = _chat(vault, "q", "--model", MODEL_A.id, "--agent", "research")
    sid = first.stdout.split()[1]
    res = _chat(vault, "q", "--model", MODEL_A.id, "--session", sid, "--agent", "writer")
    assert res.exit_code == 2


def test_cli_help_lists_the_setup_options():
    res = runner.invoke(app, ["chat", "--help"])
    assert res.exit_code == 0
    for option in ("--model", "--session", "--agent", "--mode", "--show-context"):
        assert option in res.stdout


# --- event contract guard ----------------------------------------------------------------------

EVENT_SAMPLES = {
    ContextEvent: ContextEvent(
        session_id="s_abcdefabcdef", tokens_used=1, baseline_tokens=2, tokens_saved=1,
        doc_ids=[uuid4()], rendered="# Agent persona",
    ),
    TokenEvent: TokenEvent(text="hi"),
    ToolCallEvent: ToolCallEvent(name="list_agents", arguments={}, result_summary="ok"),
    DoneEvent: DoneEvent(session_id="s_abcdefabcdef", model="m", prompt_tokens=None, completion_tokens=3),
    ErrorEvent: ErrorEvent(message="boom", retryable=True),
}


def test_every_chat_event_has_a_sample():
    union = typing.get_args(typing.get_args(ChatEvent)[0])
    assert set(union) == set(EVENT_SAMPLES)


@pytest.mark.parametrize("event", list(EVENT_SAMPLES.values()), ids=lambda e: e.type)
def test_chat_event_json_round_trip(event):
    assert EVENTS.validate_json(event.model_dump_json()) == event
