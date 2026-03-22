"""Tests for hybrid search features: cross-encoder reranking and version-aware penalties.

Covers:
1. Cross-encoder reranker reorders results according to reranker scores
2. Superseded chunks receive a 0.3x score penalty, ranking below current chunks
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L3Chunk,
)
from ingestible.search.hybrid import HybridSearcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_l3(chunk_id: str, content: str, version_status: str = "current") -> L3Chunk:
    return L3Chunk(
        chunk_id=chunk_id,
        content=content,
        position=ChunkPosition(chapter="ch1", section="sec1"),
        version_status=version_status,
    )


def _make_chunkset(chunks: list[L3Chunk], doc_id: str = "test-doc") -> ChunkSet:
    return ChunkSet(
        doc_id=doc_id,
        l0=L0Chunk(chunk_id=f"{doc_id}-l0", title="Test Document"),
        l3_chunks=chunks,
    )


def _simple_embedder(dim: int = 64):
    """Mock embedder that produces deterministic content-seeded vectors."""
    embedder = MagicMock()

    def _vec(text: str) -> list[float]:
        rng = np.random.RandomState(hash(text) % 2**31)
        v = rng.randn(dim).astype(np.float32)
        v /= np.linalg.norm(v)
        return v.tolist()

    embedder.embed_passages.side_effect = lambda texts: [_vec(t) for t in texts]
    embedder.embed_query.side_effect = _vec
    return embedder


# ---------------------------------------------------------------------------
# 1. Cross-encoder reranking
# ---------------------------------------------------------------------------


class TestCrossEncoderReranking:
    """Verify that when a reranker is present, results are reordered by
    blended RRF + cross-encoder scores."""

    def test_reranker_swaps_result_order(self, tmp_path):
        """A reranker that prefers chunk_b over chunk_a should flip the
        default fusion ordering."""
        settings = Settings(
            data_dir=tmp_path / "data",
            checkpoint_enabled=False,
            reranker_model="",  # We inject the reranker manually
            reranker_weight=0.9,  # Heavy reranker weight so it dominates
            reranker_top_k=10,
            exact_match_boost=0.0,  # Disable — this test is about reranker ordering
        )

        chunk_a = _make_l3("chunk-a", "Alpha content about machine learning models")
        chunk_b = _make_l3("chunk-b", "Beta content about neural network training")
        chunks = _make_chunkset([chunk_a, chunk_b])

        # Mock vector store: returns chunk_a ranked first (lower distance)
        mock_vector = MagicMock()
        mock_vector.query.return_value = [
            ("chunk-a", 0.1, {"version_status": "current"}),
            ("chunk-b", 0.5, {"version_status": "current"}),
        ]

        # Mock BM25: also returns chunk_a first
        mock_bm25 = MagicMock()
        mock_bm25.query.return_value = [
            ("chunk-a", 5.0),
            ("chunk-b", 2.0),
        ]

        # No concept boost
        mock_concepts = MagicMock()
        mock_concepts.lookup.return_value = []

        mock_embedder = _simple_embedder()

        searcher = HybridSearcher(
            vector_store=mock_vector,
            bm25_store=mock_bm25,
            concept_index=mock_concepts,
            chunks=chunks,
            embedder=mock_embedder,
            settings=settings,
        )

        # Inject a mock reranker that strongly prefers chunk_b
        mock_reranker = MagicMock()
        # predict receives [(query, chunk_a.content), (query, chunk_b.content)]
        # Return scores: chunk_a gets low score, chunk_b gets high score
        mock_reranker.predict.return_value = [0.1, 0.95]
        searcher._reranker = mock_reranker

        response = searcher.search("neural network training", n_results=5)

        assert len(response.results) == 2
        # Reranker prefers chunk_b, so it should be first
        assert response.results[0].chunk_id == "chunk-b"
        assert response.results[1].chunk_id == "chunk-a"
        # Verify the reranker was actually called
        mock_reranker.predict.assert_called_once()

    def test_no_reranker_preserves_fusion_order(self, tmp_path):
        """Without a reranker, the RRF fusion order is preserved."""
        settings = Settings(
            data_dir=tmp_path / "data",
            checkpoint_enabled=False,
            reranker_model="",
            exact_match_boost=0.0,
        )

        chunk_a = _make_l3("chunk-a", "Alpha content about machine learning")
        chunk_b = _make_l3("chunk-b", "Beta content about deep learning")
        chunks = _make_chunkset([chunk_a, chunk_b])

        mock_vector = MagicMock()
        mock_vector.query.return_value = [
            ("chunk-a", 0.1, {"version_status": "current"}),
            ("chunk-b", 0.5, {"version_status": "current"}),
        ]

        mock_bm25 = MagicMock()
        mock_bm25.query.return_value = [
            ("chunk-a", 5.0),
            ("chunk-b", 2.0),
        ]

        mock_concepts = MagicMock()
        mock_concepts.lookup.return_value = []

        mock_embedder = _simple_embedder()

        searcher = HybridSearcher(
            vector_store=mock_vector,
            bm25_store=mock_bm25,
            concept_index=mock_concepts,
            chunks=chunks,
            embedder=mock_embedder,
            settings=settings,
        )
        # _reranker is None by default (reranker_model is empty)
        assert searcher._reranker is None

        response = searcher.search("machine learning", n_results=5)

        # chunk_a was ranked first by both vector and BM25 — should stay first
        assert len(response.results) == 2
        assert response.results[0].chunk_id == "chunk-a"
        assert response.results[1].chunk_id == "chunk-b"

    def test_reranker_with_three_candidates(self, tmp_path):
        """Reranker reorders 3 candidates; verify the full new ordering."""
        settings = Settings(
            data_dir=tmp_path / "data",
            checkpoint_enabled=False,
            reranker_weight=0.95,
            reranker_top_k=10,
            exact_match_boost=0.0,
        )

        chunk_a = _make_l3("chunk-a", "First chunk about algorithms")
        chunk_b = _make_l3("chunk-b", "Second chunk about data structures")
        chunk_c = _make_l3("chunk-c", "Third chunk about optimization")
        chunks = _make_chunkset([chunk_a, chunk_b, chunk_c])

        # Fusion order: a > b > c
        mock_vector = MagicMock()
        mock_vector.query.return_value = [
            ("chunk-a", 0.1, {"version_status": "current"}),
            ("chunk-b", 0.3, {"version_status": "current"}),
            ("chunk-c", 0.6, {"version_status": "current"}),
        ]

        mock_bm25 = MagicMock()
        mock_bm25.query.return_value = [
            ("chunk-a", 6.0),
            ("chunk-b", 4.0),
            ("chunk-c", 2.0),
        ]

        mock_concepts = MagicMock()
        mock_concepts.lookup.return_value = []

        mock_embedder = _simple_embedder()

        searcher = HybridSearcher(
            vector_store=mock_vector,
            bm25_store=mock_bm25,
            concept_index=mock_concepts,
            chunks=chunks,
            embedder=mock_embedder,
            settings=settings,
        )

        # Reranker reverses the order: c > b > a
        mock_reranker = MagicMock()
        mock_reranker.predict.return_value = [0.1, 0.5, 0.9]
        searcher._reranker = mock_reranker

        response = searcher.search("optimization techniques", n_results=5)

        assert len(response.results) == 3
        assert response.results[0].chunk_id == "chunk-c"
        assert response.results[1].chunk_id == "chunk-b"
        assert response.results[2].chunk_id == "chunk-a"


# ---------------------------------------------------------------------------
# 2. Superseded chunk version penalty
# ---------------------------------------------------------------------------


class TestSupersededChunkPenalty:
    """Verify that superseded chunks receive a 0.3x RRF score penalty,
    causing them to rank lower than equivalent current chunks."""

    def test_superseded_chunk_ranks_below_current(self, tmp_path):
        """A superseded chunk with same base relevance should rank below
        a current chunk."""
        settings = Settings(
            data_dir=tmp_path / "data",
            checkpoint_enabled=False,
            exact_match_boost=0.0,
        )

        chunk_current = _make_l3("chunk-cur", "Guide to machine learning models")
        chunk_superseded = _make_l3(
            "chunk-sup",
            "Guide to machine learning models (old version)",
            version_status="superseded",
        )
        chunks = _make_chunkset([chunk_current, chunk_superseded])

        # Both chunks rank equally in vector search, but superseded is flagged
        mock_vector = MagicMock()
        mock_vector.query.return_value = [
            ("chunk-sup", 0.1, {"version_status": "superseded"}),
            ("chunk-cur", 0.1, {"version_status": "current"}),
        ]

        # Both rank equally in BM25
        mock_bm25 = MagicMock()
        mock_bm25.query.return_value = [
            ("chunk-sup", 5.0),
            ("chunk-cur", 5.0),
        ]

        mock_concepts = MagicMock()
        mock_concepts.lookup.return_value = []

        mock_embedder = _simple_embedder()

        searcher = HybridSearcher(
            vector_store=mock_vector,
            bm25_store=mock_bm25,
            concept_index=mock_concepts,
            chunks=chunks,
            embedder=mock_embedder,
            settings=settings,
        )

        response = searcher.search("machine learning", n_results=5)

        assert len(response.results) == 2
        assert response.results[0].chunk_id == "chunk-cur"
        assert response.results[1].chunk_id == "chunk-sup"
        # The superseded result should be flagged in the response
        assert response.results[1].version_status == "superseded"
        assert response.results[0].version_status == "current"

    def test_superseded_score_is_reduced(self, tmp_path):
        """The superseded chunk's score should be ~0.3x the current chunk's
        score when both have identical base scores."""
        settings = Settings(
            data_dir=tmp_path / "data",
            checkpoint_enabled=False,
            exact_match_boost=0.0,
        )

        chunk_current = _make_l3("chunk-cur", "Content about testing")
        chunk_superseded = _make_l3(
            "chunk-sup", "Content about testing", version_status="superseded"
        )
        chunks = _make_chunkset([chunk_current, chunk_superseded])

        # Give them the same vector rank positions
        mock_vector = MagicMock()
        mock_vector.query.return_value = [
            ("chunk-cur", 0.2, {"version_status": "current"}),
            ("chunk-sup", 0.2, {"version_status": "superseded"}),
        ]

        # Same BM25 rank
        mock_bm25 = MagicMock()
        mock_bm25.query.return_value = [
            ("chunk-cur", 4.0),
            ("chunk-sup", 4.0),
        ]

        mock_concepts = MagicMock()
        mock_concepts.lookup.return_value = []

        mock_embedder = _simple_embedder()

        searcher = HybridSearcher(
            vector_store=mock_vector,
            bm25_store=mock_bm25,
            concept_index=mock_concepts,
            chunks=chunks,
            embedder=mock_embedder,
            settings=settings,
        )

        response = searcher.search("testing content", n_results=5)

        cur_result = next(r for r in response.results if r.chunk_id == "chunk-cur")
        sup_result = next(r for r in response.results if r.chunk_id == "chunk-sup")

        # Superseded score should be roughly 0.3x the current score
        # (Not exact due to different BM25 rank positions, but the vector
        # contribution is penalized)
        assert sup_result.score < cur_result.score
        assert sup_result.score == pytest.approx(cur_result.score * 0.3, rel=0.15)

    def test_superseded_with_e2e_ingestion(self, tmp_path):
        """End-to-end: ingest a document, write superseded.json to simulate
        a previously superseded chunk, and verify the penalty is applied."""
        import json

        data_dir = tmp_path / "data"
        settings = Settings(
            data_dir=data_dir,
            checkpoint_enabled=False,
        )

        mock_emb = _simple_embedder()

        md = tmp_path / "versioned.md"
        md.write_text(
            "# Versioned Document\n\n"
            "## Current Section\n\n"
            "Machine learning requires training data and validation data. "
            "Models learn patterns from labeled examples using gradient descent.\n\n"
            "## Another Section\n\n"
            "Neural networks use backpropagation to optimize weights. "
            "Deep learning enables hierarchical feature extraction.\n"
        )

        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
        ):
            from ingestible.pipeline.orchestrator import ingest

            doc_dir = ingest(md, settings, skip_enrichment=True)

        from ingestible.pipeline.stage6_storage import load_chunks
        from ingestible.search.hybrid import load_searcher
        from ingestible.search.vector_store import VectorStore

        chunks = load_chunks(doc_dir)
        assert len(chunks.l3_chunks) >= 2, "Need at least 2 chunks for this test"

        # Write superseded.json to simulate an old version of the first chunk.
        # This is how the real pipeline records superseded chunks (stage5 writes it).
        sup_chunk = chunks.l3_chunks[0]
        sup_data = [
            {
                "chunk_id": sup_chunk.chunk_id,
                "content": sup_chunk.content,
                "chapter": sup_chunk.position.chapter,
                "section": sup_chunk.position.section,
                "page_start": sup_chunk.page_start,
                "page_end": sup_chunk.page_end,
            }
        ]
        sup_path = doc_dir / "superseded.json"
        sup_path.write_text(json.dumps(sup_data))

        # Also add the superseded embedding to ChromaDB with version_status metadata
        vector_store = VectorStore(doc_dir / "chroma")
        sup_vec = mock_emb.embed_passages([sup_chunk.content])[0]
        vector_store.add_embeddings(
            ids=[f"{sup_chunk.chunk_id}::content::sup"],
            embeddings=[sup_vec],
            metadatas=[
                {
                    "chunk_id": sup_chunk.chunk_id,
                    "chapter": sup_chunk.position.chapter,
                    "section": sup_chunk.position.section,
                    "version_status": "superseded",
                    "embedding_type": "content",
                }
            ],
        )

        # Reload searcher — load_searcher reads superseded.json
        searcher = load_searcher(doc_dir, chunks, mock_emb, settings)

        # Search for content that matches the superseded chunk
        response = searcher.search("machine learning training data", n_results=10)

        assert len(response.results) >= 1

        # Verify superseded results are flagged
        sup_results = [r for r in response.results if r.version_status == "superseded"]
        cur_results = [r for r in response.results if r.version_status == "current"]

        # The superseded chunk should appear with reduced score if both are present
        if sup_results and cur_results:
            best_current_score = max(r.score for r in cur_results)
            best_superseded_score = max(r.score for r in sup_results)
            assert best_superseded_score < best_current_score, (
                f"Superseded score {best_superseded_score} should be lower than "
                f"current score {best_current_score}"
            )
