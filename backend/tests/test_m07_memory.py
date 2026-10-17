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
from pam.contracts.fact import Fact, FactStatus  # noqa: E402
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
        "conflict": {"candidate_value": "UW", "detected_by": "extractor",
                     "detected_at": fact.updated_at},
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

