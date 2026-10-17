"""The `pam derive` pipeline: episodes in, facts and the default persona out (SPEC §8 M3).

Behavior:
    Mines the user messages of unprocessed episodes for facts, merges them into the `shared`
    slots, recomputes the rules, style, and identity from every episode, rewrites the Derived
    persona sections, and records everything as one commit. Processed episode ids are kept in
    `.pam/derive_state.json` (derived, gitignored), so repeating a run never adds confidence twice.
"""

from __future__ import annotations

import json
import time
import warnings
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import normalize_value
from pam.contracts.reports import DeriveReport
from pam.core import config, mdio
from pam.core.errors import PamError
from pam.core.lock import vault_write_lock
from pam.core.vault import Vault
from pam.extract import persona
from pam.extract.facts import EpisodeRef, Merger, extract_candidates, load_shared_facts, write_merge
from pam.extract.rules import derive_rules
from pam.extract.style import compute_stats, style_sentences
from pam.extract.text import transcript_messages
from pam.sync import git

STATE_FILE = "derive_state.json"


@dataclass(frozen=True)
class Episode:
    """An episode reduced to what derivation needs: its id, time, and user messages."""

    id: UUID
    agent: str
    created_at: datetime
    messages: tuple[str, ...]


def load_episodes(vault: Vault) -> list[Episode]:
    """Read every episode of every agent.

    Behavior:
        Keeps only `user` messages. Unreadable episodes are skipped with a warning.
    Returns:
        Episodes oldest first (ties by id).
    Parameters:
        vault: The vault to read.
    """
    episodes = []
    for path in sorted(vault.root.glob("memory/*/episodes/*.md")):
        try:
            fm, body = mdio.read_model(path, EpisodeFrontmatter)
        except (PamError, ValidationError, ValueError) as e:
            warnings.warn(f"skipping unreadable episode {path.name}: {e}", RuntimeWarning, stacklevel=2)
            continue
        users = tuple(text for role, text in transcript_messages(body) if role == "user" and text)
        episodes.append(Episode(fm.id, fm.agent, fm.created_at, users))
    return sorted(episodes, key=lambda e: (e.created_at, str(e.id)))


def _select(episodes: list[Episode], ref: str | None) -> list[Episode]:
    if ref is None:
        return episodes
    matches = [e for e in episodes if str(e.id).startswith(ref.lower())]
    if not matches:
        raise PamError(f"no episode with id {ref}")
    if len(matches) > 1:
        raise PamError(f"id prefix {ref} is ambiguous ({len(matches)} episodes)")
    return matches


def _state_path(vault: Vault) -> Path:
    return vault.pam_dir / STATE_FILE


def _load_state(vault: Vault) -> set[str]:
    try:
        data = json.loads(_state_path(vault).read_text(encoding="utf-8"))
        return {str(x) for x in data["episodes"]}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _save_state(vault: Vault, ids: set[str]) -> None:
    mdio.write_text(_state_path(vault), json.dumps({"episodes": sorted(ids)}, indent=2) + "\n")


def _rollback(vault: Vault, before: set[str]) -> None:
    # Undo what this run left behind: new files go away, changed tracked files return to HEAD.
    for status, rel in git.status_porcelain(vault.root):
        if rel in before:
            continue
        if status == "??" or status[0] == "A":
            git.run(vault.root, "reset", "-q", "--", rel, check=False)
            vault.abs(rel).unlink(missing_ok=True)
        else:
            git.restore(vault.root, rel)


def derive(vault: Vault | str | Path | None = None, episode: str | None = None, dry_run: bool = False) -> DeriveReport:
    """Run the M3 derivation.

    Behavior:
        Facts come from episodes not yet processed (all of them, or the one matching `episode`),
        merged in chronological order. Rules, style, and identity are recomputed from all episodes.
        Without `dry_run`, holds the write lock, writes the changed files, and makes exactly one
        commit `derive: +<created> ~<updated> !<conflicts>`; nothing changed means no commit.
        A failed commit removes the files this run wrote.
    Exceptions:
        PamError: The vault is not initialized, the episode id is unknown or ambiguous, or git fails.
        VaultBusy: The write lock is held by another writer.
    Returns:
        The `DeriveReport`; `rules_derived` is the number of derived rules in the persona.
    Parameters:
        vault: Vault, its folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        episode: Episode id or unique prefix to process, or `None` for every unprocessed episode.
        dry_run: Compute the report without writing anything.
    """
    started = time.monotonic()
    v = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).require_initialized()
    extraction = config.load(v).extraction
    sha = None
    with nullcontext() if dry_run else vault_write_lock(v):
        episodes = load_episodes(v)
        targets = _select(episodes, episode)
        done = _load_state(v)
        merger = Merger(v, {e.id: e.created_at for e in episodes})
        for e in targets:
            if str(e.id) in done:
                continue
            ref, seen = EpisodeRef(e.id, e.created_at), set()
            for message in e.messages:
                for cand in extract_candidates(message, "user", extraction.spacy_model):
                    key = (cand.attribute, normalize_value(cand.value))
                    if key not in seen:
                        seen.add(key)
                        merger.add(ref, cand)
        res = merger.result
        facts = load_shared_facts(v)
        facts.update(res.facts)
        rules = derive_rules(
            [(e.id, e.messages) for e in episodes], extraction.rule_min_evidence, extraction.spacy_model
        )
        stats = compute_stats(m for e in episodes for m in e.messages)
        updates = persona.persona_updates(
            v,
            {
                "identity": persona.render_identity(facts.values(), persona.load_project_names(v)),
                "rules": persona.render_rules(rules),
                "style": persona.render_style(style_sentences(stats)),
            },
        )
        created, updated, conflicts = len(res.created), len(res.updated), len(res.conflicts)
        if not dry_run:
            before = {rel for _, rel in git.status_porcelain(v.root)}
            try:
                changed, _ = write_merge(v, res)
                for path, text in updates.items():
                    mdio.write_text(path, text)
                    changed.append(path)
                if changed:
                    sha = git.commit(v.root, changed, f"derive: +{created} ~{updated} !{conflicts}")
            except BaseException:
                _rollback(v, before)
                raise
            _save_state(v, done | {str(e.id) for e in targets})
    return DeriveReport(
        facts_created=created, facts_updated=updated, conflicts_flagged=conflicts,
        rules_derived=len(rules), commit_sha=sha, duration_ms=round((time.monotonic() - started) * 1000),
    )
