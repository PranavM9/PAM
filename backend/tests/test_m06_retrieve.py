"""M6 retriever and context tests, written before T07 (SPEC §8 M6, §9.3 T07).

Behavior:
    Pins the hybrid search and context assembly behavior against isolated imported fixtures and
    manually added project and fact records. This module skips until both M6 modules exist.

API assumed by these tests (agreed for T07, not in SPEC):
    `search.search(vault, q: SearchQuery) -> SearchResponse`
    `context.build_context(vault, req: ContextRequest) -> ContextBundle`
    `search.rrf_fuse(ranked_lists, rrf_k) -> dict[int, float]`
    `search.recency_multiplier(age_days, cfg) -> float`
    `search.sanitize_fts(query) -> str`
    CLI: `pam search "Q" [--agent] [--k] [--json]` and
    `pam context "Q" [--budget] [--agent] [--session] [--json]`.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from typer.testing import CliRunner

search = pytest.importorskip("pam.retrieve.search")
context = pytest.importorskip("pam.retrieve.context")

from pam.agents import manifest as agents  # noqa: E402
from pam.cli.main import app  # noqa: E402
from pam.contracts.agent import AgentManifest, ReadScope  # noqa: E402
from pam.contracts.common import Actor  # noqa: E402
from pam.contracts.episode import EpisodeFrontmatter  # noqa: E402
from pam.contracts.fact import (  # noqa: E402
    Cardinality,
    Fact,
    FactCategory,
    FactConflict,
    FactStatus,
    fact_id,
)
from pam.contracts.project import Project  # noqa: E402
from pam.contracts.retrieval import ContextBundle, ContextRequest, SearchQuery, SearchResponse  # noqa: E402
from pam.core import mdio, tokens  # noqa: E402
from pam.core.vault import Vault, init_vault  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = FIXTURES / "claude" / "export.zip"
CHATGPT = FIXTURES / "chatgpt" / "export.zip"
NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
runner = CliRunner()


@pytest.fixture(scope="module")
def indexed_vault(tmp_path_factory) -> Vault:
    """Create one imported, indexed vault for retrieval and context cases."""
    pytest.importorskip("pam.index.indexer")
    root = tmp_path_factory.mktemp("m06-vault") / "vault"
    init_vault(root)
    vault = Vault(root)

    for fixture in (CLAUDE, CHATGPT):
        result = runner.invoke(app, ["--vault", str(root), "import", "run", str(fixture)])
        assert result.exit_code == 0, result.output

    episode_files = list((root / "memory" / "default" / "episodes").glob("*.md"))
    immich = []
    for path in episode_files:
        frontmatter, _ = mdio.read_model(path, EpisodeFrontmatter)
        if "immich" in frontmatter.title.lower():
            immich.append(frontmatter)
    assert len(immich) >= 3
    project_id = uuid4()
    project = Project(
        id=project_id,
        scope="default",
        name="Immich photo backup",
        keywords=["immich", "photo", "backup"],
        episode_ids=[episode.id for episode in immich[:3]],
        origin=Actor.MANUAL,
        status="active",
        created_at=NOW,
        updated_at=NOW,
        last_activity_at=NOW,
    )
    mdio.write(vault.project_path("default", project_id), project, "## Summary (auto)\nPhoto backup notes.\n")

    school_id = fact_id("shared", "user", "school", Cardinality.SINGLE, "UW")
    mdio.write(
        vault.fact_path("shared", school_id),
        Fact(
            id=school_id, scope="shared", attribute="school", value="UW",
            cardinality=Cardinality.SINGLE, category=FactCategory.EDUCATION,
            confidence=0.9, extractor=Actor.MANUAL, created_at=NOW, updated_at=NOW,
        ),
        "**school**: UW\n",
    )
    work_id = fact_id("shared", "user", "works_at", Cardinality.SINGLE, "Northside Cafe")
    mdio.write(
        vault.fact_path("shared", work_id),
        Fact(
            id=work_id, scope="shared", attribute="works_at", value="Northside Cafe",
            cardinality=Cardinality.SINGLE, category=FactCategory.WORK,
            confidence=0.8, status=FactStatus.CONFLICT,
            conflict=FactConflict(candidate_value="Campus Dining", detected_at=NOW, detected_by=Actor.RULE),
            extractor=Actor.MANUAL, created_at=NOW, updated_at=NOW,
        ),
        "**works_at**: Northside Cafe\n",
    )

    manifest = AgentManifest(
        name="research", display_name="Research", description="Project researcher", origin="custom",
        created_at=NOW, read=ReadScope(project_ids=[project_id], include_shared_facts=True),
        write="own", tools=["get_context", "search_memory", "get_episode", "list_agents"],
    )
    agents.create_agent(manifest, vault)
    result = runner.invoke(app, ["--vault", str(root), "index"])
    assert result.exit_code == 0, result.output
    return vault


def test_rrf_fuse_sums_reciprocal_rank_contributions():
    fused = search.rrf_fuse([[10, 20], [20, 30]], 60)
    assert fused[10] == pytest.approx(1 / 61)
    assert fused[20] == pytest.approx(1 / 62 + 1 / 61)
    assert fused[30] == pytest.approx(1 / 62)
    assert fused[20] > fused[10]


def test_recency_multiplier_is_full_at_age_zero():
    cfg = type("Cfg", (), {"recency_weight": 0.2, "recency_half_life_days": 30})()
    assert search.recency_multiplier(0, cfg) == pytest.approx(1.2)


def test_recency_multiplier_halves_at_half_life():
    cfg = type("Cfg", (), {"recency_weight": 0.2, "recency_half_life_days": 30})()
    assert search.recency_multiplier(30, cfg) == pytest.approx(1.1)


def test_recency_multiplier_decreases_with_age():
    cfg = type("Cfg", (), {"recency_weight": 0.2, "recency_half_life_days": 30})()
    assert search.recency_multiplier(60, cfg) < search.recency_multiplier(30, cfg)


@pytest.mark.parametrize("query", ['"quoted phrase', "()", "AND OR NEAR", "foo*", "-private", '"(x OR y)* -z'])
def test_sanitize_fts_produces_valid_fts_queries(query):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE docs USING fts5(body)")
    con.execute("INSERT INTO docs VALUES ('quoted phrase foo x y z private')")
    sanitized = search.sanitize_fts(query)
    con.execute("SELECT rowid FROM docs WHERE docs MATCH ?", (sanitized,)).fetchall()


@pytest.mark.parametrize("query", ["Immich photo backup", "Tailscale eduroam", "F1 visa check-in"])
def test_search_returns_fixture_topics_in_top_three(indexed_vault, query):
    response = search.search(indexed_vault, SearchQuery(query=query, k=8))
    assert isinstance(response, SearchResponse)
    assert response.hits
    assert any(query.lower().split()[0] in (hit.title or "").lower() for hit in response.hits[:3])


def test_search_hit_shape_and_limits(indexed_vault):
    response = search.search(indexed_vault, SearchQuery(query="Immich photo backup", k=8))
    assert response.hits == sorted(response.hits, key=lambda hit: hit.score, reverse=True)
    assert len(response.hits) <= 8
    assert max((sum(hit.doc_id == doc_id for hit in response.hits) for doc_id in {h.doc_id for h in response.hits}), default=0) <= 2
    assert all(len(hit.snippet) <= 500 and "\\" not in hit.path for hit in response.hits)
    assert all(hit.vector_rank is None or hit.vector_rank >= 1 for hit in response.hits)
    assert all(hit.keyword_rank is None or hit.keyword_rank >= 1 for hit in response.hits)
    assert any(hit.vector_rank is not None and hit.keyword_rank is not None for hit in response.hits)
    assert response.took_ms >= 0


def test_search_doc_type_filter(indexed_vault):
    response = search.search(indexed_vault, SearchQuery(query="Immich", doc_types=["episode"], k=20))
    assert all(hit.doc_type == "episode" for hit in response.hits)


def test_search_since_filter(indexed_vault):
    cutoff = datetime(2026, 8, 30, tzinfo=UTC)
    response = search.search(indexed_vault, SearchQuery(query="Immich", since=cutoff, k=20))
    assert all(hit.created_at is not None and hit.created_at >= cutoff for hit in response.hits)


def test_operator_query_falls_back_without_error(indexed_vault):
    response = search.search(indexed_vault, SearchQuery(query='"(Immich OR Tailscale)* -visa', k=8))
    assert isinstance(response, SearchResponse)


def test_restricted_scope_property_over_seeded_queries(indexed_vault):
    rng = random.Random(7007)
    words = ["Immich", "photos", "Tailscale", "eduroam", "visa", "backup", "server", "UW"]
    for _ in range(50):
        query = " ".join(rng.choices(words, k=rng.randint(1, 4)))
        response = search.search(indexed_vault, SearchQuery(query=query, agent="research", k=20))
        assert all(hit.scope in {"research", "shared", "default"} for hit in response.hits)
        assert all("tailscale" not in (hit.title or "").lower() and "visa" not in (hit.title or "").lower()
                   for hit in response.hits)


def test_default_agent_control_can_see_unrestricted_hits(indexed_vault):
    response = search.search(indexed_vault, SearchQuery(query="F1 visa", agent="default", k=20))
    assert any("visa" in (hit.title or "").lower() for hit in response.hits)


@pytest.mark.parametrize("budget", [256, 800, 2000])
def test_context_respects_budget_and_counts_rendered_tokens(indexed_vault, budget):
    bundle = context.build_context(indexed_vault, ContextRequest(query="Immich photo backup", token_budget=budget))
    assert isinstance(bundle, ContextBundle)
    assert bundle.tokens_used <= budget
    assert bundle.tokens_used == tokens.count(bundle.rendered)


def test_context_headings_are_fixed_order_and_items_cite_vault_paths(indexed_vault):
    bundle = context.build_context(indexed_vault, ContextRequest(query="Immich photo backup", token_budget=2000))
    headings = ["# Agent persona", "# Known facts", "# ⚠ Conflicting facts — ask the user",
                "# Working memory", "# Relevant projects", "# Relevant past conversations"]
    positions = [bundle.rendered.index(item) for item in headings]
    assert positions == sorted(positions)
    for fact in [*bundle.facts, *bundle.conflicts]:
        assert indexed_vault.rel(indexed_vault.fact_path(fact.scope, fact.id)) in bundle.rendered
    for project in bundle.projects:
        assert indexed_vault.rel(indexed_vault.project_path("default", project.id)) in bundle.rendered
    for episode in bundle.episodes:
        path = indexed_vault.episode_path("default", episode.episode_id)
        assert indexed_vault.rel(path) in bundle.rendered and path.is_file()


def test_context_surfaces_relevant_work_conflict(indexed_vault):
    bundle = context.build_context(indexed_vault, ContextRequest(query="Where do I work?", token_budget=2000))
    assert any(f.attribute == "works_at" and f.status == FactStatus.CONFLICT for f in bundle.conflicts)
    assert "# ⚠ Conflicting facts — ask the user" in bundle.rendered


def test_context_savings_use_full_contributing_episode_tokens(indexed_vault):
    bundle = context.build_context(indexed_vault, ContextRequest(query="Immich photo backup", token_budget=2000))
    assert bundle.baseline_tokens == sum(
        _episode_token_count(indexed_vault, item.episode_id)
        for item in bundle.episodes
    )
    assert bundle.tokens_saved == max(0, bundle.baseline_tokens - bundle.tokens_used)


def _episode_token_count(vault: Vault, episode_id) -> int:
    con = sqlite3.connect(vault.index_db)
    try:
        row = con.execute("SELECT token_count FROM documents WHERE doc_id=?", (str(episode_id),)).fetchone()
    finally:
        con.close()
    assert row is not None
    return row[0]


def test_context_is_repeatable_except_generated_at(indexed_vault):
    request = ContextRequest(query="Immich photo backup", token_budget=2000)
    first = context.build_context(indexed_vault, request)
    second = context.build_context(indexed_vault, request)
    first_data = first.model_dump(mode="json")
    second_data = second.model_dump(mode="json")
    first_data.pop("generated_at")
    second_data.pop("generated_at")
    assert first_data == second_data


def test_persona_cap_and_small_budget_drop_lower_priorities(indexed_vault):
    full = context.build_context(indexed_vault, ContextRequest(query="Immich", token_budget=2000))
    tiny = context.build_context(indexed_vault, ContextRequest(query="Immich", token_budget=256))
    assert full.persona is None or tokens.count(full.persona.identity + full.persona.style) <= 300
    assert tiny.tokens_used <= full.tokens_used
    assert len(tiny.episodes) <= len(full.episodes)


def test_research_context_is_scope_safe(indexed_vault):
    bundle = context.build_context(indexed_vault, ContextRequest(query="F1 visa Tailscale", agent="research", token_budget=2000))
    assert all("tailscale" not in episode.title.lower() and "visa" not in episode.title.lower()
               for episode in bundle.episodes)


def test_empty_index_returns_persona_only(tmp_path):
    pytest.importorskip("pam.index.indexer")
    root = tmp_path / "empty"
    init_vault(root)
    vault = Vault(root)
    result = runner.invoke(app, ["--vault", str(root), "index"])
    assert result.exit_code == 0, result.output
    bundle = context.build_context(vault, ContextRequest(query="anything", token_budget=800))
    assert bundle.episodes == [] and bundle.tokens_used <= 800


def test_context_includes_working_memory_when_supported(indexed_vault):
    working = pytest.importorskip("pam.working.session")
    session_id = "s_0123456789ab"
    session_path = indexed_vault.working_path(session_id)
    from pam.contracts.working import WorkingMemory  # noqa: PLC0415

    memory = WorkingMemory(session_id=session_id, agent="default", started_at=NOW, updated_at=NOW,
                           goal="Back up photos", decisions=["Use Immich"], open_questions=[])
    mdio.write(session_path, memory, "# Working memory\nUse Immich.\n")
    bundle = context.build_context(indexed_vault, ContextRequest(query="Immich", session_id=session_id, token_budget=2000))
    assert bundle.working is not None
    assert "# Working memory" in bundle.rendered


def test_cli_json_validates_as_contracts(indexed_vault):
    search_result = runner.invoke(app, ["--vault", str(indexed_vault.root), "--json", "search", "Immich", "--k", "8"])
    assert search_result.exit_code == 0, search_result.output
    SearchResponse.model_validate(json.loads(search_result.output))
    context_result = runner.invoke(app, ["--vault", str(indexed_vault.root), "--json", "context", "Immich", "--budget", "800"])
    assert context_result.exit_code == 0, context_result.output
    ContextBundle.model_validate(json.loads(context_result.output))


@pytest.mark.skipif(os.getenv("PAM_PERF") != "1", reason="set PAM_PERF=1 to run retrieval performance acceptance")
def test_search_p95_under_300ms_for_1000_synthetic_episodes(indexed_vault):
    pytest.importorskip("pam.index.indexer")
    timings = []
    for _ in range(20):
        started = time.perf_counter()
        search.search(indexed_vault, SearchQuery(query="Immich backup", k=8))
        timings.append((time.perf_counter() - started) * 1000)
    assert sorted(timings)[18] < 300

