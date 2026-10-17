"""Read, write, and tool permissions for agents (SPEC §8 M8, §7.7).

Behavior:
    Every check works from an `AgentManifest`. Reads follow `ReadScope`; writes follow the write
    level (`none`, `own`, `shared`); tool calls follow `tools`. Episodes visible through
    `read.project_ids` come from each project file's `episode_ids`, because the index has no
    project column (CHG-0002). The `can_*` functions return booleans; callers raise
    `PermissionDenied`.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, get_args

from pam.contracts.agent import READ_TOOLS, AgentManifest, ToolName
from pam.contracts.project import Project
from pam.core import mdio
from pam.core.vault import Vault

WRITE_TOOLS = frozenset(get_args(ToolName)) - READ_TOOLS
_MEMORY_TYPES = {"episodes": "episode", "facts": "fact", "projects": "project"}
_ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class DocRef:
    """The fields a read check needs from an index document or a vault path."""

    doc_id: str
    doc_type: str
    scope: str


def _doc_ref(doc: Any) -> DocRef:
    if isinstance(doc, DocRef):
        return doc

    def get(key: str) -> Any:
        try:
            return getattr(doc, key)
        except AttributeError:
            return doc[key]

    return DocRef(doc_id=str(get("doc_id")), doc_type=str(get("doc_type")), scope=str(get("scope")))


def project_episode_ids(agent: AgentManifest, vault: Vault | str | os.PathLike | None = None) -> set[str]:
    """Collect the episode ids of the projects in the agent's `read.project_ids`.

    Behavior:
        Reads every `memory/*/projects/<id>.md` for each project id. A project without a file adds
        nothing. The vault is only resolved when the agent has project ids.
    Exceptions:
        VaultNotFound: The agent has project ids and no vault resolves.
        SchemaVersionError: A project file's major `schema_version` is unknown.
    Returns:
        The episode ids as lowercase UUID strings.
    Parameters:
        agent: Agent manifest.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    if not agent.read.project_ids:
        return set()
    root = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).root
    ids: set[str] = set()
    for pid in agent.read.project_ids:
        for path in sorted(root.glob(f"memory/*/projects/{pid}.md")):
            project, _ = mdio.read_model(path, Project)
            ids.update(str(e) for e in project.episode_ids)
    return ids


def visible_doc_filter(
    agent: AgentManifest, vault: Vault | str | os.PathLike | None = None, alias: str = "documents"
) -> tuple[str, list]:
    """Build the SQL condition that keeps only the index documents an agent may read.

    Behavior:
        `read.all` gives `1=1`. Otherwise the condition ORs: the agent's own scope (if
        `include_own_memory`), shared facts (if `include_shared_facts`), the projects in
        `project_ids` and their episodes, and skills from `include_skills_from`. An agent that
        may read nothing gets `0=1`. Values are bound as `?` parameters.
    Exceptions:
        ValueError: `alias` is not a plain SQL identifier.
        VaultNotFound: The agent has project ids and no vault resolves.
    Returns:
        `(sql, params)` for use in a `WHERE` clause over the §7.8 `documents` table.
    Parameters:
        agent: Agent manifest.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
        alias: Table name or alias that qualifies the columns; empty for unqualified columns.
    """
    if alias and not _ALIAS_RE.match(alias):
        raise ValueError(f"invalid SQL alias {alias!r}")
    if agent.read.all:
        return "1=1", []
    c = f"{alias}." if alias else ""
    terms: list[str] = []
    params: list = []

    def any_of(doc_type: str, column: str, values: list[str]) -> None:
        if values:
            marks = ", ".join("?" * len(values))
            terms.append(f"({c}doc_type = '{doc_type}' AND {c}{column} IN ({marks}))")
            params.extend(values)

    if agent.read.include_own_memory:
        terms.append(f"{c}scope = ?")
        params.append(agent.name)
    if agent.read.include_shared_facts:
        terms.append(f"({c}doc_type = 'fact' AND {c}scope = 'shared')")
    any_of("project", "doc_id", [str(p) for p in agent.read.project_ids])
    any_of("episode", "doc_id", sorted(project_episode_ids(agent, vault)))
    any_of("skill", "scope", list(agent.read.include_skills_from))
    if not terms:
        return "0=1", []
    return "(" + " OR ".join(terms) + ")", params


def can_read(agent: AgentManifest, doc: Any, vault: Vault | str | os.PathLike | None = None) -> bool:
    """Decide whether an agent may read one document.

    Behavior:
        Applies the same rules as `visible_doc_filter`. Episode membership in `project_ids` is
        read from the project files only when it matters.
    Exceptions:
        VaultNotFound: The document is an episode, the agent has project ids, and no vault resolves.
    Returns:
        `True` if the document is visible to the agent.
    Parameters:
        agent: Agent manifest.
        doc: Anything with `doc_id`, `doc_type`, and `scope` as attributes or keys (`DocRef`,
            `SearchHit`, a `dict`, or a `sqlite3.Row`).
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    r, d = agent.read, _doc_ref(doc)
    if r.all:
        return True
    if r.include_own_memory and d.scope == agent.name:
        return True
    if r.include_shared_facts and d.doc_type == "fact" and d.scope == "shared":
        return True
    if d.doc_type == "project" and d.doc_id in {str(p) for p in r.project_ids}:
        return True
    if d.doc_type == "skill" and d.scope in r.include_skills_from:
        return True
    return d.doc_type == "episode" and bool(r.project_ids) and d.doc_id in project_episode_ids(agent, vault)


def can_write(agent: AgentManifest, target_scope: str) -> bool:
    """Decide whether an agent may write into a scope.

    Behavior:
        `none` denies everything. `own` allows only the agent's own scope. `shared` also allows
        the `shared` scope (shared facts). Other agents' scopes are always denied.
    Returns:
        `True` if the write is allowed.
    Parameters:
        agent: Agent manifest.
        target_scope: `shared` or an agent name.
    """
    if agent.write == "none":
        return False
    if target_scope == agent.name:
        return True
    return target_scope == "shared" and agent.write == "shared"


def can_call(agent: AgentManifest, tool: str) -> bool:
    """Decide whether an agent may call an MCP tool.

    Behavior:
        The tool must be in the agent's `tools`. Write tools are also denied when the write
        level is `none`.
    Returns:
        `True` if the call is allowed.
    Parameters:
        agent: Agent manifest.
        tool: Tool name.
    """
    if tool not in agent.tools:
        return False
    return tool in READ_TOOLS or agent.write != "none"


def doc_ref_from_path(rel_path: str) -> DocRef | None:
    """Map a vault-relative path to the document it holds.

    Behavior:
        Recognizes `memory/<scope>/{episodes,facts,projects}/<id>.md` and `skills/<scope>/<id>.md`.
    Returns:
        The document reference, or `None` for any other path.
    Parameters:
        rel_path: Vault-relative POSIX path.
    """
    parts = PurePosixPath(rel_path).parts
    if not parts or not parts[-1].endswith(".md") or ".." in parts:
        return None
    doc_id = parts[-1][:-3]
    if len(parts) == 4 and parts[0] == "memory" and parts[2] in _MEMORY_TYPES:
        return DocRef(doc_id=doc_id, doc_type=_MEMORY_TYPES[parts[2]], scope=parts[1])
    if len(parts) == 3 and parts[0] == "skills":
        return DocRef(doc_id=doc_id, doc_type="skill", scope=parts[1])
    return None


def can_write_path(agent: AgentManifest, rel_path: str, vault: Vault | str | os.PathLike | None = None) -> bool:
    """Decide whether an agent may write a vault file.

    Behavior:
        `none` denies everything. Allowed: `memory/<self>/**`, `skills/<self>/**`, and
        `working/<session>.md` when the file is new or belongs to the agent. With `shared`, also
        `memory/shared/facts/<id>.md`. Everything else (`agent/`, `imports/`, other agents) is denied.
    Exceptions:
        VaultNotFound: The path is an existing working file and no vault resolves.
    Returns:
        `True` if the write is allowed.
    Parameters:
        agent: Agent manifest.
        rel_path: Vault-relative POSIX path.
        vault: Vault, vault folder, or `None` to resolve from `--vault` / `PAM_VAULT`.
    """
    parts = PurePosixPath(rel_path).parts
    if agent.write == "none" or len(parts) < 2 or ".." in parts:
        return False
    head, scope = parts[0], parts[1]
    if head == "memory" and scope == "shared":
        return agent.write == "shared" and len(parts) == 4 and parts[2] == "facts"
    if head in ("memory", "skills"):
        return scope == agent.name and len(parts) > 2
    if head == "working" and len(parts) == 2 and scope.endswith(".md"):
        path = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).abs(rel_path)
        if not path.is_file():
            return True
        data, _ = mdio.read(path)
        return data.get("agent") == agent.name
    return False
