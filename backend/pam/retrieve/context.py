"""Assemble a scope-safe, budget-safe context bundle (SPEC §7.9, §8 M6)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache

import tiktoken
from pydantic import ValidationError

from pam.agents.manifest import load_manifest, load_persona
from pam.agents.permissions import visible_doc_filter
from pam.contracts.agent import AgentManifest, Persona
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Fact, FactCategory, FactStatus
from pam.contracts.project import Project
from pam.contracts.retrieval import (
    ContextBundle, ContextRequest, EpisodeSnippet, ProjectBrief, SearchHit, SearchQuery,
)
from pam.contracts.working import WorkingMemory
from pam.core import mdio, tokens
from pam.core.config import load as load_config
from pam.core.errors import PamError
from pam.core.vault import Vault
from pam.retrieve import _index, render, search

SEARCH_K = 20  # §8 M6 context step 2
CORE_CATEGORIES = (FactCategory.IDENTITY, FactCategory.EDUCATION, FactCategory.WORK)  # §8 M6 step 3
PROJECT_SUMMARY_HEADING = "## Summary (auto)"  # §7.5
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
STOP_WORDS = {"at", "in", "of", "on", "to", "the", "a", "an", "and", "or", "is", "my", "id"}
MIN_PREFIX = 4  # "work" matches "works", "school" matches "schools"
# §7.9 fill priority after the persona. Conflicts that are not relevant go last: §8 M6 step 3 lets
# them in "only if budget remains".
FILL_ORDER = ("conflicts", "working", "facts", "projects", "episodes", "other_conflicts")


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding(tokens.TOKENIZER)


def _truncate(text: str, max_tokens: int) -> str:
    ids = _encoding().encode(text, disallowed_special=())
    if len(ids) <= max_tokens:
        return text
    return _encoding().decode_bytes(ids[:max_tokens]).decode("utf-8", errors="ignore").rstrip()


def _trim_persona(persona: Persona, limit: int) -> Persona:
    """Keep identity, then rules, then style until `limit` text tokens; cut the part that overflows."""
    left = limit
    identity = _truncate(persona.identity.strip(), max(left, 0))
    left -= tokens.count(identity)
    rules = []
    for rule in persona.rules:
        text = _truncate(rule.text, max(left, 0)) if left > 0 else ""
        if not text:
            break
        rules.append(rule.model_copy(update={"text": text}))
        left -= tokens.count(text)
    style = _truncate(persona.style.strip(), left) if left > 0 else ""
    return persona.model_copy(update={"identity": identity, "rules": rules, "style": style})


def _fit_persona(persona: Persona, cap: int, budget: int) -> Persona | None:
    """Return the largest trimmed persona whose section fits `cap` and whose bundle fits `budget`.

    Behavior:
        Binary search over a text-token limit, so a very large persona costs a few tokenizer
        passes, not one pass per character. `None` when even the bare heading does not fit.
    """
    def fits(candidate: Persona) -> bool:
        return (tokens.count(render.persona_section(candidate)) <= cap
                and tokens.count(render.render(candidate, [], [], None, [], [])) <= budget)

    total = tokens.count(persona.identity) + sum(tokens.count(r.text) for r in persona.rules) + tokens.count(persona.style)
    if fits(persona):
        return persona
    low, high = 0, total
    if not fits(_trim_persona(persona, 0)):
        return None
    while low < high:
        mid = (low + high + 1) // 2
        if fits(_trim_persona(persona, mid)):
            low = mid
        else:
            high = mid - 1
    return _trim_persona(persona, low)


def _mentions(attribute: str, words: set[str]) -> bool:
    """Tell whether a snake_case attribute is mentioned by a set of lowercase query words."""
    for part in attribute.lower().split("_"):
        if len(part) < 2 or part in STOP_WORDS:
            continue
        for word in words:
            if word == part or (min(len(word), len(part)) >= MIN_PREFIX and (word.startswith(part) or part.startswith(word))):
                return True
    return False


def _section(body: str, heading: str) -> str:
    lines = body.split("\n")
    if heading not in lines:
        return ""
    out = []
    for line in lines[lines.index(heading) + 1:]:
        if line.startswith("## "):
            break
        out.append(line)
    return "\n".join(out).strip()


def _scope_documents(vault: Vault, agent: AgentManifest) -> dict[str, tuple[str, str, int]]:
    """Map every in-scope indexed document id to `(doc_type, path, token_count)`."""
    conn = _index.connect(vault)
    if conn is None:
        return {}
    try:
        sql, params = visible_doc_filter(agent, vault, alias="d")
        rows = conn.execute(f"SELECT d.doc_id, d.doc_type, d.path, d.token_count FROM documents d WHERE {sql}", params)
        return {str(doc_id): (doc_type, path, int(count)) for doc_id, doc_type, path, count in rows}
    finally:
        conn.close()


def _read(vault: Vault, path: str, cls):
    try:
        return mdio.read_model(vault.abs(path), cls)
    except (OSError, ValueError, ValidationError, PamError):
        return None  # a file changed or broken since indexing is left out, not fatal


def _facts(vault: Vault, docs: dict, hits: list[SearchHit], words: set[str], max_facts: int) -> tuple[list, list, list]:
    """Return `(facts, relevant_conflicts, other_conflicts)` as lists of `(Fact, path)`.

    Behavior:
        Facts: every active identity/education/work fact (by category, attribute, value), then
        active fact hits in hit order, capped at `max_facts`. A conflict is relevant when its
        attribute is mentioned in the query or it is a keyword hit of the query.
    """
    core, actives, conflicts = [], {}, []
    for doc_id, (doc_type, path, _) in sorted(docs.items()):
        if doc_type != "fact" or (loaded := _read(vault, path, Fact)) is None:
            continue
        fact = loaded[0]
        if fact.status is FactStatus.CONFLICT:
            conflicts.append((fact, path))
        else:
            actives[doc_id] = (fact, path)
            if fact.category in CORE_CATEGORIES:
                core.append((fact, path))
    core.sort(key=lambda item: (item[0].category.value, item[0].attribute, item[0].value, str(item[0].id)))
    chosen = list(core)
    for hit in hits:
        item = actives.get(str(hit.doc_id))
        if hit.doc_type == "fact" and item is not None and item not in chosen:
            chosen.append(item)

    keyword_fact_hits = {str(h.doc_id) for h in hits if h.doc_type == "fact" and h.keyword_rank is not None}
    conflicts.sort(key=lambda item: (item[0].attribute, str(item[0].id)))
    relevant = [c for c in conflicts if _mentions(c[0].attribute, words) or str(c[0].id) in keyword_fact_hits]
    others = [c for c in conflicts if c not in relevant]
    return chosen[:max_facts], relevant, others


def _projects(vault: Vault, docs: dict, hit_rank: dict[str, int], max_projects: int) -> list:
    """Projects owning hit episodes (best hit first), then other active projects by recent activity."""
    owning, others = [], []
    for doc_id, (doc_type, path, _) in sorted(docs.items()):
        if doc_type != "project" or (loaded := _read(vault, path, Project)) is None:
            continue
        project, body = loaded
        brief = ProjectBrief(id=project.id, name=project.name, keywords=project.keywords, status=project.status,
                             last_activity_at=project.last_activity_at,
                             summary=_section(body, PROJECT_SUMMARY_HEADING))
        ranks = [hit_rank[str(e)] for e in project.episode_ids if str(e) in hit_rank]
        if ranks:
            owning.append((min(ranks), str(project.id), (brief, path)))
        elif project.status == "active":
            others.append((-project.last_activity_at.timestamp(), str(project.id), (brief, path)))
    return [item for *_, item in [*sorted(owning), *sorted(others)]][:max_projects]


def _snippets(vault: Vault, docs: dict, hits: list[SearchHit]) -> list:
    """Turn episode hits into snippets, merging only chunks with consecutive ordinals."""
    by_episode: dict[str, list[tuple[int, int, SearchHit]]] = {}
    for rank, hit in enumerate(hits):
        if hit.doc_type == "episode" and str(hit.doc_id) in docs:
            by_episode.setdefault(str(hit.doc_id), []).append((int(hit.chunk_id.rsplit(":", 1)[1]), rank, hit))
    if not by_episode:
        return []
    conn = _index.connect(vault)
    if conn is None:
        return []
    try:
        ids = [h.chunk_id for chunks in by_episode.values() for *_, h in chunks]
        texts = dict(conn.execute(f"SELECT chunk_id, text FROM chunks WHERE chunk_id IN ({','.join('?' for _ in ids)})", ids))
    finally:
        conn.close()

    snippets = []
    for doc_id, chunks in by_episode.items():
        loaded = _read(vault, docs[doc_id][1], EpisodeFrontmatter)
        if loaded is None:
            continue
        episode = loaded[0]
        prefix = f"[{episode.title}] "
        runs: list[list[tuple[int, int, SearchHit]]] = []
        for chunk in sorted(chunks):
            if runs and chunk[0] == runs[-1][-1][0] + 1:
                runs[-1].append(chunk)
            else:
                runs.append([chunk])
        for run in runs:
            body = "\n\n".join(texts.get(h.chunk_id, h.snippet).removeprefix(prefix) for *_, h in run)
            snippet = EpisodeSnippet(episode_id=episode.id, title=episode.title, source=episode.source,
                                     created_at=episode.created_at, text=body, chunk_ids=[h.chunk_id for *_, h in run])
            snippets.append((min(r for _, r, _ in run), snippet.chunk_ids[0], (snippet, docs[doc_id][1])))
    return [item for *_, item in sorted(snippets)]


def _working(vault: Vault, session_id: str | None, agent: str) -> tuple[WorkingMemory, str] | None:
    """Read `working/<session_id>.md` when it belongs to this agent (§7.10)."""
    if not session_id or not SESSION_ID.match(session_id):
        return None
    path = vault.working_path(session_id)
    loaded = _read(vault, vault.rel(path), WorkingMemory) if path.is_file() else None
    if loaded is None or loaded[0].agent != agent:
        return None
    return loaded[0], vault.rel(path)


def build_context(vault: Vault, req: ContextRequest) -> ContextBundle:
    """Build a scope-safe, budget-safe, deterministic context bundle for a query.

    Behavior:
        Loads the persona and trims it to `persona_max_tokens` (and to the budget), runs search
        with k=20, and gathers: relevant conflicts (attribute mentioned in the query, or a keyword
        hit), working memory from `working/<session_id>.md` when it belongs to the agent, facts
        (identity/education/work plus fact hits, up to `max_facts`), projects (owning hit
        episodes, then most recently active, up to `max_projects`), episode snippets (consecutive
        hit chunks merged), and finally the other conflicts. Items are added in that order while
        the token count of the whole rendered bundle stays within the budget; after the first item
        that does not fit, the rest of its section is still tried but no lower section is.
        `baseline_tokens` sums `documents.token_count` of every episode that contributed a
        snippet. Read-only.
    Exceptions:
        PamError: The agent does not exist, or the index was built with another embedding model.
    Returns:
        The validated `ContextBundle`.
    Parameters:
        vault: Vault to read.
        req: Context request.
    """
    cfg = load_config(vault)
    agent = load_manifest(req.agent, vault)
    budget = req.token_budget if req.token_budget is not None else agent.token_budget
    persona = load_persona(req.agent, vault) if req.include_persona else None
    if persona is not None:
        persona = _fit_persona(persona, cfg.context.persona_max_tokens, budget)

    hits = search.search(vault, SearchQuery(query=req.query, agent=req.agent, k=SEARCH_K)).hits
    docs = _scope_documents(vault, agent)
    hit_rank: dict[str, int] = {}
    for rank, hit in enumerate(hits):
        if hit.doc_type == "episode":
            hit_rank.setdefault(str(hit.doc_id), rank)
    facts, relevant, others = _facts(vault, docs, hits, set(search.query_terms(req.query)), cfg.context.max_facts)
    working = _working(vault, req.session_id, req.agent)
    candidates = {
        "conflicts": relevant, "working": [working] if working else [], "facts": facts,
        "projects": _projects(vault, docs, hit_rank, cfg.context.max_projects),
        "episodes": _snippets(vault, docs, hits), "other_conflicts": others,
    }

    chosen: dict[str, list] = {kind: [] for kind in FILL_ORDER}

    def rendered() -> str:
        return render.render(persona, chosen["facts"], chosen["conflicts"] + chosen["other_conflicts"],
                             chosen["working"][0] if chosen["working"] else None, chosen["projects"], chosen["episodes"])

    for kind in FILL_ORDER:
        dropped = False
        for item in candidates[kind]:
            chosen[kind].append(item)
            if tokens.count(rendered()) > budget:
                chosen[kind].pop()
                dropped = True
        if dropped:
            break  # §7.9: lower-priority sections are dropped first

    text = rendered()
    used = tokens.count(text)
    contributing = {str(snippet.episode_id) for snippet, _ in chosen["episodes"]}
    baseline = sum(docs[doc_id][2] for doc_id in contributing if doc_id in docs)
    return ContextBundle(
        agent=req.agent, query=req.query, persona=persona,
        facts=[f for f, _ in chosen["facts"]], conflicts=[f for f, _ in chosen["conflicts"] + chosen["other_conflicts"]],
        projects=[p for p, _ in chosen["projects"]], episodes=[e for e, _ in chosen["episodes"]],
        working=chosen["working"][0][0] if chosen["working"] else None,
        rendered=text, tokens_used=used, token_budget=budget,
        baseline_tokens=baseline, tokens_saved=max(0, baseline - used), generated_at=datetime.now(UTC),
    )
