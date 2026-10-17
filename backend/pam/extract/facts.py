"""Fact extraction, merging, and the minimal fact writer (SPEC §8 M3, §7.4).

Behavior:
    `extract_candidates` mines one user message with the `patterns.PATTERNS` table. `Merger`
    applies candidates to the `shared` fact slots following the §8 M3 merge rules, and
    `write_merge` stores the result under the vault write lock. T09 reroutes the writer half
    through `pam.memory`; the extraction half stays here.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError

from pam.contracts.common import Actor
from pam.contracts.config import ExtractCfg
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import (
    Cardinality,
    Fact,
    FactCategory,
    FactConflict,
    FactHistoryEntry,
    FactStatus,
    fact_id,
    normalize_value,
)
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.ids import sha256_text
from pam.core.lock import vault_write_lock
from pam.core.time import utcnow
from pam.core.vault import Vault
from pam.extract import patterns as pat
from pam.extract.text import Sentence, cap_value, iter_sentences, load_nlp, mask_ignored, negated
from pam.sync import git

SCOPE = "shared"
SUBJECT = "user"
HISTORY_LIMIT = 20


@dataclass(frozen=True)
class Candidate:
    """One value a pattern captured from a sentence.

    Behavior:
        `start` and `end` are character offsets of the value in the masked message line. `skipped`
        names the reason a match is not a fact (`question`, `hypothetical`, `negation`, `junk`,
        `not ORG`, `not GPE`); it is `None` for real candidates.
    """

    attribute: str
    value: str
    pattern_id: str
    category: str
    cardinality: str
    confidence: float
    start: int = 0
    end: int = 0
    skipped: str | None = None


@dataclass(frozen=True)
class EpisodeRef:
    """The episode that is the evidence for a candidate; `id` is `None` for unsaved text."""

    id: UUID | None
    created_at: datetime


def _has_match(line: str) -> bool:
    return any(pat.compiled(p["id"]).search(line) for p in pat.PATTERNS)


def _split_raw(raw: str, pattern: dict) -> list[tuple[str, int]]:
    """Trim a captured value at its first clause boundary and split list values."""
    list_valued = bool(pattern.get("split"))
    cut = (pat.LIST_CLAUSE_BOUNDARY if list_valued else pat.CLAUSE_BOUNDARY).search(raw)
    head = raw[: cut.start()] if cut else raw
    if not list_valued:
        return [(head, 0)]
    items, pos = [], 0
    for sep in pat.LIST_SEPARATOR.finditer(head):
        items.append((head[pos : sep.start()], pos))
        pos = sep.end()
    items.append((head[pos:], pos))
    return items


def _is_junk(value: str, pattern: dict) -> bool:
    if not value or not re.search(r"\w", value) or pat.JUNK_VALUE.match(value):
        return True
    reject = pattern.get("reject")
    return bool(reject and re.match(reject, value, re.I))


def _passes_ner(label: str, value: str, span: tuple[int, int], sentence: Sentence) -> bool:
    # A real ORG/GPE value is capitalized; an acronym such as UW or WSU passes even if spaCy misses it.
    if not any(word[:1].isupper() for word in value.split()):
        return False
    if pat.ACRONYM.fullmatch(value) or not sentence.has_ner:
        return True
    accepted = pat.NER_LABELS[label]
    return any(l in accepted and s < span[1] and span[0] < e for s, e, l in sentence.entities)


def _scan_sentence(sentence: Sentence) -> list[Candidate]:
    text = sentence.text
    blanket = "question" if "?" in text else "hypothetical" if pat.HYPOTHETICAL.search(text) else None
    found = []
    for pattern in pat.PATTERNS:
        for m in pat.compiled(pattern["id"]).finditer(text):
            reason = blanket or ("negation" if negated(text[: m.start()]) else None)
            base = m.start(pattern["value_group"])
            for item, offset in _split_raw(m.group(pattern["value_group"]), pattern):
                value = cap_value(item.strip().rstrip(" .,;:!-–—"))
                start = base + offset + (len(item) - len(item.lstrip()))
                span = (start, start + len(value))
                skip = reason
                if skip is None and _is_junk(value, pattern):
                    skip = "junk"
                label = pattern.get("ner_filter")
                if skip is None and label and not _passes_ner(label, value, span, sentence):
                    skip = f"not {label}"
                found.append(
                    Candidate(
                        pattern["attribute"], value, pattern["id"], pattern["category"],
                        pattern["cardinality"], pattern["confidence"], span[0], span[1], skip,
                    )
                )
    return found


def scan_text(text: str, role: str = "user", spacy_model: str | None = None) -> list[Candidate]:
    """Match every pattern against a message and keep the skipped matches for diagnostics.

    Behavior:
        Masks quotes and code fences, splits sentences, and marks matches in questions,
        hypotheticals, or within 3 tokens after a negation as skipped. Values are trimmed at the
        first clause boundary, capped at 60 characters, and checked against the junk and NER filters.
    Returns:
        Every candidate, skipped or not; empty unless `role == "user"`.
    Parameters:
        text: One message.
        role: Message role; only `user` is mined.
        spacy_model: spaCy model name, or `None` for the `ExtractCfg` default.
    """
    if role != "user":
        return []
    nlp = load_nlp(spacy_model or ExtractCfg().spacy_model)
    found = []
    for sentence in iter_sentences(mask_ignored(text), nlp, prefilter=_has_match):
        found.extend(_scan_sentence(sentence))
    return found


def extract_candidates(text: str, role: str = "user", spacy_model: str | None = None) -> list[Candidate]:
    """Extract fact candidates from one message.

    Behavior:
        Returns the non-skipped matches of `scan_text`, de-duplicated by attribute and normalized
        value (first occurrence wins).
    Returns:
        The candidates in text order; empty unless `role == "user"`.
    Parameters:
        text: One message.
        role: Message role; only `user` is mined.
        spacy_model: spaCy model name, or `None` for the `ExtractCfg` default.
    """
    seen, kept = set(), []
    for c in scan_text(text, role, spacy_model):
        key = (c.attribute, normalize_value(c.value))
        if c.skipped is None and key not in seen:
            seen.add(key)
            kept.append(c)
    return kept


@dataclass
class MergeResult:
    """Facts touched by a merge run and what happened to them.

    Behavior:
        `facts` holds the final state of every touched fact. `created` are new ids; `updated` are
        pre-existing facts that gained confidence or a new value; `conflicts` are slots flagged this
        run. `backlinks` pairs the episode that produced an overwritten value with the fact id.
    """

    facts: dict[UUID, Fact] = field(default_factory=dict)
    created: set[UUID] = field(default_factory=set)
    updated: set[UUID] = field(default_factory=set)
    conflicts: set[UUID] = field(default_factory=set)
    backlinks: list[tuple[UUID, UUID]] = field(default_factory=list)
    on_disk: set[UUID] = field(default_factory=set)


class Merger:
    """Apply candidates to the `shared` fact slots (§8 M3 merging).

    Behavior:
        New slot: create (`extractor=rule`). Same value: confidence +0.05, capped at 0.95, and the
        episode becomes `updated_by_episode`. Different value on a SINGLE slot: flag a conflict,
        unless the existing fact is rule-extracted and the new evidence is from a newer episode
        (overwrite and push the old value to history) or an older one (keep the value and record
        the older one in history). A slot already in conflict is never changed by rules.
    Parameters:
        vault: The vault whose facts are read.
        episode_times: `created_at` of every known episode, to decide which evidence is newer.
        now: Timestamp stamped on every change in this run.
    """

    def __init__(self, vault: Vault, episode_times: dict[UUID, datetime], now: datetime | None = None) -> None:
        self.vault = vault
        self.times = episode_times
        self.now = now or utcnow()
        self.result = MergeResult()

    def _load(self, fid: UUID) -> Fact | None:
        if fid in self.result.facts:
            return self.result.facts[fid]
        path = self.vault.fact_path(SCOPE, fid)
        if not path.is_file():
            return None
        try:
            fact, _ = mdio.read_model(path, Fact)
        except (PamError, ValidationError, ValueError) as e:
            warnings.warn(f"skipping unreadable fact {path.name}: {e}", RuntimeWarning, stacklevel=2)
            return None
        self.result.on_disk.add(fid)
        return fact

    def _store(self, fact: Fact, **changes) -> Fact:
        fact = Fact.model_validate({**fact.model_dump(), **changes, "updated_at": self.now})
        self.result.facts[fact.id] = fact
        return fact

    def _seen(self, fact: Fact, ep: EpisodeRef) -> bool:
        if ep.id is None:
            return False
        ids = {fact.source_episode, fact.updated_by_episode, *(h.episode_id for h in fact.history)}
        return ep.id in ids

    def _newer(self, fact: Fact, ep: EpisodeRef) -> bool:
        known = self.times.get(fact.source_episode) if fact.source_episode else None
        return known is None or ep.created_at > known

    def _older(self, fact: Fact, ep: EpisodeRef) -> bool:
        known = self.times.get(fact.source_episode) if fact.source_episode else None
        return ep.id is not None and known is not None and ep.created_at < known

    def add(self, ep: EpisodeRef, cand: Candidate) -> str:
        """Merge one candidate.

        Returns:
            `created`, `bumped`, `overwritten`, `superseded`, `conflict`, or `unchanged`.
        Parameters:
            ep: The episode the candidate came from.
            cand: A non-skipped candidate.
        """
        card = Cardinality(cand.cardinality)
        fid = fact_id(SCOPE, SUBJECT, cand.attribute, card, cand.value)
        existing = self._load(fid)
        if existing is None:
            self._store_new(fid, ep, cand, card)
            return "created"
        if self._seen(existing, ep):
            return "unchanged"
        if normalize_value(existing.value) == normalize_value(cand.value):
            conf = min(pat.CONFIDENCE_CAP, round(existing.confidence + pat.CONFIDENCE_BUMP, 2))
            if conf == existing.confidence:
                return "unchanged"
            # Recording the confirming episode lets `_seen` stop it from bumping twice.
            self._store(existing, confidence=conf, updated_by_episode=ep.id or existing.updated_by_episode)
            self._mark_updated(fid)
            return "bumped"
        if existing.status is FactStatus.CONFLICT:
            return "unchanged"
        if existing.extractor is Actor.RULE and self._newer(existing, ep):
            self._overwrite(existing, ep, cand)
            return "overwritten"
        if existing.extractor is Actor.RULE and self._older(existing, ep):
            self._record_older(existing, ep, cand)
            return "superseded"
        conflict = FactConflict(
            candidate_value=cand.value, candidate_source_episode=ep.id,
            detected_at=self.now, detected_by=Actor.RULE,
        )
        self._store(existing, status=FactStatus.CONFLICT, conflict=conflict)
        self.result.conflicts.add(fid)
        return "conflict"

    def _store_new(self, fid: UUID, ep: EpisodeRef, cand: Candidate, card: Cardinality) -> None:
        fact = Fact(
            id=fid, scope=SCOPE, subject=SUBJECT, attribute=cand.attribute, value=cand.value,
            cardinality=card, category=FactCategory(cand.category), confidence=cand.confidence,
            source_episode=ep.id, updated_by_episode=ep.id, extractor=Actor.RULE,
            pattern_id=cand.pattern_id, created_at=self.now, updated_at=self.now,
        )
        self.result.facts[fid] = fact
        self.result.created.add(fid)

    def _overwrite(self, old: Fact, ep: EpisodeRef, cand: Candidate) -> None:
        entry = FactHistoryEntry(
            value=old.value, changed_at=self.now, changed_by=Actor.RULE,
            episode_id=old.source_episode, reason=f"replaced by a newer statement in episode {ep.id}",
        )
        self._store(
            old, value=cand.value, confidence=cand.confidence, source_episode=ep.id,
            updated_by_episode=ep.id, pattern_id=cand.pattern_id,
            history=[*old.history, entry][-HISTORY_LIMIT:],
        )
        self._mark_updated(old.id)
        if old.source_episode is not None:
            self.result.backlinks.append((old.source_episode, old.id))

    def _record_older(self, fact: Fact, ep: EpisodeRef, cand: Candidate) -> None:
        # An older statement mined after a newer one: the current value stays, the old one becomes
        # history, matching the state a chronological run would have produced.
        entry = FactHistoryEntry(
            value=cand.value, changed_at=self.now, changed_by=Actor.RULE,
            episode_id=ep.id, reason=f"older than the current value from episode {fact.source_episode}",
        )
        self._store(fact, history=[*fact.history, entry][-HISTORY_LIMIT:])
        self._mark_updated(fact.id)
        self.result.backlinks.append((ep.id, fact.id))

    def _mark_updated(self, fid: UUID) -> None:
        if fid not in self.result.created:
            self.result.updated.add(fid)


def load_shared_facts(vault: Vault) -> dict[UUID, Fact]:
    """Read every readable fact file of the `shared` scope.

    Behavior:
        Unreadable files are skipped with a warning.
    Returns:
        Facts keyed by id.
    Parameters:
        vault: The vault to read.
    """
    facts = {}
    for path in sorted(vault.memory_dir(SCOPE).glob("facts/*.md")):
        try:
            fact, _ = mdio.read_model(path, Fact)
        except (PamError, ValidationError, ValueError) as e:
            warnings.warn(f"skipping unreadable fact {path.name}: {e}", RuntimeWarning, stacklevel=2)
            continue
        facts[fact.id] = fact
    return facts


def write_fact(vault: Vault, fact: Fact) -> Path:
    """Write one fact file (`memory/<scope>/facts/<id>.md`).

    Behavior:
        The body is one human-readable line, `**<attribute>**: <value>`. The caller holds the
        vault write lock and commits.
    Exceptions:
        OSError: The file cannot be written.
    Returns:
        The absolute path written.
    Parameters:
        vault: Target vault.
        fact: Fact to store.
    """
    path = vault.fact_path(fact.scope, fact.id)
    mdio.write(path, fact, f"**{fact.attribute}**: {fact.value}\n")
    return path


def add_backlink(vault: Vault, episode_id: UUID, fid: UUID) -> Path | None:
    """Append a fact id to an episode's `superseded_facts` (§7.4).

    Behavior:
        Only the frontmatter changes. The write is skipped when the id is already listed, when the
        episode file is missing, or when the body no longer matches `body_sha256`.
    Returns:
        The episode path when it was rewritten, else `None`.
    Parameters:
        vault: Target vault.
        episode_id: Episode that produced the replaced value.
        fid: Fact whose value was replaced.
    """
    path = next(iter(sorted(vault.root.glob(f"memory/*/episodes/{episode_id}.md"))), None)
    if path is None:
        return None
    fm, body = mdio.read_model(path, EpisodeFrontmatter)
    if fid in fm.superseded_facts:
        return None
    if sha256_text(body) != fm.body_sha256:
        warnings.warn(f"episode {episode_id} body does not match body_sha256; backlink skipped", RuntimeWarning)
        return None
    mdio.write(path, fm.model_copy(update={"superseded_facts": [*fm.superseded_facts, fid]}), body)
    return path


def write_merge(vault: Vault, result: MergeResult) -> tuple[list[Path], list[Path]]:
    """Write every touched fact and backlink of a merge.

    Behavior:
        The caller holds the vault write lock and makes the commit.
    Exceptions:
        OSError: A file cannot be written.
    Returns:
        The paths changed, and the subset that did not exist before.
    Parameters:
        vault: Target vault.
        result: The merge to store.
    """
    changed, created = [], []
    for fid, fact in result.facts.items():
        existed = fid in result.on_disk
        path = write_fact(vault, fact)
        changed.append(path)
        if not existed:
            created.append(path)
    for episode_id, fid in result.backlinks:
        path = add_backlink(vault, episode_id, fid)
        if path is not None and path not in changed:
            changed.append(path)
    return changed, created


def write_candidates(
    vault: Vault | str | Path,
    text: str,
    agent: str = "default",
    episode_id: UUID | None = None,
    created_at: datetime | None = None,
) -> list[Fact]:
    """Extract facts from one message and store them as one commit.

    Behavior:
        Facts land in the `shared` scope (`agent` is reserved for M7's permission check). Holds the
        write lock and commits as `derive: +c ~u !k`; makes no commit when nothing changed.
        T09 replaces the write step with `pam.memory.writer`.
    Exceptions:
        VaultBusy: The write lock is held by another writer.
    Returns:
        The facts created or changed.
    Parameters:
        vault: Vault, or its folder.
        text: One user message.
        agent: Agent on whose behalf the text is mined.
        episode_id: Episode the message belongs to, if any.
        created_at: Time of the evidence; defaults to now.
    """
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    with vault_write_lock(v):
        merger = Merger(v, {})
        ep = EpisodeRef(episode_id, created_at or merger.now)
        for cand in extract_candidates(text):
            merger.add(ep, cand)
        res = merger.result
        changed, created = write_merge(v, res)
        if changed:
            try:
                git.commit(v.root, changed, f"derive: +{len(res.created)} ~{len(res.updated)} !{len(res.conflicts)}")
            except PamError:
                for path in created:
                    path.unlink(missing_ok=True)
                raise
    return list(res.facts.values())
