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

    def _discover_doc_dirs(
        self,
        doc_ids: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> list[Path]:
        """List document directories, optionally filtered by doc_ids and/or tags."""
        docs_dir = self._settings.documents_dir
        if not docs_dir.exists():
            return []
        dirs = []
        for d in sorted(docs_dir.iterdir()):
            if not d.is_dir() or not (d / "meta.json").exists():
                continue
            if doc_ids and d.name not in doc_ids:
                continue
            if tags:
                try:
                    meta = load_document_meta(d)
                    doc_tags = set(meta.get("tags", []))
                    if not doc_tags & set(tags):
                        continue
                except Exception:
                    continue
            dirs.append(d)
        return dirs

    def _get_searcher(self, doc_dir: Path, doc_weight: float = 0.0) -> HybridSearcher:
        """Get or create a cached HybridSearcher for a document."""
        doc_id = doc_dir.name
        cached = self._searcher_cache.get(doc_id)
        if cached is not None:
            # Update weight if changed (cheap attribute set)
            cached._doc_weight = doc_weight
            return cached
        chunks = load_chunks(doc_dir)
        searcher = load_searcher(
            doc_dir, chunks, self.embedder, self._settings, doc_weight=doc_weight
        )
        self._searcher_cache.put(doc_id, searcher)
        return searcher

    def search(
        self,
        query: str,
        n_results: int = 10,
        doc_ids: list[str] | None = None,
        user_tags: list[str] | None = None,
        user: str = "",
        tags: list[str] | None = None,
    ) -> CorpusSearchResponse:
        """Search across all (or selected) documents, merging via RRF."""
        doc_dirs = self._discover_doc_dirs(doc_ids, tags=tags)

        if not doc_dirs:
            return CorpusSearchResponse(query=query)

        # Collect pinned document directories (search all docs, not just filtered)
        pinned_dirs: list[Path] = []
        if not doc_ids:
            # Only auto-include pinned docs when not explicitly filtering by doc_ids
            all_dirs = self._discover_doc_dirs()
            for d in all_dirs:
                try:
                    meta = load_document_meta(d)
                    if meta.get("pinned", False) and d not in doc_dirs:
                        pinned_dirs.append(d)
                except Exception:
                    pass

        # Query each document's searcher
        per_doc_results: list[tuple[str, str, list[SearchResult], list[str]]] = []

        for doc_dir in doc_dirs:
            doc_id = doc_dir.name
            try:
                meta = load_document_meta(doc_dir)
                doc_title = meta.get("title", doc_id)
                doc_weight = meta.get("weight", 0.0)
                doc_tags = meta.get("tags", [])
                searcher = self._get_searcher(doc_dir, doc_weight=doc_weight)
                response = searcher.search(
                    query, n_results=n_results, user_tags=user_tags, user=user
                )
                per_doc_results.append((doc_id, doc_title, response.results, doc_tags))
            except Exception as e:
                logger.warning("Search failed for %s: %s", doc_id, e)

        # Query pinned documents that weren't in the main set
        pinned_results: list[SearchResult] = []
        pinned_top_n = self._settings.pinned_top_n

        for doc_dir in pinned_dirs:
            doc_id = doc_dir.name
            try:
                meta = load_document_meta(doc_dir)
                doc_title = meta.get("title", doc_id)
                doc_weight = meta.get("weight", 0.0)
                doc_tags = meta.get("tags", [])
                searcher = self._get_searcher(doc_dir, doc_weight=doc_weight)
                response = searcher.search(
                    query, n_results=pinned_top_n, user_tags=user_tags, user=user
                )
                for r in response.results[:pinned_top_n]:
                    pinned_results.append(
                        r.model_copy(
                            update={
                                "doc_id": doc_id,
                                "doc_title": doc_title,
                                "doc_tags": doc_tags,
                                "pinned": True,
                            }
                        )
                    )
            except Exception as e:
                logger.warning("Pinned search failed for %s: %s", doc_id, e)

        # Also collect pinned results from docs in the main set
        for doc_dir in doc_dirs:
            try:
                meta = load_document_meta(doc_dir)
                if meta.get("pinned", False):
                    doc_id = doc_dir.name
                    doc_title = meta.get("title", doc_id)
                    doc_tags = meta.get("tags", [])
                    doc_weight = meta.get("weight", 0.0)
                    searcher = self._get_searcher(doc_dir, doc_weight=doc_weight)
                    response = searcher.search(
                        query, n_results=pinned_top_n, user_tags=user_tags, user=user
                    )
                    for r in response.results[:pinned_top_n]:
                        pinned_results.append(
                            r.model_copy(
                                update={
                                    "doc_id": doc_id,
                                    "doc_title": doc_title,
                                    "doc_tags": doc_tags,
                                    "pinned": True,
                                }
                            )
                        )
            except Exception:
                pass

        # Cross-document RRF merge
        scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}

        for doc_id, doc_title, results, doc_tags in per_doc_results:
            for rank, result in enumerate(results):
                # Prefix chunk_id with doc_id to avoid collisions
                key = f"{doc_id}::{result.chunk_id}"
                rrf_score = 1.0 / (RRF_K + rank + 1)
                scores[key] = scores.get(key, 0.0) + rrf_score

                # Annotate with doc info
                enriched = result.model_copy(
                    update={"doc_id": doc_id, "doc_title": doc_title, "doc_tags": doc_tags}
                )
                result_map[key] = enriched

        # Sort and take top N
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:n_results]

        merged = []
        for key, score in ranked:
            result = result_map[key]
            merged.append(result.model_copy(update={"score": round(score, 4)}))

        # Prepend pinned results, deduplicating against merged results
        if pinned_results:
            merged_keys = {f"{r.doc_id}::{r.chunk_id}" for r in merged}
            unique_pinned = []
            seen_pinned_keys: set[str] = set()
            for pr in pinned_results:
                key = f"{pr.doc_id}::{pr.chunk_id}"
                if key not in merged_keys and key not in seen_pinned_keys:
                    unique_pinned.append(pr)
                    seen_pinned_keys.add(key)
                elif key in merged_keys:
                    # Mark existing result as pinned
                    for i, mr in enumerate(merged):
                        if f"{mr.doc_id}::{mr.chunk_id}" == key:
                            merged[i] = mr.model_copy(update={"pinned": True})
                            break
            merged = unique_pinned + merged

        return CorpusSearchResponse(
            query=query,
            results=merged,
            total_candidates=sum(len(r) for _, _, r, _ in per_doc_results),
            documents_searched=len(per_doc_results),
        )
