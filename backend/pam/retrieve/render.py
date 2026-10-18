"""Render context bundle sections in the fixed §7.9 heading order."""

from __future__ import annotations

from pam.contracts.agent import Persona
from pam.contracts.fact import Fact
from pam.contracts.retrieval import EpisodeSnippet, ProjectBrief
from pam.contracts.working import WorkingMemory

HEADINGS = (
    "# Agent persona", "# Known facts", "# ⚠ Conflicting facts — ask the user",
    "# Working memory", "# Relevant projects", "# Relevant past conversations",
)


def render(
    persona: Persona | None, facts: list[tuple[Fact, str]], conflicts: list[tuple[Fact, str]],
    working: tuple[WorkingMemory, str] | None, projects: list[tuple[ProjectBrief, str]],
    episodes: list[tuple[EpisodeSnippet, str]],
) -> str:
    """Render selected context objects with source paths.

    Behavior:
        Emits every fixed heading in contract order, including empty sections. Every emitted item
        includes its vault-relative source path.
    Returns:
        Markdown ready to place in a system prompt.
    Parameters:
        persona: Selected persona, if included.
        facts: Facts and paths.
        conflicts: Conflicting facts and paths.
        working: Working memory and path.
        projects: Project briefs and paths.
        episodes: Episode snippets and paths.
    """
    sections = []
    persona_text = ""
    if persona:
        persona_text = "\n".join(x for x in (persona.identity, *(f"- {r.text}" for r in persona.rules), persona.style) if x)
        if persona_text:
            persona_text += (
                f"\nSources: agent/{persona.agent}/identity.md, agent/{persona.agent}/rules.md, "
                f"agent/{persona.agent}/style.md"
            )
    sections.append(f"{HEADINGS[0]}\n{persona_text}")
    sections.append(f"{HEADINGS[1]}\n" + "\n".join(f"- {f.subject} {f.attribute}: {f.value} (source: {p})" for f, p in facts))
    sections.append(f"{HEADINGS[2]}\n" + "\n".join(
        f"- {f.subject} {f.attribute}: {f.value}; candidate: {f.conflict.candidate_value} (source: {p})"
        for f, p in conflicts
    ))
    working_text = ""
    if working:
        memory, path = working
        bits = [memory.goal or "", *memory.decisions, *memory.open_questions]
        working_text = "\n".join(f"- {bit} (source: {path})" for bit in bits if bit)
        if not working_text:
            working_text = f"(source: {path})"
    sections.append(f"{HEADINGS[3]}\n{working_text}")
    sections.append(f"{HEADINGS[4]}\n" + "\n".join(
        f"- {p.name} [{p.status}]: {p.summary} (source: {path})" for p, path in projects
    ))
    sections.append(f"{HEADINGS[5]}\n" + "\n".join(
        f"- {e.title} ({e.created_at.isoformat()}):\n  {e.text}\n  Source: {path}" for e, path in episodes
    ))
    return "\n\n".join(sections).rstrip() + "\n"
