"""M7 memory writer tests, written before T09 (SPEC §8 M7, §9.3 T09).

Behavior:
    Exercises the public writer functions, their CLI wrappers, and their vault side effects.
    This module skips until `pam.memory.writer` exists; permission cases also skip until M8 exists.

Pinned writer API:
    `add_fact(vault, data, agent="default") -> WriteResult`
    `supersede_fact(vault, data, agent="default") -> WriteResult`
    `log_episode(vault, data, agent="default", session_id=None) -> WriteResult`
    `update_project(vault, data, agent="default", session_id=None) -> WriteResult`
    `add_skill(vault, data, agent="default") -> WriteResult`
    Inputs are the corresponding `pam.contracts.writes` models. `add_fact` replaces an existing
    SINGLE slot when called directly; extraction uses the separate `merge_candidate` path and
    leaves the old value conflicted. CLI commands are `fact add|list|show|supersede`,
    `project note|create`, `skill add|list`, and `episode log`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import UUID

import pytest
from typer.testing import CliRunner

writer = pytest.importorskip("pam.memory.writer")

from pam.cli.main import app  # noqa: E402
from pam.contracts.fact import Fact, FactConflict, FactStatus  # noqa: E402
from pam.contracts.project import Project  # noqa: E402
from pam.contracts.skill import Skill  # noqa: E402
from pam.contracts.writes import (  # noqa: E402
    AddFactInput,
    AddSkillInput,
    LogEpisodeInput,
    SupersedeFactInput,
    UpdateProjectInput,
)
from pam.core import mdio  # noqa: E402
from pam.core.vault import Vault, init_vault  # noqa: E402

runner = CliRunner()
EP1 = UUID("aaaaaaaa-0000-4000-8000-000000000001")
EP2 = UUID("aaaaaaaa-0000-4000-8000-000000000002")


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """Create an initialized, isolated vault for one writer case."""
    root = tmp_path / "vault"
    init_vault(root)
    return Vault(root)


def _count_commits(vault: Vault) -> int:
    result = subprocess.run(
        ["git", "-C", str(vault.root), "rev-list", "--count", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout)


def _fact_input(value: str, **overrides) -> AddFactInput:
    data = {"attribute": "school", "value": value, "category": "education", **overrides}
    return AddFactInput.model_validate(data)


def _facts(vault: Vault) -> list[tuple[Fact, str]]:
    found = []
    for path in (vault.root / "memory").glob("*/facts/*.md"):
        fact, body = mdio.read_model(path, Fact)
        found.append((fact, body))
    return found


def _create_agent(vault: Vault, name: str, write: str) -> None:
    """Create a custom agent; the writer denies agents that have no manifest."""
    from typing import get_args

    from pam.agents.manifest import create_agent
    from pam.contracts.agent import AgentManifest, ReadScope, ToolName

    create_agent(
        AgentManifest(
            name=name, display_name=name.title(), origin="custom", created_at="2026-10-01T00:00:00Z",
            read=ReadScope(), write=write, tools=list(get_args(ToolName)),
        ),
        vault,
    )


def _invoke(vault: Vault, *args: str):
    return runner.invoke(app, ["--vault", str(vault.root), *args])


def test_add_fact_creates_value_file_and_one_commit(vault):
    before = _count_commits(vault)
    result = writer.add_fact(vault, _fact_input("University of Washington"))
    assert result.ok and result.commit_sha
    facts = _facts(vault)
    assert len(facts) == 1
    assert facts[0][0].value == "University of Washington"
    assert facts[0][1].strip() == "**school**: University of Washington"
    assert _count_commits(vault) == before + 1


def test_same_value_bumps_confidence_in_place(vault):
    writer.add_fact(vault, _fact_input("UW", confidence=0.3))
    before = _count_commits(vault)
    result = writer.add_fact(vault, _fact_input("UW", confidence=0.9))
    fact, _ = _facts(vault)[0]
    assert result.ok and _count_commits(vault) == before + 1
    assert fact.value == "UW" and fact.confidence == pytest.approx(0.9)
    assert fact.history == []


def test_replacement_keeps_history_and_reuses_single_slot_file(vault):
    first_result = writer.add_fact(vault, _fact_input("WSU"))
    result = writer.add_fact(vault, _fact_input("UW"))
    fact, _ = _facts(vault)[0]
    assert result.ok and len(_facts(vault)) == 1
    assert fact.value == "UW"
    assert [entry.value for entry in fact.history] == ["WSU"]
    assert fact.history[-1].episode_id is None
    assert result.path == first_result.path


def test_multi_facts_use_one_file_per_distinct_value(vault):
    common = {"attribute": "uses_tool", "category": "tooling", "cardinality": "multi"}
    writer.add_fact(vault, _fact_input("Python", **common))
    writer.add_fact(vault, _fact_input("Rust", **common))
    writer.add_fact(vault, _fact_input("Python", **common))
    facts = _facts(vault)
    assert len(facts) == 2
    assert {fact.value for fact, _ in facts} == {"Python", "Rust"}
    assert len({fact.id for fact, _ in facts}) == 2


@pytest.mark.parametrize("n", [21, 25])
def test_history_is_capped_at_twenty_entries(vault, n):
    writer.add_fact(vault, _fact_input("school-0"))
    for i in range(1, n + 1):
        writer.add_fact(vault, _fact_input(f"school-{i}"))
    fact, _ = _facts(vault)[0]
    assert len(fact.history) == 20
    assert fact.history[0].value == f"school-{n - 20}"
    assert fact.history[-1].value == f"school-{n - 1}"


@pytest.mark.parametrize(
    ("agent", "shared", "expected_scope"),
    [("default", True, "shared"), ("research", False, "research"), ("research", True, "shared")],
)
def test_fact_scope_tracks_shared_flag(vault, agent, shared, expected_scope):
    if agent != "default":
        _create_agent(vault, agent, write="shared" if shared else "own")
    result = writer.add_fact(vault, _fact_input("UW", shared=shared), agent=agent)
    fact, _ = _facts(vault)[0]
    assert result.ok and fact.scope == expected_scope


@pytest.mark.parametrize(
    "data",
    [
        {"attribute": "bad key", "value": "UW", "category": "education"},
        {"attribute": "school", "value": "", "category": "education"},
        {"attribute": "school", "value": "UW", "category": "unknown"},
        {"attribute": "school", "value": "UW", "category": "education", "confidence": 1.1},
        {"attribute": "school", "value": "UW", "category": "education", "extra": True},
    ],
)
def test_invalid_fact_input_writes_nothing(vault, data):
    before = _count_commits(vault)
    with pytest.raises(Exception):
        parsed = AddFactInput.model_validate(data)
        writer.add_fact(vault, parsed)
    assert _count_commits(vault) == before
    assert _facts(vault) == []


def test_supersede_clears_conflict_and_records_reason(vault):
    result = writer.add_fact(vault, _fact_input("WSU"))
    fact, _ = _facts(vault)[0]
    conflicted = fact.model_copy(update={
        "status": FactStatus.CONFLICT,
        "conflict": FactConflict(candidate_value="UW", detected_by="rule",
                                 detected_at=fact.updated_at),
    })
    mdio.write(vault.root / result.path, conflicted, "**school**: WSU\n")
    before = _count_commits(vault)
    outcome = writer.supersede_fact(
        vault,
        SupersedeFactInput(fact_id=fact.id, new_value="UW", reason="User confirmed transfer"),
    )
    updated, _ = _facts(vault)[0]
    assert outcome.ok and _count_commits(vault) == before + 1
    assert updated.value == "UW" and updated.status is FactStatus.ACTIVE and updated.conflict is None
    assert updated.history[-1].reason == "User confirmed transfer"


def test_supersede_unknown_id_returns_not_found_without_commit(vault):
    before = _count_commits(vault)
    result = writer.supersede_fact(
        vault,
        SupersedeFactInput(
            fact_id=UUID("99999999-0000-4000-8000-000000000009"),
            new_value="UW",
            reason="Confirmed",
        ),
    )
    assert not result.ok and "not found" in result.message.lower()
    assert _count_commits(vault) == before


def test_overwrite_backlinks_old_episode_without_changing_episode_body(vault):
    first = writer.log_episode(vault, _episode_input("First", "I attend WSU."))
    episode_path = vault.root / first.path
    old_body = mdio.read(episode_path)[1]
    writer.add_fact(vault, _fact_input("WSU", episode_id=first.doc_id))
    writer.add_fact(vault, _fact_input("UW", episode_id=EP2))
    data, body = mdio.read(episode_path)
    assert body == old_body
    assert str(_facts(vault)[0][0].id) in [str(item) for item in data["superseded_facts"]]


def _episode_input(title: str, text: str) -> LogEpisodeInput:
    from pam.contracts.raw import RawMessage
    return LogEpisodeInput(title=title, messages=[RawMessage(role="user", text=text)])


def test_log_episode_creates_episode_and_one_commit(vault):
    before = _count_commits(vault)
    result = writer.log_episode(vault, _episode_input("Planning", "We decided to use UW."))
    assert result.ok and result.path and result.commit_sha
    assert (vault.root / result.path).is_file()
    assert _count_commits(vault) == before + 1


def test_update_project_creates_project_and_note(vault):
    result = writer.update_project(vault, UpdateProjectInput(name="Memory redesign", note="Keep tests first."))
    assert result.ok and result.path
    project, body = mdio.read_model(vault.root / result.path, Project)
    assert project.name == "Memory redesign"
    assert "Keep tests first." in body


def test_project_notes_append_and_auto_summary_is_preserved(vault):
    result = writer.update_project(vault, UpdateProjectInput(name="Memory redesign", note="First note."))
    path = vault.root / result.path
    original = mdio.read(path)[1]
    summary = original.split("## Notes", 1)[0]
    writer.update_project(vault, UpdateProjectInput(project_id=result.doc_id, note="Second note."))
    updated = mdio.read(path)[1]
    assert updated.startswith(summary)
    assert updated.index("First note.") < updated.index("Second note.")


def test_update_project_appends_episode_membership(vault):
    result = writer.update_project(vault, UpdateProjectInput(name="Research", add_episode_ids=[EP1]))
    updated = writer.update_project(
        vault, UpdateProjectInput(project_id=result.doc_id, add_episode_ids=[EP2])
    )
    project = mdio.read_model(vault.root / updated.path, Project)[0]
    assert project.episode_ids == [EP1, EP2]


def test_add_skill_creates_skill_and_one_commit(vault):
    data = AddSkillInput(name="Release checklist", description="Prepare a release", steps_markdown="1. Review",
                         trigger_keywords=["release"])
    before = _count_commits(vault)
    result = writer.add_skill(vault, data)
    skill = mdio.read_model(vault.root / result.path, Skill)[0]
    assert result.ok and skill.name == data.name
    assert _count_commits(vault) == before + 1


def test_add_skill_updates_matching_name_in_place(vault):
    first = AddSkillInput(name="Release checklist", description="Old", steps_markdown="1. Old")
    writer.add_skill(vault, first)
    second = AddSkillInput(name="release-checklist", description="New", steps_markdown="1. New")
    result = writer.add_skill(vault, second)
    paths = list((vault.root / "skills").glob("*/*.md"))
    skill = mdio.read_model(paths[0], Skill)[0]
    assert result.ok and len(paths) == 1 and skill.description == "New"


def test_writes_never_delete_existing_vault_files(vault):
    before = {p.relative_to(vault.root) for p in vault.root.rglob("*") if p.is_file()}
    writer.add_fact(vault, _fact_input("UW"))
    writer.update_project(vault, UpdateProjectInput(name="Research", note="Added."))
    after = {p.relative_to(vault.root) for p in vault.root.rglob("*") if p.is_file()}
    assert before <= after


def test_lock_timeout_returns_busy_without_mutation(vault, monkeypatch):
    from pam.core.errors import VaultBusy

    def busy(*args, **kwargs):
        raise VaultBusy("vault is busy")

    monkeypatch.setattr(writer, "vault_write_lock", busy)
    before = _count_commits(vault)
    result = writer.add_fact(vault, _fact_input("UW"))
    assert not result.ok and "busy" in result.message.lower()
    assert _count_commits(vault) == before and _facts(vault) == []


@pytest.mark.parametrize("args", [
    ("fact", "add", "--attribute", "school", "--value", "UW", "--category", "education"),
    ("fact", "list"),
    ("project", "create", "--name", "Research"),
    ("skill", "list"),
])
def test_cli_writer_commands_are_registered(vault, args):
    result = _invoke(vault, *args)
    assert result.exit_code == 0, result.output


def test_t08_extracted_facts_route_through_m7_writer(vault, monkeypatch):
    facts = pytest.importorskip("pam.extract.facts")
    route = getattr(facts, "write_candidates", None)
    if route is None:
        pytest.skip("T08 candidate writer route is not present")
    calls = []
    original = writer.add_fact

    def recording_add_fact(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    monkeypatch.setattr(writer, "add_fact", recording_add_fact)
    route(vault, "I attend UW.", agent="default")
    assert calls


def test_permission_cases_wait_until_m8_is_available(vault):
    permissions = pytest.importorskip("pam.agents.permissions")
    from pam.contracts.agent import AgentManifest, ReadScope

    # A research agent may write its own scope but may not write shared memory.
    agent = AgentManifest(
        name="research", display_name="Research", origin="custom", created_at="2026-10-01T00:00:00Z",
        read=ReadScope(), write="own", tools=["add_fact"],
    )
    assert permissions.can_write(agent, "research")
    assert not permissions.can_write(agent, "shared")
    denied = writer.add_fact(vault, _fact_input("UW", shared=True), agent="research")
    assert not denied.ok and denied.message.startswith("PERMISSION_DENIED:")
    assert _facts(vault) == []


def test_cli_fact_add_writes_exactly_one_commit(vault):
    before = _count_commits(vault)
    result = _invoke(vault, "fact", "add", "--attribute", "school", "--value", "UW",
                     "--category", "education")
    assert result.exit_code == 0, result.output
    assert _count_commits(vault) == before + 1



# -- T09: pipeline, commit messages, reindex, backlinks, extraction route -------------------------

FIXTURE = Path(__file__).parent / "fixtures" / "claude" / "export.zip"
SESSION = "s_abc123def456"


def _subject(vault: Vault) -> str:
    out = subprocess.run(
        ["git", "-C", str(vault.root), "log", "-1", "--format=%s"], check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _commit_regex(action: str, session: str | None = None) -> str:
    suffix = rf", session={session}" if session else ""
    return rf"^{action}: \S.* \(agent=default{suffix}\)$"


def test_commit_message_format_for_every_action(vault):
    import re

    fact = writer.add_fact(vault, _fact_input("WSU"))
    assert re.match(_commit_regex("add_fact"), _subject(vault)), _subject(vault)
    fact_id = fact.doc_id

    writer.supersede_fact(vault, SupersedeFactInput(fact_id=fact_id, new_value="UW", reason="Confirmed"))
    assert re.match(_commit_regex("supersede_fact"), _subject(vault)), _subject(vault)

    writer.log_episode(vault, _episode_input("Planning", "We chose sqlite."))
    assert re.match(_commit_regex("log_episode"), _subject(vault)), _subject(vault)
    writer.log_episode(vault, _episode_input("Planning 2", "We chose fts5."), session_id=SESSION)
    assert re.match(_commit_regex("log_episode", SESSION), _subject(vault)), _subject(vault)

    writer.update_project(vault, UpdateProjectInput(name="Research"))
    assert re.match(_commit_regex("update_project"), _subject(vault)), _subject(vault)
    created = writer.update_project(vault, UpdateProjectInput(name="Other"), session_id=SESSION)
    assert re.match(_commit_regex("update_project", SESSION), _subject(vault)), _subject(vault)
    assert created.ok

    writer.add_skill(vault, AddSkillInput(name="Deploy", description="Ship it", steps_markdown="1. Go"))
    assert re.match(_commit_regex("add_skill"), _subject(vault)), _subject(vault)


def test_commit_message_collapses_newlines_and_caps_length(vault):
    writer.add_fact(vault, _fact_input("University of\nWashington " + "x" * 200))
    subject = _subject(vault)
    assert "\n" not in subject and len(subject) < 140
    assert subject.endswith("(agent=default)")


@pytest.fixture
def index_spy(monkeypatch):
    calls = []
    monkeypatch.setattr(writer, "index_paths", lambda v, paths: calls.append((v, list(paths))), raising=False)
    return calls


def test_index_paths_is_called_once_with_the_touched_paths(vault, index_spy):
    result = writer.add_fact(vault, _fact_input("UW"))
    assert len(index_spy) == 1
    assert index_spy[0][0] is vault
    assert result.path in index_spy[0][1]
    writer.add_fact(vault, _fact_input("WSU"))
    assert len(index_spy) == 2


def test_log_episode_reindexes_episode_and_facts_in_one_call(vault, index_spy):
    result = writer.log_episode(vault, _episode_input("Plan", "I attend UW."))
    assert len(index_spy) == 1
    paths = index_spy[0][1]
    assert result.path in paths and any("/facts/" in p for p in paths)


def test_index_paths_is_not_called_on_failure_denial_or_noop(vault, index_spy, monkeypatch):
    from pam.core.errors import VaultBusy

    writer.add_fact(vault, _fact_input("UW"))
    index_spy.clear()
    missing = SupersedeFactInput(fact_id=UUID(int=7), new_value="UW", reason="No such fact")
    assert not writer.supersede_fact(vault, missing).ok
    assert not writer.add_fact(vault, _fact_input("UW"), agent="ghost").ok
    assert writer.add_fact(vault, _fact_input("UW")).ok  # exact repeat: nothing to commit
    monkeypatch.setattr(writer, "vault_write_lock", lambda *a, **k: (_ for _ in ()).throw(VaultBusy("busy")))
    assert not writer.add_fact(vault, _fact_input("MIT")).ok
    assert index_spy == []


def test_indexer_error_does_not_fail_a_committed_write(vault, monkeypatch):
    def broken(v, paths):
        raise RuntimeError("index offline")

    monkeypatch.setattr(writer, "index_paths", broken, raising=False)
    before = _count_commits(vault)
    assert writer.add_fact(vault, _fact_input("UW")).ok
    assert _count_commits(vault) == before + 1


def test_mixed_sequence_makes_one_commit_per_successful_write(vault):
    ghost = _fact_input("UW")
    steps = [
        (lambda: writer.add_fact(vault, _fact_input("WSU")), True),
        (lambda: writer.add_fact(vault, _fact_input("WSU", confidence=0.95)), True),
        (lambda: writer.add_fact(vault, _fact_input("UW")), True),
        (lambda: writer.log_episode(vault, _episode_input("Chat", "I attend MIT.")), True),
        (lambda: writer.update_project(vault, UpdateProjectInput(name="P", note="n1")), True),
        (lambda: writer.add_skill(vault, AddSkillInput(name="S", description="d", steps_markdown="1. a")), True),
        (lambda: writer.add_fact(vault, ghost, agent="ghost"), False),
        (lambda: writer.supersede_fact(vault, SupersedeFactInput(fact_id=UUID(int=3), new_value="x", reason="r")), False),
        (lambda: writer.update_project(vault, UpdateProjectInput(note="no id and no name")), False),
    ]
    for step, should_pass in steps:
        before = _count_commits(vault)
        result = step()
        assert result.ok is should_pass, result.message
        assert _count_commits(vault) == before + (1 if should_pass else 0)
        assert (result.commit_sha is not None) is should_pass


def test_unchanged_repeat_is_ok_without_a_commit(vault):
    writer.add_fact(vault, _fact_input("UW", confidence=0.9))
    before = _count_commits(vault)
    result = writer.add_fact(vault, _fact_input("UW", confidence=0.4))
    assert result.ok and result.commit_sha is None and _count_commits(vault) == before
    assert _facts(vault)[0][0].confidence == pytest.approx(0.9)


def test_overwriting_an_imported_episodes_fact_backlinks_it_and_verify_passes(vault):
    imported = _invoke(vault, "import", "run", str(FIXTURE))
    assert imported.exit_code == 0, imported.output
    episode = sorted((vault.root / "memory").glob("*/episodes/*.md"))[0]
    data, body = mdio.read(episode)
    ep_id = UUID(str(data["id"]))
    writer.add_fact(vault, _fact_input("WSU", episode_id=ep_id))
    before = _count_commits(vault)
    assert writer.add_fact(vault, _fact_input("UW")).ok
    assert _count_commits(vault) == before + 1
    fact = _facts(vault)[0][0]
    after, after_body = mdio.read(episode)
    assert str(fact.id) in [str(x) for x in after["superseded_facts"]]
    assert after_body == body and after["body_sha256"] == data["body_sha256"]
    verified = _invoke(vault, "episode", "verify")
    assert verified.exit_code == 0, verified.output
    assert " 0 failed" in verified.output


def test_overwrite_aborts_and_rolls_back_when_the_old_episode_body_was_edited(vault):
    episode = writer.log_episode(vault, _episode_input("Chat", "I attend WSU."))
    path = vault.root / episode.path
    path.write_text(path.read_text(encoding="utf-8") + "tampered\n", encoding="utf-8")
    snapshot = path.read_bytes()
    before, head = _count_commits(vault), _subject(vault)
    result = writer.add_fact(vault, _fact_input("UW"))
    assert not result.ok and "body_sha256" in result.message
    assert _count_commits(vault) == before and _subject(vault) == head
    assert _facts(vault)[0][0].value == "WSU"
    assert path.read_bytes() == snapshot


def test_log_episode_id_format_and_extracted_fact(vault):
    import re

    from pam.contracts.common import Source
    from pam.contracts.episode import EpisodeFrontmatter, episode_id
    from pam.core.ids import sha256_text

    result = writer.log_episode(vault, _episode_input("Plan", "I attend UW."))
    fm, body = mdio.read_model(vault.root / result.path, EpisodeFrontmatter)
    assert fm.source is Source.PAM and fm.agent == "default"
    assert re.fullmatch(r"default:\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ:[0-9a-f]{8}", fm.source_conversation_id)
    assert fm.id == result.doc_id == episode_id(Source.PAM, fm.source_conversation_id)
    assert sha256_text(body) == fm.body_sha256
    (fact, _), = _facts(vault)
    assert (fact.attribute, fact.value, fact.scope) == ("school", "UW", "shared")
    assert fact.source_episode == fm.id and fact.extractor.value == "rule"


def test_log_episode_by_an_own_scope_agent_skips_shared_fact_extraction(vault):
    _create_agent(vault, "research", write="own")
    before = _count_commits(vault)
    result = writer.log_episode(vault, _episode_input("Chat", "I attend UW."), agent="research")
    assert result.ok and _count_commits(vault) == before + 1
    assert result.path.startswith("memory/research/episodes/")
    assert _facts(vault) == []


def test_write_candidates_makes_one_commit_for_many_facts(vault):
    facts = pytest.importorskip("pam.extract.facts")
    text = "I attend UW. I work at Microsoft."
    before = _count_commits(vault)
    stored = facts.write_candidates(vault, text, agent="default", episode_id=EP1)
    assert {f.attribute for f in stored} == {"school", "works_at"}
    assert _count_commits(vault) == before + 1
    assert _subject(vault) == "derive: +2 ~0 !0"
    assert facts.write_candidates(vault, text, agent="default", episode_id=EP1) == []
    assert _count_commits(vault) == before + 1


def test_extraction_flags_a_conflict_with_an_agent_written_value(vault):
    facts = pytest.importorskip("pam.extract.facts")
    writer.add_fact(vault, _fact_input("WSU"))
    before = _count_commits(vault)
    facts.write_candidates(vault, "I attend UW.", agent="default")
    fact = _facts(vault)[0][0]
    assert fact.value == "WSU" and fact.status is FactStatus.CONFLICT
    assert fact.conflict.candidate_value == "UW"
    assert _count_commits(vault) == before + 1 and _subject(vault) == "derive: +0 ~0 !1"


def test_write_candidates_needs_shared_write_permission(vault):
    facts = pytest.importorskip("pam.extract.facts")
    from pam.core.errors import PermissionDenied

    _create_agent(vault, "research", write="own")
    before = _count_commits(vault)
    with pytest.raises(PermissionDenied):
        facts.write_candidates(vault, "I attend UW.", agent="research")
    assert _count_commits(vault) == before and _facts(vault) == []


def test_supersede_rejects_multi_valued_facts_without_a_commit(vault):
    common = {"attribute": "uses_tool", "category": "tooling", "cardinality": "multi"}
    added = writer.add_fact(vault, _fact_input("Python", **common))
    before = _count_commits(vault)
    result = writer.supersede_fact(vault, SupersedeFactInput(fact_id=added.doc_id, new_value="Rust", reason="r"))
    assert not result.ok and "multi" in result.message
    assert _count_commits(vault) == before


def test_update_project_note_is_one_bullet_in_the_documented_format(vault):
    import re

    result = writer.update_project(vault, UpdateProjectInput(name="Memory", note="Decided\nto use sqlite-vec"))
    _, body = mdio.read(vault.root / result.path)
    bullets = [line for line in body.splitlines() if line.startswith("- ")]
    assert len(bullets) == 1
    assert re.fullmatch(r"- \d{4}-\d\d-\d\dT\d\d:\d\dZ \(agent:default\) Decided to use sqlite-vec", bullets[0])


def test_an_episode_belongs_to_at_most_one_project(vault):
    writer.update_project(vault, UpdateProjectInput(name="One", add_episode_ids=[EP1]))
    before = _count_commits(vault)
    result = writer.update_project(vault, UpdateProjectInput(name="Two", add_episode_ids=[EP1]))
    assert not result.ok and "already belongs" in result.message
    assert _count_commits(vault) == before


def test_cli_fact_add_then_supersede_grows_history_with_one_commit_each(vault):
    import json

    assert _invoke(vault, "fact", "add", "--attribute", "school", "--value", "WSU", "--category", "education").exit_code == 0
    listing = _invoke(vault, "--json", "fact", "list")
    fid = json.loads(listing.output)[0]["id"]
    before = _count_commits(vault)
    result = _invoke(vault, "fact", "supersede", fid, "--value", "UW", "--reason", "User confirmed")
    assert result.exit_code == 0, result.output
    assert _count_commits(vault) == before + 1
    shown = json.loads(_invoke(vault, "--json", "fact", "show", fid[:8]).output)
    assert shown["value"] == "UW" and [h["value"] for h in shown["history"]] == ["WSU"]
    assert shown["history"][0]["reason"] == "User confirmed"


@pytest.mark.parametrize(
    ("args", "code"),
    [
        (("fact", "add", "--attribute", "school", "--value", "UW", "--category", "nonsense"), 2),
        (("fact", "supersede", "99999999", "--value", "UW", "--reason", "r"), 1),
        (("fact", "add", "--attribute", "school", "--value", "UW", "--category", "education", "--agent", "ghost"), 3),
        (("fact", "list", "--status", "weird"), 2),
    ],
)
def test_cli_exit_codes(vault, args, code):
    result = _invoke(vault, *args)
    assert result.exit_code == code, result.output


def test_cli_permission_denied_for_shared_write_and_busy_vault(vault, monkeypatch):
    from pam.core.errors import VaultBusy

    _create_agent(vault, "research", write="own")
    denied = _invoke(vault, "fact", "add", "--attribute", "school", "--value", "UW", "--category", "education",
                     "--agent", "research", "--shared")
    assert denied.exit_code == 3 and _facts(vault) == []
    monkeypatch.setattr(writer, "vault_write_lock", lambda *a, **k: (_ for _ in ()).throw(VaultBusy("busy")))
    busy = _invoke(vault, "fact", "add", "--attribute", "school", "--value", "UW", "--category", "education")
    assert busy.exit_code == 4


def test_cli_project_skill_and_episode_commands_make_one_commit_each(vault, tmp_path):
    import json

    steps = tmp_path / "steps.md"
    steps.write_text("1. Review\n2. Tag\n", encoding="utf-8")
    msgs = tmp_path / "msgs.jsonl"
    msgs.write_text('{"role": "user", "text": "I attend UW."}\n{"role": "assistant", "text": "Noted."}\n', encoding="utf-8")
    created = json.loads(_invoke(vault, "--json", "project", "create", "--name", "Research").output)
    for args in [
        ("project", "note", created["doc_id"][:8], "Keep tests first."),
        ("skill", "add", "--name", "Release", "--description", "Ship", "--steps-file", str(steps), "--keywords", "ship,tag"),
        ("episode", "log", "--title", "Chat", "--messages", str(msgs), "--tags", "a,b"),
    ]:
        before = _count_commits(vault)
        result = _invoke(vault, *args)
        assert result.exit_code == 0, result.output
        assert _count_commits(vault) == before + 1, args
    assert len(_facts(vault)) == 1
    assert _invoke(vault, "skill", "list").exit_code == 0


def test_writes_are_indexed_for_real(vault):
    from pam.index import indexer

    writer.add_fact(vault, _fact_input("UW"))
    writer.update_project(vault, UpdateProjectInput(name="Research", note="Indexed."))
    writer.add_skill(vault, AddSkillInput(name="Deploy", description="Ship", steps_markdown="1. Go"))
    types = indexer.stats(vault)["types"]
    assert [types[t]["documents"] for t in ("fact", "project", "skill")] == [1, 1, 1]
    writer.add_fact(vault, _fact_input("WSU"))
    report = indexer.index_vault(vault)
    assert report.documents_indexed == 0 and report.documents_unchanged == 3


@pytest.mark.parametrize("args", [
    ("project", "note", " ", "Note."),
    ("project", "add-episodes", "", str(EP1)),
    ("fact", "show", ""),
    ("fact", "supersede", "", "--value", "WSU", "--reason", "Typo"),
])
def test_cli_empty_id_is_rejected_without_commit(vault, args):
    """An empty id never resolves to the only project or fact."""
    writer.update_project(vault, UpdateProjectInput(name="Research"))
    writer.add_fact(vault, _fact_input("UW"))
    before = _count_commits(vault)
    result = _invoke(vault, *args)
    assert result.exit_code == 1 and "must not be empty" in result.output, result.output
    assert _count_commits(vault) == before
