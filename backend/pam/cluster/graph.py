"""Build the force-graph data for one agent (SPEC §7.12 GraphData, §8 M5)."""

from __future__ import annotations

import math
import os
import sqlite3
import warnings

import numpy as np
from pydantic import ValidationError

from pam.agents.manifest import load_manifest
from pam.agents.permissions import DocRef, can_read, project_episode_ids
from pam.cluster.assign import load_vectors
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.fact import Fact
from pam.contracts.graph import GraphData, GraphLink, GraphNode
from pam.contracts.project import Project
from pam.core import config, mdio
from pam.core.errors import PamError
from pam.core.time import utcnow
from pam.core.vault import Vault
from pam.index import db


def _read(v: Vault, pattern: str, cls: type) -> list[tuple[str, object]]:
    out = []
    for path in sorted(v.root.glob(pattern)):
        try:
            out.append((v.rel(path), mdio.read_model(path, cls)[0]))
        except (PamError, ValidationError, ValueError) as exc:
            warnings.warn(f"skipping {v.rel(path)}: {exc}")
    return out


def _similar_links(ids: list[str], vectors: dict[str, np.ndarray], threshold: float, per_node: int) -> list[GraphLink]:
    """Link each episode to its most similar episodes above the threshold, without duplicates."""
    have = [i for i in ids if i in vectors]
    if len(have) < 2 or per_node <= 0:
        return []
    matrix = np.stack([vectors[i] for i in have]).astype(np.float64)
    sims = matrix @ matrix.T
    np.fill_diagonal(sims, -np.inf)
    pairs: dict[tuple[int, int], float] = {}
    for i in range(len(have)):
        order = np.argsort(-sims[i], kind="stable")[:per_node]
        for j in order:
            if sims[i, j] >= threshold:
                pairs[(min(i, j), max(i, j))] = float(sims[i, j])
    return [
        GraphLink(source=have[a], target=have[b], kind="similar", weight=min(max(w, 0.0), 1.0))
        for (a, b), w in sorted(pairs.items())
    ]


def build_graph(vault: Vault | str | os.PathLike | None = None, agent: str = "default", facts: bool = False) -> GraphData:
    """Build the projects, episodes, and optional facts an agent may read as graph nodes and links.

    Behavior:
        Nodes are read from the vault files and filtered with `can_read`, so the graph respects the
        agent's scope. Project nodes have `size` = number of episodes and `cluster_id` = their own
        id; episode nodes have `size` = `log(message_count + 1)` and `cluster_id` = the visible
        project that holds them (or `None`). Links: `member` (episode → project, weight 1);
        `similar` (episode ↔ episode with cosine >= `similar_link_threshold`, the top
        `similar_links_per_node` per episode, each pair once, from `doc_vectors`; none without an
        index); with `facts`, fact nodes (label `attribute: value`, size = confidence) and
        `derived_from` links (fact → `source_episode`, weight = confidence). Every link endpoint is
        a node. Node ids are the document UUIDs.
    Exceptions:
        VaultNotFound: The vault is not initialized.
        PamError: The agent does not exist.
    Returns:
        The validated `GraphData`.
    Parameters:
        vault: Vault, its folder, or `None` to resolve `--vault` / `PAM_VAULT`.
        agent: Agent whose read scope filters the graph.
        facts: Include fact nodes and `derived_from` links.
    """
    v = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).require_initialized()
    manifest = load_manifest(agent, v)
    cfg = config.load(v).clustering
    via_projects = project_episode_ids(manifest, v)

    def visible(doc_id: str, doc_type: str, scope: str) -> bool:
        if doc_type == "episode" and doc_id in via_projects:
            return True
        return can_read(manifest, DocRef(doc_id, doc_type, scope), v)

    nodes: list[GraphNode] = []
    links: list[GraphLink] = []
    episode_ids: list[str] = []
    owner: dict[str, str] = {}

    projects = [
        (path, p) for path, p in _read(v, "memory/*/projects/*.md", Project)
        if visible(str(p.id), "project", p.scope)
    ]
    for path, ep in _read(v, "memory/*/episodes/*.md", EpisodeFrontmatter):
        eid, scope = str(ep.id), path.split("/")[1]
        if not visible(eid, "episode", scope):
            continue
        episode_ids.append(eid)
        nodes.append(GraphNode(
            id=eid, type="episode", label=ep.title, cluster_id=None,
            size=math.log(ep.message_count + 1), created_at=ep.created_at, path=path,
        ))
    shown = set(episode_ids)
    for path, p in projects:
        pid = str(p.id)
        nodes.append(GraphNode(
            id=pid, type="project", label=p.name, cluster_id=pid,
            size=float(len(p.episode_ids)), created_at=p.created_at, path=path,
        ))
        for e in map(str, p.episode_ids):
            if e in shown and e not in owner:
                owner[e] = pid
                links.append(GraphLink(source=e, target=pid, kind="member", weight=1.0))
    for node in nodes:
        if node.type == "episode":
            node.cluster_id = owner.get(node.id)

    if v.index_db.exists() and episode_ids:
        try:
            conn = db.connect(v)
        except (PamError, sqlite3.Error) as exc:
            warnings.warn(f"no similar links: {exc}")
        else:
            try:
                vectors = load_vectors(conn, episode_ids)
            finally:
                conn.close()
            links += _similar_links(episode_ids, vectors, cfg.similar_link_threshold, cfg.similar_links_per_node)

    if facts:
        for path, fact in _read(v, "memory/*/facts/*.md", Fact):
            fid = str(fact.id)
            if not visible(fid, "fact", fact.scope):
                continue
            nodes.append(GraphNode(
                id=fid, type="fact", label=f"{fact.attribute}: {fact.value}", cluster_id=None,
                size=fact.confidence, created_at=fact.created_at, path=path,
            ))
            source = str(fact.source_episode) if fact.source_episode else None
            if source in shown:
                links.append(GraphLink(source=fid, target=source, kind="derived_from", weight=fact.confidence))

    return GraphData(agent=agent, nodes=nodes, links=links, generated_at=utcnow())
