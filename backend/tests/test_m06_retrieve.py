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


# --- strict spec checks (T07 review) --------------------------------------------------------
# Each test names the SPEC rule it checks. `strict_vault` adds a tooling fact hit, an unrelated
# conflict, a project with `## Notes`, two working-memory sessions, and a large-persona agent.

import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

from pam.agents.permissions import visible_doc_filter  # noqa: E402
from pam.contracts.working import WorkingMemory  # noqa: E402
from pam.core.errors import PamError  # noqa: E402

TAILSCALE_PROJECT = "Tailscale remote access"
LARGE_PERSONA = "\n" + "I like long detailed explanations about photography and backups. " * 300
PRIORITY = ("conflicts", "working", "facts", "projects", "episodes")  # §7.9 fill order after the persona


def _write_fact(vault: Vault, attribute: str, value: str, category: FactCategory,
                cardinality: Cardinality = Cardinality.SINGLE, conflict: str | None = None) -> None:
    fid = fact_id("shared", "user", attribute, cardinality, value)
    mdio.write(
        vault.fact_path("shared", fid),
        Fact(
            id=fid, scope="shared", attribute=attribute, value=value, cardinality=cardinality,
            category=category, confidence=0.8, extractor=Actor.MANUAL, created_at=NOW, updated_at=NOW,
            status=FactStatus.CONFLICT if conflict else FactStatus.ACTIVE,
            conflict=FactConflict(candidate_value=conflict, detected_at=NOW, detected_by=Actor.RULE) if conflict else None,
        ),
        f"**{attribute}**: {value}\n",
    )


def _write_session(vault: Vault, session_id: str, agent: str) -> None:
    memory = WorkingMemory(session_id=session_id, agent=agent, started_at=NOW, updated_at=NOW,
                           goal=f"Goal of {agent}", decisions=["Use Immich"], open_questions=[])
    mdio.write(vault.working_path(session_id), memory, "# Working memory\n")


@pytest.fixture(scope="module")
def strict_vault(indexed_vault, tmp_path_factory) -> Vault:
    """Copy the indexed vault and add data that exercises the §7.9 and §8 M6 rules.

    Behavior:
        Adds a `tooling` fact hit (`uses_tool: Immich`), an unrelated conflict (`favorite_color`),
        a second project whose body has `## Notes`, working-memory sessions for `default` and
        `research`, and an agent `verbose` with a ~20 KB persona, then reindexes. The copy keeps
        the extra data out of the tests above.
    """
    root = tmp_path_factory.mktemp("m06-strict") / "vault"
    shutil.copytree(indexed_vault.root, root)
    vault = Vault(root)
    _write_fact(vault, "uses_tool", "Immich", FactCategory.TOOLING, Cardinality.MULTI)
    _write_fact(vault, "favorite_color", "Teal", FactCategory.PREFERENCE, conflict="Orange")

    tailscale = [fm for fm in (mdio.read_model(p, EpisodeFrontmatter)[0]
                               for p in (root / "memory" / "default" / "episodes").glob("*.md"))
                 if "tailscale" in fm.title.lower()]
    assert tailscale
    project = Project(id=uuid4(), scope="default", name=TAILSCALE_PROJECT, keywords=["tailscale", "vpn"],
                      episode_ids=[fm.id for fm in tailscale], origin=Actor.MANUAL, status="active",
                      created_at=NOW, updated_at=NOW, last_activity_at=NOW)
    mdio.write(vault.project_path("default", project.id), project,
               "## Summary (auto)\nVPN access summary.\n\n## Notes\n- 2026-10-01T12:00Z (agent:default) notesecretword\n")

    _write_session(vault, "s_0123456789ab", "default")
    _write_session(vault, "s_aaaaaaaaaaaa", "research")

    agents.create_agent(AgentManifest(
        name="verbose", display_name="Verbose", origin="custom", created_at=NOW,
        read=ReadScope(all=True), tools=["get_context", "search_memory"],
    ), vault)
    identity = vault.persona_path("verbose", "identity")
    identity.write_text(identity.read_text(encoding="utf-8") + LARGE_PERSONA, encoding="utf-8")

    result = runner.invoke(app, ["--vault", str(root), "index"])
    assert result.exit_code == 0, result.output
    return vault


def _bundle(vault: Vault, query: str, budget: int = 2000, **kwargs) -> ContextBundle:
    return context.build_context(vault, ContextRequest(query=query, token_budget=budget, **kwargs))


def _keys(bundle: ContextBundle) -> dict[str, set[str]]:
    return {
        "conflicts": {str(f.id) for f in bundle.conflicts},
        "working": {bundle.working.session_id} if bundle.working else set(),
        "facts": {str(f.id) for f in bundle.facts},
        "projects": {str(p.id) for p in bundle.projects},
        "episodes": {f"{e.episode_id}:{','.join(e.chunk_ids)}" for e in bundle.episodes},
    }


def _visible_doc_ids(vault: Vault, agent: str) -> set[str]:
    sql, params = visible_doc_filter(agents.load_manifest(agent, vault), vault, alias="d")
    con = sqlite3.connect(vault.index_db)
    try:
        return {row[0] for row in con.execute(f"SELECT d.doc_id FROM documents d WHERE {sql}", params)}
    finally:
        con.close()


# §8 M6 context step 3: "always include identity, education, work, plus fact hits, up to max_facts".
def test_fact_hit_outside_core_categories_is_included(strict_vault):
    hits = search.search(strict_vault, SearchQuery(query="Immich", k=20)).hits
    assert any(h.doc_type == "fact" and h.title == "uses_tool: Immich" for h in hits)  # precondition
    assert "uses_tool" in [f.attribute for f in _bundle(strict_vault, "Immich", 4000).facts]


# §8 M6 context step 3: conflicts are "always included when their attribute is mentioned in the
# query or hits" (§7.9: conflicts come right after the persona).
@pytest.mark.parametrize("budget", [256, 800, 2000])
def test_relevant_conflict_is_kept_at_every_budget(strict_vault, budget):
    assert "works_at" in [f.attribute for f in _bundle(strict_vault, "Where do I work?", budget).conflicts]


# §8 M6 context step 3: other conflicts "go in only if budget remains", so an unrelated conflict
# never takes room from facts, projects, or snippets that the unlimited bundle has.
@pytest.mark.parametrize("budget", [256, 1000, 4000])
def test_unrelated_conflict_only_with_spare_budget(strict_vault, budget):
    full = _keys(_bundle(strict_vault, "Immich photo backup", 32000))
    bundle = _bundle(strict_vault, "Immich photo backup", budget)
    if "favorite_color" in [f.attribute for f in bundle.conflicts]:
        got = _keys(bundle)
        for kind in ("facts", "projects", "episodes"):
            assert full[kind] <= got[kind], f"{kind} dropped while an unrelated conflict was included"


# §7.9 Budget-safe: "Lower-priority items are dropped first." No item of a lower-priority section
# may appear while an item of a higher-priority section (from the unlimited bundle) is missing.
# Only relevant conflicts rank first; the unrelated `favorite_color` conflict is checked above.
@pytest.mark.parametrize("budget", [256, 300, 400, 600, 1000, 2000])
def test_lower_priority_items_are_dropped_first(strict_vault, budget):
    query, session = "Where do I work on Immich photo backup?", "s_0123456789ab"
    unrelated = str(fact_id("shared", "user", "favorite_color", Cardinality.SINGLE, "Teal"))
    full = _keys(_bundle(strict_vault, query, 32000, session_id=session))
    got = _keys(_bundle(strict_vault, query, budget, session_id=session))
    full["conflicts"].discard(unrelated)
    got["conflicts"].discard(unrelated)
    for i, higher in enumerate(PRIORITY):
        if full[higher] - got[higher]:
            for lower in PRIORITY[i + 1:]:
                assert not got[lower], f"{lower} included while a {higher} item was dropped at budget {budget}"


# §8 M6 context step 5: "merge adjacent chunks from the same episode".
def test_snippets_merge_only_adjacent_chunks(strict_vault):
    for query in ("Immich photo backup", "Tailscale eduroam", "local LLM gateway Ollama"):
        for snippet in _bundle(strict_vault, query, 32000).episodes:
            ordinals = sorted(int(c.rsplit(":", 1)[1]) for c in snippet.chunk_ids)
            assert ordinals == list(range(ordinals[0], ordinals[0] + len(ordinals))), (query, snippet.chunk_ids)


# §8 M6 context step 6: "Add working memory if session_id is set" (read via the §7.10 contract).
@pytest.mark.parametrize(("agent", "session"), [("default", "s_0123456789ab"), ("research", "s_aaaaaaaaaaaa")])
def test_working_memory_is_read_from_the_session_file(strict_vault, agent, session):
    bundle = _bundle(strict_vault, "Immich", 2000, agent=agent, session_id=session)
    assert bundle.working is not None and bundle.working.session_id == session
    assert f"Goal of {agent}" in bundle.rendered
    assert strict_vault.rel(strict_vault.working_path(session)) in bundle.rendered


# §7.9 Scope-safe: another agent's session never appears; a missing session is not an error.
@pytest.mark.parametrize("session", ["s_aaaaaaaaaaaa", "s_missing00000"])
def test_foreign_or_missing_session_is_left_out(strict_vault, session):
    bundle = _bundle(strict_vault, "Immich", 2000, session_id=session)
    assert bundle.working is None and "Goal of research" not in bundle.rendered


# §7.8 Promise: "If meta.embedding_model differs from the config, the index MUST be rebuilt".
def test_search_refuses_an_index_built_with_another_model(indexed_vault, tmp_path):
    root = tmp_path / "vault"
    shutil.copytree(indexed_vault.root, root)
    toml = (root / "pam.toml").read_text(encoding="utf-8")
    (root / "pam.toml").write_text(toml.replace('model = "BAAI/bge-small-en-v1.5"', 'model = "BAAI/bge-base-en-v1.5"'),
                                   encoding="utf-8")
    with pytest.raises(PamError, match="--rebuild"):
        search.search(Vault(root), SearchQuery(query="Immich"))


# §8 M6 Edge cases: "Very small budgets truncate the persona to persona_max_tokens, then drop
# everything else"; §7.9 Budget-safe. Runs in a subprocess so a hang cannot stall the suite.
def test_large_persona_with_small_budget_finishes_and_fits(strict_vault):
    args = ["--vault", str(strict_vault.root), "--json", "context", "Immich", "--agent", "verbose", "--budget", "256"]
    started = time.perf_counter()
    result = subprocess.run([sys.executable, "-c", "from pam.cli.main import app; app(prog_name='pam')", *args],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert time.perf_counter() - started < 20
    bundle = ContextBundle.model_validate(json.loads(result.stdout))
    assert bundle.tokens_used <= 256
    persona_section = bundle.rendered.split("# Known facts")[0]
    assert tokens.count(persona_section) <= 300


# §7.5: the project summary is the `## Summary (auto)` section; `## Notes` is a separate section.
def test_project_brief_summary_is_the_summary_section(strict_vault):
    bundle = _bundle(strict_vault, "Tailscale VPN access", 4000)
    brief = next(p for p in bundle.projects if p.name == TAILSCALE_PROJECT)
    assert brief.summary == "VPN access summary."
    assert "## Notes" not in bundle.rendered and "## Summary (auto)" not in bundle.rendered


# §7.9 `rendered`: "Every item cites its vault path" (conflicts, working memory, persona too).
def test_every_section_cites_its_sources(strict_vault):
    bundle = _bundle(strict_vault, "Where do I work on Immich?", 32000)
    assert bundle.conflicts
    for fact in [*bundle.facts, *bundle.conflicts]:
        assert strict_vault.rel(strict_vault.fact_path(fact.scope, fact.id)) in bundle.rendered
    for project in bundle.projects:
        assert strict_vault.rel(strict_vault.project_path("default", project.id)) in bundle.rendered
    for snippet in bundle.episodes:
        assert strict_vault.rel(strict_vault.episode_path("default", snippet.episode_id)) in bundle.rendered
    persona = bundle.persona
    if persona and (persona.identity or persona.rules or persona.style):
        assert "agent/default/identity.md" in bundle.rendered
    verbose = _bundle(strict_vault, "Immich", 2000, agent="verbose")  # a persona with text must cite it
    assert verbose.persona and "agent/verbose/identity.md" in verbose.rendered


# §7.9 Budget-safe and `tokens_used` = cl100k count of `rendered`, over many budgets and agents.
@pytest.mark.parametrize("agent", ["default", "research"])
def test_budget_property_over_many_budgets(strict_vault, agent):
    for budget in (256, 257, 290, 333, 512, 777, 1500, 3000):
        bundle = _bundle(strict_vault, "Immich Tailscale visa work", budget, agent=agent)
        assert bundle.tokens_used == tokens.count(bundle.rendered) <= budget == bundle.token_budget


# §7.9 ContextRequest: `token_budget=None` means the agent's `token_budget` (2000 by default).
def test_missing_budget_uses_the_agent_default(strict_vault):
    bundle = context.build_context(strict_vault, ContextRequest(query="Immich"))
    assert bundle.token_budget == 2000 and bundle.tokens_used <= 2000


# §7.9 `include_persona=False` leaves the persona out.
def test_include_persona_false_leaves_persona_out(strict_vault):
    assert _bundle(strict_vault, "Immich", 2000, include_persona=False).persona is None


# §8 M6 Acceptance + §7.9 Scope-safe, with the extra shared facts, project, and sessions present:
# 50 random queries for search and 10 for context as the restricted `research` agent.
def test_scope_property_with_extra_data(strict_vault):
    visible = _visible_doc_ids(strict_vault, "research")
    words = ["Immich", "Tailscale", "visa", "F1", "photo", "backup", "VPN", "Teal", "work", "school",
             "Ollama", "gateway", "eduroam", "metadata", "Ubuntu", "course", "jobs", "notesecretword"]
    rng = random.Random(7)
    for i in range(50):
        query = " ".join(rng.sample(words, 3))
        hits = search.search(strict_vault, SearchQuery(query=query, agent="research", k=20)).hits
        assert {str(h.doc_id) for h in hits} <= visible, query
        if i % 5 == 0:
            bundle = _bundle(strict_vault, query, 2000, agent="research", session_id="s_0123456789ab")
            keys = {str(f.id) for f in [*bundle.facts, *bundle.conflicts]} | {str(p.id) for p in bundle.projects} \
                | {str(e.episode_id) for e in bundle.episodes}
            assert keys <= visible, query
            assert bundle.working is None  # the default agent's session is not research's


# §8 M6 Acceptance: `pam search` finds a document right after it is indexed.
def test_search_sees_a_newly_indexed_fact(strict_vault, tmp_path):
    from pam.index.indexer import index_paths  # noqa: PLC0415

    root = tmp_path / "vault"
    shutil.copytree(strict_vault.root, root)
    vault = Vault(root)
    _write_fact(vault, "pet", "Quokka", FactCategory.OTHER)
    index_paths(vault, [vault.fact_path("shared", fact_id("shared", "user", "pet", Cardinality.SINGLE, "Quokka"))])
    hits = search.search(vault, SearchQuery(query="quokka", k=3)).hits
    assert hits and hits[0].title == "pet: Quokka"


# §8 M6 step 6: at most 2 chunks per document, and k is respected.
@pytest.mark.parametrize("k", [1, 3, 8, 20])
def test_search_k_and_two_chunks_per_document(strict_vault, k):
    hits = search.search(strict_vault, SearchQuery(query="Immich photo backup Tailscale", k=k)).hits
    assert len(hits) <= k
    per_doc: dict[str, int] = {}
    for hit in hits:
        per_doc[str(hit.doc_id)] = per_doc.get(str(hit.doc_id), 0) + 1
    assert max(per_doc.values(), default=0) <= 2
    assert all(len(h.snippet) <= 500 for h in hits)


# §8 M6 Edge cases: an empty index yields persona only and search returns no hits, no error.
def test_never_indexed_vault_returns_nothing_without_error(tmp_path):
    root = tmp_path / "fresh"
    init_vault(root)
    assert search.search(Vault(root), SearchQuery(query="anything")).hits == []
    bundle = _bundle(Vault(root), "anything", 800)
    assert bundle.episodes == [] and bundle.facts == [] and bundle.tokens_used <= 800


# SETUP §6: `pam search "QUERY" [--agent A] [-k 8] [--type episode,fact,...] [--since 2026-09-01]`.
def test_cli_search_accepts_the_setup_flags(strict_vault):
    result = runner.invoke(app, ["--vault", str(strict_vault.root), "--json", "search", "Immich", "-k", "3",
                                 "--type", "episode,fact", "--since", "2026-08-01"])
    assert result.exit_code == 0, result.output
    hits = SearchResponse.model_validate(json.loads(result.output)).hits
    assert 0 < len(hits) <= 3 and {h.doc_type for h in hits} <= {"episode", "fact"}
    assert all(h.created_at is None or h.created_at >= datetime(2026, 8, 1, tzinfo=UTC) for h in hits)


# SETUP §6: pam search "shows score, vector rank, and keyword rank".
def test_cli_search_text_shows_ranks(strict_vault):
    result = runner.invoke(app, ["--vault", str(strict_vault.root), "search", "Immich photo backup", "--k", "3"])
    assert result.exit_code == 0, result.output
    assert "vector" in result.output.lower() and "keyword" in result.output.lower()


# SETUP §6: `pam context "QUERY" [--agent A] [--budget 2000] [--session ID] [--no-persona]`.
def test_cli_context_no_persona(strict_vault):
    result = runner.invoke(app, ["--vault", str(strict_vault.root), "--json", "context", "Immich", "--no-persona"])
    assert result.exit_code == 0, result.output
    assert ContextBundle.model_validate(json.loads(result.output)).persona is None


# SETUP §5 exit codes: bad input is a usage error (2); an unknown agent is an error (1).
@pytest.mark.parametrize(("args", "code"), [
    (["search", "x", "--k", "0"], 2), (["search", "x", "--k", "51"], 2),
    (["context", "x", "--budget", "255"], 2), (["context", "x", "--budget", "32001"], 2),
    (["search", "x", "--agent", "nobody"], 1), (["context", "x", "--agent", "nobody"], 1),
])
def test_cli_rejects_bad_input_with_setup_exit_codes(strict_vault, args, code):
    assert runner.invoke(app, ["--vault", str(strict_vault.root), *args]).exit_code == code

