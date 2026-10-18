"""M5 clusterer and graph tests (SPEC §7.5, §7.12, §8 M5, §9.3 T10).

Behavior:
    Uses an offline topic embedder: words from three fixture topics (Immich, Tailscale,
    university) load one shared dimension each, every other word a small hashed one, so the Claude
    and ChatGPT fixtures form topic clusters without downloading a model. Small vaults are built
    with `writer.log_episode`, which indexes through the same embedder.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
import pytest
from typer.testing import CliRunner

from pam.agents.manifest import create_agent
from pam.cli.main import app
from pam.cluster import assign, naming
from pam.cluster.cluster import run_cluster
from pam.cluster.graph import build_graph
from pam.contracts.agent import READ_TOOLS, AgentManifest, ReadScope
from pam.contracts.common import Actor
from pam.contracts.fact import Cardinality, Fact, FactCategory, fact_id
from pam.contracts.graph import GraphData
from pam.contracts.project import Project
from pam.contracts.raw import RawMessage
from pam.contracts.reports import ClusterReport
from pam.contracts.writes import LogEpisodeInput, UpdateProjectInput
from pam.core import mdio
from pam.core.vault import Vault, init_vault
from pam.index import embedder, indexer
from pam.memory import writer

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = FIXTURES / "claude" / "export.zip"
CHATGPT = FIXTURES / "chatgpt" / "export.zip"
NOW = datetime(2026, 10, 18, 12, tzinfo=UTC)
runner = CliRunner()

TOPICS = {
    0: "immich photo photos backup backups backing metadata library exif album",
    1: "tailscale vpn ollama eduroam llm gateway caddy tailnet",
    2: "visa course campus uw jobs job winter cse cds f1 student",
}
TOPIC_OF = {w: dim for dim, words in TOPICS.items() for w in words.split()}


class _TopicEmbedder:
    """Deterministic bag-of-words embedder with one strong dimension per fixture topic."""

    model_name = "BAAI/bge-small-en-v1.5"
    dim = 384

    def embed_documents(self, texts):
        rows = np.zeros((len(texts), 384))
        for row, text in zip(rows, texts):
            for word in re.findall(r"[a-z0-9]+", text.lower()):
                if word in TOPIC_OF:
                    row[TOPIC_OF[word]] += 1.0
                else:
                    row[8 + int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % 376] += 0.05
            row[:] = np.log1p(row)
            if not row.any():
                row[383] = 1.0
        return embedder.l2_normalize(rows)

    def embed_query(self, text):
        return self.embed_documents([text])[0]


@pytest.fixture(autouse=True)
def _topic_embedder(monkeypatch):
    fake = _TopicEmbedder()
    monkeypatch.setattr(indexer, "get_embedder", lambda cfg: fake)


def _invoke(root: Path, *args: str):
    result = runner.invoke(app, ["--vault", str(root), *args])
    assert result.exit_code == 0, result.output + repr(result.exception)
    return result


def _head(vault: Vault) -> str:
    return subprocess.run(
        ["git", "-C", str(vault.root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _projects(vault: Vault, scope: str = "default") -> dict[str, tuple[Project, str]]:
    out = {}
    for path in sorted(vault.memory_dir(scope).glob("projects/*.md")):
        project, body = mdio.read_model(path, Project)
        out[str(project.id)] = (project, body)
    return out


def _new_vault(tmp_path: Path) -> Vault:
    root = tmp_path / "vault"
    init_vault(root)
    return Vault(root)


def _log(vault: Vault, title: str, text: str, when: datetime = NOW) -> UUID:
    data = LogEpisodeInput(title=title, messages=[
        RawMessage(role="user", text=text, created_at=when),
        RawMessage(role="assistant", text="Noted.", created_at=when),
    ])
    result = writer.log_episode(vault, data)
    assert result.ok, result.message
    return result.doc_id


IMMICH = [
    ("Immich setup", "How do I install immich for photo backup?"),
    ("Immich backups", "My immich backup misses photo metadata."),
    ("Immich library", "Immich library and photo album import."),
    ("Immich exif", "Immich exif metadata for photo backup."),
]


@pytest.fixture(scope="module")
def fixture_vault(tmp_path_factory) -> Vault:
    """Import and index the Claude and ChatGPT fixtures once; tests copy it before writing."""
    mp = pytest.MonkeyPatch()
    mp.setattr(indexer, "get_embedder", lambda cfg: _TopicEmbedder())
    root = tmp_path_factory.mktemp("m05") / "vault"
    init_vault(root)
    for fixture in (CLAUDE, CHATGPT):
        _invoke(root, "import", "run", str(fixture))
    _invoke(root, "index")
    mp.undo()
    return Vault(root)


@pytest.fixture
def vault(fixture_vault, tmp_path) -> Vault:
    dest = tmp_path / "vault"
    subprocess.run(["cp", "-R", str(fixture_vault.root), str(dest)], check=True)
    return Vault(dest)


# -- naming ------------------------------------------------------------------------------------

def test_ctfidf_top_term_on_hand_corpus():
    ranked = naming.ctfidf([
        "sqlite vec index sqlite vec rag",
        "photo backup photo immich backup photo",
        "visa visa course",
    ])
    assert ranked[0][0] == "sqlite vec" or ranked[0][0] in {"sqlite", "vec"}
    assert ranked[1][0] == "photo"
    assert ranked[2][0] == "visa"
    assert all(len(r) <= naming.TOP_KEYWORDS for r in ranked)


def test_ctfidf_shared_term_ranks_below_distinct_term():
    ranked = naming.ctfidf(["server immich. immich", "server tailscale. tailscale"], top_n=20)
    assert ranked[0][0] == "immich" and ranked[1][0] == "tailscale"
    assert ranked[0].index("server") > ranked[0].index("immich")


def test_ctfidf_stop_words_only_gives_empty_keywords():
    assert naming.ctfidf(["the and of", "is was"]) == [[], []]


def test_name_uses_frequent_title_ngram():
    titles = ["Setting up Immich on Ubuntu", "Backing up Immich photos", "Immich job queue", "Router reset"]
    assert naming.project_name(titles, ["photos", "immich"]) == "Immich"


def test_name_falls_back_to_top_two_keywords():
    titles = ["Alpha one", "Beta two", "Gamma three", "Delta four"]
    assert naming.project_name(titles, ["sqlite vec", "rag pipeline", "other"]) == "Sqlite Vec · Rag Pipeline"


def test_name_needs_two_titles_and_keeps_capitals():
    assert naming.project_name(["Finding winter jobs", "Course prep", "Visa check"], ["cse", "cds"],
                               ["I take CSE and CDS"]) == "CSE · CDS"
    assert naming.project_name(["UW CS prep", "UW CS jobs", "Other"], []) == "UW CS"


def test_replace_summary_keeps_notes_byte_exact():
    body = "## Summary (auto)\nold text\n\n## Notes\n- 2026-10-01T10:00Z (agent:default) keep me\n"
    member = naming.Member("Immich setup", "", NOW)
    new = naming.replace_summary(body, naming.summary_section(["immich"], [member]))
    assert new.endswith("## Notes\n- 2026-10-01T10:00Z (agent:default) keep me\n")
    assert "old text" not in new and "- 2026-10-18 Immich setup" in new
    assert "Date range: 2026-10-18 to 2026-10-18 (1 episode)" in new


def test_summary_lists_five_most_recent_titles():
    members = [naming.Member(f"T{i}", "", NOW - timedelta(days=i)) for i in range(7)]
    section = naming.summary_section(["k"], members)
    assert [line for line in section.splitlines() if line.startswith("- ")] == [
        f"- {(NOW - timedelta(days=i)).date()} T{i}" for i in range(5)
    ]


# -- assign ------------------------------------------------------------------------------------

def test_cluster_labels_noise_and_small_inputs():
    rng = np.random.default_rng(0)
    base = embedder.l2_normalize(np.eye(4, 16))
    near = [embedder.l2_normalize((base[i] + 0.02 * rng.standard_normal(16))[None])[0] for i in (0, 0, 0, 0, 1, 1, 1, 1)]
    outlier = base[3]
    labels = assign.cluster_labels(np.stack([*near, outlier]), 3)
    assert labels[-1] == assign.NOISE
    assert len(set(labels[:4])) == 1 and len(set(labels[4:8])) == 1 and labels[0] != labels[4]
    assert assign.cluster_labels(np.stack(near[:2]), 3) == [assign.NOISE, assign.NOISE]


def test_assign_incremental_threshold_and_running_mean():
    a, b = np.array([1.0, 0.0]), np.array([0.0, 1.0])
    near_a = np.array([0.9, 0.436])
    chosen = assign.assign_incremental([("e1", near_a), ("e2", b)], {"p": [a]}, 0.6)
    assert chosen == {"e1": "p"}


def test_match_clusters_jaccard_threshold():
    old = {"p1": {"a", "b", "c", "d"}, "p2": {"x", "y"}}
    matched = assign.match_clusters([{"a", "b", "c"}, {"x", "z", "w"}], old, 0.5)
    assert matched == {0: "p1"}


# -- clustering on the fixtures ----------------------------------------------------------------

def test_fixtures_give_projects_with_sensible_keywords(vault):
    report = run_cluster(vault)
    projects = _projects(vault)
    assert report.projects_created >= 2 and len(projects) == report.projects_created
    assert report.commit_sha == _head(vault)
    immich = [p for p, _ in projects.values() if {"immich", "backup"} & set(p.keywords)]
    assert immich and "Immich" in immich[0].name
    assert all(p.origin is Actor.CLUSTER and 1 <= len(p.keywords) <= 5 for p, _ in projects.values())
    owners = [e for p, _ in projects.values() for e in p.episode_ids]
    assert len(owners) == len(set(owners))  # at most one project per episode
    log = subprocess.run(["git", "-C", str(vault.root), "log", "-1", "--format=%s"], capture_output=True, text=True)
    assert log.stdout.strip() == f"cluster: incremental +{report.projects_created} ~0"


def test_summary_and_notes_sections(vault):
    run_cluster(vault)
    for project, body in _projects(vault).values():
        assert body.startswith("## Summary (auto)\n")
        assert "Keywords: " in body and "Recent episodes:" in body and "Date range: " in body
        assert body.rstrip().endswith("## Notes")


def test_second_cluster_is_a_noop(vault):
    run_cluster(vault)
    head = _head(vault)
    again = run_cluster(vault)
    assert (again.projects_created, again.projects_updated, again.episodes_assigned) == (0, 0, 0)
    assert again.commit_sha is None and _head(vault) == head


def test_rebuild_keeps_project_ids(vault):
    run_cluster(vault)
    before = {pid: set(p.episode_ids) for pid, (p, _) in _projects(vault).items()}
    report = run_cluster(vault, rebuild=True)
    after = {pid: set(p.episode_ids) for pid, (p, _) in _projects(vault).items()}
    assert report.mode == "rebuild" and report.projects_created == 0
    assert set(after) == set(before)
    assert after == before


def test_centroids_are_stored_normalized(vault):
    run_cluster(vault)
    from pam.index import db
    conn = db.connect(vault)
    rows = conn.execute("SELECT project_id, embedding FROM project_centroids").fetchall()
    conn.close()
    assert {r[0] for r in rows} == set(_projects(vault))
    for _, blob in rows:
        assert abs(np.linalg.norm(np.frombuffer(blob, dtype=np.float32)) - 1) < 1e-5


def test_new_episode_joins_existing_project(vault):
    run_cluster(vault)
    eid = _log(vault, "Immich restore", "Restore immich photo backup with metadata.")
    report = run_cluster(vault)
    assert report.projects_created == 0 and report.episodes_assigned == 1 and report.projects_updated == 1
    owner = [p for p, _ in _projects(vault).values() if eid in p.episode_ids]
    assert owner and {"immich", "backup"} & set(owner[0].keywords)


def test_cli_cluster_json_and_graph_export(vault, tmp_path):
    out = _invoke(vault.root, "--json", "cluster")
    report = ClusterReport.model_validate_json(out.stdout)
    assert report.projects_created >= 2
    again = ClusterReport.model_validate_json(_invoke(vault.root, "--json", "cluster").stdout)
    assert again.projects_created == again.projects_updated == 0
    rebuilt = ClusterReport.model_validate_json(_invoke(vault.root, "--json", "cluster", "--rebuild").stdout)
    assert rebuilt.projects_created == 0
    target = tmp_path / "g.json"
    _invoke(vault.root, "graph", "export", "--out", str(target))
    graph = GraphData.model_validate_json(target.read_text())
    assert sum(n.type == "project" for n in graph.nodes) == report.projects_created


# -- edge cases on small vaults ----------------------------------------------------------------

def test_fewer_than_min_cluster_size_gives_no_projects(tmp_path):
    vault = _new_vault(tmp_path)
    _log(vault, *IMMICH[0])
    _log(vault, *IMMICH[1])
    head = _head(vault)
    report = run_cluster(vault)
    assert report.projects_created == 0 and report.episodes_unassigned == 2
    assert report.commit_sha is None and _head(vault) == head and not _projects(vault)


def test_noise_episode_stays_unassigned(tmp_path):
    vault = _new_vault(tmp_path)
    ids = [_log(vault, t, x) for t, x in IMMICH]
    zebra = _log(vault, "Zebra facts", "Zebras have stripes and gallop quickly.")
    report = run_cluster(vault)
    projects = _projects(vault)
    assert report.projects_created == 1 and report.episodes_unassigned == 1
    (project, _), = projects.values()
    assert set(project.episode_ids) == set(ids) and zebra not in project.episode_ids
    assert project.name == "Immich"


def test_agent_project_is_never_renamed(tmp_path):
    vault = _new_vault(tmp_path)
    ids = [_log(vault, t, x) for t, x in IMMICH]
    made = writer.update_project(vault, UpdateProjectInput(name="My photo stuff", add_episode_ids=ids[:2], note="mine"))
    assert made.ok
    for rebuild in (False, True, False):
        run_cluster(vault, rebuild=rebuild)
        project, body = _projects(vault)[str(made.doc_id)]
        assert project.name == "My photo stuff" and project.origin is Actor.AGENT
        assert "(agent:default) mine" in body and "## Summary (auto)" in body
    owners = [e for p, _ in _projects(vault).values() for e in p.episode_ids]
    assert len(owners) == len(set(owners))


def test_rebuild_unmatched_project_goes_dormant_with_note(tmp_path):
    vault = _new_vault(tmp_path)
    ids = [_log(vault, t, x) for t, x in IMMICH]
    zebra = _log(vault, "Zebra facts", "Zebras have stripes and gallop quickly.")
    old_id = uuid4()
    mdio.write(vault.project_path("default", old_id), Project(
        id=old_id, scope="default", name="Mixed bag", episode_ids=[zebra, ids[0]], origin=Actor.CLUSTER,
        created_at=NOW, updated_at=NOW, last_activity_at=NOW,
    ), "## Summary (auto)\n\n## Notes\n")
    report = run_cluster(vault, rebuild=True)
    old, body = _projects(vault)[str(old_id)]
    assert report.projects_created == 1 and report.projects_updated == 1
    assert old.status == "dormant" and old.episode_ids == [] and old.name == "Mixed bag"
    assert "(cluster) Dormant after `cluster --rebuild`" in body
    assert run_cluster(vault, rebuild=True).commit_sha is None


def test_dormant_after_configured_days(tmp_path):
    vault = _new_vault(tmp_path)
    for t, x in IMMICH:
        _log(vault, t, x)
    run_cluster(vault)
    (project, _), = _projects(vault).values()
    assert project.status == "active"
    later = project.last_activity_at + timedelta(days=31)
    report = run_cluster(vault, now=later)
    (project, _), = _projects(vault).values()
    assert project.status == "dormant" and report.projects_updated == 1


# -- graph -------------------------------------------------------------------------------------

def _facts_on(vault: Vault, episode: UUID) -> UUID:
    fid = fact_id("shared", "user", "school", Cardinality.SINGLE, "UW")
    mdio.write(vault.fact_path("shared", fid), Fact(
        id=fid, scope="shared", attribute="school", value="UW", cardinality=Cardinality.SINGLE,
        category=FactCategory.EDUCATION, confidence=0.9, source_episode=episode, extractor=Actor.MANUAL,
        created_at=NOW, updated_at=NOW,
    ), "**school**: UW\n")
    return fid


def test_graph_validates_and_links_resolve(vault):
    run_cluster(vault)
    graph = build_graph(vault)
    GraphData.model_validate_json(graph.model_dump_json())
    ids = {n.id for n in graph.nodes}
    assert len(ids) == len(graph.nodes)
    assert all(link.source in ids and link.target in ids for link in graph.links)
    assert not any(n.type == "fact" for n in graph.nodes)
    projects = _projects(vault)
    members = sum(len(p.episode_ids) for p, _ in projects.values())
    assert sum(link.kind == "member" for link in graph.links) == members
    for node in graph.nodes:
        if node.type == "project":
            assert node.size == len(projects[node.id][0].episode_ids) and node.cluster_id == node.id
    similar = [(link.source, link.target) for link in graph.links if link.kind == "similar"]
    assert len(similar) == len({frozenset(p) for p in similar})
    assert similar and all(link.weight >= 0.75 for link in graph.links if link.kind == "similar")


def test_graph_facts_flag_adds_fact_nodes(vault):
    run_cluster(vault)
    episode = next(n for n in build_graph(vault).nodes if n.type == "episode")
    fid = _facts_on(vault, UUID(episode.id))
    graph = build_graph(vault, facts=True)
    assert any(n.id == str(fid) and n.type == "fact" for n in graph.nodes)
    assert any(lk.kind == "derived_from" and lk.source == str(fid) and lk.target == episode.id for lk in graph.links)
    ids = {n.id for n in graph.nodes}
    assert all(link.source in ids and link.target in ids for link in graph.links)


def test_restricted_agent_graph_excludes_out_of_scope(vault):
    run_cluster(vault)
    projects = _projects(vault)
    pid, (project, _) = next((k, v) for k, v in projects.items() if "Immich" in v[0].name)
    create_agent(AgentManifest(
        name="research", display_name="Research", origin="custom", created_at=NOW,
        read=ReadScope(project_ids=[UUID(pid)], include_shared_facts=False), write="own",
        tools=sorted(READ_TOOLS),
    ), vault)
    graph = build_graph(vault, agent="research", facts=True)
    episodes = {n.id for n in graph.nodes if n.type == "episode"}
    assert episodes == {str(e) for e in project.episode_ids}
    assert {n.id for n in graph.nodes if n.type == "project"} == {pid}
    assert graph.agent == "research"
    ids = {n.id for n in graph.nodes}
    assert all(link.source in ids and link.target in ids for link in graph.links)


def test_graph_cli_stdout_json(vault):
    out = _invoke(vault.root, "graph", "export", "--facts")
    data = json.loads(out.stdout)
    GraphData.model_validate(data)


def test_agent_note_counts_as_activity(tmp_path):
    vault = _new_vault(tmp_path)
    for t, x in IMMICH:
        _log(vault, t, x)
    run_cluster(vault)
    (project, _), = _projects(vault).values()
    time.sleep(1.1)  # the note must land on a later second than the episodes
    assert writer.update_project(vault, UpdateProjectInput(project_id=project.id, note="still on it")).ok
    noted, _ = _projects(vault)[str(project.id)]
    assert noted.last_activity_at > project.last_activity_at
    report = run_cluster(vault, rebuild=True)
    after, body = _projects(vault)[str(project.id)]
    assert after.last_activity_at == noted.last_activity_at and "still on it" in body
    assert report.projects_updated == 0 and report.commit_sha is None
