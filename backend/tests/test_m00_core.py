"""M0 contracts and core tests (SPEC §8 M0, §9.3 T01).

Behavior:
    Round-trips one sample of every public contract model through `mdio` and JSON, and fails if a
    model has no sample. Checks the §7 contract promises, the core helpers, CLI auto-discovery, and
    `pam init`, `pam config`, and `pam schema export` through Typer's `CliRunner` on `tmp_path` vaults.
"""

import json
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
import typer
import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError
from typer.testing import CliRunner

from pam.cli.main import app
from pam.contracts import all_models
from pam.contracts.agent import AgentManifest, Persona, PersonaRule, ReadScope
from pam.contracts.api import (
    ChatRequest, ContextEvent, DoneEvent, ErrorEvent, TokenEvent, ToolCallEvent,
)
from pam.contracts.common import PAM_NAMESPACE, Actor, Source
from pam.contracts.config import ConnectorsCfg
from pam.contracts.connector import (
    CardChart, CardField, CardLink, CardPrice, ChartSeries, Connector, ConnectorAuth, ConnectorCard,
    ConnectorParam, ConnectorResult, ConnectorTool,
)
from pam.contracts.config import (
    ChunkCfg, ClusterCfg, ContextCfg, EmbeddingCfg, ExtractCfg, ModelEntry, PamConfig, RetrievalCfg,
)
from pam.contracts.episode import EpisodeFrontmatter, episode_id
from pam.contracts.fact import (
    Cardinality, Fact, FactCategory, FactConflict, FactHistoryEntry, FactStatus, fact_id,
)
from pam.contracts.graph import GraphData, GraphLink, GraphNode
from pam.contracts.project import Project
from pam.contracts.raw import AttachmentRef, RawConversation, RawMessage
from pam.contracts.reports import (
    ClusterReport, DeriveReport, ImportReport, IndexReport, JobStatus, SyncReport,
)
from pam.contracts.retrieval import (
    ContextBundle, ContextRequest, EpisodeSnippet, ProjectBrief, SearchHit, SearchQuery, SearchResponse,
)
from pam.contracts.skill import Skill
from pam.contracts.working import ModelSwitch, WorkingMemory
from pam.contracts.writes import (
    AddFactInput, AddSkillInput, GetEpisodeInput, LogEpisodeInput, SupersedeFactInput,
    UpdateProjectInput, UpdateWorkingMemoryInput, WriteResult,
)
from pam.core import config as core_config
from pam.core import mdio, tokens
from pam.core.errors import SchemaVersionError, VaultBusy, VaultNotFound
from pam.core.ids import sha256_text
from pam.core.lock import vault_write_lock
from pam.core.time import iso_z, utcnow
from pam.core.vault import Vault, init_vault, resolve_vault, set_vault_override
from pam.cli.schema_cmd import export_schemas

NOW = datetime(2026, 10, 1, 18, 4, 11, tzinfo=timezone.utc)
LATER = NOW + timedelta(hours=1)
EP = episode_id(Source.CLAUDE, "conv-1")
PROJ = UUID("11111111-2222-4333-8444-555555555555")


@pytest.fixture(autouse=True)
def _clean_vault_env(monkeypatch):
    monkeypatch.delenv("PAM_VAULT", raising=False)
    set_vault_override(None)
    yield
    set_vault_override(None)


# -- one sample instance per public model ------------------------------------------------------

def _msg(role="user", text="Let's use sqlite-vec.\n\n```py\nprint('x')\n```") -> RawMessage:
    return RawMessage(role=role, text=text, created_at=NOW,
                      attachments=[AttachmentRef(name="diagram.png", kind="image", mime_type="image/png")])


def _fact(**kw) -> Fact:
    base = dict(
        id=fact_id("shared", "user", "school", Cardinality.SINGLE, "UW"), scope="shared", attribute="school",
        value="University of Washington", cardinality=Cardinality.SINGLE, category=FactCategory.EDUCATION,
        confidence=0.9, source_episode=EP, extractor=Actor.RULE, pattern_id="edu.attend",
        created_at=NOW, updated_at=LATER,
        history=[FactHistoryEntry(value="UCLA", changed_at=NOW, changed_by=Actor.AGENT, agent="default",
                                  episode_id=EP, reason="user transferred")],
    )
    base.update(kw)
    return Fact(**base)


def _working() -> WorkingMemory:
    return WorkingMemory(
        session_id="s_abc123def456", agent="default", started_at=NOW, updated_at=LATER,
        models_used=[ModelSwitch(at=NOW, from_model=None, to_model="anthropic/claude-sonnet")],
        goal="ship T01", decisions=["use sqlite-vec"], open_questions=["which model?"],
        recent_turns=[_msg(), _msg("assistant", "ok")],
    )


def _persona() -> Persona:
    return Persona(agent="default", identity="I am a student.",
                   rules=[PersonaRule(id="r_0123abcd", text="No bullet points.", origin="derived",
                                      evidence_count=2, evidence_episodes=[EP])],
                   style="Concise.")


def _import_report() -> ImportReport:
    return ImportReport(source=Source.CLAUDE, input_path="/demo/export.zip",
                        archived_path="imports/claude/20261001T180411Z/export.zip", conversations_found=3,
                        episodes_written=2, episodes_skipped_existing=1, errors=["conv 3: empty"],
                        commit_sha="a" * 40, duration_ms=120)


SAMPLES: dict[str, BaseModel] = {
    "AttachmentRef": AttachmentRef(name="a.pdf", kind="file"),
    "RawMessage": _msg(),
    "RawConversation": RawConversation(source=Source.CLAUDE, source_conversation_id="conv-1", title="Hi",
                                       created_at=NOW, updated_at=LATER, summary="A chat.",
                                       messages=[_msg(), _msg("assistant", "Sure.")],
                                       source_metadata={"model": "claude", "n": 2, "nested": {"a": [1, 2]}}),
    "EpisodeFrontmatter": EpisodeFrontmatter(id=EP, source=Source.CLAUDE, source_conversation_id="conv-1",
                                             title="Hi: a chat — with ünïcode", created_at=NOW, updated_at=LATER,
                                             imported_at=LATER, message_count=2, has_summary=True,
                                             body_sha256=sha256_text("body"), tags=["supersedes:x"],
                                             superseded_facts=[PROJ]),
    "FactHistoryEntry": FactHistoryEntry(value="UCLA", changed_at=NOW, changed_by=Actor.MANUAL),
    "FactConflict": FactConflict(candidate_value="MIT", candidate_source_episode=EP, detected_at=NOW,
                                 detected_by=Actor.RULE),
    "Fact": _fact(),
    "Project": Project(id=PROJ, scope="default", name="PAM hackathon", keywords=["pam", "vault"],
                       episode_ids=[EP], origin=Actor.CLUSTER, created_at=NOW, updated_at=LATER,
                       last_activity_at=LATER),
    "Skill": Skill(id=PROJ, scope="default", name="Deploy", description="How to deploy",
                   trigger_keywords=["deploy"], source_episodes=[EP], created_by=Actor.AGENT,
                   created_at=NOW, updated_at=LATER),
    "ReadScope": ReadScope(project_ids=[PROJ], include_skills_from=["default"]),
    "AgentManifest": AgentManifest(name="research", display_name="Research", origin="custom", created_at=NOW,
                                   read=ReadScope(project_ids=[PROJ]), tools=["get_context", "add_fact"],
                                   default_model="ollama/llama3", token_budget=4000),
    "PersonaRule": PersonaRule(id="r_0123abcd", text="No bullet points.", origin="manual", evidence_count=0),
    "Persona": _persona(),
    "SearchQuery": SearchQuery(query="dubhacks frontend", k=5, doc_types=["episode", "fact"], since=NOW),
    "SearchHit": SearchHit(chunk_id=f"{EP}:0", doc_id=EP, doc_type="episode", scope="default", title="Hi",
                           snippet="snippet", path=f"memory/default/episodes/{EP}.md", score=0.031,
                           vector_rank=1, keyword_rank=None, created_at=NOW),
    "SearchResponse": None,  # filled below (needs SearchHit)
    "ContextRequest": ContextRequest(query="what was I doing?", session_id="s_abc123def456", token_budget=1000),
    "ProjectBrief": ProjectBrief(id=PROJ, name="PAM", keywords=["pam"], status="dormant",
                                 last_activity_at=NOW, summary="Summary."),
    "EpisodeSnippet": EpisodeSnippet(episode_id=EP, title="Hi", source=Source.CLAUDE, created_at=NOW,
                                     text="snippet", chunk_ids=[f"{EP}:0"]),
    "ContextBundle": None,  # filled below
    "ModelSwitch": ModelSwitch(at=NOW, from_model="a", to_model="b"),
    "WorkingMemory": _working(),
    "AddFactInput": AddFactInput(attribute="uses_tool", value="uv", category=FactCategory.TOOLING,
                                 cardinality=Cardinality.MULTI, episode_id=EP),
    "SupersedeFactInput": SupersedeFactInput(fact_id=PROJ, new_value="UW", reason="user confirmed"),
    "LogEpisodeInput": LogEpisodeInput(title="Chat", messages=[_msg()], summary="s", tags=["t"]),
    "UpdateProjectInput": UpdateProjectInput(project_id=PROJ, note="Decided X", add_episode_ids=[EP],
                                             status="active"),
    "AddSkillInput": AddSkillInput(name="Deploy", description="d", steps_markdown="1. build\n2. ship\n",
                                   trigger_keywords=["deploy"]),
    "UpdateWorkingMemoryInput": UpdateWorkingMemoryInput(session_id="s_abc123def456", goal="g",
                                                         add_decisions=["d"], add_open_questions=["q"]),
    "GetEpisodeInput": GetEpisodeInput(episode_id=EP, max_tokens=512),
    "WriteResult": WriteResult(ok=False, action="add_fact", doc_id=PROJ, path="memory/shared/facts/x.md",
                               conflict=_fact(status=FactStatus.CONFLICT,
                                              conflict=FactConflict(candidate_value="MIT", detected_at=NOW,
                                                                    detected_by=Actor.RULE)),
                               message="PERMISSION_DENIED: nope"),
    "ImportReport": _import_report(),
    "DeriveReport": DeriveReport(facts_created=1, facts_updated=2, conflicts_flagged=1, rules_derived=3,
                                 commit_sha=None, duration_ms=5),
    "IndexReport": IndexReport(documents_indexed=3, documents_unchanged=1, documents_removed_from_index=0,
                               chunks_written=9, embedding_model="BAAI/bge-small-en-v1.5", duration_ms=50),
    "ClusterReport": ClusterReport(mode="rebuild", projects_created=1, projects_updated=0,
                                   episodes_assigned=3, episodes_unassigned=1, commit_sha="b" * 40,
                                   duration_ms=10),
    "SyncReport": SyncReport(dirty_paths=["memory/shared/facts/x.md"], reindexed=1, commit_sha=None),
    "JobStatus": JobStatus(job_id="j1", stage="done", progress=1.0, report=_import_report()),
    "GraphNode": GraphNode(id=str(PROJ), type="project", label="PAM", cluster_id="c1", size=3.0,
                           created_at=NOW, path=None),
    "GraphLink": GraphLink(source=str(PROJ), target=str(EP), kind="member", weight=1.0),
    "GraphData": None,  # filled below
    "EmbeddingCfg": EmbeddingCfg(),
    "ChunkCfg": ChunkCfg(max_tokens=256),
    "RetrievalCfg": RetrievalCfg(),
    "ContextCfg": ContextCfg(),
    "ClusterCfg": ClusterCfg(),
    "ExtractCfg": ExtractCfg(),
    "ModelEntry": ModelEntry(id="openrouter/org/model:free", label="Free", supports_tools=True),
    "PamConfig": PamConfig(models=[ModelEntry(id="ollama/llama3", label="Llama")], sync_interval_seconds=10),
    "ChatRequest": ChatRequest(model="ollama/llama3", message="hi", mode="tool"),
    "ContextEvent": ContextEvent(session_id="s_abc123def456", tokens_used=10, baseline_tokens=100,
                                 tokens_saved=90, doc_ids=[EP], rendered="# Known facts"),
    "TokenEvent": TokenEvent(text="Hel"),
    "ToolCallEvent": ToolCallEvent(name="get_context", arguments={"query": "x", "k": 3}, result_summary="ok"),
    "DoneEvent": DoneEvent(session_id="s_abc123def456", model="m", prompt_tokens=None, completion_tokens=7),
    "ErrorEvent": ErrorEvent(message="rate limited", retryable=True),
}
SAMPLES["SearchResponse"] = SearchResponse(query="q", agent="default", hits=[SAMPLES["SearchHit"]], took_ms=12)
SAMPLES["ContextBundle"] = ContextBundle(
    agent="default", query="q", persona=_persona(), facts=[_fact()], conflicts=[], projects=[SAMPLES["ProjectBrief"]],
    episodes=[SAMPLES["EpisodeSnippet"]], working=_working(), rendered="# Agent persona\n…", tokens_used=120,
    token_budget=2000, baseline_tokens=4000, tokens_saved=3880, generated_at=NOW,
)
SAMPLES["GraphData"] = GraphData(agent="default", nodes=[SAMPLES["GraphNode"]], links=[SAMPLES["GraphLink"]],
                                 generated_at=NOW)
# ChatEvent is a discriminated union (TypeAdapter); round-trip one member through it.
SAMPLES["ChatEvent"] = SAMPLES["ContextEvent"]
# §7.16 connectors (CHG-0027, T17).
SAMPLES["ConnectorsCfg"] = ConnectorsCfg(timeout_seconds=5.0)
SAMPLES["ConnectorAuth"] = ConnectorAuth(type="api_key", header="x-api-key", env_var="ACME_KEY")
SAMPLES["ConnectorParam"] = ConnectorParam(name="customer_id", required=True, description="Customer id")
SAMPLES["ConnectorTool"] = ConnectorTool(name="get_household", description="Household", path="/customers/{customer_id}",
                                         params=[SAMPLES["ConnectorParam"]])
SAMPLES["Connector"] = Connector(id="acme", name="Acme (synthetic)", base_url="http://acme:8100",
                                 public_base_url="/connectors/acme", auth=SAMPLES["ConnectorAuth"],
                                 tools=[SAMPLES["ConnectorTool"]], agents=["research"])
SAMPLES["CardField"] = CardField(label="Battery", value="78%")
SAMPLES["CardPrice"] = CardPrice(amount=29.17, was=35.0, note="after $350 trade-in, 24 months")
SAMPLES["CardLink"] = CardLink(label="Details", url="/connectors/acme/devices/x")
SAMPLES["ChartSeries"] = ChartSeries(label="Trade-in", points=[(0.0, 350.0), (3.0, 300.0)])
SAMPLES["CardChart"] = CardChart(x_label="Month", y_label="USD", series=[SAMPLES["ChartSeries"]], marker_x=0.0)
SAMPLES["ConnectorCard"] = ConnectorCard(kind="product", title="Aurora 9", image_url="/connectors/acme/a.svg",
                                         badges=["Synthetic demo data"], price=SAMPLES["CardPrice"],
                                         fields=[SAMPLES["CardField"]], chart=SAMPLES["CardChart"],
                                         link=SAMPLES["CardLink"], connector_id="acme")
SAMPLES["ConnectorResult"] = ConnectorResult(ok=True, status=200, latency_ms=12, data={"a": [1]},
                                             cards=[SAMPLES["ConnectorCard"]])

BODY = "# Hi\n\n## Transcript\n\n### user · 2026-10-01T18:04:11Z\nhello  \n\n---\nnot frontmatter\n\n"


def test_every_public_model_has_a_sample():
    assert set(all_models()) == set(SAMPLES), "add a sample for each new contract model"


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_mdio_round_trip(tmp_path, name):
    model = all_models()[name]
    sample = SAMPLES[name]
    path = tmp_path / "sub" / f"{name}.md"
    mdio.write(path, sample, BODY)
    data, body = mdio.read(path)
    assert body == BODY
    if isinstance(model, TypeAdapter):
        again = model.validate_python(data)
    else:
        again = model.model_validate(data)
    assert again == sample
    # Also through the JSON boundary (REST/MCP).
    if not isinstance(model, TypeAdapter):
        assert model.model_validate_json(sample.model_dump_json()) == sample


def test_read_model_and_body_sha(tmp_path):
    path = tmp_path / "ep.md"
    mdio.write(path, SAMPLES["EpisodeFrontmatter"], BODY)
    fm, body = mdio.read_model(path, EpisodeFrontmatter)
    assert fm == SAMPLES["EpisodeFrontmatter"]
    assert sha256_text(body) == sha256_text(BODY)


def test_mdio_writes_lf_utf8_and_no_temp_left(tmp_path):
    path = tmp_path / "x.md"
    mdio.write(path, SAMPLES["TokenEvent"], "line1\r\nline2 ü\r\n")
    raw = path.read_bytes()
    assert b"\r\n" not in raw
    assert "ü".encode() in raw
    assert raw.startswith(b"---\n")
    assert [p.name for p in tmp_path.iterdir()] == ["x.md"]


def test_mdio_file_without_frontmatter(tmp_path):
    path = tmp_path / "plain.md"
    mdio.write_text(path, "## Derived\n")
    assert mdio.read(path) == ({}, "## Derived\n")


def test_mdio_empty_frontmatter():
    assert mdio.split("---\n---\nbody") == ({}, "body")


# -- contract promises ----------------------------------------------------------------------

def test_datetimes_serialize_with_z():
    dumped = SAMPLES["Project"].model_dump(mode="json")
    assert dumped["created_at"] == "2026-10-01T18:04:11Z"
    assert iso_z(NOW) == "2026-10-01T18:04:11Z"


def test_naive_datetime_rejected():
    with pytest.raises(ValidationError):
        ModelSwitch(at=datetime(2026, 1, 1), from_model=None, to_model="x")


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        RawMessage(role="user", text="x", bogus=1)
    with pytest.raises(ValidationError):
        Fact.model_validate(SAMPLES["Fact"].model_dump() | {"bogus": 1})
    with pytest.raises(ValidationError):
        PamConfig.model_validate({"bogus": 1})


def test_fact_conflict_iff_status():
    with pytest.raises(ValidationError):
        _fact(status=FactStatus.CONFLICT)
    with pytest.raises(ValidationError):
        _fact(conflict=FactConflict(candidate_value="x", detected_at=NOW, detected_by=Actor.RULE))


def test_shared_is_not_an_agent_name():
    with pytest.raises(ValidationError):
        AgentManifest(name="shared", display_name="x", origin="custom", created_at=NOW, read=ReadScope(), tools=[])


def test_deterministic_ids():
    assert episode_id(Source.CLAUDE, "c") == episode_id(Source.CLAUDE, "c") != episode_id(Source.CHATGPT, "c")
    single_a = fact_id("shared", "user", "school", Cardinality.SINGLE, "UW")
    single_b = fact_id("shared", "user", "school", Cardinality.SINGLE, "MIT")
    assert single_a == single_b
    multi_a = fact_id("shared", "user", "uses_tool", Cardinality.MULTI, "  UV ")
    multi_b = fact_id("shared", "user", "uses_tool", Cardinality.MULTI, "uv")
    multi_c = fact_id("shared", "user", "uses_tool", Cardinality.MULTI, "git")
    assert multi_a == multi_b != multi_c
    # Pinned: if this changes, every existing vault's IDs change (PAM_NAMESPACE must never change).
    assert PAM_NAMESPACE.version == 5
    assert str(EP) == "a24a19be-0ed2-55d4-92a3-00751bef8321"


def test_chat_event_discriminator():
    adapter = all_models()["ChatEvent"]
    ev = adapter.validate_json('{"type": "done", "session_id": "s", "model": "m", '
                               '"prompt_tokens": 1, "completion_tokens": 2}')
    assert isinstance(ev, DoneEvent)


@pytest.mark.parametrize("version,ok", [("1.0.0", True), ("1.7.0", True), ("2.0.0", False), ("0.9.0", False)])
def test_schema_major_version(tmp_path, version, ok):
    path = tmp_path / "s.md"
    mdio.write(path, SAMPLES["Skill"].model_copy(update={"schema_version": version}), "steps")
    assert mdio.read(path)[0]["schema_version"] == version
    if ok:
        mdio.read_model(path, Skill)
    else:
        with pytest.raises(SchemaVersionError):
            mdio.read_model(path, Skill)


# -- core helpers ---------------------------------------------------------------------------

def test_tokens_count():
    assert tokens.count("hello world") == 2
    assert tokens.count("") == 0
    assert tokens.count("<|endoftext|>") > 0  # special tokens are counted as text, not rejected


def test_utcnow_is_aware_utc():
    now = utcnow()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0) and now.microsecond == 0


def test_resolve_vault_order(tmp_path, monkeypatch):
    with pytest.raises(VaultNotFound):
        resolve_vault()
    monkeypatch.setenv("PAM_VAULT", str(tmp_path / "env"))
    assert resolve_vault() == (tmp_path / "env").resolve()
    set_vault_override(tmp_path / "flag")
    assert resolve_vault() == (tmp_path / "flag").resolve()
    assert resolve_vault(tmp_path / "arg") == (tmp_path / "arg").resolve()


def test_vault_paths_are_posix(tmp_path):
    v = Vault(tmp_path)
    assert v.rel(v.episode_path("default", EP)) == f"memory/default/episodes/{EP}.md"
    assert v.rel(v.fact_path("shared", EP)) == f"memory/shared/facts/{EP}.md"
    assert v.rel(v.project_path("default", PROJ)) == f"memory/default/projects/{PROJ}.md"
    assert v.rel(v.skill_path("default", PROJ)) == f"skills/default/{PROJ}.md"
    assert v.rel(v.working_path("s_abc123def456")) == "working/s_abc123def456.md"
    assert v.rel(v.persona_path("default", "rules")) == "agent/default/rules.md"
    assert v.rel(v.import_dir("claude", NOW)) == "imports/claude/20261001T180411Z"
    assert v.rel(v.lock_path) == ".pam/write.lock"
    assert v.abs("memory/shared/facts/x.md") == tmp_path.resolve() / "memory" / "shared" / "facts" / "x.md"


def test_lock_contention(tmp_path):
    v = Vault(tmp_path)
    held, release = threading.Event(), threading.Event()

    def holder():
        with vault_write_lock(v):
            held.set()
            release.wait(5)

    t = threading.Thread(target=holder)
    t.start()
    try:
        assert held.wait(5)
        with pytest.raises(VaultBusy) as exc:
            with vault_write_lock(v, timeout=0.1):
                pass
        assert exc.value.exit_code == 4
    finally:
        release.set()
        t.join()
    with vault_write_lock(v, timeout=0.1):
        pass


def test_config_defaults_and_round_trip(tmp_path):
    v = Vault(tmp_path)
    assert core_config.load(v) == PamConfig()
    cfg = SAMPLES["PamConfig"]
    mdio.write_text(v.config_path, core_config.dump_toml(cfg))
    assert core_config.load(v) == cfg


def test_config_rejects_unknown_major(tmp_path):
    v = Vault(tmp_path)
    mdio.write_text(v.config_path, 'schema_version = "2.0.0"\n')
    with pytest.raises(SchemaVersionError):
        core_config.load(v)


# -- pam init / config / schema -------------------------------------------------------------

runner = CliRunner()


def _git_log(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "log", "--format=%an <%ae>|%s"], capture_output=True,
                         text=True, check=True)
    return out.stdout.splitlines()


def test_init_creates_tree_and_one_commit(tmp_path):
    root = tmp_path / "v"
    res = runner.invoke(app, ["init", "--vault", str(root)])
    assert res.exit_code == 0, res.output
    assert _git_log(root) == ["PAM <pam@local>|pam: init vault"]
    for d in ("agent/default", "imports", "memory/shared/facts", "memory/default/episodes",
              "memory/default/facts", "memory/default/projects", "skills/default", "working", ".pam"):
        assert (root / d).is_dir(), d
    assert (root / ".gitattributes").read_text() == "* text eol=lf\n"
    assert (root / ".gitignore").read_text() == ".pam/\n"
    autocrlf = subprocess.run(["git", "-C", str(root), "config", "core.autocrlf"], capture_output=True, text=True)
    assert autocrlf.stdout.strip() == "false"
    status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True)
    assert status.stdout == ""

    v = Vault(root)
    assert core_config.load(v) == PamConfig()
    manifest = AgentManifest.model_validate(yaml.safe_load(v.manifest_path("default").read_text("utf-8")))
    assert manifest.read.all and manifest.write == "shared" and len(manifest.tools) == 10
    for kind in ("identity", "rules", "style"):
        text = v.persona_path("default", kind).read_text("utf-8")
        assert text.startswith("## Derived") and "## Custom" in text


def test_init_is_noop_on_existing_vault(tmp_path):
    root = tmp_path / "v"
    assert init_vault(root).created
    res = runner.invoke(app, ["init", "--vault", str(root)])
    assert res.exit_code == 0
    assert "already a PAM vault" in res.output
    assert len(_git_log(root)) == 1


def test_init_refuses_non_empty_non_vault(tmp_path):
    (tmp_path / "stuff.txt").write_text("x")
    res = runner.invoke(app, ["init", "--vault", str(tmp_path)])
    assert res.exit_code == 1
    assert not (tmp_path / "pam.toml").exists()


HALF_VAULT_TOML = (
    'schema_version = "1.0.0"\n\n[[models]]\nid = "openrouter/test/model:free"\nlabel = "Test model"\n'
    'supports_tools = true\n'
)


def test_stray_pam_toml_is_not_a_vault(tmp_path):
    (tmp_path / "pam.toml").write_text(HALF_VAULT_TOML)
    v = Vault(tmp_path)
    assert not v.is_initialized()
    with pytest.raises(VaultNotFound):
        v.require_initialized()


def test_init_finishes_a_half_made_vault_and_keeps_settings(tmp_path):
    (tmp_path / "pam.toml").write_text(HALF_VAULT_TOML)
    (tmp_path / ".pam").mkdir()
    (tmp_path / ".pam" / "secrets.json").write_text('{"openrouter": "sk-test"}')
    res = runner.invoke(app, ["init", "--vault", str(tmp_path)])
    assert res.exit_code == 0, res.output
    v = Vault(tmp_path)
    assert v.is_initialized()
    assert [m.id for m in core_config.load(v).models] == ["openrouter/test/model:free"]
    assert (tmp_path / ".pam" / "secrets.json").read_text() == '{"openrouter": "sk-test"}'
    assert len(_git_log(tmp_path)) == 1
    tracked = subprocess.run(["git", "-C", str(tmp_path), "ls-files"], capture_output=True, text=True,
                             check=True).stdout.splitlines()
    assert "pam.toml" in tracked and "agent/default/agent.yaml" in tracked
    assert not any(t.startswith(".pam/") for t in tracked)
    clean = subprocess.run(["git", "-C", str(tmp_path), "status", "--porcelain"], capture_output=True, text=True,
                           check=True).stdout
    assert clean == ""


def test_init_keeps_existing_persona_files(tmp_path):
    persona = tmp_path / "agent" / "default" / "identity.md"
    persona.parent.mkdir(parents=True)
    persona.write_text("## Custom\nmine\n")
    assert init_vault(tmp_path).created
    assert persona.read_text() == "## Custom\nmine\n"


def test_init_refuses_invalid_half_vault_toml(tmp_path):
    (tmp_path / "pam.toml").write_text("models = [\n")
    res = runner.invoke(app, ["init", "--vault", str(tmp_path)])
    assert res.exit_code != 0
    assert not (tmp_path / ".git").exists()


def test_init_refuses_git_repo_without_pam_toml(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    res = runner.invoke(app, ["init", "--vault", str(tmp_path)])
    assert res.exit_code == 1
    assert not (tmp_path / "pam.toml").exists()


def test_init_refuses_half_vault_with_other_files(tmp_path):
    (tmp_path / "pam.toml").write_text(HALF_VAULT_TOML)
    (tmp_path / "notes.txt").write_text("x")
    res = runner.invoke(app, ["init", "--vault", str(tmp_path)])
    assert res.exit_code == 1
    assert not (tmp_path / ".git").exists()


def test_init_uses_global_vault_option_and_env(tmp_path, monkeypatch):
    res = runner.invoke(app, ["--vault", str(tmp_path / "a"), "init"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "a" / "pam.toml").is_file()
    set_vault_override(None)
    monkeypatch.setenv("PAM_VAULT", str(tmp_path / "b"))
    res = runner.invoke(app, ["init"])
    assert res.exit_code == 0, res.output
    assert (tmp_path / "b" / "pam.toml").is_file()


def test_config_show_and_path(tmp_path):
    root = tmp_path / "v"
    init_vault(root)
    res = runner.invoke(app, ["--vault", str(root), "--json", "config", "show"])
    assert res.exit_code == 0, res.output
    assert PamConfig.model_validate_json(res.output) == PamConfig()
    res = runner.invoke(app, ["--vault", str(root), "--json", "config", "path"])
    assert json.loads(res.output) == {"path": str((root / "pam.toml").resolve()), "exists": True}


@pytest.mark.parametrize("source,command", [
    ("import typer\n\ndef register(app):\n    app.command('zzhello')(lambda: typer.echo('hi'))\n", ["zzhello"]),
    ("import typer\n\napp = typer.Typer()\n\n@app.command('run')\ndef run():\n    typer.echo('hi')\n",
     ["zzdemo", "run"]),
])
def test_cli_discovers_cmd_modules(tmp_path, monkeypatch, source, command):
    import sys

    import pam.cli
    from pam.cli.main import PamGroup, _discover

    (tmp_path / "zzdemo_cmd.py").write_text(source, encoding="utf-8")
    monkeypatch.setattr(pam.cli, "__path__", [*pam.cli.__path__, str(tmp_path)])
    monkeypatch.delitem(sys.modules, "pam.cli.zzdemo_cmd", raising=False)
    root = typer.Typer(cls=PamGroup)
    root.callback()(lambda: None)
    _discover(root)
    res = runner.invoke(root, command)
    sys.modules.pop("pam.cli.zzdemo_cmd", None)
    assert res.exit_code == 0, res.output
    assert res.output.strip() == "hi"


def test_missing_vault_exit_code():
    res = runner.invoke(app, ["config", "show"])
    assert res.exit_code == 1
    assert "PAM_VAULT" in res.output


def test_schema_export_one_file_per_model(tmp_path):
    res = runner.invoke(app, ["schema", "export", "--out", str(tmp_path)])
    assert res.exit_code == 0, res.output
    files = {p.stem for p in tmp_path.glob("*.json")}
    assert files == set(all_models())
    fact = json.loads((tmp_path / "Fact.json").read_text("utf-8"))
    assert fact["title"] == "Fact" and "attribute" in fact["properties"]
    chat = json.loads((tmp_path / "ChatEvent.json").read_text("utf-8"))
    assert chat["title"] == "ChatEvent" and "discriminator" in chat
    # Deterministic: a second export is byte-identical.
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    export_schemas(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before
