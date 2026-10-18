"""Split vault documents into searchable chunks (SPEC §7.3 episode grammar, §8 M4)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import tiktoken

from pam.contracts.config import ChunkCfg
from pam.contracts.fact import Fact
from pam.contracts.project import Project
from pam.contracts.skill import Skill
from pam.core import tokens

SKILL_STEPS_TOKENS = 300  # §8 M4: a skill chunk keeps the first 300 tokens of its steps
TURN_HEADING = re.compile(
    r"^### (user|assistant|system|tool) · (?:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z|unknown)$"
)
PROJECT_SUMMARY_HEADING = "## Summary (auto)"


@dataclass
class Turn:
    """One message of an episode transcript: its role and verbatim text."""

    role: str
    text: str


@dataclass
class ParsedEpisode:
    """The parts of an episode body that M4 indexes."""

    title: str
    summary: str | None
    turns: list[Turn] = field(default_factory=list)


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(tokens.TOKENIZER)


def _decode(ids: list[int]) -> str:
    # A token slice can end inside a multi-byte character; drop the partial bytes.
    return _encoding().decode_bytes(ids).decode("utf-8", errors="ignore")


def parse_episode(body: str) -> ParsedEpisode:
    """Parse an episode body written in the §7.3 grammar.

    Behavior:
        The title is the first `# ` line. The summary is the text under `## Summary`, before
        `## Transcript`. Each `### <role> · <ISO Z time, optionally with fractional seconds, or
        unknown>` line starts a turn whose text
        runs to the next such line; attachment lines stay in the text. Turns with no text are dropped.
    Returns:
        The title, the summary or `None`, and the turns in order.
    Parameters:
        body: The episode body (everything after the frontmatter).
    """
    lines = body.split("\n")
    try:
        start = lines.index("## Transcript")
    except ValueError:
        start = len(lines)
    head, transcript = lines[:start], lines[start + 1:]

    title = next((line[2:].strip() for line in head if line.startswith("# ")), "")
    summary = None
    if "## Summary" in head:
        text = "\n".join(head[head.index("## Summary") + 1:]).strip()
        summary = text or None

    turns: list[Turn] = []
    role, buffer = None, []
    for line in [*transcript, "### user · unknown"]:  # sentinel heading flushes the last turn
        match = TURN_HEADING.match(line)
        if not match:
            buffer.append(line)
            continue
        text = "\n".join(buffer).strip()
        if role and text:
            turns.append(Turn(role, text))
        role, buffer = match.group(1), []
    return ParsedEpisode(title, summary, turns)


def _hard_split(text: str, max_tokens: int) -> list[str]:
    ids = _encoding().encode(text, disallowed_special=())
    pieces = []
    for start in range(0, len(ids), max_tokens):
        end = min(start + max_tokens, len(ids))
        piece = _decode(ids[start:end])
        while tokens.count(piece) > max_tokens and end > start + 1:  # re-encoding can merge differently
            end -= 1
            piece = _decode(ids[start:end])
        if piece.strip():
            pieces.append(piece.strip())
    return pieces


def _tail(text: str, overlap_tokens: int) -> str:
    ids = _encoding().encode(text, disallowed_special=())
    if len(ids) <= overlap_tokens:
        return text
    tail = _decode(ids[-overlap_tokens:])
    first_space = re.search(r"\s", tail)  # start at a word boundary, not mid-word
    return (tail[first_space.end():] if first_space else tail).strip()


def split_text(text: str, max_tokens: int, overlap_tokens: int) -> list[str]:
    """Split a text into pieces of at most `max_tokens`, on paragraph boundaries.

    Behavior:
        Text that fits is returned whole. Otherwise paragraphs (separated by blank lines) are packed
        greedily; a paragraph longer than `max_tokens` is first cut into token windows. Each new
        piece starts with about the last `overlap_tokens` tokens of the previous piece, cut at a
        word boundary, unless that would push it over `max_tokens`.
    Returns:
        The pieces in order; empty for blank text.
    Parameters:
        text: Text to split.
        max_tokens: Largest piece size in `cl100k_base` tokens.
        overlap_tokens: Approximate size of the repeated window between pieces.
    """
    text = text.strip()
    if not text:
        return []
    if tokens.count(text) <= max_tokens:
        return [text]
    paragraphs: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if para:
            paragraphs.extend([para] if tokens.count(para) <= max_tokens else _hard_split(para, max_tokens))

    pieces: list[str] = []
    current = ""
    for para in paragraphs:
        candidate = f"{current}\n\n{para}" if current else para
        if tokens.count(candidate) <= max_tokens:
            current = candidate
            continue
        pieces.append(current)
        tail = _tail(current, overlap_tokens)
        with_tail = f"{tail}\n\n{para}"
        current = with_tail if tail and tokens.count(with_tail) <= max_tokens else para
    pieces.append(current)
    return pieces


def episode_chunks(body: str, cfg: ChunkCfg) -> list[str]:
    """Build the chunks of one episode.

    Behavior:
        Chunk 0 is `Summary: <summary>` when the episode has one. Then each user turn starts a group
        that collects the following non-user turns (a leading non-user turn forms its own group).
        A group renders as `<role>: <text>` blocks separated by blank lines, without timestamps,
        and is split with `split_text` when it exceeds `max_tokens`. Every chunk starts with
        `[<title>] `, which counts toward `max_tokens`. An episode with nothing else gets one
        title-only chunk, so every episode has a vector.
    Returns:
        The chunk texts in order.
    Parameters:
        body: The episode body in the §7.3 grammar.
        cfg: Chunk size and overlap.
    """
    parsed = parse_episode(body)
    prefix = f"[{parsed.title}] "
    budget = max(cfg.max_tokens - tokens.count(prefix), 1)
    overlap = min(cfg.overlap_tokens, budget // 2)

    groups: list[list[Turn]] = []
    for turn in parsed.turns:
        if turn.role == "user" or not groups:
            groups.append([turn])
        else:
            groups[-1].append(turn)

    texts = [f"Summary: {parsed.summary}"] if parsed.summary else []
    texts += ["\n\n".join(f"{t.role}: {t.text}" for t in group) for group in groups]
    chunks = [prefix + piece for text in texts for piece in split_text(text, budget, overlap)]
    return chunks or [prefix.strip()]


def fact_chunk(fact: Fact) -> str:
    """Render a fact as its single chunk: `<subject> <attribute>: <value>`."""
    return f"{fact.subject} {fact.attribute}: {fact.value}"


def _section(body: str, heading: str) -> str:
    lines = body.split("\n")
    if heading not in lines:
        return ""
    section = []
    for line in lines[lines.index(heading) + 1:]:
        if line.startswith("## "):
            break
        section.append(line)
    return "\n".join(section).strip()


def project_chunk(project: Project, body: str) -> str:
    """Render a project as its single chunk.

    Behavior:
        Joins the name, the comma-separated keywords, and the `## Summary (auto)` section text on
        separate lines, skipping empty parts. `## Notes` is not included.
    Returns:
        The chunk text.
    Parameters:
        project: The project frontmatter.
        body: The project body.
    """
    parts = [project.name, ", ".join(project.keywords), _section(body, PROJECT_SUMMARY_HEADING)]
    return "\n".join(p for p in parts if p)


def skill_chunk(skill: Skill, body: str) -> str:
    """Render a skill as its single chunk.

    Behavior:
        Joins the name, the description, and the first `SKILL_STEPS_TOKENS` tokens of the steps
        (the body) on separate lines, skipping empty parts.
    Returns:
        The chunk text.
    Parameters:
        skill: The skill frontmatter.
        body: The skill body (its steps in Markdown).
    """
    ids = _encoding().encode(body.strip(), disallowed_special=())
    steps = _decode(ids[:SKILL_STEPS_TOKENS]).strip()
    return "\n".join(p for p in (skill.name, skill.description, steps) if p)
