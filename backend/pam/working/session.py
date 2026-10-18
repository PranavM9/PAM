"""Working memory: one short-term session per chat, promoted to an episode on end (SPEC §8 M9).

Behavior:
    A session is `working/<id>.md` (frontmatter = `WorkingMemory`, body = goal, decisions, and
    open questions as Markdown) plus `working/<id>.transcript.jsonl`, one `RawMessage` and its
    `model` per line. The transcript is never added to git (M10 sync skips it). Per-turn state
    (`recent_turns`, `models_used`) is rebuilt from the transcript, so a turn writes only the
    transcript and makes no commit; the `.md` is refreshed and committed on start, on the
    first-user-message goal, on `update`, and on `end`. Every write holds the vault write lock.
"""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from pam.agents.manifest import load_manifest
from pam.contracts.raw import RawMessage
from pam.contracts.working import ModelSwitch, WorkingMemory
from pam.contracts.writes import LogEpisodeInput, UpdateWorkingMemoryInput, WriteResult
from pam.core import mdio
from pam.core.errors import PamError, VaultBusy
from pam.core.lock import vault_write_lock
from pam.core.time import utcnow
from pam.core.vault import Vault
from pam.memory import writer
from pam.sync import git

ID_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"
ID_LENGTH = 12
RECENT_TURNS = 8
GOAL_CHARS = 200
TRANSCRIPT_SUFFIX = ".transcript.jsonl"
UPDATE_ACTION = "update_working_memory"
END_ACTION = "end_session"


def _vault(vault: Vault | str | Path | None) -> Vault:
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    return v.require_initialized()


def _valid_id(session_id: str) -> bool:
    return (
        len(session_id) == 2 + ID_LENGTH and session_id.startswith("s_")
        and all(c in ID_ALPHABET for c in session_id[2:])
    )


def _new_id() -> str:
    return "s_" + "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def transcript_path(vault: Vault, session_id: str) -> Path:
    """Return the path of a session's transcript, `working/<id>.transcript.jsonl`."""
    return vault.working_path(session_id).with_name(session_id + TRANSCRIPT_SUFFIX)


def _goal_from(text: str) -> str:
    return " ".join(text.split())[:GOAL_CHARS]


def render_body(memory: WorkingMemory) -> str:
    """Render the Markdown body of a working-memory file.

    Behavior:
        Writes a title, then `## Goal`, `## Decisions`, and `## Open questions`; an empty section
        shows `_none_`.
    Returns:
        The body text, ending in a newline.
    Parameters:
        memory: The session to render.
    """

    def bullets(items: list[str]) -> str:
        return "\n".join(f"- {' '.join(item.split())}" for item in items) if items else "_none_"

    return (
        f"# Working memory {memory.session_id}\n\n"
        f"## Goal\n\n{memory.goal or '_none_'}\n\n"
        f"## Decisions\n\n{bullets(memory.decisions)}\n\n"
        f"## Open questions\n\n{bullets(memory.open_questions)}\n"
    )


def _read_transcript(v: Vault, session_id: str) -> list[tuple[RawMessage, str]]:
    path = transcript_path(v, session_id)
    if not path.is_file():
        return []
    turns = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            model = data.pop("model")
            turns.append((RawMessage.model_validate(data), str(model)))
        except (ValueError, KeyError, ValidationError) as e:
            raise PamError(f"{v.rel(path)}:{number}: not a valid transcript line: {e}") from e
    return turns


def _with_turns(memory: WorkingMemory, turns: list[tuple[RawMessage, str]]) -> WorkingMemory:
    if not turns:
        return memory
    switches = memory.models_used[:1]
    last = switches[0].to_model if switches else None
    for message, model in turns:
        if model != last:
            switches.append(ModelSwitch(at=message.created_at or memory.updated_at, from_model=last, to_model=model))
            last = model
    latest = turns[-1][0].created_at
    return memory.model_copy(update={
        "models_used": switches,
        "recent_turns": [message for message, _ in turns[-RECENT_TURNS:]],
        "updated_at": max(memory.updated_at, latest) if latest else memory.updated_at,
    })


def _load(v: Vault, session_id: str) -> WorkingMemory:
    path = v.working_path(session_id) if _valid_id(session_id) else None
    if path is None or not path.is_file():
        raise PamError(f"session {session_id} not found")
    memory, _ = mdio.read_model(path, WorkingMemory)
    return _with_turns(memory, _read_transcript(v, session_id))


def _commit(v: Vault, memory: WorkingMemory, message: str) -> str:
    txn = writer.Txn()
    path = v.working_path(memory.session_id)
    try:
        txn.write(path, memory, render_body(memory))
        return git.commit(v.root, txn.paths, message)
    except BaseException:
        txn.rollback()
        raise


def _session_message(action: str, agent: str, session_id: str) -> str:
    return f"session: {action} (agent={agent}, session={session_id})"


def start(vault: Vault | str | Path | None, agent: str, model: str) -> WorkingMemory:
    """Create a session and commit its working file.

    Behavior:
        Picks an unused id `s_` + 12 random base36 characters, records `model` as the first
        `models_used` entry, writes `working/<id>.md`, and commits it as
        `session: start (agent=<a>, session=<id>)`.
    Exceptions:
        PamError: The agent has no manifest, or the commit fails.
        VaultBusy: The vault write lock was not acquired.
        ValidationError: `agent` is not a valid slug.
    Returns:
        The new session.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        agent: Agent that owns the session.
        model: Model of the first turn.
    """
    v = _vault(vault)
    load_manifest(agent, v)
    with vault_write_lock(v):
        session_id = _new_id()
        while v.working_path(session_id).exists():
            session_id = _new_id()
        now = utcnow()
        memory = WorkingMemory(
            session_id=session_id, agent=agent, started_at=now, updated_at=now,
            models_used=[ModelSwitch(at=now, from_model=None, to_model=model)],
        )
        _commit(v, memory, _session_message("start", agent, session_id))
    return memory


def record_turn(
    vault: Vault | str | Path | None,
    session_id: str,
    role: Literal["user", "assistant", "system", "tool"],
    text: str,
    model: str,
) -> WorkingMemory:
    """Append one chat turn to a session's transcript.

    Behavior:
        Appends `{role, text, created_at, model}` to `working/<id>.transcript.jsonl` without a
        commit. The returned session keeps the last 8 turns in `recent_turns` and has a new
        `ModelSwitch` when `model` differs from the last model used. The first user message of a
        session without a goal sets the goal (whitespace collapsed, 200 characters), which is the
        only case that commits (`session: goal ...`).
    Exceptions:
        PamError: The session is missing or ended, or the transcript is unreadable.
        VaultBusy: The vault write lock was not acquired.
    Returns:
        The session after the turn.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        session_id: Session to record into.
        role: Author of the turn.
        text: Message text.
        model: Model that produced or received the turn.
    """
    v = _vault(vault)
    with vault_write_lock(v):
        memory = _load(v, session_id)
        if memory.status == "ended":
            raise PamError(f"session {session_id} already ended")
        message = RawMessage(role=role, text=text, created_at=utcnow())
        line = json.dumps({**message.model_dump(mode="json"), "model": model}, ensure_ascii=False)
        path = transcript_path(v, session_id)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(line + "\n")
        memory = _load(v, session_id)
        if memory.goal is None and role == "user" and text.strip():
            memory = memory.model_copy(update={"goal": _goal_from(text)})
            _commit(v, memory, _session_message("goal", memory.agent, session_id))
    return memory


def _write_result(
    vault: Vault | str | Path | None, action: str, step: Callable[[Vault], WriteResult],
) -> WriteResult:
    try:
        return step(_vault(vault))
    except VaultBusy as e:
        return WriteResult(ok=False, action=action, message=f"{writer.BUSY_PREFIX} {e}")
    except ValidationError as e:
        return WriteResult(ok=False, action=action, message=f"{writer.INVALID_PREFIX} {e}")
    except PamError as e:
        return WriteResult(ok=False, action=action, message=str(e))


def update(vault: Vault | str | Path | None, data: UpdateWorkingMemoryInput, agent: str = "default") -> WriteResult:
    """Set a session's goal and append decisions or open questions.

    Behavior:
        `decisions` and `open_questions` are append-only (blank entries are dropped); `goal`
        replaces the current goal. A change is one commit
        `update_working_memory: <session> (agent=<a>, session=<id>)`; nothing to change is an
        `ok` result with no commit. Any agent may update any session.
    Returns:
        A `WriteResult` with the working file's path; a missing or ended session, a busy vault,
        or invalid data is `ok=False`.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        data: Session id, optional goal, decisions and questions to append.
        agent: Agent named in the commit message.
    """

    def step(v: Vault) -> WriteResult:
        with vault_write_lock(v):
            memory = _load(v, data.session_id)
            if memory.status == "ended":
                raise PamError(f"session {data.session_id} already ended")
            decisions = [d.strip() for d in data.add_decisions if d.strip()]
            questions = [q.strip() for q in data.add_open_questions if q.strip()]
            goal = memory.goal if data.goal is None else data.goal.strip() or None
            rel = v.rel(v.working_path(data.session_id))
            if not decisions and not questions and goal == memory.goal:
                return WriteResult(ok=True, action=UPDATE_ACTION, path=rel, message="nothing to update")
            memory = memory.model_copy(update={
                "goal": goal,
                "decisions": [*memory.decisions, *decisions],
                "open_questions": [*memory.open_questions, *questions],
                "updated_at": utcnow(),
            })
            WorkingMemory.model_validate(memory.model_dump())
            message = writer.commit_message(UPDATE_ACTION, data.session_id, agent, data.session_id)
            sha = _commit(v, memory, message)
        return WriteResult(
            ok=True, action=UPDATE_ACTION, path=rel, commit_sha=sha,
            message=f"working memory updated (+{len(decisions)} decisions, +{len(questions)} questions)",
        )

    return _write_result(vault, UPDATE_ACTION, step)


update_working_memory = update  # the name the MCP tool imports (CHG-0010 item 1)


def show(vault: Vault | str | Path | None, session_id: str) -> WorkingMemory:
    """Read one session with its current turns.

    Exceptions:
        PamError: The session does not exist, or its transcript is unreadable.
        SchemaVersionError: The working file has an unknown major version.
    Returns:
        The session; `recent_turns` and `models_used` include turns not yet committed.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        session_id: Session to read.
    """
    return _load(_vault(vault), session_id)


def list_sessions(vault: Vault | str | Path | None) -> list[WorkingMemory]:
    """Read every session in `working/`, newest first.

    Exceptions:
        PamError: A working file or transcript is unreadable.
    Returns:
        The sessions, sorted by `started_at` descending.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    v = _vault(vault)
    folder = v.root / "working"
    ids = sorted(p.stem for p in folder.glob("*.md")) if folder.is_dir() else []
    sessions = [_load(v, sid) for sid in ids if _valid_id(sid)]
    return sorted(sessions, key=lambda m: m.started_at, reverse=True)


def _episode_input(memory: WorkingMemory, messages: list[RawMessage]) -> LogEpisodeInput:
    summary = f"Goal: {memory.goal or 'none'}"
    if memory.decisions:
        summary += "\nDecisions: " + "; ".join(memory.decisions)
    title = (memory.goal or f"Session {memory.session_id}")[:GOAL_CHARS]
    return LogEpisodeInput(title=title, messages=messages, summary=summary, tags=[f"session:{memory.session_id}"])


def end(vault: Vault | str | Path | None, session_id: str, agent: str | None = None) -> WriteResult:
    """Promote a session to an episode and mark it ended.

    Behavior:
        Builds a `LogEpisodeInput` from the full transcript (title = goal or `Session <id>`,
        summary = goal and decisions, tag `session:<id>`) and stores it with
        `pam.memory.writer.log_episode`, which makes its own commit. Then sets `status=ended`
        and `promoted_episode_id` and commits `session: end ...`. The working file and the
        transcript are kept. Any agent may end any session.
    Returns:
        A `WriteResult` whose `doc_id` and `path` are the episode's and whose `commit_sha` is the
        end commit. `ok=False` for a missing session, an `already ended` session, a session with
        no turns, a busy vault, or a failed `log_episode` (whose message is passed through); the
        session then stays active.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        session_id: Session to end.
        agent: Agent that owns the episode; defaults to the session's agent.
    """

    def step(v: Vault) -> WriteResult:
        memory = _load(v, session_id)
        if memory.status == "ended":
            return WriteResult(ok=False, action=END_ACTION, message=f"session {session_id} already ended")
        messages = [message for message, _ in _read_transcript(v, session_id)]
        if not messages:
            return WriteResult(ok=False, action=END_ACTION, message=f"session {session_id} has no turns to promote")
        owner = agent or memory.agent
        logged = writer.log_episode(v, _episode_input(memory, messages), owner, session_id)
        if not logged.ok:
            return logged.model_copy(update={"action": END_ACTION})
        with vault_write_lock(v):
            memory = _load(v, session_id)
            memory = memory.model_copy(update={
                "status": "ended", "promoted_episode_id": logged.doc_id, "updated_at": utcnow(),
            })
            sha = _commit(v, memory, _session_message("end", owner, session_id))
        return WriteResult(
            ok=True, action=END_ACTION, doc_id=logged.doc_id, path=logged.path, commit_sha=sha,
            message=f"session ended; {logged.message}",
        )

    return _write_result(vault, END_ACTION, step)


list = list_sessions  # noqa: A001 - the M9 API name; nothing below this line calls the builtin
