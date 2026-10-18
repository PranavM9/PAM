"""Assemble a scope-safe context bundle within its rendered token budget."""

from __future__ import annotations

import importlib.util
import sqlite3
from datetime import UTC, datetime

from pam.agents.manifest import load_manifest, load_persona
from pam.agents.permissions import visible_doc_filter
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Fact, FactCategory, FactStatus
from pam.contracts.project import Project
from pam.contracts.retrieval import (
    ContextBundle, ContextRequest, EpisodeSnippet, ProjectBrief, SearchQuery,
)
from pam.contracts.working import WorkingMemory
from pam.core import mdio, tokens
from pam.core.config import load as load_config
from pam.core.vault import Vault
from pam.retrieve import _index, render, search


def _fit_persona(persona, cap: int):
    """Trim persona text to a tokenizer cap while preserving Derived then Custom order."""
    fields = [persona.identity, *(r.text for r in persona.rules), persona.style]
    while fields and tokens.count("\n".join(fields)) > cap:
        longest = max(range(len(fields)), key=lambda i: len(fields[i]))
        if not fields[longest]:
            break
        fields[longest] = fields[longest][:-1]
    data = persona.model_dump()
    data["identity"] = fields[0]
    data["rules"] = [r.model_copy(update={"text": fields[i + 1]}) for i, r in enumerate(persona.rules) if fields[i + 1]]
    data["style"] = fields[-1] if fields else ""
    return type(persona).model_validate(data)


def build_context(vault: Vault, req: ContextRequest) -> ContextBundle:
    """Build a deterministic, scope-filtered and budget-safe context bundle.

    Behavior:
        Selects persona, conflicts, working memory, facts, projects and episode snippets in §7.9
        priority order. Every tentative addition is retained only when its complete rendered
        bundle fits the token budget.
    Returns:
        A validated context bundle with honest episode token savings.
    Parameters:
        vault: Vault to read.
        req: Context request.
    """
    cfg = load_config(vault)
    agent = load_manifest(req.agent, vault)
    budget = req.token_budget if req.token_budget is not None else agent.token_budget
    persona = load_persona(req.agent, vault) if req.include_persona else None
    if persona:
        persona_cap = cfg.context.persona_max_tokens
        while persona_cap >= 0:
            candidate_persona = _fit_persona(persona, persona_cap)
            empty_render = render.render(candidate_persona, [], [], None, [], [])
            if tokens.count(empty_render) <= budget:
                persona = candidate_persona
                break
            persona_cap -= 1
    response = search.search(vault, SearchQuery(query=req.query, agent=req.agent, k=20))
    facts: list[tuple[Fact, str]] = []
    conflicts: list[tuple[Fact, str]] = []
    projects: list[tuple[ProjectBrief, str]] = []
    episodes: list[tuple[EpisodeSnippet, str]] = []
    working: tuple[WorkingMemory, str] | None = None
    # Collect all in-scope files using the same SQL permission predicate as retrieval.
    try:
        conn = _index.connect(vault)
    except (sqlite3.Error, OSError, ImportError):
        conn = None
    docs = []
    token_counts: dict[str, int] = {}
    if conn is not None:
        try:
            scope, params = visible_doc_filter(agent, vault, "d")
            docs = conn.execute(f"SELECT d.doc_id,d.doc_type,d.scope,d.path,d.title,d.created_at FROM documents d WHERE {scope}", params).fetchall()
            token_counts = _index.doc_token_counts(conn, [row[0] for row in docs])
        finally:
            conn.close()
    paths = {str(row[0]): row[3] for row in docs}
    doc_types = {str(row[0]): row[1] for row in docs}
    for doc_id in sorted(paths):
        path = vault.abs(paths[doc_id])
        try:
            if doc_types[doc_id] == "fact":
                fact, _ = mdio.read_model(path, Fact)
                if fact.status == FactStatus.CONFLICT:
                    conflicts.append((fact, paths[doc_id]))
                elif fact.category in {FactCategory.IDENTITY, FactCategory.EDUCATION, FactCategory.WORK}:
                    facts.append((fact, paths[doc_id]))
            elif doc_types[doc_id] == "project":
                project, body = mdio.read_model(path, Project)
                projects.append((ProjectBrief(
                    id=project.id, name=project.name, keywords=project.keywords, status=project.status,
                    last_activity_at=project.last_activity_at, summary=body,
                ), paths[doc_id]))
        except (OSError, ValueError):
            continue
    facts.sort(key=lambda item: (item[0].category.value, item[0].attribute, str(item[0].id)))
    conflicts.sort(key=lambda item: (item[0].attribute, str(item[0].id)))
    projects.sort(key=lambda item: (-item[0].last_activity_at.timestamp(), str(item[0].id)))
    hit_doc_ids = {str(hit.doc_id) for hit in response.hits}
    fact_hits = [str(hit.doc_id) for hit in response.hits if hit.doc_type == "fact"]
    selected_facts = list(facts)
    for doc_id in fact_hits:
        item = next((item for item in facts if str(item[0].id) == doc_id), None)
        if item and item not in selected_facts:
            selected_facts.append(item)
    selected_facts = selected_facts[:cfg.context.max_facts]
    query_terms = set(search.sanitize_fts(req.query).lower().replace('"', "").split(" or "))
    selected_conflicts = [item for item in conflicts if item[0].attribute.lower() in query_terms or str(item[0].id) in hit_doc_ids]
    for item in conflicts:
        if item not in selected_conflicts:
            selected_conflicts.append(item)
    episode_ids = {str(hit.doc_id) for hit in response.hits if hit.doc_type == "episode"}
    project_members = {}
    for brief, project_path in projects:
        try:
            project_members[str(brief.id)] = {str(ep) for ep in mdio.read_model(vault.abs(project_path), Project)[0].episode_ids}
        except (OSError, ValueError):
            project_members[str(brief.id)] = set()
    owning = [item for item in projects if project_members.get(str(item[0].id), set()) & episode_ids]
    selected_projects = (owning + [p for p in projects if p not in owning and p[0].status == "active"])[:cfg.context.max_projects]
    if docs and response.hits:
        conn = _index.connect(vault)
        try:
            rows = conn.execute(
                    "SELECT c.doc_id,c.ordinal,c.chunk_id,c.text,d.title,d.path FROM chunks c JOIN documents d ON d.doc_id=c.doc_id WHERE c.chunk_id IN (" + ",".join("?" for _ in response.hits) + ") ORDER BY c.doc_id,c.ordinal",
                    [hit.chunk_id for hit in response.hits],
            ).fetchall()
            by_doc = {}
            for row in rows:
                by_doc.setdefault(str(row[0]), []).append(row)
            for doc_id, chunks in sorted(by_doc.items()):
                if doc_types.get(doc_id) != "episode":
                    continue
                ep, _ = mdio.read_model(vault.abs(paths[doc_id]), EpisodeFrontmatter)
                text = "\n\n".join(row[3] for row in chunks)
                episodes.append((EpisodeSnippet(
                    episode_id=ep.id, title=ep.title, source=ep.source, created_at=ep.created_at,
                    text=text, chunk_ids=[row[2] for row in chunks],
                ), paths[doc_id]))
        finally:
            conn.close()
    episodes.sort(key=lambda item: (str(item[0].episode_id), item[0].chunk_ids))
    if req.session_id and importlib.util.find_spec("pam.working.session"):
        try:
            memory, _ = mdio.read_model(vault.working_path(req.session_id), WorkingMemory)
            if memory.agent == req.agent:
                working = (memory, vault.rel(vault.working_path(req.session_id)))
        except (OSError, ValueError):
            pass
    # Start empty and append one item at a time in the contract's priority order.
    chosen = {"facts": [], "conflicts": [], "projects": [], "episodes": [], "working": None}
    persona_on = persona
    def rendered():
        return render.render(persona_on, chosen["facts"], chosen["conflicts"], chosen["working"], chosen["projects"], chosen["episodes"])
    if tokens.count(rendered()) > budget:
        persona_on = None
    candidates = [("conflicts", selected_conflicts), ("working", [working] if working else []),
                  ("facts", selected_facts), ("projects", selected_projects), ("episodes", episodes)]
    for kind, items in candidates:
        for item in items:
            current = chosen[kind]
            if kind == "working":
                chosen[kind] = item
            else:
                current.append(item)
            if tokens.count(rendered()) > budget:
                if kind == "working":
                    chosen[kind] = None
                else:
                    current.pop()
    rendered_text = rendered()
    used_episodes = {str(item[0].episode_id) for item in chosen["episodes"]}
    baseline = sum(token_counts.get(doc_id, 0) for doc_id in used_episodes)
    return ContextBundle(
        agent=req.agent, query=req.query, persona=persona_on, facts=[x[0] for x in chosen["facts"]],
        conflicts=[x[0] for x in chosen["conflicts"]], projects=[x[0] for x in chosen["projects"]],
        episodes=[x[0] for x in chosen["episodes"]], working=chosen["working"][0] if chosen["working"] else None,
        rendered=rendered_text, tokens_used=tokens.count(rendered_text), token_budget=budget,
        baseline_tokens=baseline, tokens_saved=max(0, baseline - tokens.count(rendered_text)), generated_at=datetime.now(UTC),
    )
