"""Shared test setup: keep writer reindexing offline.

Behavior:
    Writers (M7) reindex touched files through `pam.index.indexer`, which would download the
    fastembed model. This autouse fixture swaps in a deterministic fake embedder; tests that need
    their own embedder (`test_m04_index.py`, which also runs the real model) are left alone.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from pam.index import embedder, indexer


class _HashEmbedder:
    """Deterministic stand-in for fastembed: a text's sha256 seeds a random unit vector."""

    model_name = "BAAI/bge-small-en-v1.5"
    dim = 384

    def embed_documents(self, texts):
        rows = [
            np.random.default_rng(int(hashlib.sha256(t.encode()).hexdigest()[:16], 16)).standard_normal(384)
            for t in texts
        ]
        return embedder.l2_normalize(np.array(rows).reshape(len(texts), 384))

    def embed_query(self, text):
        return self.embed_documents([text])[0]


@pytest.fixture(autouse=True)
def _offline_embedder(request, monkeypatch):
    if request.module.__name__.endswith("test_m04_index"):
        return
    fake = _HashEmbedder()
    monkeypatch.setattr(indexer, "get_embedder", lambda cfg: fake)
