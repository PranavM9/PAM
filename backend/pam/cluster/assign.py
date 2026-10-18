"""Vector math for clustering: centroids, incremental assignment, HDBSCAN, and Jaccard matching (SPEC §8 M5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence

import numpy as np
from sklearn.cluster import HDBSCAN

from pam.index.embedder import l2_normalize

NOISE = -1  # HDBSCAN's label for points in no cluster


def load_vectors(conn: sqlite3.Connection, doc_ids: Iterable[str]) -> dict[str, np.ndarray]:
    """Read the `doc_vectors` rows of the given documents.

    Behavior:
        Documents without a row (not indexed yet) are left out.
    Returns:
        Each found document id mapped to its float32 vector.
    Parameters:
        conn: An open index connection.
        doc_ids: Document ids to look up.
    """
    wanted = list(dict.fromkeys(doc_ids))
    found: dict[str, np.ndarray] = {}
    for start in range(0, len(wanted), 500):
        batch = wanted[start:start + 500]
        marks = ", ".join("?" * len(batch))
        rows = conn.execute(f"SELECT doc_id, embedding FROM doc_vectors WHERE doc_id IN ({marks})", batch)
        found.update({doc_id: np.frombuffer(blob, dtype=np.float32).copy() for doc_id, blob in rows})
    return found


def centroid(vectors: Sequence[np.ndarray]) -> np.ndarray | None:
    """Return the L2-normalized mean of some vectors, or `None` when there are none."""
    if not len(vectors):
        return None
    return l2_normalize(np.mean(np.stack(vectors), axis=0, keepdims=True))[0].astype(np.float32)


def save_centroids(conn: sqlite3.Connection, centroids: Mapping[str, np.ndarray | None], updated_at: str) -> None:
    """Store or delete `project_centroids` rows.

    Behavior:
        A `None` centroid deletes the project's row. A row whose stored bytes already match is left
        as it is, so an unchanged run does not touch `updated_at`. Runs in the caller's transaction.
    Parameters:
        conn: An open index connection.
        centroids: Project id mapped to its normalized centroid or `None`.
        updated_at: ISO timestamp for changed rows.
    """
    stored = dict(conn.execute("SELECT project_id, embedding FROM project_centroids").fetchall())
    for pid, vec in centroids.items():
        if vec is None:
            conn.execute("DELETE FROM project_centroids WHERE project_id = ?", (pid,))
            continue
        blob = vec.astype(np.float32).tobytes()
        if stored.get(pid) != blob:
            conn.execute(
                "INSERT OR REPLACE INTO project_centroids (project_id, embedding, updated_at) VALUES (?, ?, ?)",
                (pid, blob, updated_at),
            )


def assign_incremental(
    episodes: Sequence[tuple[str, np.ndarray]],
    projects: Mapping[str, Sequence[np.ndarray]],
    threshold: float,
) -> dict[str, str]:
    """Assign episodes to the most similar project centroid, updating centroids as a running mean.

    Behavior:
        Episodes are taken in the given order. Each one goes to the project whose centroid has the
        highest cosine similarity, if that similarity is at least `threshold`; that project's mean
        then absorbs the vector (`mean += (v - mean) / (n + 1)`). Projects with no vectors have no
        centroid and receive nothing. Ties go to the project listed first.
    Returns:
        Episode id mapped to the chosen project id, for assigned episodes only.
    Parameters:
        episodes: `(episode_id, normalized vector)` pairs in processing order.
        projects: Project id mapped to its current member vectors.
        threshold: `ClusterCfg.assign_threshold`.
    """
    means = {pid: np.mean(np.stack(vs), axis=0) for pid, vs in projects.items() if len(vs)}
    counts = {pid: len(vs) for pid, vs in projects.items() if len(vs)}
    chosen: dict[str, str] = {}
    for eid, vec in episodes:
        best_pid, best_sim = None, -2.0
        for pid, mean in means.items():
            norm = float(np.linalg.norm(mean))
            sim = float(vec @ mean) / norm if norm else -1.0
            if sim > best_sim:
                best_pid, best_sim = pid, sim
        if best_pid is None or best_sim < threshold:
            continue
        chosen[eid] = best_pid
        counts[best_pid] += 1
        means[best_pid] = means[best_pid] + (vec - means[best_pid]) / counts[best_pid]
    return chosen


def cluster_labels(matrix: np.ndarray, min_cluster_size: int) -> list[int]:
    """Cluster normalized vectors with HDBSCAN.

    Behavior:
        Uses `sklearn.cluster.HDBSCAN(metric="euclidean", min_cluster_size=...)`; on L2-normalized
        vectors euclidean distance orders pairs like cosine distance. When every row comes back as
        noise, HDBSCAN runs once more with `allow_single_cluster=True`, so one dense group (e.g.
        four episodes on one topic) still forms a cluster; its outliers stay noise. Fewer rows
        than `min_cluster_size` (or fewer than 2) are all noise without running HDBSCAN.
    Returns:
        One label per row; `-1` is noise (unassigned).
    Parameters:
        matrix: `(n, dim)` array of normalized vectors.
        min_cluster_size: `ClusterCfg.min_cluster_size`.
    """
    n = len(matrix)
    if n < max(min_cluster_size, 2):
        return [NOISE] * n
    size = max(min_cluster_size, 2)
    data = np.asarray(matrix, dtype=np.float64)
    labels: list[int] = []
    for single in (False, True):
        model = HDBSCAN(
            min_cluster_size=size, min_samples=min(size, n - 1), metric="euclidean",
            allow_single_cluster=single, copy=True,
        )
        labels = [int(label) for label in model.fit_predict(data)]
        if any(label != NOISE for label in labels):
            break
    return labels


def jaccard(a: set[str], b: set[str]) -> float:
    """Return `|a ∩ b| / |a ∪ b|`, or 0 for two empty sets."""
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def match_clusters(
    new: Sequence[set[str]], old: Mapping[str, set[str]], threshold: float
) -> dict[int, str]:
    """Match new clusters to old projects by membership Jaccard similarity.

    Behavior:
        Pairs are taken greedily from the highest Jaccard down, each cluster and each project used
        at most once; a pair below `threshold` is never matched. Equal scores prefer the lower
        cluster index, then the lower project id, so the result is deterministic.
    Returns:
        New cluster index mapped to the reused project id.
    Parameters:
        new: Member sets of the new clusters.
        old: Project id mapped to its current member set.
        threshold: `ClusterCfg.rebuild_match_jaccard`.
    """
    pairs = sorted(
        ((jaccard(members, old_members), i, pid) for i, members in enumerate(new) for pid, old_members in old.items()),
        key=lambda p: (-p[0], p[1], p[2]),
    )
    matched: dict[int, str] = {}
    used: set[str] = set()
    for score, i, pid in pairs:
        if score < threshold or score == 0:
            break
        if i in matched or pid in used:
            continue
        matched[i] = pid
        used.add(pid)
    return matched
