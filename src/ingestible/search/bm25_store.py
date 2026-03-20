"""BM25 sparse search index with pickle persistence."""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

from rank_bm25 import BM25Okapi

logger = logging.getLogger(__name__)


class BM25Store:
    def __init__(self, language: str = "en"):
        self._chunk_ids: list[str] = []
        self._corpus_tokens: list[list[str]] = []
        self._bm25: BM25Okapi | None = None
        self._language: str = language
        self._tokenize = _get_tokenize_fn(language)

    def add_documents(self, chunk_ids: list[str], texts: list[str]) -> None:
        """Add documents to the BM25 index. Call build() after all adds."""
        for cid, text in zip(chunk_ids, texts):
            self._chunk_ids.append(cid)
            self._corpus_tokens.append(self._tokenize(text))

    def build(self) -> None:
        """Build the BM25 index from added documents."""
        if not self._corpus_tokens:
            logger.warning("No documents to build BM25 index from")
            return
        self._bm25 = BM25Okapi(self._corpus_tokens)
        logger.info("BM25 index built with %d documents", len(self._chunk_ids))

    def query(self, text: str, n_results: int = 20) -> list[tuple[str, float]]:
        """Query the BM25 index. Returns (chunk_id, score) sorted descending."""
        if self._bm25 is None:
            return []

        tokens = self._tokenize(text)
        scores = self._bm25.get_scores(tokens)

        ranked = sorted(zip(self._chunk_ids, scores), key=lambda x: x[1], reverse=True)
        return [(cid, score) for cid, score in ranked[:n_results] if score > 0]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(
                {
                    "chunk_ids": self._chunk_ids,
                    "corpus_tokens": self._corpus_tokens,
                    "language": self._language,
                },
                f,
            )
        logger.info("BM25 index saved to %s (lang=%s)", path, self._language)

    @classmethod
    def load(cls, path: Path) -> BM25Store:
        with open(path, "rb") as f:
            # NOTE: pickle is used for BM25Okapi compatibility; a JSON format
            # would require re-serialising the tokenised corpus.  Validate the
            # deserialised structure to catch corrupted or tampered files.
            data = pickle.load(f)
        # Validate expected structure (defense against corrupted/malicious pickle)
        if not isinstance(data, dict) or "chunk_ids" not in data:
            raise ValueError("Invalid BM25 index format")
        language = data.get("language", "en")
        store = cls(language=language)
        store._chunk_ids = data["chunk_ids"]
        store._corpus_tokens = data["corpus_tokens"]
        store.build()
        return store

    @property
    def count(self) -> int:
        return len(self._chunk_ids)


def _tokenize(text: str) -> list[str]:
    """Simple whitespace + lowercase tokenizer."""
    return text.lower().split()


def _get_tokenize_fn(language: str):
    """Return a tokenization function, using language-aware stemmer if available."""
    from ingestible.utils.language import get_tokenizer

    return get_tokenizer(language)
