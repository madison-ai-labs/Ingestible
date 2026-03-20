"""Cross-document corpus search — WP 2.1.

Discovers all document directories, loads per-document HybridSearcher instances
(with LRU cache), queries each in parallel, merges results via cross-document RRF.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.search import CorpusSearchResponse, SearchResult
from ingestible.pipeline.stage5_embedding import Embedder
from ingestible.pipeline.stage6_storage import load_chunks, load_document_meta
from ingestible.search.hybrid import HybridSearcher, load_searcher

logger = logging.getLogger(__name__)

RRF_K = 60


class _LRUCache:
    """Simple LRU cache with a maximum size."""

    def __init__(self, maxsize: int = 50):
        self._maxsize = maxsize
        self._cache: OrderedDict = OrderedDict()

    def get(self, key: str):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        return None

    def put(self, key: str, value):
        if key in self._cache:
            self._cache.move_to_end(key)
        else:
            if len(self._cache) >= self._maxsize:
                self._cache.popitem(last=False)
        self._cache[key] = value

    def __len__(self):
        return len(self._cache)


class CorpusSearcher:
    """Search across all ingested documents."""

    def __init__(self, settings: Settings, embedder: Embedder | None = None):
        self._settings = settings
        self._embedder = embedder
        self._searcher_cache = _LRUCache(maxsize=settings.searcher_cache_size)

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            self._embedder = Embedder(self._settings)
        return self._embedder

    def _discover_doc_dirs(self, doc_ids: list[str] | None = None) -> list[Path]:
        """List document directories, optionally filtered by doc_ids."""
        docs_dir = self._settings.documents_dir
        if not docs_dir.exists():
            return []
        dirs = []
        for d in sorted(docs_dir.iterdir()):
            if not d.is_dir() or not (d / "meta.json").exists():
                continue
            if doc_ids and d.name not in doc_ids:
                continue
            dirs.append(d)
        return dirs

    def _get_searcher(self, doc_dir: Path) -> HybridSearcher:
        """Get or create a cached HybridSearcher for a document."""
        doc_id = doc_dir.name
        cached = self._searcher_cache.get(doc_id)
        if cached is not None:
            return cached
        chunks = load_chunks(doc_dir)
        searcher = load_searcher(doc_dir, chunks, self.embedder, self._settings)
        self._searcher_cache.put(doc_id, searcher)
        return searcher

    def search(
        self,
        query: str,
        n_results: int = 10,
        doc_ids: list[str] | None = None,
    ) -> CorpusSearchResponse:
        """Search across all (or selected) documents, merging via RRF."""
        doc_dirs = self._discover_doc_dirs(doc_ids)

        if not doc_dirs:
            return CorpusSearchResponse(query=query)

        # Query each document's searcher
        per_doc_results: list[tuple[str, str, list[SearchResult]]] = []

        for doc_dir in doc_dirs:
            doc_id = doc_dir.name
            try:
                meta = load_document_meta(doc_dir)
                doc_title = meta.get("title", doc_id)
                searcher = self._get_searcher(doc_dir)
                response = searcher.search(query, n_results=n_results)
                per_doc_results.append((doc_id, doc_title, response.results))
            except Exception as e:
                logger.warning("Search failed for %s: %s", doc_id, e)

        # Cross-document RRF merge
        scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}

        for doc_id, doc_title, results in per_doc_results:
            for rank, result in enumerate(results):
                # Prefix chunk_id with doc_id to avoid collisions
                key = f"{doc_id}::{result.chunk_id}"
                rrf_score = 1.0 / (RRF_K + rank + 1)
                scores[key] = scores.get(key, 0.0) + rrf_score

                # Annotate with doc info
                enriched = result.model_copy(update={"doc_id": doc_id, "doc_title": doc_title})
                result_map[key] = enriched

        # Sort and take top N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n_results]

        merged = []
        for key, score in ranked:
            result = result_map[key]
            merged.append(result.model_copy(update={"score": round(score, 4)}))

        return CorpusSearchResponse(
            query=query,
            results=merged,
            total_candidates=sum(len(r) for _, _, r in per_doc_results),
            documents_searched=len(per_doc_results),
        )
