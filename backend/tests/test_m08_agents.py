"""M8 agents and permissions tests (SPEC §8 M8, §9.3 T05).

Behavior:
    Drives `pam agent create|list|show|set-scope|check` through Typer's `CliRunner` on `tmp_path`
    vaults, checks persona parsing and the `rules.md` format (CHG-0002), and checks the permission
    helpers against an in-memory §7.8 `documents` table. The M8 acceptance is proven at the
    function level here; T07 and T09 re-check it through `pam search` and `pam fact add`.
"""

import json
import random
import sqlite3
import subprocess
from datetime import datetime, timezone
from uuid import UUID

import pytest
import yaml
from typer.testing import CliRunner

from pam.agents import manifest as agents
from pam.agents.permissions import (
    WRITE_TOOLS, DocRef, can_call, can_read, can_write, can_write_path, doc_ref_from_path,
    visible_doc_filter,
)
from pam.cli.main import app
from pam.contracts.agent import READ_TOOLS, AgentManifest, PersonaRule, ReadScope
from pam.contracts.common import Actor
from pam.contracts.project import Project
from pam.core import mdio
from pam.core.vault import PERSONA_TEMPLATE, Vault, default_manifest, init_vault, set_vault_override

NOW = datetime(2026, 10, 1, 18, 4, 11, tzinfo=timezone.utc)
P1 = UUID("11111111-1111-4111-8111-111111111111")
P2 = UUID("22222222-2222-4222-8222-222222222222")
EP1 = UUID("aaaaaaaa-0000-4000-8000-000000000001")   # in P1
EP2 = UUID("aaaaaaaa-0000-4000-8000-000000000002")   # in P2
EP3 = UUID("aaaaaaaa-0000-4000-8000-000000000003")   # research's own episode
EV = [UUID(f"bbbbbbbb-0000-4000-8000-00000000000{i}") for i in range(1, 4)]

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clean_vault_env(monkeypatch):
    monkeypatch.delenv("PAM_VAULT", raising=False)
    set_vault_override(None)
    yield
    set_vault_override(None)


@pytest.fixture
def vault(tmp_path) -> Vault:
    init_vault(tmp_path / "v")
    return Vault(tmp_path / "v")


def pam(vault: Vault, *args: str):
    return runner.invoke(app, ["--vault", str(vault.root), *args])


def commits(vault: Vault) -> int:
    out = subprocess.run(["git", "-C", str(vault.root), "rev-list", "--count", "HEAD"],
                         capture_output=True, text=True, check=True)
    return int(out.stdout)


def _agent(name="research", **read) -> AgentManifest:
    return AgentManifest(
        name=name, display_name=name, origin="custom", created_at=NOW,
        read=ReadScope(**read), write="own", tools=sorted(READ_TOOLS),
    )


def _project(vault: Vault, pid: UUID, episodes: list[UUID], scope="default") -> None:
    mdio.write(vault.project_path(scope, pid), Project(
        id=pid, scope=scope, name=str(pid)[:4], episode_ids=episodes, origin=Actor.CLUSTER,
        created_at=NOW, updated_at=NOW, last_activity_at=NOW,
    ), "")


# -- documents table (§7.8 subset) -----------------------------------------------------------

DOCS = [
    # (doc_id, doc_type, scope)
    (str(EP1), "episode", "default"),
    (str(EP2), "episode", "default"),
    (str(EP3), "episode", "research"),
    (str(P1), "project", "default"),
    (str(P2), "project", "default"),
    ("f-shared", "fact", "shared"),
    ("f-default", "fact", "default"),
    ("f-research", "fact", "research"),
    ("s-default", "skill", "default"),
    ("s-research", "skill", "research"),
    ("s-coder", "skill", "coder"),
]


@pytest.fixture
def db() -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE documents (doc_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL, scope TEXT NOT NULL, "
        "path TEXT NOT NULL UNIQUE, title TEXT, created_at TEXT, content_sha256 TEXT NOT NULL, "
        "token_count INTEGER NOT NULL, indexed_at TEXT NOT NULL)"
    )
    con.executemany(
        "INSERT INTO documents VALUES (?, ?, ?, ?, NULL, NULL, 'x', 1, 'now')",
        [(i, t, s, f"{t}/{s}/{i}.md") for i, t, s in DOCS],
    )
    return con


@pytest.fixture
def projects(vault):
    _project(vault, P1, [EP1])
    _project(vault, P2, [EP2])
    return vault


def visible(con, agent, vault, alias="documents") -> set[str]:
    sql, params = visible_doc_filter(agent, vault, alias=alias)
    table = "documents" if alias in ("documents", "") else f"documents AS {alias}"
    return {r[0] for r in con.execute(f"SELECT doc_id FROM {table} WHERE {sql}", params)}


# -- CLI: create / list / show ---------------------------------------------------------------

def test_create_writes_files_and_one_commit(vault):
    before = commits(vault)
    r = pam(vault, "agent", "create", "research", "--projects", f"{P1}", "--description", "R")
    assert r.exit_code == 0, r.output
    assert commits(vault) == before + 1
    m = agents.load_manifest("research", vault)
    assert m.origin == "custom" and m.read.project_ids == [P1] and m.write == "own"
    assert set(m.tools) == READ_TOOLS | WRITE_TOOLS
    for kind in ("identity", "rules", "style"):
        assert vault.persona_path("research", kind).read_text(encoding="utf-8") == PERSONA_TEMPLATE
    assert (vault.memory_dir("research") / "episodes").is_dir()
    assert (vault.root / "skills" / "research").is_dir()
    log = subprocess.run(["git", "-C", str(vault.root), "log", "-1", "--format=%an %s"],
                         capture_output=True, text=True, check=True).stdout.strip()
    assert log == "PAM pam: create agent research"


def test_create_write_none_gets_read_tools_only(vault):
    assert pam(vault, "agent", "create", "reader", "--write", "none").exit_code == 0
    assert set(agents.load_manifest("reader", vault).tools) == READ_TOOLS


def test_create_duplicate_exits_1(vault):
    assert pam(vault, "agent", "create", "research").exit_code == 0
    assert pam(vault, "agent", "create", "research").exit_code == 1
    assert pam(vault, "agent", "create", "default").exit_code == 1


@pytest.mark.parametrize("args", [
    ["shared"], ["Bad"], ["-x"], ["ok", "--projects", "nope"], ["ok", "--tools", "rm_rf"],
    ["ok", "--write", "all"], ["ok", "--budget", "10"],
])
def test_create_invalid_exits_2(vault, args):
    before = commits(vault)
    assert pam(vault, "agent", "create", *args).exit_code == 2
    assert commits(vault) == before


def test_create_warns_on_missing_project(vault):
    r = pam(vault, "agent", "create", "research", "--projects", str(P2))
    assert r.exit_code == 0 and "Warning: project" in r.output


def test_list_and_show_json(vault):
    pam(vault, "agent", "create", "research")
    r = pam(vault, "--json", "agent", "list")
    assert r.exit_code == 0
    names = [AgentManifest.model_validate(d).name for d in json.loads(r.output)]
    assert names == ["default", "research"]
    r = pam(vault, "--json", "agent", "show", "research")
    data = json.loads(r.output)
    assert AgentManifest.model_validate(data["manifest"]).name == "research"
    assert data["persona"]["agent"] == "research"
    assert pam(vault, "agent", "show", "research").exit_code == 0
    assert pam(vault, "agent", "list").output.startswith("default")


def test_show_missing_agent_exits_1(vault):
    assert pam(vault, "agent", "show", "ghost").exit_code == 1


def test_manifest_major_version_exits_2(vault):
    pam(vault, "agent", "create", "research")
    path = vault.manifest_path("research")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["schema_version"] = "2.0.0"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert pam(vault, "agent", "show", "research").exit_code == 2


# -- CLI: set-scope --------------------------------------------------------------------------

def test_set_scope_one_commit_then_noop(vault):
    pam(vault, "agent", "create", "research", "--projects", str(P1))
    before = commits(vault)
    r = pam(vault, "agent", "set-scope", "research", "--projects", f"{P1},{P2}",
            "--no-shared-facts", "--write", "shared", "--tools", "search_memory,add_fact")
    assert r.exit_code == 0, r.output
    assert commits(vault) == before + 1
    m = agents.load_manifest("research", vault)
    assert m.read.project_ids == [P1, P2] and not m.read.include_shared_facts
    assert m.write == "shared" and m.tools == ["search_memory", "add_fact"]
    r = pam(vault, "agent", "set-scope", "research", "--write", "shared")
    assert "No changes" in r.output and commits(vault) == before + 1


def test_set_scope_replaces_and_clears_projects(vault):
    pam(vault, "agent", "create", "research", "--projects", str(P1))
    pam(vault, "agent", "set-scope", "research", "--projects", str(P2))
    assert agents.load_manifest("research", vault).read.project_ids == [P2]
    pam(vault, "agent", "set-scope", "research", "--projects", "")
    assert agents.load_manifest("research", vault).read.project_ids == []


def test_set_scope_refuses_default_and_bad_values(vault):
    before = commits(vault)
    assert pam(vault, "agent", "set-scope", "default", "--write", "none").exit_code == 1
    pam(vault, "agent", "create", "research")
    assert pam(vault, "agent", "set-scope", "research", "--write", "all").exit_code == 2
    assert pam(vault, "agent", "set-scope", "ghost", "--write", "own").exit_code == 1
    assert commits(vault) == before + 1


# -- persona files ---------------------------------------------------------------------------

def test_split_sections_template_is_empty():
    assert agents.split_sections(PERSONA_TEMPLATE) == ("", "")


@pytest.mark.parametrize("text,expected", [
    ("## Derived (x)\nD1\n\n## Custom (y)\nC1\n", ("D1", "C1")),
    ("just my notes\n", ("", "just my notes")),
    ("pre\n## Derived\nD\n## Custom\nC\n", ("D", "pre\nC")),
    ("## Custom\nC\n## Derived\nD\n", ("D", "C")),
    ("## Derived\nonly derived\n", ("only derived", "")),
])
def test_split_sections_cases(text, expected):
    assert agents.split_sections(text) == expected


def test_replace_derived_keeps_custom_byte_exact():
    custom = "## Custom (yours)\n  keep   this\r\nexactly\n\n"
    text = "## Derived (auto)\nold line\n\n" + custom
    new = agents.replace_derived(text, "new line")
    assert new == "## Derived (auto)\n\nnew line\n\n" + custom
    assert new.endswith(custom)
    assert agents.replace_derived(PERSONA_TEMPLATE, "") == PERSONA_TEMPLATE


def test_replace_derived_inserts_heading_when_missing():
    new = agents.replace_derived("my notes\n", "D")
    assert agents.split_sections(new) == ("D", "my notes")
    assert new.endswith("my notes\n")
    again = agents.replace_derived(new, "D2")
    assert agents.split_sections(again) == ("D2", "my notes")
    custom_first = "## Custom (yours)\nC\n"
    assert agents.replace_derived(custom_first, "D").endswith(custom_first)
    assert agents.split_sections(agents.replace_derived(custom_first, "D")) == ("D", "C")


def test_rule_id_is_normalized_and_deterministic():
    assert agents.rule_id("Don't use  bullet points.") == agents.rule_id(" don't use bullet POINTS. ")
    assert agents.rule_id("a").startswith("r_") and len(agents.rule_id("a")) == 10


@pytest.mark.parametrize("rule", [
    PersonaRule(id=agents.rule_id("No emojis."), text="No emojis.", origin="derived",
                evidence_count=3, evidence_episodes=EV),
    PersonaRule(id=agents.rule_id("Keep it short."), text="Keep it short.", origin="derived",
                evidence_count=2),
])
def test_derived_rule_round_trip(rule):
    line = agents.format_rule(rule)
    assert "<!--" in line
    assert agents.parse_rules(line, "") == [rule]


def test_custom_plain_bullets_are_manual_rules():
    rules = agents.parse_rules("", "Intro text.\n- Always answer in British English.\n* Cite sources.\n")
    assert [(r.text, r.origin, r.evidence_count) for r in rules] == [
        ("Always answer in British English.", "manual", 0), ("Cite sources.", "manual", 0),
    ]
    assert rules[0].id == agents.rule_id("Always answer in British English.")
    assert agents.format_rule(rules[0]) == "- Always answer in British English."


def test_rule_meta_skips_bad_episode_ids_and_caps_at_five():
    eps = ",".join([str(EV[0]), "junk"] + [str(UUID(int=i)) for i in range(1, 7)])
    [rule] = agents.parse_rules(f"- X. <!-- r_deadbeef evidence=9 episodes={eps} -->", "")
    assert rule.id == "r_deadbeef" and rule.evidence_count == 9
    assert len(rule.evidence_episodes) == 5 and rule.evidence_episodes[0] == EV[0]


def test_load_persona_derived_then_custom(vault):
    pam(vault, "agent", "create", "research")
    for kind in ("identity", "style"):
        path = vault.persona_path("research", kind)
        path.write_text(agents.replace_derived(PERSONA_TEMPLATE, f"{kind} derived") + f"{kind} custom\n",
                        encoding="utf-8")
    rule = PersonaRule(id="r_00000001", text="No emojis.", origin="derived", evidence_count=2)
    vault.persona_path("research", "rules").write_text(
        agents.replace_derived(PERSONA_TEMPLATE, agents.format_rule(rule)) + "- Be direct.\n", encoding="utf-8")
    p = agents.load_persona("research", vault)
    assert p.identity == "identity derived\n\nidentity custom"
    assert p.style == "style derived\n\nstyle custom"
    assert [r.origin for r in p.rules] == ["derived", "manual"] and p.rules[0] == rule


def test_load_persona_missing_files_read_empty(vault):
    pam(vault, "agent", "create", "research")
    vault.persona_path("research", "style").unlink()
    assert agents.load_persona("research", vault).style == ""
    with pytest.raises(Exception):
        agents.load_persona("ghost", vault)


# -- visible_doc_filter / can_read -----------------------------------------------------------

@pytest.mark.parametrize("read,expected", [
    (dict(all=True), {d[0] for d in DOCS}),
    (dict(), {str(EP3), "f-research", "s-research", "f-shared"}),
    (dict(include_shared_facts=False), {str(EP3), "f-research", "s-research"}),
    (dict(include_own_memory=False), {"f-shared"}),
    (dict(include_own_memory=False, include_shared_facts=False), set()),
    (dict(include_own_memory=False, include_shared_facts=False, project_ids=[P1]), {str(P1), str(EP1)}),
    (dict(include_own_memory=False, include_shared_facts=False, include_skills_from=["coder", "default"]),
     {"s-coder", "s-default"}),
])
def test_filter_matrix(db, projects, read, expected):
    agent = _agent(**read)
    assert visible(db, agent, projects) == expected
    for doc_id, doc_type, scope in DOCS:
        assert can_read(agent, DocRef(doc_id, doc_type, scope), projects) == (doc_id in expected)


def test_filter_nothing_visible_is_false_condition(vault):
    agent = _agent(include_own_memory=False, include_shared_facts=False)
    assert visible_doc_filter(agent, vault) == ("0=1", [])


def test_filter_alias_and_rejects_bad_alias(db, projects):
    agent = _agent(project_ids=[P1])
    assert visible(db, agent, projects, alias="d") == visible(db, agent, projects)
    assert visible(db, agent, projects, alias="") == visible(db, agent, projects)
    with pytest.raises(ValueError):
        visible_doc_filter(agent, projects, alias="d; DROP TABLE documents")


def test_filter_missing_project_file_adds_nothing(db, vault):
    agent = _agent(include_own_memory=False, include_shared_facts=False, project_ids=[P1])
    assert visible(db, agent, vault) == {str(P1)}


def test_can_read_accepts_rows_dicts_and_search_hits(db, projects):
    agent = _agent(project_ids=[P1])
    rows = db.execute("SELECT * FROM documents").fetchall()
    assert {r["doc_id"] for r in rows if can_read(agent, r, projects)} == visible(db, agent, projects)
    assert can_read(agent, {"doc_id": EP1, "doc_type": "episode", "scope": "default"}, projects)


def test_acceptance_research_sees_no_other_project(db, projects):
    """M8 acceptance (function level): research scoped to P1 gets 0 docs from P2, and no shared writes."""
    r = pam(projects, "agent", "create", "research", "--projects", str(P1))
    assert r.exit_code == 0, r.output
    research = agents.load_manifest("research", projects)
    seen = visible(db, research, projects)
    assert str(EP1) in seen and str(P1) in seen
    assert not seen & {str(EP2), str(P2)}
    assert can_write(research, "shared") is False
    assert can_write_path(research, "memory/shared/facts/x.md", projects) is False
    out = pam(projects, "agent", "check", "research", "--path", "memory/shared/facts/x.md").output
    assert "write memory/shared/facts/x.md: denied" in out


def test_can_read_agrees_with_filter_for_random_agents(db, projects):
    rng = random.Random(0)
    for _ in range(50):
        agent = _agent(
            name=rng.choice(["research", "default-copy", "coder"]),
            include_own_memory=rng.random() < 0.5,
            include_shared_facts=rng.random() < 0.5,
            project_ids=rng.sample([P1, P2], rng.randint(0, 2)),
            include_skills_from=rng.sample(["default", "research", "coder"], rng.randint(0, 3)),
        )
        expected = {i for i, t, s in DOCS if can_read(agent, DocRef(i, t, s), projects)}
        assert visible(db, agent, projects) == expected


# -- can_write / can_call / can_write_path ---------------------------------------------------

@pytest.mark.parametrize("write,target,ok", [
    ("none", "research", False), ("none", "shared", False),
    ("own", "research", True), ("own", "shared", False), ("own", "default", False),
    ("shared", "research", True), ("shared", "shared", True), ("shared", "default", False),
])
def test_can_write_matrix(write, target, ok):
    assert can_write(_agent().model_copy(update={"write": write}), target) is ok


def test_default_agent_permissions():
    d = default_manifest()
    assert can_write(d, "shared") and can_write(d, "default") and not can_write(d, "research")
    assert all(can_call(d, t) for t in READ_TOOLS | WRITE_TOOLS)


@pytest.mark.parametrize("write,tools,tool,ok", [
    ("own", ["search_memory"], "search_memory", True),
    ("own", ["search_memory"], "add_fact", False),
    ("own", ["add_fact"], "add_fact", True),
    ("none", ["add_fact", "search_memory"], "add_fact", False),
    ("none", ["add_fact", "search_memory"], "search_memory", True),
])
def test_can_call_matrix(write, tools, tool, ok):
    assert can_call(_agent().model_copy(update={"write": write, "tools": tools}), tool) is ok


@pytest.mark.parametrize("write,path,ok", [
    ("own", "memory/research/facts/x.md", True),
    ("own", "memory/research/episodes/x.md", True),
    ("own", "skills/research/x.md", True),
    ("own", "memory/shared/facts/x.md", False),
    ("shared", "memory/shared/facts/x.md", True),
    ("shared", "memory/shared/other/x.md", False),
    ("shared", "memory/default/facts/x.md", False),
    ("own", "skills/default/x.md", False),
    ("own", "agent/research/agent.yaml", False),
    ("own", "imports/claude/x/export.zip", False),
    ("own", "memory/research/../shared/facts/x.md", False),
    ("own", "working/new-session.md", True),
    ("none", "memory/research/facts/x.md", False),
])
def test_can_write_path_matrix(vault, write, path, ok):
    assert can_write_path(_agent().model_copy(update={"write": write}), path, vault) is ok


def test_can_write_path_working_file_owner(vault):
    mdio.write_text(vault.working_path("s1"), "---\nagent: research\n---\n")
    mdio.write_text(vault.working_path("s2"), "---\nagent: coder\n---\n")
    agent = _agent()
    assert can_write_path(agent, "working/s1.md", vault)
    assert not can_write_path(agent, "working/s2.md", vault)


@pytest.mark.parametrize("path,ref", [
    ("memory/default/episodes/e1.md", DocRef("e1", "episode", "default")),
    ("memory/shared/facts/f1.md", DocRef("f1", "fact", "shared")),
    ("memory/x/projects/p1.md", DocRef("p1", "project", "x")),
    ("skills/coder/s1.md", DocRef("s1", "skill", "coder")),
    ("agent/default/agent.yaml", None),
    ("working/s1.md", None),
    ("memory/default/notes/n.md", None),
])
def test_doc_ref_from_path(path, ref):
    assert doc_ref_from_path(path) == ref


# -- CLI: check ------------------------------------------------------------------------------

def test_check_tool_and_path(vault):
    pam(vault, "agent", "create", "reader", "--write", "none", "--tools", "search_memory,add_fact")
    out = pam(vault, "agent", "check", "reader", "--tool", "add_fact").output
    assert "tool add_fact: denied (write tool and write level is none)" in out
    out = pam(vault, "agent", "check", "reader", "--tool", "get_episode").output
    assert "denied (not in the agent's tools)" in out
    r = pam(vault, "--json", "agent", "check", "reader", "--tool", "search_memory",
            "--path", "memory/reader/facts/x.md")
    data = json.loads(r.output)
    assert data["tool"]["allowed"] is True
    assert data["path"]["read"]["allowed"] is True and data["path"]["write"]["allowed"] is False
    assert pam(vault, "agent", "check", "reader").exit_code == 2
