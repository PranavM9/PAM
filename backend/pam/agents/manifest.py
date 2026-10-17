"""Agent manifests and persona files (SPEC §8 M8, §7.7).

Behavior:
    Loads, saves, lists, creates, and re-scopes agents stored as `agent/<name>/agent.yaml`, and
    parses the `## Derived` / `## Custom` sections of `identity.md`, `rules.md`, and `style.md`.
    A rule in `rules.md` is one `- ` bullet; derived metadata rides in a trailing HTML comment:
    `- Don't use bullet points. <!-- r_1a2b3c4d evidence=3 episodes=<uuid>,<uuid> -->` (CHG-0002).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from uuid import UUID

import yaml

from pam.contracts.agent import AgentManifest, Persona, PersonaRule
from pam.core import mdio
from pam.core.errors import PamError
from pam.core.ids import sha256_text
from pam.core.lock import vault_write_lock
from pam.core.vault import PERSONA_KINDS, PERSONA_TEMPLATE, Vault
from pam.sync import git

DERIVED_HEADING = "## Derived"
CUSTOM_HEADING = "## Custom"
_DERIVED_LINE, _CUSTOM_LINE = PERSONA_TEMPLATE.splitlines()[0], PERSONA_TEMPLATE.splitlines()[2]
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_RULE_RE = re.compile(r"^\s*[-*]\s+(?P<text>.*?)\s*(?:<!--(?P<meta>.*?)-->)?\s*$")


def _vault(vault: Vault | str | os.PathLike | None) -> Vault:
    v = vault if isinstance(vault, Vault) else Vault.resolve(vault)
    return v.require_initialized()


def _check_name(name: str) -> None:
    if not _NAME_RE.match(name):
        raise PamError(f"invalid agent name {name!r}", exit_code=2)


# -- manifests ------------------------------------------------------------------------------

def load_manifest(name: str, vault: Vault | str | os.PathLike | None = None) -> AgentManifest:
    """Read and validate an agent's `agent.yaml`.

    Exceptions:
        PamError: The name is not a valid slug (exit 2), the agent does not exist, or the YAML is not a mapping.
        SchemaVersionError: The manifest's major `schema_version` is unknown.
        pydantic.ValidationError: The manifest does not match `AgentManifest`.
    Returns:
        The agent's manifest.
    Parameters:
        name: Agent name.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    _check_name(name)
    path = _vault(vault).manifest_path(name)
    if not path.is_file():
        raise PamError(f"agent {name!r} not found")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise PamError(f"{path} is not a YAML mapping")
    mdio.check_schema_version(data.get("schema_version"))
    return AgentManifest.model_validate(data)


def save_manifest(manifest: AgentManifest, vault: Vault | str | os.PathLike | None = None) -> Path:
    """Write an agent's `agent.yaml` without committing.

    Behavior:
        Uses the same YAML layout as `pam init` (field order kept, UTF-8, LF). Callers hold the
        vault write lock and commit.
    Returns:
        The manifest path.
    Parameters:
        manifest: Manifest to write.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    path = _vault(vault).manifest_path(manifest.name)
    data = manifest.model_dump(mode="json")
    mdio.write_text(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return path


def list_agents(vault: Vault | str | os.PathLike | None = None) -> list[AgentManifest]:
    """Load every agent in the vault.

    Behavior:
        Reads each `agent/<name>/agent.yaml`; folders without a manifest are skipped.
    Exceptions:
        SchemaVersionError: A manifest's major `schema_version` is unknown.
        pydantic.ValidationError: A manifest does not match `AgentManifest`.
    Returns:
        The manifests sorted by name.
    Parameters:
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    v = _vault(vault)
    agent_root = v.root / "agent"
    if not agent_root.is_dir():
        return []
    return [
        load_manifest(d.name, v)
        for d in sorted(agent_root.iterdir())
        if (d / "agent.yaml").is_file() and _NAME_RE.match(d.name)
    ]


def create_agent(manifest: AgentManifest, vault: Vault | str | os.PathLike | None = None) -> str:
    """Create an agent's manifest, empty persona files, and memory folders in one commit.

    Behavior:
        Under the vault write lock, writes `agent/<name>/agent.yaml` and the three persona files
        (both sections, empty), creates `memory/<name>/{episodes,facts,projects}` and
        `skills/<name>/`, and commits the four files as `pam: create agent <name>`.
    Exceptions:
        PamError: The agent already exists, or git fails.
        VaultBusy: The write lock is held by another writer.
    Returns:
        The sha of the new commit.
    Parameters:
        manifest: Manifest of the new agent.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    v = _vault(vault)
    name = manifest.name
    with vault_write_lock(v):
        if v.agent_dir(name).exists():
            raise PamError(f"agent {name!r} already exists")
        paths = [save_manifest(manifest, v)]
        for kind in PERSONA_KINDS:
            path = v.persona_path(name, kind)
            mdio.write_text(path, PERSONA_TEMPLATE)
            paths.append(path)
        for sub in ("episodes", "facts", "projects"):
            (v.memory_dir(name) / sub).mkdir(parents=True, exist_ok=True)
        (v.root / "skills" / name).mkdir(parents=True, exist_ok=True)
        return git.commit(v.root, paths, f"pam: create agent {name}")


def set_scope(
    name: str,
    *,
    project_ids: list[UUID] | None = None,
    include_shared_facts: bool | None = None,
    write: str | None = None,
    tools: list[str] | None = None,
    vault: Vault | str | os.PathLike | None = None,
) -> tuple[AgentManifest, str | None]:
    """Update an agent's read scope, write level, or tools in one commit.

    Behavior:
        Fields left as `None` are kept. `project_ids` replaces the list. The `default` agent is
        refused because §7.7 fixes its scope. Nothing is written when the result is unchanged.
    Exceptions:
        PamError: The agent is `default` or does not exist, or git fails.
        VaultBusy: The write lock is held by another writer.
        pydantic.ValidationError: A new value is invalid (e.g. an unknown tool or write level).
    Returns:
        The resulting manifest, and the commit sha or `None` if nothing changed.
    Parameters:
        name: Agent name.
        project_ids: New `read.project_ids`.
        include_shared_facts: New `read.include_shared_facts`.
        write: New write level (`none`, `own`, `shared`).
        tools: New tool list.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    if name == "default":
        raise PamError("the default agent's scope is fixed (SPEC §7.7)")
    v = _vault(vault)
    with vault_write_lock(v):
        current = load_manifest(name, v)
        data = current.model_dump()
        if project_ids is not None:
            data["read"]["project_ids"] = list(project_ids)
        if include_shared_facts is not None:
            data["read"]["include_shared_facts"] = include_shared_facts
        if write is not None:
            data["write"] = write
        if tools is not None:
            data["tools"] = list(tools)
        updated = AgentManifest.model_validate(data)
        if updated == current:
            return current, None
        path = save_manifest(updated, v)
        return updated, git.commit(v.root, [path], f"pam: set scope for agent {name}")


# -- persona files --------------------------------------------------------------------------

def split_sections(text: str) -> tuple[str, str]:
    """Split a persona file into its Derived and Custom sections.

    Behavior:
        Lines after a `## Derived` heading belong to Derived and lines after a `## Custom`
        heading belong to Custom. Text before any heading, or a file with no headings, counts as
        Custom. Each section is stripped of surrounding blank space.
    Returns:
        `(derived, custom)`.
    Parameters:
        text: Persona file contents.
    """
    sections: dict[str, list[str]] = {"derived": [], "custom": []}
    current = "custom"
    for line in text.splitlines():
        if line.startswith(DERIVED_HEADING):
            current = "derived"
        elif line.startswith(CUSTOM_HEADING):
            current = "custom"
        else:
            sections[current].append(line)
    return "\n".join(sections["derived"]).strip(), "\n".join(sections["custom"]).strip()


def replace_derived(text: str, derived: str) -> str:
    """Replace the Derived section of a persona file and keep everything else byte-exact.

    Behavior:
        Rewrites the lines between the `## Derived` heading and the next `## Custom` heading (or
        the end of the file). If the file has no Derived heading, one is inserted at the top and
        the existing text is kept under a `## Custom` heading.
        An empty `derived` leaves the heading followed by one blank line, as in a new file.
    Returns:
        The new file contents.
    Parameters:
        text: Current persona file contents.
        derived: New Derived section body (Markdown, without the heading).
    """
    lines = text.splitlines(keepends=True)
    body = ["\n"] + ([derived.strip() + "\n", "\n"] if derived.strip() else [])
    start = next((i for i, line in enumerate(lines) if line.startswith(DERIVED_HEADING)), None)
    if start is None:
        # Keep the existing text in Custom; otherwise it would fall under the new Derived heading.
        custom_line = "" if text.startswith(CUSTOM_HEADING) else _CUSTOM_LINE + "\n"
        return "".join([_DERIVED_LINE + "\n", *body, custom_line]) + text
    end = next(
        (i for i in range(start + 1, len(lines)) if lines[i].startswith(CUSTOM_HEADING)), len(lines)
    )
    heading = lines[start] if lines[start].endswith("\n") else lines[start] + "\n"
    return "".join([*lines[:start], heading, *body, *lines[end:]])


def rule_id(text: str) -> str:
    """Compute a rule's stable id.

    Behavior:
        Normalizes the text (lowercase, whitespace collapsed, stripped) and hashes it (§7.7).
    Returns:
        `"r_"` followed by the first 8 hex digits of the SHA-256 of the normalized text.
    Parameters:
        text: Rule sentence.
    """
    return "r_" + sha256_text(" ".join(text.lower().split()))[:8]


def _parse_rule(line: str, origin: str) -> PersonaRule | None:
    m = _RULE_RE.match(line)
    if not m or not m.group("text"):
        return None
    text = m.group("text")
    rid, evidence, episodes = rule_id(text), 0, []
    for token in (m.group("meta") or "").split():
        if token.startswith("r_"):
            rid = token
        elif token.startswith("evidence=") and token[9:].isdigit():
            evidence = int(token[9:])
        elif token.startswith("episodes="):
            for raw in token[9:].split(","):
                try:
                    episodes.append(UUID(raw))
                except ValueError:
                    continue
    return PersonaRule(
        id=rid, text=text, origin=origin, evidence_count=evidence, evidence_episodes=episodes[:5]
    )


def parse_rules(derived: str, custom: str) -> list[PersonaRule]:
    """Parse the bullets of both `rules.md` sections into rules.

    Behavior:
        Each `- ` or `* ` bullet is one rule; other lines are ignored. Derived bullets get
        `origin="derived"` and Custom bullets `origin="manual"`. A trailing
        `<!-- r_<id> evidence=<n> episodes=<uuid>,... -->` sets the id and evidence; without it
        the id comes from `rule_id(text)` and the evidence is empty. Invalid episode ids are skipped.
    Returns:
        Derived rules first, then Custom rules, in file order.
    Parameters:
        derived: Derived section body.
        custom: Custom section body.
    """
    rules = []
    for section, origin in ((derived, "derived"), (custom, "manual")):
        for line in section.splitlines():
            rule = _parse_rule(line, origin)
            if rule is not None:
                rules.append(rule)
    return rules


def format_rule(rule: PersonaRule) -> str:
    """Render a rule as one `rules.md` bullet line (without the newline).

    Behavior:
        Derived rules, and any rule with evidence, carry the metadata comment so `parse_rules`
        restores them exactly. Manual rules without evidence are a plain bullet.
    Returns:
        The bullet line.
    Parameters:
        rule: Rule to render.
    """
    if rule.origin == "manual" and not rule.evidence_count and not rule.evidence_episodes:
        return f"- {rule.text}"
    meta = f"{rule.id} evidence={rule.evidence_count}"
    if rule.evidence_episodes:
        meta += " episodes=" + ",".join(str(e) for e in rule.evidence_episodes)
    return f"- {rule.text} <!-- {meta} -->"


def _join(derived: str, custom: str) -> str:
    return "\n\n".join(part for part in (derived, custom) if part)


def load_persona(name: str, vault: Vault | str | os.PathLike | None = None) -> Persona:
    """Read an agent's three persona files into a `Persona`.

    Behavior:
        `identity` and `style` are the Derived section followed by the Custom section, so Custom
        wins on contradictions by appearing last. `rules` lists Derived rules, then Custom rules.
        A missing persona file reads as empty.
    Exceptions:
        PamError: The name is invalid or the agent does not exist.
    Returns:
        The agent's persona.
    Parameters:
        name: Agent name.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    _check_name(name)
    v = _vault(vault)
    if not v.manifest_path(name).is_file():
        raise PamError(f"agent {name!r} not found")
    parts = {}
    for kind in PERSONA_KINDS:
        path = v.persona_path(name, kind)
        parts[kind] = split_sections(path.read_text(encoding="utf-8") if path.is_file() else "")
    return Persona(
        agent=name,
        identity=_join(*parts["identity"]),
        rules=parse_rules(*parts["rules"]),
        style=_join(*parts["style"]),
    )
