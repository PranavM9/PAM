"""fastembed wrapper that returns L2-normalized float32 vectors (SPEC §8 M4, §7.13 `EmbeddingCfg`)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from functools import lru_cache

import numpy as np

from pam.contracts.config import EmbeddingCfg
from pam.core.errors import PamError

BATCH_SIZE = 64  # §8 M4


def l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to unit length.

    Behavior:
        Accepts one vector or a 2-D matrix. All-zero rows are left as zeros.
    Returns:
        A float32 array of the same shape.
    Parameters:
        matrix: Vectors to normalize.
    """
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=-1, keepdims=True)
    return (matrix / np.where(norms == 0, 1, norms)).astype(np.float32)


class Embedder:
    """Embed documents and queries with one fastembed model.

    Behavior:
        The ONNX model loads on first use. The first load downloads it (about 130 MB) into
        `FASTEMBED_CACHE_PATH`, or fastembed's default cache, and prints a notice on stderr; the
        download itself shows its own progress bar. Documents are embedded as-is and queries get
        `query_prefix`.
    Parameters:
        cfg: Model name, dimension, and query prefix.
    """

    def __init__(self, cfg: EmbeddingCfg) -> None:
        self.model_name = cfg.model
        self.dim = cfg.dim
        self.query_prefix = cfg.query_prefix
        self._model = None

    def _load(self):
        if self._model is None:
            from fastembed import TextEmbedding  # noqa: PLC0415 - slow import, only when embedding

            print(f"Loading embedding model {self.model_name} (downloads about 130 MB if it is not cached yet)",
                  file=sys.stderr)
            self._model = TextEmbedding(self.model_name)
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> np.ndarray:
        """Embed document texts in batches of `BATCH_SIZE`.

        Exceptions:
            PamError: The model returns vectors of a dimension other than `dim`.
        Returns:
            A float32 matrix of shape `(len(texts), dim)` with unit-length rows.
        Parameters:
            texts: Texts to embed, in order.
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = np.array(list(self._load().embed(list(texts), batch_size=BATCH_SIZE)), dtype=np.float32)
        if vectors.shape[1] != self.dim:
            raise PamError(f"{self.model_name} returned {vectors.shape[1]}-dim vectors; the config says {self.dim}")
        return l2_normalize(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query with the configured query prefix.

        Returns:
            One unit-length float32 vector of length `dim`.
        Parameters:
            text: The query text, without the prefix.
        """
        return self.embed_documents([self.query_prefix + text])[0]


@lru_cache(maxsize=4)
def _cached(model: str, dim: int, query_prefix: str) -> Embedder:
    return Embedder(EmbeddingCfg(model=model, dim=dim, query_prefix=query_prefix))


def get_embedder(cfg: EmbeddingCfg) -> Embedder:
    """Return the process-wide embedder for a config.

    Behavior:
        One instance per model, dimension, and prefix, so the model loads once per process (the
        indexer and the retriever share it).
    Returns:
        The embedder; the model is not loaded until the first embed call.
    Parameters:
        cfg: The `embedding` section of `PamConfig`.
    """
    return _cached(cfg.model, cfg.dim, cfg.query_prefix)
