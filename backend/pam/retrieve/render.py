"""Render a context bundle as Markdown with the fixed §7.9 headings (SPEC §7.9, §8 M6)."""

from __future__ import annotations

from pam.contracts.agent import Persona
from pam.contracts.fact import Fact
from pam.contracts.retrieval import EpisodeSnippet, ProjectBrief
from pam.contracts.working import WorkingMemory
from pam.core.time import iso_z

HEADINGS = (
    "# Agent persona", "# Known facts", "# ⚠ Conflicting facts — ask the user",
    "# Working memory", "# Relevant projects", "# Relevant past conversations",
)


def _indent(text: str) -> str:
    # Indented lines cannot be read as one of the bundle's own `# ` headings.
    return "\n".join(f"  {line}" if line else "" for line in text.split("\n"))


def persona_section(persona: Persona | None) -> str:
    """Render the `# Agent persona` section.

    Behavior:
        Lists identity, rules (as `- ` bullets), and style, skipping empty parts, then one
        `Sources:` line with the three persona files. An empty or missing persona gives the
        heading alone.
    Returns:
        The section text without a trailing newline.
    Parameters:
        persona: The persona, or `None`.
    """
    if persona is None:
        return HEADINGS[0]
    parts = [persona.identity.strip(), *(f"- {r.text}" for r in persona.rules), persona.style.strip()]
    text = "\n".join(p for p in parts if p)
    if not text:
        return HEADINGS[0]
    base = f"agent/{persona.agent}"
    return f"{HEADINGS[0]}\n{text}\nSources: {base}/identity.md, {base}/rules.md, {base}/style.md"


def render(
    persona: Persona | None, facts: list[tuple[Fact, str]], conflicts: list[tuple[Fact, str]],
    working: tuple[WorkingMemory, str] | None, projects: list[tuple[ProjectBrief, str]],
    episodes: list[tuple[EpisodeSnippet, str]],
) -> str:
    """Render the selected context items under the six fixed headings.

    Behavior:
        Always emits all six headings in §7.9 order, also for empty sections. Every item cites its
        vault-relative path. Project summaries are collapsed to one line; snippet text is indented
        so chat content cannot look like a bundle heading.
    Returns:
        Markdown ready to place in a system prompt, ending with one newline.
    Parameters:
        persona: Selected persona, or `None`.
        facts: Facts with their paths.
        conflicts: Conflicting facts with their paths.
        working: Working memory with its path, or `None`.
        projects: Project briefs with their paths.
        episodes: Episode snippets with their paths.
    """
    sections = [persona_section(persona)]
    sections.append("\n".join([HEADINGS[1], *(
        f"- {f.subject} {f.attribute}: {f.value} (source: {p})" for f, p in facts)]))
    sections.append("\n".join([HEADINGS[2], *(
        f"- {f.subject} {f.attribute}: {f.value}; candidate: {f.conflict.candidate_value} (source: {p})"
        for f, p in conflicts)]))
    lines = [HEADINGS[3]]
    if working:
        memory, path = working
        if memory.goal:
            lines.append(f"- Goal: {memory.goal} (source: {path})")
        lines += [f"- Decision: {d} (source: {path})" for d in memory.decisions]
        lines += [f"- Open question: {q} (source: {path})" for q in memory.open_questions]
        if len(lines) == 1:
            lines.append(f"- (empty) (source: {path})")
    sections.append("\n".join(lines))
    sections.append("\n".join([HEADINGS[4], *(
        f"- {p.name} [{p.status}]{': ' + ' '.join(p.summary.split()) if p.summary.strip() else ''} (source: {path})"
        for p, path in projects)]))
    sections.append("\n".join([HEADINGS[5], *(
        f"- {e.title} ({iso_z(e.created_at)}, {e.source.value}):\n{_indent(e.text)}\n  Source: {path}"
        for e, path in episodes)]))
    return "\n\n".join(sections) + "\n"
