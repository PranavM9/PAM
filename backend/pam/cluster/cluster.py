"""Group an agent's episodes into projects and keep the project files in step (SPEC §8 M5).

Behavior:
    `run_cluster` is the only entry point. Under the vault write lock it reads the scope's episode
    files, their `doc_vectors` rows, and the scope's project files; assigns or re-clusters; rewrites
    only `## Summary (auto)` (and appends to `## Notes`); commits once as
    `cluster: <mode> +<created> ~<updated>`; then stores `project_centroids` and reindexes the
    touched project files.
"""

from __future__ import annotations

import os
import time
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

import numpy as np
from pydantic import ValidationError

from pam.agents.manifest import load_manifest
from pam.cluster import assign, naming
from pam.contracts.common import Actor
from pam.contracts.config import ClusterCfg
from pam.contracts.episode import EpisodeFrontmatter
from pam.contracts.project import Project
from pam.contracts.reports import ClusterReport
from pam.core import config, mdio
from pam.core.errors import PamError
from pam.core.ids import new_uuid
from pam.core.lock import vault_write_lock
from pam.core.time import iso_z, utcnow
from pam.core.vault import Vault
from pam.index import db
from pam.index.chunker import parse_episode
from pam.index.indexer import index_paths
from pam.sync import git

NOTES_HEADING = "## Notes"


@dataclass(frozen=True)
class _Episode:
    id: str
    title: str
    text: str  # title plus user messages: the naming "class document" input
    created_at: datetime
    updated_at: datetime


@dataclass
class _ProjectFile:
    path: Path
    project: Project
    body: str
    members: list[str] = field(default_factory=list)
    refresh: bool = False  # recompute keywords from the members
    note: str | None = None
    created: bool = False


def _load_episodes(v: Vault, scope: str) -> dict[str, _Episode]:
    episodes: dict[str, _Episode] = {}
    for path in sorted(v.memory_dir(scope).glob("episodes/*.md")):
        try:
            fm, body = mdio.read_model(path, EpisodeFrontmatter)
        except (PamError, ValidationError, ValueError) as exc:
            warnings.warn(f"skipping {v.rel(path)}: {exc}")
            continue
        parsed = parse_episode(body)
        user_text = "\n".join(t.text for t in parsed.turns if t.role == "user")
        episodes[str(fm.id)] = _Episode(str(fm.id), fm.title, f"{fm.title}\n{user_text}", fm.created_at, fm.updated_at)
    return episodes


def _load_projects(v: Vault, scope: str) -> list[_ProjectFile]:
    """Read every project file of the scope, oldest first.

    Behavior:
        An unreadable file stops the run instead of being skipped: its members would otherwise look
        unassigned and be moved into another project, leaving them in two projects once the file
        is fixed (§7.5: an episode belongs to at most one project).
    Exceptions:
        PamError: Some project file cannot be read; the message names each one.
    """
    files: list[_ProjectFile] = []
    broken: list[str] = []
    for path in sorted(v.memory_dir(scope).glob("projects/*.md")):
        try:
            project, body = mdio.read_model(path, Project)
        except (PamError, ValidationError, ValueError) as exc:
            broken.append(f"{v.rel(path)} ({str(exc).splitlines()[0]})")
            continue
        files.append(_ProjectFile(path, project, body, [str(e) for e in project.episode_ids]))
    if broken:
        raise PamError(
            "cannot read project files; fix or restore them (`git checkout -- <file>`) before clustering: "
            + "; ".join(broken)
        )
    return sorted(files, key=lambda f: (f.project.created_at, str(f.project.id)))


def _groups(ids: Sequence[str], labels: Sequence[int]) -> list[list[str]]:
    clusters: dict[int, list[str]] = {}
    for eid, label in zip(ids, labels):
        if label != assign.NOISE:
            clusters.setdefault(label, []).append(eid)
    return [clusters[k] for k in sorted(clusters)]


def _matrix(ids: Sequence[str], vectors: dict[str, np.ndarray]) -> np.ndarray:
    return np.stack([vectors[e] for e in ids]) if ids else np.zeros((0, 0), dtype=np.float32)


def _settle(
    projects: list[_ProjectFile],
    pending: list[str],
    vectors: dict[str, np.ndarray],
    cfg: ClusterCfg,
    make: Callable[[list[str]], _ProjectFile],
) -> None:
    """Assign pending episodes to centroids and spawn HDBSCAN projects until nothing changes.

    Behavior:
        Each round assigns what clears `assign_threshold`, then clusters the rest (when at least
        `min_cluster_size`) into new projects. Rounds repeat while either step changed something,
        so the next run finds nothing to do. Each round shrinks `pending`, so the loop ends.
    """
    pending = list(pending)
    while True:
        candidates = {str(p.project.id): [vectors[e] for e in p.members if e in vectors] for p in projects}
        chosen = assign.assign_incremental([(e, vectors[e]) for e in pending], candidates, cfg.assign_threshold)
        by_id = {str(p.project.id): p for p in projects}
        for eid in pending:
            if eid in chosen:
                by_id[chosen[eid]].members.append(eid)
                by_id[chosen[eid]].refresh = True
        pending = [e for e in pending if e not in chosen]
        groups = _groups(pending, assign.cluster_labels(_matrix(pending, vectors), cfg.min_cluster_size))
        for group in groups:
            projects.append(make(group))
        taken = {e for g in groups for e in g}
        pending = [e for e in pending if e not in taken]
        if not chosen and not groups:
            return


def _rebuild(
    projects: list[_ProjectFile],
    ordered: list[str],
    vectors: dict[str, np.ndarray],
    cfg: ClusterCfg,
    make: Callable[[list[str]], _ProjectFile],
) -> None:
    # Agent and manual projects keep their members; only the other episodes are re-clustered.
    pinned = {e for p in projects if p.project.origin is not Actor.CLUSTER for e in p.members}
    pool = [e for e in ordered if e not in pinned]
    clusters = _groups(pool, assign.cluster_labels(_matrix(pool, vectors), cfg.min_cluster_size))
    old = {str(p.project.id): set(p.members) for p in projects if p.project.origin is Actor.CLUSTER and p.members}
    matched = assign.match_clusters([set(c) for c in clusters], old, cfg.rebuild_match_jaccard)
    by_id = {str(p.project.id): p for p in projects}
    previous = {pid: list(by_id[pid].members) for pid in old}
    for pid in old:
        by_id[pid].members, by_id[pid].refresh = [], True
    for i, pid in matched.items():
        by_id[pid].members = list(clusters[i])
    projects += [make(c) for i, c in enumerate(clusters) if i not in matched]
    clustered = {e for c in clusters for e in c}
    _settle(projects, [e for e in pool if e not in clustered], vectors, cfg, make)
    for pid, members in old.items():
        if set(by_id[pid].members) == members:
            by_id[pid].members = previous[pid]  # same members: keep the stored order
        if not by_id[pid].members:
            by_id[pid].note = (
                f"Dormant after `cluster --rebuild`: no new cluster shared at least "
                f"{cfg.rebuild_match_jaccard:.0%} (Jaccard) of its {len(members)} episodes."
            )


def _append_note(body: str, note: str, now: datetime) -> str:
    bullet = f"- {now.strftime('%Y-%m-%dT%H:%MZ')} (cluster) {note}\n"
    if not any(line.rstrip() == NOTES_HEADING for line in body.split("\n")):
        body = body.rstrip("\n") + f"\n\n{NOTES_HEADING}\n"
    elif not body.endswith("\n"):
        body += "\n"
    return body + bullet


def _finish(
    f: _ProjectFile, keywords: list[str] | None, episodes: dict[str, _Episode], cfg: ClusterCfg, now: datetime
) -> tuple[Project, str]:
    """Build the project frontmatter and body a run should leave on disk."""
    p = f.project
    present = [episodes[e] for e in f.members if e in episodes]
    times = [e.updated_at for e in present]
    if f.created:
        last = max(times) if times else p.last_activity_at
    else:  # a note or episode added by an agent counts as activity too
        last = max([p.last_activity_at, *times])
    if p.origin is Actor.CLUSTER and not f.members:
        status = "dormant"
    else:
        status = "dormant" if now - last > timedelta(days=cfg.dormant_after_days) else "active"
    kw = keywords if keywords is not None else list(p.keywords)
    members = [naming.Member(e.title, e.text, e.created_at) for e in present]
    body = naming.replace_summary(f.body, naming.summary_section(kw, members))
    if f.note:
        body = _append_note(body, f.note, now)
    project = Project.model_validate(
        {
            **p.model_dump(),
            "keywords": kw,
            "episode_ids": [UUID(e) for e in f.members],
            "status": status,
            "last_activity_at": last,
        }
    )
    return project, body


def _new_project(scope: str, members: list[str], now: datetime, v: Vault) -> _ProjectFile:
    pid = new_uuid()
    project = Project(
        id=pid, scope=scope, name="Untitled project", origin=Actor.CLUSTER,
        created_at=now, updated_at=now, last_activity_at=now,
    )
    body = f"{naming.SUMMARY_HEADING}\n\n{NOTES_HEADING}\n"
    return _ProjectFile(v.project_path(scope, pid), project, body, list(members), refresh=True, created=True)


def _restore(saved: dict[Path, bytes | None]) -> None:
    for path, raw in saved.items():
        if raw is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(raw)


def run_cluster(
    vault: Vault | str | os.PathLike | None = None,
    agent: str = "default",
    rebuild: bool = False,
    now: datetime | None = None,
) -> ClusterReport:
    """Assign or re-cluster an agent's episodes into projects and commit the project files once.

    Behavior:
        Works on `memory/<agent>/episodes` and `memory/<agent>/projects`; episodes without a
        `doc_vectors` row are skipped with a warning and stay unassigned.
        Incremental: each episode in no project goes to the best centroid when cosine >=
        `assign_threshold` (running mean); the rest are clustered with HDBSCAN once there are at
        least `min_cluster_size`, and each cluster becomes a new project (noise stays unassigned).
        Rebuild: every episode not held by an `agent`/`manual` project is re-clustered; a cluster
        reuses the id and name of the `cluster` project it overlaps by Jaccard >=
        `rebuild_match_jaccard`, other clusters become new projects, and unmatched `cluster`
        projects become dormant with no episodes and a Notes line.
        Keywords (c-TF-IDF over all of the scope's projects) are recomputed for new projects and
        projects whose members changed; a name is set only when a project is created, so
        `agent`/`manual` projects are never renamed. `## Summary (auto)` is re-rendered for every
        project; other sections are kept and `## Notes` is only appended to. A project is dormant
        when its last activity (the later of its stored `last_activity_at` and its newest member
        `updated_at`; a new project starts from its members) is older than `dormant_after_days`.
        Only files whose content changes are written; `updated_at` moves only for them. No change
        means no commit.
    Exceptions:
        VaultNotFound: The vault is not initialized.
        VaultBusy: The write lock is not acquired within 10 s.
        PamError: The agent does not exist, a project file of the scope cannot be read (nothing is
            changed), the index cannot be opened, or git fails (files are restored before raising).
    Returns:
        The `ClusterReport`; `episodes_assigned` counts episodes placed in a project by this run and
        `episodes_unassigned` the scope's episodes in no project afterwards.
    Parameters:
        vault: Vault, its folder, or `None` to resolve `--vault` / `PAM_VAULT`.
        agent: Agent whose memory scope is clustered.
        rebuild: Re-cluster everything instead of assigning new episodes.
        now: Clock override for tests.
    """
    started = time.perf_counter()
    v = (vault if isinstance(vault, Vault) else Vault.resolve(vault)).require_initialized()
    load_manifest(agent, v)
    cfg = config.load(v).clustering
    now = now or utcnow()
    mode = "rebuild" if rebuild else "incremental"

    with vault_write_lock(v):
        episodes = _load_episodes(v, agent)
        projects = _load_projects(v, agent)
        conn = db.connect(v)
        try:
            vectors = assign.load_vectors(conn, episodes)
            if len(vectors) < len(episodes):
                warnings.warn(f"{len(episodes) - len(vectors)} episodes are not indexed; run `pam index` first")
            ordered = sorted(vectors, key=lambda e: (episodes[e].created_at, e))
            before = {e for p in projects for e in p.members}
            make = lambda members: _new_project(agent, members, now, v)  # noqa: E731
            if rebuild:
                _rebuild(projects, ordered, vectors, cfg, make)
            else:
                _settle(projects, [e for e in ordered if e not in before], vectors, cfg, make)

            docs = [" ".join(episodes[e].text for e in p.members if e in episodes) for p in projects]
            ranked = naming.ctfidf(docs) if docs else []
            saved: dict[Path, bytes | None] = {}
            created = updated = 0
            for f, keywords in zip(projects, ranked):
                fresh = f.refresh or rebuild or not f.project.keywords
                project, body = _finish(f, keywords if fresh else None, episodes, cfg, now)
                if f.created:
                    present = [episodes[e] for e in f.members if e in episodes]
                    name = naming.project_name([e.title for e in present], project.keywords, [e.text for e in present])
                    project = project.model_copy(update={"name": name})
                elif project == f.project and body == f.body:
                    continue
                project = project.model_copy(update={"updated_at": now})
                saved[f.path] = f.path.read_bytes() if f.path.exists() else None
                mdio.write(f.path, project, body)
                f.project, f.body = project, body
                created += f.created
                updated += not f.created

            commit_sha = None
            if saved:
                try:
                    commit_sha = git.commit(v.root, list(saved), f"cluster: {mode} +{created} ~{updated}")
                except Exception:
                    _restore(saved)
                    raise
            centroids = {
                str(f.project.id): assign.centroid([vectors[e] for e in f.members if e in vectors]) for f in projects
            }
            assign.save_centroids(conn, centroids, iso_z(now))
            conn.commit()
        finally:
            conn.close()

        if saved:
            try:
                index_paths(v, [v.rel(p) for p in saved])
            except Exception as exc:  # the commit stands; the next `pam index` catches up
                warnings.warn(f"reindexing project files failed: {exc}")

    after = {e for f in projects for e in f.members}
    return ClusterReport(
        mode=mode,
        projects_created=created,
        projects_updated=updated,
        episodes_assigned=len((after - before) & set(episodes)),
        episodes_unassigned=len(set(episodes) - after),
        commit_sha=commit_sha,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )
