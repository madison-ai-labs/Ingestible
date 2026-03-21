"""SPLADE sparse retrieval — learned sparse vectors with term expansion.

SPLADE produces sparse vectors where each dimension corresponds to a vocabulary
term. Non-zero weights indicate term importance, including terms NOT in the
original text (term expansion). This captures synonyms and related concepts
that BM25 misses.

Model: naver/splade-cocondenser-ensembledistil (default)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SpladeStore:
    """SPLADE sparse index for learned sparse retrieval."""

    def __init__(self, model_name: str = "naver/splade-cocondenser-ensembledistil"):
        self._model_name = model_name
        self._model = None
        self._tokenizer = None
        self._chunk_ids: list[str] = []
        self._sparse_vectors: list[dict[int, float]] = []  # token_id → weight

    def _load_model(self):
        if self._model is not None:
            return
        try:
            import torch  # noqa: F401
            from transformers import AutoModelForMaskedLM, AutoTokenizer
        except ImportError:
            raise ImportError(
                "SPLADE requires transformers and torch. "
                "Install with: pip install transformers torch"
            )
        logger.info("Loading SPLADE model: %s", self._model_name)
        self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        self._model = AutoModelForMaskedLM.from_pretrained(self._model_name)
        self._model.eval()

    def _encode_sparse(self, text: str) -> dict[int, float]:
        """Encode text into a sparse SPLADE vector."""
        import torch

        self._load_model()
        tokens = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            output = self._model(**tokens)
        # SPLADE: log(1 + ReLU(logits)) aggregated over tokens
        logits = output.logits
        sparse = torch.max(torch.log1p(torch.relu(logits)), dim=1).values.squeeze()
        # Extract non-zero entries
        indices = sparse.nonzero().squeeze(-1).tolist()
        if isinstance(indices, int):
            indices = [indices]
        weights = sparse[indices].tolist()
        if isinstance(weights, float):
            weights = [weights]
        return {idx: w for idx, w in zip(indices, weights) if w > 0}

    def add_documents(self, chunk_ids: list[str], texts: list[str]) -> None:
        """Index documents as sparse SPLADE vectors."""
        self._load_model()
        logger.info("Encoding %d documents with SPLADE...", len(texts))
        self._chunk_ids = chunk_ids
        self._sparse_vectors = []
        for text in texts:
            sv = self._encode_sparse(text)
            self._sparse_vectors.append(sv)

    def query(self, query: str, n_results: int = 20) -> list[tuple[str, float]]:
        """Query using SPLADE sparse dot product."""
        if not self._sparse_vectors:
            return []

        query_vec = self._encode_sparse(query)

        # Compute sparse dot product with all documents
        scores: list[float] = []
        for doc_vec in self._sparse_vectors:
            score = sum(query_vec.get(idx, 0) * doc_vec.get(idx, 0) for idx in query_vec)
            scores.append(score)

        # Rank by score
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        results = []
        for i in ranked_indices[:n_results]:
            if scores[i] > 0:
                results.append((self._chunk_ids[i], scores[i]))
        return results

    def save(self, path: Path) -> None:
        """Save SPLADE index to disk."""
        data = {
            "model_name": self._model_name,
            "chunk_ids": self._chunk_ids,
            "sparse_vectors": [{str(k): v for k, v in sv.items()} for sv in self._sparse_vectors],
        }
        path.write_text(json.dumps(data), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> SpladeStore:
        """Load a saved SPLADE index."""
        data = json.loads(path.read_text(encoding="utf-8"))
        store = cls(model_name=data.get("model_name", "naver/splade-cocondenser-ensembledistil"))
        store._chunk_ids = data["chunk_ids"]
        store._sparse_vectors = [
            {int(k): v for k, v in sv.items()} for sv in data["sparse_vectors"]
        ]
        return store

    @property
    def count(self) -> int:
        return len(self._chunk_ids)
