"""Render the `default` agent's persona from facts, rules, and style (SPEC §8 M3, CHG-0002).

Behavior:
    Fills `templates/identity.md.j2` and `templates/style.md.j2`, formats rules with
    `pam.agents.manifest.format_rule`, and rewrites only the `## Derived` section of each persona
    file with `replace_derived`. The `## Custom` section is never touched.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import ValidationError

from pam.agents.manifest import format_rule, replace_derived
from pam.contracts.agent import PersonaRule
from pam.contracts.fact import Fact, FactStatus, normalize_value
from pam.contracts.project import Project
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.vault import PERSONA_KINDS, Vault

TEMPLATE_DIR = Path(__file__).parent / "templates"
AGENT = "default"
TOP_PROJECTS = 5
TOP_TOOLS = 8


@lru_cache(maxsize=1)
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR), autoescape=False, trim_blocks=True, lstrip_blocks=True,
        keep_trailing_newline=True, undefined=StrictUndefined,
    )


def load_project_names(vault: Vault) -> list[str]:
    """List the names of the most recently active projects.

    Behavior:
        Reads every `memory/*/projects/*.md`, keeps `status="active"` projects with a name, and
        orders them by `last_activity_at` (newest first, then name). Unreadable files are skipped.
    Returns:
        At most `TOP_PROJECTS` names.
    Parameters:
        vault: The vault to read.
    """
    projects = []
    for path in sorted(vault.root.glob("memory/*/projects/*.md")):
        try:
            project, _ = mdio.read_model(path, Project)
        except (PamError, ValidationError, ValueError):
            continue
        if project.status == "active" and project.name.strip():
            projects.append(project)
    projects.sort(key=lambda p: (-p.last_activity_at.timestamp(), p.name))
    return [p.name for p in projects[:TOP_PROJECTS]]


def identity_context(facts: Iterable[Fact], projects: list[str]) -> dict:
    """Build the template context for `identity.md.j2`.

    Behavior:
        Uses active `shared` facts only. A SINGLE attribute with several candidates takes the one
        with the highest confidence, then the newest. The organisation is `works_at`, else `school`.
        Tools are ordered by confidence, then value.
    Returns:
        The context mapping.
    Parameters:
        facts: All known facts.
        projects: Project names, most recent first.
    """
    active = [f for f in facts if f.scope == "shared" and f.status is FactStatus.ACTIVE]

    def best(attribute: str) -> str | None:
        rows = [f for f in active if f.attribute == attribute]
        return max(rows, key=lambda f: (f.confidence, f.updated_at)).value if rows else None

    name, preferred = best("name"), best("preferred_name")
    if name is None:
        name, preferred = preferred, None
    elif preferred and normalize_value(preferred) == normalize_value(name):
        preferred = None
    role, works_at, school, location = best("role"), best("works_at"), best("school"), best("location")
    org = works_at or school
    tools = sorted((f for f in active if f.attribute == "uses_tool"), key=lambda f: (-f.confidence, normalize_value(f.value)))
    details = []
    if works_at and school:
        details.append(f"Studies at {school}")
    if location:
        details.append(f"Lives in {location}")
    return {
        "name": name or "the user",
        "preferred_name": preferred,
        "descriptor": " at ".join(x for x in (role, org) if x) if role else (org or ""),
        "details": details,
        "projects": projects,
        "tools": [f.value for f in tools[:TOP_TOOLS]],
    }


def render_identity(facts: Iterable[Fact], projects: list[str]) -> str:
    """Render the identity Derived section.

    Returns:
        Markdown text.
    Parameters:
        facts: All known facts.
        projects: Project names, most recent first.
    """
    return _env().get_template("identity.md.j2").render(**identity_context(facts, projects)).strip()


def render_style(sentences: list[str]) -> str:
    """Render the style Derived section as a bullet list.

    Returns:
        Markdown text, empty when there are no sentences.
    Parameters:
        sentences: Output of `style.style_sentences`.
    """
    return _env().get_template("style.md.j2").render(sentences=sentences).strip()


def render_rules(rules: list[PersonaRule]) -> str:
    """Render derived rules as `rules.md` bullets (CHG-0002).

    Returns:
        One `format_rule` line per rule, empty when there are none.
    Parameters:
        rules: Derived rules.
    """
    return "\n".join(format_rule(r) for r in rules)


def persona_updates(vault: Vault, derived: dict[str, str]) -> dict[Path, str]:
    """Compute the persona files whose Derived section changes.

    Behavior:
        Applies `replace_derived` to each file in `derived` (a missing file reads as empty) and keeps
        only results that differ from what is on disk. Writes nothing.
    Returns:
        New full text keyed by absolute path.
    Parameters:
        vault: Target vault.
        derived: New Derived section text keyed by `identity`, `rules`, or `style`.
    """
    updates = {}
    for kind in PERSONA_KINDS:
        if kind not in derived:
            continue
        path = vault.persona_path(AGENT, kind)
        old = path.read_text(encoding="utf-8") if path.is_file() else ""
        new = replace_derived(old, derived[kind])
        if new != old.replace("\r\n", "\n"):
            updates[path] = new
    return updates
