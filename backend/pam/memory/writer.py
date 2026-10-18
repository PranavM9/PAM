"""The memory writer: the only code path that writes facts, logged episodes, projects, and skills (SPEC §8 M7).

Behavior:
    Every operation runs under `vault_write_lock` and follows one sequence: authorize through
    `pam.agents.permissions`, load, mutate, validate, write atomically, `git.commit`, then reindex
    the touched paths. A successful write makes exactly one commit and a failed write leaves the
    vault unchanged. Facts are updated in place with history, episode bodies are never touched
    (only the `superseded_facts` backlink in their frontmatter), and nothing is deleted.
    Failures come back as `WriteResult(ok=False)`: `PERMISSION_DENIED: ...`, `vault busy: ...`,
    `validation failed: ...`, or a not-found message.
"""

from __future__ import annotations

import json
import logging
import re
import warnings
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from pam.agents.manifest import load_manifest
from pam.agents.permissions import can_call, can_write
from pam.contracts.agent import AgentManifest
from pam.contracts.common import Actor, Source
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Cardinality, Fact, FactStatus, fact_id, normalize_value
from pam.contracts.project import Project
from pam.contracts.raw import RawConversation
from pam.contracts.skill import Skill
from pam.contracts.writes import (
    AddFactInput,
    AddSkillInput,
    LogEpisodeInput,
    SupersedeFactInput,
    UpdateProjectInput,
    WriteResult,
)
from pam.core import mdio
from pam.core.errors import PamError, PermissionDenied, VaultBusy
from pam.core.ids import new_uuid, sha256_text
from pam.core.lock import vault_write_lock
from pam.core.time import iso_z, utcnow
from pam.core.vault import Vault
from pam.memory import conflicts
from pam.normalize.render import render
from pam.sync import git

try:  # T06 (pam.index) may not be merged yet; tests spy on this module-level name.
    from pam.index.indexer import index_paths
except ImportError:
    index_paths = None

log = logging.getLogger(__name__)

SHARED = "shared"
SUMMARY_HEADING = "## Summary (auto)"
NOTES_HEADING = "## Notes"
NEW_PROJECT_BODY = f"{SUMMARY_HEADING}\n\n{NOTES_HEADING}\n"
DENIED_PREFIX = "PERMISSION_DENIED:"
BUSY_PREFIX = "vault busy:"
INVALID_PREFIX = "validation failed:"
MAX_SHORT = 72


class Txn:
    """The files one write changes, with their previous bytes for rollback.

    Behavior:
        `write` remembers a file's prior content (or that it did not exist) before replacing it
        atomically. `rollback` restores every remembered file and removes the ones that were new.
        The caller of a write that was handed a `Txn` commits `paths` or rolls back.
    """

    def __init__(self) -> None:
        self._saved: dict[Path, bytes | None] = {}

    @property
    def paths(self) -> list[Path]:
        """Files changed so far, in write order."""
        return list(self._saved)

    def _remember(self, path: Path) -> None:
        if path not in self._saved:
            self._saved[path] = path.read_bytes() if path.is_file() else None

    def write(self, path: Path, model, body: str) -> None:
        """Remember `path`, then write a model and body atomically (`mdio.write`)."""
        self._remember(path)
        mdio.write(path, model, body)

    def rollback(self) -> None:
        """Restore the previous content of every changed file."""
        for path, data in reversed(list(self._saved.items())):
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        self._saved.clear()


class _Fail(PamError):
    """A controlled write failure whose message is returned in the `WriteResult`."""


@dataclass
class _Done:
    short: str
    message: str
    doc_id: UUID | None = None
    path: str | None = None
    conflict: Fact | None = None
    changed: bool = True


def _vault(vault: Vault | str | Path | None) -> Vault:
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    return v.require_initialized()


def _short(text: str) -> str:
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= MAX_SHORT else collapsed[: MAX_SHORT - 1].rstrip() + "…"


def commit_message(action: str, short: str, agent: str, session_id: str | None = None) -> str:
    """Format a commit message as `<action>: <short> (agent=<name>[, session=<id>])`.

    Behavior:
        `short` is collapsed to one line and capped at 72 characters.
    Returns:
        The message.
    Parameters:
        action: Write operation name.
        short: What was written.
        agent: Agent that wrote.
        session_id: Working-memory session, if any.
    """
    suffix = f", session={session_id}" if session_id else ""
    return f"{action}: {_short(short) or '-'} (agent={agent}{suffix})"


def failure_exit_code(result: WriteResult) -> int:
    """Map a failed `WriteResult` to the SETUP §5 CLI exit code.

    Returns:
        `3` permission denied, `4` vault busy, `2` validation failed, else `1`.
    Parameters:
        result: A result with `ok=False`.
    """
    if result.message.startswith(DENIED_PREFIX):
        return 3
    if result.message.startswith(BUSY_PREFIX):
        return 4
    if result.message.startswith(INVALID_PREFIX):
        return 2
    return 1


def raise_for_result(result: WriteResult) -> None:
    """Raise the PAM error that matches a failed `WriteResult`.

    Exceptions:
        PermissionDenied: The message starts with `PERMISSION_DENIED:`.
        VaultBusy: The vault write lock was not acquired.
        PamError: Any other failure, with the exit code from `failure_exit_code`.
    Parameters:
        result: The result to check; successful results are ignored.
    """
    if result.ok:
        return
    if result.message.startswith(DENIED_PREFIX):
        raise PermissionDenied(result.message.removeprefix(DENIED_PREFIX).strip())
    if result.message.startswith(BUSY_PREFIX):
        raise VaultBusy(result.message)
    raise PamError(result.message, exit_code=failure_exit_code(result))


def reindex(vault: Vault, paths: Iterable[Path]) -> None:
    """Reindex committed paths with `pam.index.indexer.index_paths`.

    Behavior:
        Paths go to the indexer as vault-relative POSIX strings. When the indexer is not available
        the step is skipped with a debug log. An indexer error is logged and does not fail the
        write, which is already committed.
    Parameters:
        vault: The vault.
        paths: Files that were written.
    """
    rels = sorted({vault.rel(p) for p in paths})
    if index_paths is None:
        log.debug("indexer not available; skipped reindex of %d paths", len(rels))
        return
    try:
        index_paths(vault, rels)
    except Exception:  # noqa: BLE001 - the commit is done; a stale index is repaired by `pam index`
        log.warning("reindex of %d paths failed", len(rels), exc_info=True)


def _authorize(v: Vault, agent: str, tool: str, scope: str | None = None) -> AgentManifest:
    try:
        manifest = load_manifest(agent, v)
    except PamError as e:
        raise PermissionDenied(f"agent {agent!r} is not usable: {e}") from e
    if not can_call(manifest, tool):
        raise PermissionDenied(f"agent {agent!r} may not call {tool}")
    if scope is not None and not can_write(manifest, scope):
        raise PermissionDenied(f"agent {agent!r} may not write to the {scope!r} scope")
    return manifest


def _execute(
    vault: Vault | str | Path | None,
    action: str,
    agent: str,
    session_id: str | None,
    step: Callable[[Vault, Txn], _Done],
    txn: Txn | None = None,
) -> WriteResult:
    v = _vault(vault)
    own = txn is None
    local = Txn() if own else txn
    sha = None
    try:
        with vault_write_lock(v) if own else nullcontext():
            try:
                done = step(v, local)
                if own and done.changed:
                    sha = git.commit(v.root, local.paths, commit_message(action, done.short, agent, session_id))
            except BaseException:
                if own:
                    local.rollback()
                raise
    except PermissionDenied as e:
        return WriteResult(ok=False, action=action, message=f"{DENIED_PREFIX} {e}")
    except VaultBusy as e:
        return WriteResult(ok=False, action=action, message=f"{BUSY_PREFIX} {e}")
    except ValidationError as e:
        return WriteResult(ok=False, action=action, message=f"{INVALID_PREFIX} {e}")
    except PamError as e:
        return WriteResult(ok=False, action=action, message=str(e))
    if own and done.changed:
        reindex(v, local.paths)
    return WriteResult(
        ok=True, action=action, doc_id=done.doc_id, path=done.path, commit_sha=sha,
        conflict=done.conflict, message=done.message,
    )


def _fact_body(fact: Fact) -> str:
    return f"**{fact.attribute}**: {fact.value}\n"


def _backlink(v: Vault, txn: Txn, episode_id: UUID, fid: UUID, strict: bool) -> Path | None:
    """Append a fact id to an episode's `superseded_facts` and prove the body did not change."""
    path = next(iter(sorted(v.root.glob(f"memory/*/episodes/{episode_id}.md"))), None)
    if path is None:
        return None
    fm, body = mdio.read_model(path, EpisodeFrontmatter)
    if fid in fm.superseded_facts:
        return None
    if sha256_text(body) != fm.body_sha256:
        message = f"episode {episode_id} body does not match body_sha256; backlink not written"
        if strict:
            raise _Fail(f"{INVALID_PREFIX} {message}")
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        return None
    txn.write(path, fm.model_copy(update={"superseded_facts": [*fm.superseded_facts, fid]}), body)
    if sha256_text(mdio.read(path)[1]) != fm.body_sha256:
        raise _Fail(f"{INVALID_PREFIX} episode {episode_id} body changed while writing the backlink")
    return path


def plan_fact(
    existing: Fact | None,
    data: AddFactInput,
    scope: str,
    *,
    agent: str | None,
    extractor: Actor,
    pattern_id: str | None,
    now: datetime,
    reason: str | None = None,
) -> tuple[Fact, str]:
    """Decide what `add_fact` does to a slot and build the resulting fact.

    Behavior:
        Missing slot: `created`. Same normalized value: `bumped` (confidence is raised to the larger
        value and `updated_by_episode` follows the episode) or `unchanged`. Different value:
        `overwritten` through `conflicts.replace_value`, which records history and clears a conflict.
    Exceptions:
        pydantic.ValidationError: The resulting fact is invalid.
    Returns:
        The resulting fact and the outcome name.
    Parameters:
        existing: The fact currently in the slot, or `None`.
        data: The fact to add.
        scope: `shared` or an agent name.
        agent: Agent name for the history entry.
        extractor: Who decided the value.
        pattern_id: Extractor pattern behind the value, if any.
        now: Time stamped on the change.
        reason: History reason for an overwrite.
    """
    if existing is None:
        fid = fact_id(scope, data.subject, data.attribute, data.cardinality, data.value)
        fact = Fact(
            id=fid, scope=scope, subject=data.subject, attribute=data.attribute, value=data.value,
            cardinality=data.cardinality, category=data.category, confidence=data.confidence,
            source_episode=data.episode_id, updated_by_episode=data.episode_id, extractor=extractor,
            pattern_id=pattern_id, created_at=now, updated_at=now,
        )
        return fact, "created"
    if normalize_value(existing.value) == normalize_value(data.value):
        confidence = max(existing.confidence, data.confidence)
        updated_by = data.episode_id or existing.updated_by_episode
        if confidence == existing.confidence and updated_by == existing.updated_by_episode:
            return existing, "unchanged"
        bumped = Fact.model_validate(
            {**existing.model_dump(), "confidence": confidence, "updated_by_episode": updated_by, "updated_at": now}
        )
        return bumped, "bumped"
    replaced = conflicts.replace_value(
        existing, data.value, now=now, actor=extractor, agent=agent, source_episode=data.episode_id,
        confidence=data.confidence, reason=reason, pattern_id=pattern_id,
    )
    return replaced, "overwritten"


def add_fact(
    vault: Vault | str | Path | None,
    data: AddFactInput,
    agent: str = "default",
    *,
    extractor: Actor = Actor.AGENT,
    pattern_id: str | None = None,
    now: datetime | None = None,
    reason: str | None = None,
    txn: Txn | None = None,
) -> WriteResult:
    """Create a fact, bump its confidence, or overwrite its SINGLE value with history.

    Behavior:
        `shared=True` writes to `memory/shared/facts/` and needs `write="shared"`; otherwise the
        fact goes to the agent's own scope. An overwrite pushes the old value into `history`,
        sets `updated_by_episode`, and appends the fact id to the old `source_episode`'s
        `superseded_facts`, after which that episode's `body_sha256` is verified again (a mismatch
        aborts the write). An exact repeat is a successful no-op without a commit.
        The keyword-only arguments are for M3's extraction route: `extractor`, `pattern_id`, `now`,
        and `reason` stamp the fact, and a `txn` makes the call join the caller's transaction (no
        lock, no commit, no reindex, no rollback; the caller holds the lock and commits).
    Returns:
        A `WriteResult` with the fact's id and path; `conflict` is set when the stored fact is in
        conflict. Failures are returned, not raised.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        data: The fact to add.
        agent: Agent performing the write.
        extractor: Who decided the value.
        pattern_id: Extractor pattern behind the value.
        now: Time stamped on the change; defaults to the current time.
        reason: History reason for an overwrite.
        txn: The caller's transaction.
    """

    def step(v: Vault, txn: Txn) -> _Done:
        scope = SHARED if data.shared else agent
        _authorize(v, agent, "add_fact", scope)
        fid = fact_id(scope, data.subject, data.attribute, data.cardinality, data.value)
        path = v.fact_path(scope, fid)
        existing = mdio.read_model(path, Fact)[0] if path.is_file() else None
        fact, outcome = plan_fact(
            existing, data, scope, agent=agent, extractor=extractor, pattern_id=pattern_id,
            now=now or utcnow(), reason=reason,
        )
        rel = v.rel(path)
        flagged = fact if fact.status is FactStatus.CONFLICT else None
        short = f"{fact.attribute}={fact.value}"
        if outcome == "unchanged":
            return _Done(short, f"fact {fact.attribute} unchanged", fid, rel, flagged, changed=False)
        txn.write(path, fact, _fact_body(fact))
        if outcome == "overwritten" and existing is not None and existing.source_episode is not None:
            _backlink(v, txn, existing.source_episode, fid, strict=True)
        return _Done(short, f"fact {fact.attribute} {outcome}", fid, rel, flagged)

    return _execute(vault, "add_fact", agent, None, step, txn)


def supersede_fact(
    vault: Vault | str | Path | None, data: SupersedeFactInput, agent: str = "default"
) -> WriteResult:
    """Replace a fact's value by id, clear its conflict, and record why.

    Behavior:
        Works like an `add_fact` overwrite addressed by `fact_id`: the old value goes into `history`
        with `data.reason`, `status` returns to `active`, `conflict` is cleared, confidence is kept,
        and the old `source_episode` gets the `superseded_facts` backlink (body hash re-verified).
        An unknown id returns a not-found result and writes nothing. A MULTI fact has no single
        slot to replace (its id depends on the value), so it is rejected; add the new value instead.
    Returns:
        A `WriteResult` for the fact; failures are returned, not raised.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        data: Fact id, new value, and reason.
        agent: Agent performing the write.
    """

    def step(v: Vault, txn: Txn) -> _Done:
        _authorize(v, agent, "supersede_fact")
        path = conflicts.find_fact_path(v, data.fact_id)
        if path is None:
            raise _Fail(f"fact {data.fact_id} not found")
        existing = mdio.read_model(path, Fact)[0]
        _authorize(v, agent, "supersede_fact", existing.scope)
        if existing.cardinality is Cardinality.MULTI:
            raise _Fail(f"{INVALID_PREFIX} fact {data.fact_id} is multi-valued; add the new value with add_fact")
        fact = conflicts.replace_value(
            existing, data.new_value, now=utcnow(), actor=Actor.AGENT, agent=agent,
            source_episode=data.episode_id, reason=data.reason,
        )
        txn.write(path, fact, _fact_body(fact))
        if existing.source_episode is not None:
            _backlink(v, txn, existing.source_episode, fact.id, strict=True)
        return _Done(f"{fact.attribute}={fact.value}", f"fact {fact.attribute} superseded", fact.id, v.rel(path))

    return _execute(vault, "supersede_fact", agent, None, step)


def _raw_for_log(data: LogEpisodeInput, agent: str, now: datetime) -> RawConversation:
    digest = sha256_text(json.dumps(
        {"title": data.title, "summary": data.summary, "messages": [m.model_dump(mode="json") for m in data.messages]},
        sort_keys=True, ensure_ascii=False,
    ))
    return RawConversation(
        source=Source.PAM,
        source_conversation_id=f"{agent}:{iso_z(now)}:{digest[:8]}",
        title=data.title,
        created_at=now,
        updated_at=now,
        summary=data.summary,
        messages=data.messages,
    )


def log_episode(
    vault: Vault | str | Path | None,
    data: LogEpisodeInput,
    agent: str = "default",
    session_id: str | None = None,
) -> WriteResult:
    """Store a conversation as a new episode and mine its user messages for facts.

    Behavior:
        Builds a `RawConversation(source=pam)` with id `{agent}:{utc_iso}:{sha8}`, renders it with
        `pam.normalize.render`, and writes `memory/<agent>/episodes/<id>.md`. The user messages are
        then run through M3 extraction and merged into the shared facts (skipped when the agent may
        not write shared memory). The episode and its facts are one commit. Logging the identical
        conversation in the same second is a successful no-op.
    Returns:
        A `WriteResult` whose `doc_id` is the episode id; failures are returned, not raised.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        data: Title, messages, optional summary and tags.
        agent: Agent that owns the episode.
        session_id: Working-memory session recorded in the commit message.
    """

    def step(v: Vault, txn: Txn) -> _Done:
        from pam.extract import facts as extract  # deferred: pam.extract.facts imports this module

        manifest = _authorize(v, agent, "log_episode", agent)
        now = utcnow()
        fm, body = render(_raw_for_log(data, agent, now), now, agent)
        fm = fm.model_copy(update={"tags": list(dict.fromkeys(data.tags))})
        path = v.episode_path(agent, fm.id)
        rel = v.rel(path)
        if path.is_file():
            return _Done(fm.title, "episode already logged", fm.id, rel, changed=False)
        txn.write(path, fm, body)
        found = 0
        if can_write(manifest, SHARED):
            texts = [m.text for m in data.messages if m.role == "user"]
            ref = extract.EpisodeRef(fm.id, fm.created_at)
            found = len(extract.extract_and_store(v, texts, ref, agent, txn, {fm.id: fm.created_at}).facts)
        return _Done(fm.title, f"episode logged; {found} facts extracted", fm.id, rel)

    return _execute(vault, "log_episode", agent, session_id, step)


def _append_note(body: str, agent: str, note: str, now: datetime) -> str:
    bullet = f"- {now.strftime('%Y-%m-%dT%H:%MZ')} (agent:{agent}) {' '.join(note.split())}\n"
    if not re.search(rf"^{re.escape(NOTES_HEADING)}\s*$", body, re.M):
        body = body.rstrip("\n") + f"\n\n{NOTES_HEADING}\n"
    elif not body.endswith("\n"):
        body += "\n"
    return body + bullet


def _project_owners(v: Vault, scope: str, skip: UUID) -> dict[UUID, UUID]:
    # episode id -> id of the other project (same scope) that already holds it
    owners: dict[UUID, UUID] = {}
    for path in sorted(v.memory_dir(scope).glob("projects/*.md")):
        try:
            other = mdio.read_model(path, Project)[0]
        except (PamError, ValidationError, ValueError):
            continue
        if other.id != skip:
            owners.update({e: other.id for e in other.episode_ids})
    return owners


def update_project(
    vault: Vault | str | Path | None,
    data: UpdateProjectInput,
    agent: str = "default",
    session_id: str | None = None,
) -> WriteResult:
    """Create a project, or append a note, episodes, or a status to an existing one.

    Behavior:
        Without `project_id` a project is created in the agent's scope (`origin=agent`, `name`
        required). Otherwise the project is found in any scope and the agent must be allowed to
        write that scope. A note becomes exactly one `- <YYYY-MM-DDTHH:MMZ> (agent:<name>) <note>`
        bullet at the end of `## Notes`; `## Summary (auto)` is never rewritten. Episodes are added
        once each and an episode may belong to only one project of the scope. Nothing to change is a
        successful no-op without a commit.
    Returns:
        A `WriteResult` whose `doc_id` is the project id; failures are returned, not raised.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        data: Project id or name, note, episodes, status.
        agent: Agent performing the write.
        session_id: Working-memory session recorded in the commit message.
    """

    def step(v: Vault, txn: Txn) -> _Done:
        now = utcnow()
        if data.project_id is None:
            name = " ".join((data.name or "").split())
            if not name:
                raise _Fail(f"{INVALID_PREFIX} a name is required to create a project")
            _authorize(v, agent, "update_project", agent)
            scope, pid, body, verb = agent, new_uuid(), NEW_PROJECT_BODY, "created"
            project = Project(
                id=pid, scope=scope, name=name, origin=Actor.AGENT, status=data.status or "active",
                created_at=now, updated_at=now, last_activity_at=now,
            )
        else:
            _authorize(v, agent, "update_project")
            pid = data.project_id
            found = next(iter(sorted(v.root.glob(f"memory/*/projects/{pid}.md"))), None)
            if found is None:
                raise _Fail(f"project {pid} not found")
            scope = found.parent.parent.name
            _authorize(v, agent, "update_project", scope)
            project, body = mdio.read_model(found, Project)
            verb = "updated"
        new_eps = [e for e in dict.fromkeys(data.add_episode_ids) if e not in project.episode_ids]
        taken = _project_owners(v, scope, pid) if new_eps else {}
        for e in new_eps:
            if e in taken:
                raise _Fail(f"{INVALID_PREFIX} episode {e} already belongs to project {taken[e]}")
        changes: dict = {}
        if verb == "updated":
            name = " ".join((data.name or "").split())
            if name and name != project.name:
                changes["name"] = name
            if data.status and data.status != project.status:
                changes["status"] = data.status
        if new_eps:
            changes["episode_ids"] = [*project.episode_ids, *new_eps]
        if data.note and data.note.strip():
            body = _append_note(body, agent, data.note, now)
            changes["note"] = True
        if verb == "updated" and not changes:
            return _Done(project.name, "project unchanged", pid, v.rel(v.project_path(scope, pid)), changed=False)
        changes.pop("note", None)
        project = Project.model_validate(
            {**project.model_dump(), **changes, "updated_at": now, "last_activity_at": now}
        )
        path = v.project_path(scope, pid)
        txn.write(path, project, body)
        return _Done(project.name, f"project {verb}", pid, v.rel(path))

    return _execute(vault, "update_project", agent, session_id, step)


def normalize_skill_name(name: str) -> str:
    """Normalize a skill name for matching: lowercase, runs of other characters become `-`.

    Returns:
        The normalized name, e.g. `release-checklist` for `Release checklist`.
    Parameters:
        name: Skill name.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def add_skill(vault: Vault | str | Path | None, data: AddSkillInput, agent: str = "default") -> WriteResult:
    """Create a skill, or update it in place when the normalized name already exists.

    Behavior:
        The skill is stored at `skills/<agent>/<id>.md` with the steps as its body. A skill of the
        same scope whose normalized name matches keeps its id, name, and creation data; its
        description, keywords, and steps are replaced (history lives in git).
    Returns:
        A `WriteResult` whose `doc_id` is the skill id; failures are returned, not raised.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        data: Name, description, steps, and trigger keywords.
        agent: Agent performing the write.
    """

    def step(v: Vault, txn: Txn) -> _Done:
        _authorize(v, agent, "add_skill", agent)
        key = normalize_skill_name(data.name)
        if not key:
            raise _Fail(f"{INVALID_PREFIX} the skill name has no letters or digits")
        steps = data.steps_markdown.replace("\r\n", "\n").rstrip("\n") + "\n"
        now = utcnow()
        match: tuple[Path, Skill] | None = None
        for path in sorted((v.root / "skills" / agent).glob("*.md")):
            try:
                old = mdio.read_model(path, Skill)[0]
            except (PamError, ValidationError, ValueError):
                continue
            if normalize_skill_name(old.name) == key:
                match = (path, old)
                break
        if match is None:
            skill = Skill(
                id=new_uuid(), scope=agent, name=" ".join(data.name.split()), description=data.description,
                trigger_keywords=data.trigger_keywords, created_by=Actor.AGENT, created_at=now, updated_at=now,
            )
            path, verb = v.skill_path(agent, skill.id), "created"
        else:
            path, old = match
            skill = Skill.model_validate({
                **old.model_dump(), "description": data.description,
                "trigger_keywords": data.trigger_keywords, "updated_at": now,
            })
            verb = "updated"
        txn.write(path, skill, steps)
        return _Done(skill.name, f"skill {verb}", skill.id, v.rel(path))

    return _execute(vault, "add_skill", agent, None, step)


def merge_candidate(
    vault: Vault | str | Path | None, result, agent: str = "default", *, txn: Txn | None = None
) -> tuple[list[Path], list[Path]]:
    """Write a finished M3 merge (facts and backlinks) without locking or committing.

    Behavior:
        For callers that already hold the vault write lock and make their own commit (`pam derive`
        and `facts.write_candidates`). Checks that the agent may call `add_fact` and write the
        shared scope, writes every fact in `result.facts`, then appends each backlink after
        verifying the episode's `body_sha256`; an episode whose body does not match is skipped with
        a warning, as are backlinks to missing episodes. Conflicted facts are written as flagged.
    Exceptions:
        PermissionDenied: The agent may not write shared facts.
        OSError: A file cannot be written.
    Returns:
        The paths changed, and the subset that did not exist before.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        result: The `MergeResult` to store.
        agent: Agent on whose behalf the merge runs.
        txn: Transaction that records the files for the caller's rollback.
    """
    v = _vault(vault)
    local = txn if txn is not None else Txn()
    _authorize(v, agent, "add_fact", SHARED)
    changed: list[Path] = []
    created: list[Path] = []
    for fid, fact in result.facts.items():
        path = v.fact_path(fact.scope, fid)
        existed = fid in result.on_disk
        local.write(path, fact, _fact_body(fact))
        changed.append(path)
        if not existed:
            created.append(path)
    for episode_id, fid in result.backlinks:
        path = _backlink(v, local, episode_id, fid, strict=False)
        if path is not None and path not in changed:
            changed.append(path)
    return changed, created
