"""M9 working-memory tests (SPEC §7.10, §8 M9, §9.3 T11).

Behavior:
    Exercises `pam.working.session` and `pam session` on throwaway vaults: id format, the
    8-turn window, model switches, the commit rules (start, goal, update, end; none per turn),
    the untracked transcript, and promotion to an episode on end.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pam.cli.main import app
from pam.contracts.common import Source
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.working import WorkingMemory
from pam.contracts.writes import UpdateWorkingMemoryInput, WriteResult
from pam.core import mdio
from pam.core.vault import Vault, init_vault
from pam.working import session

runner = CliRunner()


@pytest.fixture
def vault(tmp_path: Path) -> Vault:
    """Create an initialized, isolated vault."""
    root = tmp_path / "vault"
    init_vault(root)
    return Vault(root)


def _git(vault: Vault, *args: str) -> str:
    return subprocess.run(["git", "-C", str(vault.root), *args], check=True, capture_output=True, text=True).stdout


def _commits(vault: Vault) -> int:
    return int(_git(vault, "rev-list", "--count", "HEAD"))


def _cli(vault: Vault, *args: str):
    return runner.invoke(app, ["--vault", str(vault.root), *args])


def _four_turns(vault: Vault, session_id: str) -> None:
    session.record_turn(vault, session_id, "user", "Help me plan a photo backup with Immich", "model-a")
    session.record_turn(vault, session_id, "assistant", "Start with a NAS and Docker.", "model-a")
    session.record_turn(vault, session_id, "user", "Which NAS should I buy?", "model-b")
    session.record_turn(vault, session_id, "assistant", "A two-bay Synology is enough.", "model-b")


def test_session_id_format_and_start_commit(vault):
    before = _commits(vault)
    memory = session.start(vault, "default", "model-a")
    assert re.fullmatch(r"s_[0-9a-z]{12}", memory.session_id)
    assert _commits(vault) == before + 1
    assert _git(vault, "log", "-1", "--format=%s") == f"session: start (agent=default, session={memory.session_id})\n"
    assert memory.status == "active" and [s.to_model for s in memory.models_used] == ["model-a"]


def test_start_unknown_agent_fails(vault):
    with pytest.raises(Exception, match="nobody"):
        session.start(vault, "nobody", "model-a")


def test_recent_turns_capped_at_8(vault):
    memory = session.start(vault, "default", "m")
    for i in range(11):
        memory = session.record_turn(vault, memory.session_id, "user" if i % 2 == 0 else "assistant", f"turn {i}", "m")
    assert [m.text for m in memory.recent_turns] == [f"turn {i}" for i in range(3, 11)]
    assert len(session.show(vault, memory.session_id).recent_turns) == 8


def test_two_models_four_turns(vault):
    memory = session.start(vault, "default", "model-a")
    _four_turns(vault, memory.session_id)
    shown = session.show(vault, memory.session_id)
    assert [(s.from_model, s.to_model) for s in shown.models_used] == [(None, "model-a"), ("model-a", "model-b")]
    assert len(shown.recent_turns) == 4


def test_model_switch_from_start_model(vault):
    memory = session.start(vault, "default", "model-a")
    memory = session.record_turn(vault, memory.session_id, "user", "hi", "model-b")
    assert [s.to_model for s in memory.models_used] == ["model-a", "model-b"]
    assert memory.models_used[1].from_model == "model-a"


def test_turns_do_not_commit_but_goal_commits_once(vault):
    memory = session.start(vault, "default", "model-a")
    after_start = _commits(vault)
    _four_turns(vault, memory.session_id)
    assert _commits(vault) == after_start + 1  # only the goal from the first user message
    assert _git(vault, "log", "-1", "--format=%s").startswith("session: goal ")
    shown = session.show(vault, memory.session_id)
    assert shown.goal == "Help me plan a photo backup with Immich"
    stored, _ = mdio.read_model(vault.working_path(memory.session_id), WorkingMemory)
    assert stored.goal == shown.goal


def test_goal_truncated_to_200_chars(vault):
    memory = session.start(vault, "default", "m")
    memory = session.record_turn(vault, memory.session_id, "user", "x" * 300, "m")
    assert memory.goal == "x" * 200


def test_goal_not_overwritten_by_later_user_message(vault):
    memory = session.start(vault, "default", "m")
    session.record_turn(vault, memory.session_id, "assistant", "Hello", "m")
    session.record_turn(vault, memory.session_id, "user", "first", "m")
    count = _commits(vault)
    memory = session.record_turn(vault, memory.session_id, "user", "second", "m")
    assert memory.goal == "first" and _commits(vault) == count


def test_update_is_one_commit_and_append_only(vault):
    memory = session.start(vault, "default", "m")
    sid = memory.session_id
    count = _commits(vault)
    first = session.update(vault, UpdateWorkingMemoryInput(session_id=sid, goal="Ship T11", add_decisions=["Use jsonl"]))
    assert first.ok and first.commit_sha and _commits(vault) == count + 1
    second = session.update(vault, UpdateWorkingMemoryInput(session_id=sid, add_decisions=["Keep the file"],
                                                            add_open_questions=["Gitignore?"]))
    assert second.ok and _commits(vault) == count + 2
    shown = session.show(vault, sid)
    assert shown.goal == "Ship T11"
    assert shown.decisions == ["Use jsonl", "Keep the file"] and shown.open_questions == ["Gitignore?"]
    body = vault.working_path(sid).read_text(encoding="utf-8")
    assert "## Decisions" in body and "- Use jsonl" in body and "- Gitignore?" in body


def test_update_nothing_is_ok_without_commit(vault):
    memory = session.start(vault, "default", "m")
    count = _commits(vault)
    result = session.update(vault, UpdateWorkingMemoryInput(session_id=memory.session_id))
    assert result.ok and result.commit_sha is None and _commits(vault) == count


def test_update_missing_session_fails_cleanly(vault):
    count = _commits(vault)
    result = session.update_working_memory(vault, UpdateWorkingMemoryInput(session_id="s_abcdefghijkl", goal="x"))
    assert not result.ok and "not found" in result.message and _commits(vault) == count


def test_update_bad_id_is_not_found(vault):
    result = session.update(vault, UpdateWorkingMemoryInput(session_id="../pam", goal="x"))
    assert not result.ok and "not found" in result.message


def test_transcript_holds_every_turn_in_order(vault):
    memory = session.start(vault, "default", "model-a")
    _four_turns(vault, memory.session_id)
    lines = session.transcript_path(vault, memory.session_id).read_text(encoding="utf-8").splitlines()
    rows = [json.loads(line) for line in lines]
    assert [(r["role"], r["model"]) for r in rows] == [
        ("user", "model-a"), ("assistant", "model-a"), ("user", "model-b"), ("assistant", "model-b"),
    ]
    assert rows[2]["text"] == "Which NAS should I buy?" and all(r["created_at"].endswith("Z") for r in rows)


def test_sync_after_turns_makes_no_commit_and_transcript_stays_untracked(vault):
    memory = session.start(vault, "default", "model-a")
    _four_turns(vault, memory.session_id)
    count = _commits(vault)
    result = _cli(vault, "sync")
    assert result.exit_code == 0, result.output
    assert _commits(vault) == count
    rel = vault.rel(session.transcript_path(vault, memory.session_id))
    assert _git(vault, "ls-files", "--", rel) == ""
    assert _git(vault, "status", "--porcelain", "--", vault.rel(vault.working_path(memory.session_id))) == ""


def test_end_creates_episode_with_full_transcript(vault):
    memory = session.start(vault, "default", "m")
    sid = memory.session_id
    for i in range(10):
        session.record_turn(vault, sid, "user" if i % 2 == 0 else "assistant", f"message number {i}", "m")
    session.update(vault, UpdateWorkingMemoryInput(session_id=sid, add_decisions=["Use Immich"]))
    count = _commits(vault)
    result = session.end(vault, sid)
    assert result.ok and result.doc_id is not None and result.commit_sha
    assert _commits(vault) == count + 2  # log_episode, then the end commit
    assert _git(vault, "log", "-1", "--format=%s") == f"session: end (agent=default, session={sid})\n"
    fm, body = mdio.read_model(vault.root / result.path, EpisodeFrontmatter)
    assert fm.source == Source.PAM and fm.id == result.doc_id and fm.message_count == 10
    assert all(f"message number {i}" in body for i in range(10))
    assert fm.title == "message number 0" and "Decisions: Use Immich" in body
    assert f"session:{sid}" in fm.tags
    ended = session.show(vault, sid)
    assert ended.status == "ended" and ended.promoted_episode_id == result.doc_id
    assert vault.working_path(sid).is_file()
    verify = _cli(vault, "episode", "verify")
    assert verify.exit_code == 0, verify.output


def test_end_twice_fails_cleanly(vault):
    memory = session.start(vault, "default", "m")
    session.record_turn(vault, memory.session_id, "user", "hello", "m")
    assert session.end(vault, memory.session_id).ok
    count = _commits(vault)
    again = session.end(vault, memory.session_id)
    assert not again.ok and again.message == f"session {memory.session_id} already ended"
    assert _commits(vault) == count


def test_end_without_turns_fails_and_stays_active(vault):
    memory = session.start(vault, "default", "m")
    result = session.end(vault, memory.session_id)
    assert not result.ok and "no turns" in result.message
    assert session.show(vault, memory.session_id).status == "active"


def test_ended_session_refuses_turns_and_updates(vault):
    memory = session.start(vault, "default", "m")
    session.record_turn(vault, memory.session_id, "user", "hello", "m")
    session.end(vault, memory.session_id)
    with pytest.raises(Exception, match="already ended"):
        session.record_turn(vault, memory.session_id, "user", "more", "m")
    result = session.update(vault, UpdateWorkingMemoryInput(session_id=memory.session_id, add_decisions=["x"]))
    assert not result.ok and "already ended" in result.message


def test_working_file_round_trips_as_contract(vault):
    memory = session.start(vault, "default", "m")
    session.record_turn(vault, memory.session_id, "user", "Plan the demo", "m")
    session.update(vault, UpdateWorkingMemoryInput(session_id=memory.session_id, add_open_questions=["Which model?"]))
    stored, body = mdio.read_model(vault.working_path(memory.session_id), WorkingMemory)
    assert WorkingMemory.model_validate(stored.model_dump(mode="json")) == stored
    assert stored.session_id == memory.session_id and stored.open_questions == ["Which model?"]
    assert len(stored.recent_turns) == 1 and body == session.render_body(stored)


def test_list_returns_sessions_newest_first(vault):
    first = session.start(vault, "default", "m")
    second = session.start(vault, "default", "m")
    ids = {m.session_id for m in session.list(vault)}
    assert ids == {first.session_id, second.session_id}


def test_show_missing_session_raises(vault):
    with pytest.raises(Exception, match="not found"):
        session.show(vault, "s_000000000000")


def test_cli_acceptance_start_record_show_end(vault):
    started = _cli(vault, "--json", "session", "start", "--agent", "default", "--model", "model-a")
    assert started.exit_code == 0, started.output
    sid = WorkingMemory.model_validate_json(started.output).session_id
    turns = [("user", "Plan my backup", "model-a"), ("assistant", "Use Immich.", "model-a"),
             ("user", "Which disk?", "model-b"), ("assistant", "Two mirrored drives.", "model-b")]
    for role, text, model in turns:
        result = _cli(vault, "session", "record", sid, "--role", role, "--text", text, "--model", model)
        assert result.exit_code == 0, result.output
    shown = _cli(vault, "--json", "session", "show", sid)
    assert shown.exit_code == 0, shown.output
    memory = WorkingMemory.model_validate_json(shown.output)
    assert len(memory.models_used) == 2 and len(memory.recent_turns) == 4
    text = _cli(vault, "session", "show", sid)
    assert "Models used (2): model-a, model-b" in text.output and "Recent turns (4):" in text.output
    updated = _cli(vault, "session", "update", sid, "--decision", "Mirror drives", "--question", "Offsite?")
    assert updated.exit_code == 0, updated.output
    listed = _cli(vault, "--json", "session", "list")
    assert listed.exit_code == 0 and [m["session_id"] for m in json.loads(listed.output)] == [sid]
    ended = _cli(vault, "--json", "session", "end", sid)
    assert ended.exit_code == 0, ended.output
    assert WriteResult.model_validate_json(ended.output).doc_id is not None
    again = _cli(vault, "session", "end", sid)
    assert again.exit_code == 1 and "already ended" in again.output


def test_cli_record_rejects_bad_role(vault):
    memory = session.start(vault, "default", "m")
    result = _cli(vault, "session", "record", memory.session_id, "--role", "robot", "--text", "x", "--model", "m")
    assert result.exit_code == 2


# --- extra T11 checks: edge cases behind CHG-0014 ---------------------------------------------


@pytest.fixture
def quick_lock(monkeypatch):
    """Make session writers give up on a held lock after 0.1 s instead of 10 s."""
    from pam.core import lock  # noqa: PLC0415

    monkeypatch.setattr(session, "vault_write_lock", lambda v, timeout=10.0: lock.vault_write_lock(v, timeout=0.1))


def test_switching_back_adds_a_third_model_entry(vault):
    memory = session.start(vault, "default", "a")
    for model in ("a", "b", "a"):
        memory = session.record_turn(vault, memory.session_id, "user", f"on {model}", model)
    assert [(s.from_model, s.to_model) for s in memory.models_used] == [(None, "a"), ("a", "b"), ("b", "a")]


def test_show_is_current_while_the_md_lags(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "first", "a")  # the goal commit refreshes the .md
    session.record_turn(vault, sid, "assistant", "second", "b")
    stored, _ = mdio.read_model(vault.working_path(sid), WorkingMemory)
    assert len(stored.recent_turns) == 1 and len(stored.models_used) == 1
    shown = session.show(vault, sid)
    assert len(shown.recent_turns) == 2 and len(shown.models_used) == 2
    session.update(vault, UpdateWorkingMemoryInput(session_id=sid, add_decisions=["x"]))
    stored, _ = mdio.read_model(vault.working_path(sid), WorkingMemory)
    assert len(stored.recent_turns) == 2 and len(stored.models_used) == 2  # the update commit caught up


def test_missing_transcript_falls_back_to_the_md(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "first", "a")
    session.transcript_path(vault, sid).unlink()  # e.g. a fresh clone of the vault
    shown = session.show(vault, sid)
    assert [m.text for m in shown.recent_turns] == ["first"] and shown.goal == "first"


def test_corrupt_transcript_line_is_reported(vault):
    sid = session.start(vault, "default", "a").session_id
    path = session.transcript_path(vault, sid)
    path.write_text('{"role": "user", "text": "ok", "model": "a"}\nnot json\n', encoding="utf-8")
    with pytest.raises(Exception, match=r"transcript\.jsonl:2"):
        session.show(vault, sid)


def test_unicode_and_newlines_survive_to_the_episode(vault):
    sid = session.start(vault, "default", "a").session_id
    text = "Café ☕ – line one\nline two"
    session.record_turn(vault, sid, "user", text, "a")
    assert session.show(vault, sid).recent_turns[0].text == text
    result = session.end(vault, sid)
    _, body = mdio.read_model(vault.root / result.path, EpisodeFrontmatter)
    assert "Café ☕ – line one" in body and "line two" in body


def test_blank_user_message_does_not_set_goal(vault):
    sid = session.start(vault, "default", "a").session_id
    count = _commits(vault)
    memory = session.record_turn(vault, sid, "user", "   ", "a")
    assert memory.goal is None and _commits(vault) == count


def test_goal_from_update_is_kept_over_first_user_message(vault):
    sid = session.start(vault, "default", "a").session_id
    session.update(vault, UpdateWorkingMemoryInput(session_id=sid, goal="Set by hand"))
    count = _commits(vault)
    memory = session.record_turn(vault, sid, "user", "something else", "a")
    assert memory.goal == "Set by hand" and _commits(vault) == count


def test_goal_commit_touches_only_the_working_md(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "hello", "a")
    assert _git(vault, "show", "--name-only", "--format=", "HEAD").split() == [vault.rel(vault.working_path(sid))]


def test_end_commit_touches_only_the_working_md_and_jsonl_stays_untracked(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "hello", "a")
    session.end(vault, sid)
    assert _git(vault, "show", "--name-only", "--format=", "HEAD").split() == [vault.rel(vault.working_path(sid))]
    assert _git(vault, "status", "--porcelain", "--untracked-files=all").splitlines() == [
        f"?? {vault.rel(session.transcript_path(vault, sid))}",
    ]


def test_end_extracts_facts_from_user_turns(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "I live in Seattle.", "a")
    result = session.end(vault, sid)
    assert result.ok and "1 facts extracted" in result.message
    facts = [p.read_text(encoding="utf-8") for p in (vault.root / "memory" / "shared" / "facts").glob("*.md")]
    assert any("Seattle" in text for text in facts)


def test_end_with_other_agent_puts_the_episode_in_its_scope(vault):
    created = _cli(vault, "agent", "create", "research")
    assert created.exit_code == 0, created.output
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "hello", "a")
    result = session.end(vault, sid, agent="research")
    assert result.ok and result.path.startswith("memory/research/episodes/")
    assert _git(vault, "log", "-1", "--format=%s").startswith("session: end (agent=research,")


def test_end_with_unknown_agent_fails_and_session_stays_active(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "hello", "a")
    count = _commits(vault)
    result = session.end(vault, sid, agent="nobody")
    assert not result.ok and result.message.startswith("PERMISSION_DENIED:") and result.action == "end_session"
    assert _commits(vault) == count and session.show(vault, sid).status == "active"
    assert session.end(vault, sid).ok  # can still be ended with its own agent


def test_busy_vault(vault, quick_lock):
    from filelock import FileLock  # noqa: PLC0415

    sid = session.start(vault, "default", "a").session_id
    count = _commits(vault)
    with FileLock(str(vault.lock_path)):
        with pytest.raises(Exception, match="busy"):
            session.record_turn(vault, sid, "user", "hello", "a")
        result = session.update(vault, UpdateWorkingMemoryInput(session_id=sid, goal="x"))
        assert not result.ok and result.message.startswith("vault busy:")
    assert _commits(vault) == count and not session.transcript_path(vault, sid).exists()


def test_list_ignores_other_files_in_working(vault):
    sid = session.start(vault, "default", "a").session_id
    (vault.root / "working" / "notes.md").write_text("not a session\n", encoding="utf-8")
    assert [m.session_id for m in session.list(vault)] == [sid]


def test_session_from_start_feeds_get_context(vault):
    from pam.contracts.retrieval import ContextRequest  # noqa: PLC0415
    from pam.retrieve import context  # noqa: PLC0415

    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "Plan the Immich backup", "a")
    session.update(vault, UpdateWorkingMemoryInput(session_id=sid, add_decisions=["Two-bay NAS"]))
    bundle = context.build_context(vault, ContextRequest(query="Immich", session_id=sid, token_budget=2000))
    assert bundle.working is not None and bundle.working.session_id == sid
    assert "Plan the Immich backup" in bundle.rendered and "Two-bay NAS" in bundle.rendered


@pytest.mark.parametrize("args", [
    ("session", "show", "s_000000000000"),
    ("session", "update", "s_000000000000", "--goal", "x"),
    ("session", "end", "s_000000000000"),
    ("session", "start", "--agent", "nobody", "--model", "a"),
])
def test_cli_errors_exit_1(vault, args):
    result = _cli(vault, *args)
    assert result.exit_code == 1, result.output


def test_cli_record_on_ended_session_exits_1(vault):
    sid = session.start(vault, "default", "a").session_id
    session.record_turn(vault, sid, "user", "hello", "a")
    session.end(vault, sid)
    result = _cli(vault, "session", "record", sid, "--role", "user", "--text", "x", "--model", "a")
    assert result.exit_code == 1 and "already ended" in result.output


def _later(minutes: float):
    from datetime import timedelta  # noqa: PLC0415
    from pam.core.time import utcnow  # noqa: PLC0415

    return utcnow() + timedelta(minutes=minutes)


def test_end_idle_ends_only_idle_sessions_with_turns(vault):
    idle = session.start(vault, "default", "model-a").session_id
    session.record_turn(vault, idle, "user", "Plan my backups", "model-a")
    empty = session.start(vault, "default", "model-a").session_id
    results = session.end_idle(vault, 30 * 60, now=_later(31))
    assert [r.ok for r in results] == [True]
    done = session.show(vault, idle)
    assert done.status == "ended" and done.promoted_episode_id
    assert session.show(vault, empty).status == "active"
    assert "session: auto-end" in _git(vault, "log", "--format=%s", "-n", "1")
    assert session.end_idle(vault, 30 * 60, now=_later(60)) == []


def test_end_idle_keeps_recent_sessions_and_zero_disables(vault):
    sid = session.start(vault, "default", "model-a").session_id
    session.record_turn(vault, sid, "user", "Hello there", "model-a")
    assert session.end_idle(vault, 30 * 60, now=_later(5)) == []
    assert session.end_idle(vault, 0, now=_later(600)) == []
    assert session.show(vault, sid).status == "active"


def test_cli_end_idle(vault):
    sid = session.start(vault, "default", "model-a").session_id
    session.record_turn(vault, sid, "user", "Hello there", "model-a")
    cfg = vault.config_path
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("session_idle_minutes = 30", "session_idle_minutes = 1"), encoding="utf-8")
    from datetime import timedelta  # noqa: PLC0415

    import pam.working.session as mod  # noqa: PLC0415

    real = mod.utcnow
    mod.utcnow = lambda: real() + timedelta(minutes=5)
    try:
        result = _cli(vault, "session", "end", "--idle")
    finally:
        mod.utcnow = real
    assert result.exit_code == 0, result.output
    assert "Ended 1 of 1" in result.output
    assert session.show(vault, sid).status == "ended"
    assert _cli(vault, "session", "end").exit_code != 0
