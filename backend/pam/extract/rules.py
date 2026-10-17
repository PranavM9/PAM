"""Rule extraction: repeated instructions aimed at the assistant (SPEC §8 M3, CHG-0002).

Behavior:
    Three regexes find imperative instructions in user messages. Each match is normalized to a
    canonical sentence such as `Don't use bullet points.`; identical sentences from at least
    `rule_min_evidence` distinct episodes become derived rules.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from uuid import UUID

from pam.agents.manifest import rule_id
from pam.contracts.agent import PersonaRule
from pam.contracts.config import ExtractCfg
from pam.extract import patterns as pat
from pam.extract.text import cap_value, iter_sentences, load_nlp, mask_ignored, negated

MAX_EVIDENCE_EPISODES = 5

_LEAD = r"(?:(?:please|pls|also|and|ok|okay|so|just)[, ]+){0,3}"

# R1 is anchored at the sentence start and R3 at a sentence or clause start, so descriptions such as
# "I have no markdown files" are not mistaken for instructions.
_R1 = re.compile(
    rf"^\s*{_LEAD}(?P<neg>don['’]t|do not|never|always|stop|avoid) "
    r"(?P<verb>use|using|write|writing|include|including|add|adding|give|giving|say|saying) (?P<v>.+)",
    re.I,
)
_R2 = re.compile(r"\bkeep (?:it|answers|responses) (?P<v>short|brief|concise|simple)\b", re.I)
_R3 = re.compile(
    r"(?:^|[,;:]\s*|\b(?:and|also|please|pls|but|just)\s+)"
    r"(?P<t>no) (?P<v>emojis?|bullet points?|markdown|yapping|fluff)\b",
    re.I,
)
_BASE_VERB = {"using": "use", "writing": "write", "including": "include", "adding": "add", "giving": "give", "saying": "say"}
_TRAILING_POLITE = re.compile(r"\s+(?:please|pls|thanks|thank you)$", re.I)
_TRIGGER_WORD = re.compile(r"\b(?:don['’]t|do not|never|always|stop|avoid|keep|no)\b", re.I)
_PLURAL = {"emoji": "emojis", "bullet point": "bullet points"}


def _canonical(text: str) -> list[str]:
    """Return the canonical rule sentences matched in one sentence."""
    if "?" in text:
        return []
    found = []
    m = _R1.search(text)
    if m and not negated(text[: m.start("neg")]):
        cut = pat.LIST_CLAUSE_BOUNDARY.search(m.group("v"))
        value = m.group("v")[: cut.start()] if cut else m.group("v")
        value = cap_value(_TRAILING_POLITE.sub("", value.strip().rstrip(" .,;:!")))
        if value and not pat.JUNK_VALUE.match(value):
            verb = _BASE_VERB.get(m.group("verb").lower(), m.group("verb").lower())
            if m.group("neg").lower() == "always":
                found.append(f"Always {verb} {value}.")
            else:
                found.append(f"Don't {verb} {value}.")
    m = _R2.search(text)
    if m and not negated(text[: m.start()]):
        found.append(f"Keep answers {m.group('v').lower()}.")
    m = _R3.search(text)
    if m and not negated(text[: m.start("t")]):
        noun = m.group("v").lower()
        found.append(f"Don't use {_PLURAL.get(noun, noun)}.")
    return found


def extract_rules(text: str, role: str = "user", spacy_model: str | None = None) -> list[str]:
    """Extract canonical rule sentences from one message.

    Behavior:
        Masks quotes and code fences, skips questions and matches within 3 tokens after a
        negation, and keeps the first occurrence of each sentence.
    Returns:
        The canonical sentences in text order; empty unless `role == "user"`.
    Parameters:
        text: One message.
        role: Message role; only `user` is mined.
        spacy_model: spaCy model name, or `None` for the `ExtractCfg` default.
    """
    if role != "user":
        return []
    nlp = load_nlp(spacy_model or ExtractCfg().spacy_model)
    seen: dict[str, str] = {}
    for sentence in iter_sentences(mask_ignored(text), nlp, prefilter=lambda line: bool(_TRIGGER_WORD.search(line))):
        for rule in _canonical(sentence.text):
            seen.setdefault(rule.lower(), rule)
    return list(seen.values())


def derive_rules(
    episodes: Iterable[tuple[UUID, Iterable[str]]], min_evidence: int, spacy_model: str | None = None
) -> list[PersonaRule]:
    """Group rule sentences across episodes and keep the repeated ones.

    Behavior:
        A rule needs at least `min_evidence` distinct episodes; one episode counts once however
        often it repeats the instruction. `evidence_episodes` keeps the first five in the order given.
        Rules sort by evidence count (descending), then text.
    Returns:
        The derived rules, `origin="derived"`.
    Parameters:
        episodes: `(episode id, user messages)` pairs, oldest first.
        min_evidence: Minimum distinct episodes (`ExtractCfg.rule_min_evidence`).
        spacy_model: spaCy model name, or `None` for the `ExtractCfg` default.
    """
    texts: dict[str, str] = {}
    evidence: dict[str, list[UUID]] = {}
    for episode_id, messages in episodes:
        for message in messages:
            for rule in extract_rules(message, "user", spacy_model):
                key = rule.lower()
                texts.setdefault(key, rule)
                if episode_id not in evidence.setdefault(key, []):
                    evidence[key].append(episode_id)
    rules = [
        PersonaRule(
            id=rule_id(texts[key]), text=texts[key], origin="derived", evidence_count=len(ids),
            evidence_episodes=ids[:MAX_EVIDENCE_EPISODES],
        )
        for key, ids in evidence.items()
        if len(ids) >= min_evidence
    ]
    return sorted(rules, key=lambda r: (-r.evidence_count, r.text))
