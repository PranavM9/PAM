"""Fact lookups and slot updates shared by the M7 writer (SPEC §7.4, §8 M7).

Behavior:
    Finds fact files by id, lists them, and builds the new `Fact` for an overwrite: the old value
    is pushed to `history` (the most recent 20 are kept) and any conflict is cleared. Conflicts are
    never resolved here by rule; `supersede_fact` and `add_fact` call this when an agent decides.
"""

from __future__ import annotations

import warnings
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from pam.contracts.common import Actor
from pam.contracts.fact import Fact, FactHistoryEntry, FactStatus
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.vault import Vault

HISTORY_LIMIT = 20


def find_fact_path(vault: Vault, fid: UUID) -> Path | None:
    """Locate a fact file by id in any scope.

    Returns:
        The absolute path, or `None` when no scope holds the fact.
    Parameters:
        vault: Vault to search.
        fid: Fact id.
    """
    return next(iter(sorted(vault.root.glob(f"memory/*/facts/{fid}.md"))), None)


def load_facts(vault: Vault, scope: str | None = None) -> list[tuple[Path, Fact]]:
    """Read every readable fact file.

    Behavior:
        Unreadable files are skipped with a warning.
    Returns:
        `(path, fact)` pairs sorted by path.
    Parameters:
        vault: Vault to read.
        scope: Only this scope (`shared` or an agent name), or `None` for every scope.
    """
    pattern = f"memory/{scope or '*'}/facts/*.md"
    found = []
    for path in sorted(vault.root.glob(pattern)):
        try:
            fact, _ = mdio.read_model(path, Fact)
        except (PamError, ValidationError, ValueError) as e:
            warnings.warn(f"skipping unreadable fact {path.name}: {e}", RuntimeWarning, stacklevel=2)
            continue
        found.append((path, fact))
    return found


def replace_value(
    fact: Fact,
    value: str,
    *,
    now: datetime,
    actor: Actor,
    agent: str | None,
    source_episode: UUID | None,
    confidence: float | None = None,
    reason: str | None = None,
    pattern_id: str | None = None,
) -> Fact:
    """Build the fact that results from overwriting a SINGLE slot's value.

    Behavior:
        Pushes the old value into `history` (value, time, actor, agent, the episode that produced
        it, and `reason`), keeps the last 20 entries, sets the new value, and clears `status=conflict`
        together with `conflict`. `agent` is stored on the history entry only for agent writes.
    Exceptions:
        pydantic.ValidationError: The resulting fact is invalid.
    Returns:
        The updated fact; the input is not modified.
    Parameters:
        fact: Current fact.
        value: New value.
        now: Time of the change.
        actor: Who decided the change; becomes the fact's `extractor`.
        agent: Agent name for the history entry, or `None`.
        source_episode: Episode that produced the new value; also `updated_by_episode`.
        confidence: New confidence, or `None` to keep the current one.
        reason: Why the value changed.
        pattern_id: Extractor pattern behind the new value, if any.
    """
    entry = FactHistoryEntry(
        value=fact.value, changed_at=now, changed_by=actor, agent=agent if actor is Actor.AGENT else None,
        episode_id=fact.source_episode, reason=reason,
    )
    data = fact.model_dump()
    data.update(
        value=value,
        confidence=fact.confidence if confidence is None else confidence,
        status=FactStatus.ACTIVE,
        conflict=None,
        source_episode=source_episode,
        updated_by_episode=source_episode,
        extractor=actor,
        pattern_id=pattern_id,
        history=[*data["history"], entry.model_dump()][-HISTORY_LIMIT:],
        updated_at=now,
    )
    return Fact.model_validate(data)
