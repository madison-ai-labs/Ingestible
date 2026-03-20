"""Hybrid search with Reciprocal Rank Fusion (RRF).

Merges vector (weight 0.7), BM25 (weight 0.3), and concept index boost.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.chunks import ChunkPosition, ChunkSet, L3Chunk
from ingestible.models.search import SearchResponse, SearchResult
from ingestible.pipeline.stage5_embedding import Embedder, _resolve_device
from ingestible.search.bm25_store import BM25Store
from ingestible.search.concept_index import ConceptIndex
from ingestible.search.vector_store import VectorStore

logger = logging.getLogger(__name__)

RRF_K = 60  # Standard RRF constant


class HybridSearcher:
    def __init__(
        self,
        vector_store: VectorStore,
        bm25_store: BM25Store,
        concept_index: ConceptIndex,
        chunks: ChunkSet,
        embedder: Embedder,
        settings: Settings,
    ):
        self._vector = vector_store
        self._bm25 = bm25_store
        self._concepts = concept_index
        self._chunks = chunks
        self._embedder = embedder
        self._settings = settings
        # Build chunk lookup
        self._chunk_map: dict[str, L3Chunk] = {c.chunk_id: c for c in chunks.l3_chunks}
        # Lazy-load cross-encoder reranker
        self._reranker = None
        if settings.reranker_model:
            try:
                from sentence_transformers import CrossEncoder

                self._reranker = CrossEncoder(
                    settings.reranker_model, device=_resolve_device(settings.embedding_device)
                )
                logger.info("Loaded reranker: %s", settings.reranker_model)
            except Exception as e:
                logger.warning("Failed to load reranker: %s", e)

    def search(self, query: str, n_results: int | None = None) -> SearchResponse:
        n = n_results or self._settings.default_search_results

        # 1) Vector search
        query_embedding = self._embedder.embed_query(query)
        vector_results = self._vector.query(query_embedding, n_results=n * 3)

        # 2) BM25 search
        bm25_results = self._bm25.query(query, n_results=n * 3)

        # 3) Concept lookup
        concept_chunk_ids = set(self._concepts.lookup(query))

        # 4) RRF merge
        scores: dict[str, float] = {}
        sources: dict[str, list[str]] = {}

        vector_weight = self._settings.vector_weight
        bm25_weight = self._settings.bm25_weight

        superseded_cids: set[str] = set()
        for rank, (cid, _dist, _meta) in enumerate(vector_results):
            rrf = vector_weight / (RRF_K + rank + 1)
            scores[cid] = scores.get(cid, 0.0) + rrf
            sources.setdefault(cid, []).append("vector")
            if _meta.get("version_status") == "superseded":
                superseded_cids.add(cid)

        for rank, (cid, _score) in enumerate(bm25_results):
            rrf = bm25_weight / (RRF_K + rank + 1)
            scores[cid] = scores.get(cid, 0.0) + rrf
            sources.setdefault(cid, []).append("bm25")

        # Concept boost: add a small fixed score
        concept_boost = 0.005
        for cid in concept_chunk_ids:
            scores[cid] = scores.get(cid, 0.0) + concept_boost
            sources.setdefault(cid, []).append("concept")

        # Version-aware weighting: superseded chunks get 0.3x score
        for cid in superseded_cids:
            if cid in scores:
                scores[cid] *= 0.3

        # Sort by score
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

        # Cross-encoder reranking
        if self._reranker and ranked:
            rerank_n = min(self._settings.reranker_top_k, len(ranked))
            rerank_candidates = ranked[:rerank_n]

            pairs = []
            valid_cids = []
            for cid, _ in rerank_candidates:
                chunk = self._chunk_map.get(cid)
                if chunk:
                    pairs.append((query, chunk.content))
                    valid_cids.append(cid)

            if pairs:
                ce_scores = self._reranker.predict(pairs)
                # Normalize CE scores to [0, 1]
                ce_min = float(min(ce_scores))
                ce_max = float(max(ce_scores))
                ce_range = ce_max - ce_min if ce_max > ce_min else 1.0
                ce_normalized = [(s - ce_min) / ce_range for s in ce_scores]

                w = self._settings.reranker_weight
                blended: dict[str, float] = {}
                for i, cid in enumerate(valid_cids):
                    rrf_score = scores.get(cid, 0.0)
                    blended[cid] = (1 - w) * rrf_score + w * ce_normalized[i]

                # Re-sort by blended score
                ranked = sorted(blended.items(), key=lambda x: x[1], reverse=True)
                logger.info("Reranked %d candidates with cross-encoder", len(pairs))

        ranked = ranked[:n]

        results = []
        for cid, score in ranked:
            chunk = self._chunk_map.get(cid)
            if chunk is None:
                continue
            results.append(
                SearchResult(
                    chunk_id=cid,
                    content=chunk.content,
                    summary=chunk.summary,
                    score=round(score, 4),
                    chapter=chunk.position.chapter,
                    section=chunk.position.section,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    match_sources=sources.get(cid, []),
                    version_status="superseded" if cid in superseded_cids else "current",
                )
            )

        return SearchResponse(
            doc_id=self._chunks.doc_id,
            query=query,
            results=results,
            total_candidates=len(scores),
        )


def load_searcher(
    doc_dir: Path,
    chunks: ChunkSet,
    embedder: Embedder,
    settings: Settings,
) -> HybridSearcher:
    """Load persisted indexes and create a HybridSearcher."""
    vector_store = VectorStore(doc_dir / "chroma")
    bm25_store = BM25Store.load(doc_dir / "bm25_index.pkl")
    concept_index = ConceptIndex.load(doc_dir / "concept_index.json")

    searcher = HybridSearcher(
        vector_store=vector_store,
        bm25_store=bm25_store,
        concept_index=concept_index,
        chunks=chunks,
        embedder=embedder,
        settings=settings,
    )

    # Load superseded chunks for version-aware search
    sup_path = doc_dir / "superseded.json"
    if sup_path.exists():
        import json

        try:
            sup_data = json.loads(sup_path.read_text(encoding="utf-8"))
            for item in sup_data:
                cid = item["chunk_id"]
                if cid not in searcher._chunk_map:
                    searcher._chunk_map[cid] = L3Chunk(
                        chunk_id=cid,
                        content=item.get("content", ""),
                        summary=item.get("summary", ""),
                        position=ChunkPosition(
                            chapter=item.get("chapter", ""),
                            section=item.get("section", ""),
                        ),
                        page_start=item.get("page_start"),
                        page_end=item.get("page_end"),
                        version_status="superseded",
                    )
        except (json.JSONDecodeError, OSError):
            pass

    return searcher
