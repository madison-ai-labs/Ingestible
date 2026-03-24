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

    def _load_doc_metas(self, doc_dirs: list[Path]) -> dict[str, dict]:
        """Load and cache meta.json for a list of doc directories."""
        metas: dict[str, dict] = {}
        for d in doc_dirs:
            try:
                metas[d.name] = load_document_meta(d)
            except Exception:
                pass
        return metas

    def search(
        self,
        query: str,
        n_results: int = 10,
        doc_ids: list[str] | None = None,
        user_tags: list[str] | None = None,
        user: str = "",
        tags: list[str] | None = None,
        hyde_query: str | None = None,
    ) -> CorpusSearchResponse:
        """Search across all (or selected) documents, merging via RRF."""
        doc_dirs = self._discover_doc_dirs(doc_ids, tags=tags)
        doc_dir_set = set(doc_dirs)

        # Load all metas once to avoid repeated I/O
        metas = self._load_doc_metas(doc_dirs)

        # Find pinned docs not already in the search set
        pinned_extra_dirs: list[Path] = []
        if not doc_ids:
            all_dirs = self._discover_doc_dirs()
            for d in all_dirs:
                if d not in doc_dir_set:
                    try:
                        meta = load_document_meta(d)
                        if meta.get("pinned", False):
                            pinned_extra_dirs.append(d)
                            metas[d.name] = meta
                    except Exception:
                        pass

        if not doc_dirs and not pinned_extra_dirs:
            return CorpusSearchResponse(query=query)

        # Query each document's searcher
        per_doc_results: list[tuple[str, str, list[SearchResult], list[str]]] = []

        for doc_dir in doc_dirs:
            doc_id = doc_dir.name
            meta = metas.get(doc_id)
            if meta is None:
                continue
            try:
                doc_title = meta.get("title", doc_id)
                doc_weight = meta.get("weight", 0.0)
                doc_tags = meta.get("tags", [])
                searcher = self._get_searcher(doc_dir, doc_weight=doc_weight)
                response = searcher.search(
                    query,
                    n_results=n_results,
                    user_tags=user_tags,
                    user=user,
                    hyde_query=hyde_query,
                )
                per_doc_results.append((doc_id, doc_title, response.results, doc_tags))
            except Exception as e:
                logger.warning("Search failed for %s: %s", doc_id, e)

        # Collect pinned results — from docs in main set + extra pinned docs
        pinned_results: list[SearchResult] = []
        pinned_top_n = self._settings.pinned_top_n
        pinned_doc_dirs = pinned_extra_dirs + [
            d for d in doc_dirs if metas.get(d.name, {}).get("pinned", False)
        ]

        for doc_dir in pinned_doc_dirs:
            doc_id = doc_dir.name
            meta = metas.get(doc_id)
            if meta is None:
                continue
            try:
                doc_title = meta.get("title", doc_id)
                doc_weight = meta.get("weight", 0.0)
                doc_tags = meta.get("tags", [])
                searcher = self._get_searcher(doc_dir, doc_weight=doc_weight)
                response = searcher.search(
                    query,
                    n_results=pinned_top_n,
                    user_tags=user_tags,
                    user=user,
                    hyde_query=hyde_query,
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

        # Cross-document RRF merge
        scores: dict[str, float] = {}
        result_map: dict[str, SearchResult] = {}

        for doc_id, doc_title, results, doc_tags in per_doc_results:
            for rank, result in enumerate(results):
                key = f"{doc_id}::{result.chunk_id}"
                rrf_score = 1.0 / (RRF_K + rank + 1)
                scores[key] = scores.get(key, 0.0) + rrf_score
                enriched = result.model_copy(
                    update={"doc_id": doc_id, "doc_title": doc_title, "doc_tags": doc_tags}
                )
                result_map[key] = enriched

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
