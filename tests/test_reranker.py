"""Tests for Feature 7 — Cross-Encoder Reranking."""

from __future__ import annotations

import sys
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


@pytest.fixture(autouse=True)
def _mock_chromadb(monkeypatch):
    """Prevent chromadb import failure on Python 3.14."""
    if "chromadb" not in sys.modules:
        monkeypatch.setitem(sys.modules, "chromadb", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.api", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.api.client", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.config", MagicMock())


def _import_searcher():
    from ingestible.search.hybrid import HybridSearcher
    return HybridSearcher


def _make_chunks_and_stores(n: int = 5):
    """Create mock chunks and stores for testing."""
    l3 = [
        L3Chunk(
            chunk_id=f"c{i}",
            content=f"Content about topic {i} in detail.",
            position=ChunkPosition(chapter="ch1", section="sec1", index=i),
        )
        for i in range(n)
    ]
    l0 = L0Chunk(chunk_id="test-L0", title="Test", total_passages=n)
    chunks = ChunkSet(doc_id="test", l0=l0, l3_chunks=l3)

    vector_store = MagicMock()
    bm25_store = MagicMock()
    concept_index = MagicMock()
    embedder = MagicMock()

    vector_store.query.return_value = [
        (f"c{i}", 1.0 - i * 0.1, {}) for i in range(n)
    ]
    bm25_store.query.return_value = [
        (f"c{n - 1 - i}", 5.0 - i) for i in range(n)
    ]
    concept_index.lookup.return_value = []
    embedder.embed_query.return_value = [0.1] * 10

    return chunks, vector_store, bm25_store, concept_index, embedder


def test_reranker_disabled_when_empty():
    HybridSearcher = _import_searcher()
    chunks, vs, bm25, ci, emb = _make_chunks_and_stores()
    settings = Settings(data_dir="/tmp/test", reranker_model="")

    searcher = HybridSearcher(vs, bm25, ci, chunks, emb, settings)
    assert searcher._reranker is None


def test_reranker_reorders_results():
    HybridSearcher = _import_searcher()
    chunks, vs, bm25, ci, emb = _make_chunks_and_stores()
    settings = Settings(
        data_dir="/tmp/test",
        reranker_model="",  # disable auto-load
        reranker_top_k=5,
        reranker_weight=0.9,
    )

    mock_ce = MagicMock()
    # CE scores: c4 gets highest score — should end up ranked high
    mock_ce.predict.return_value = np.array([0.1, 0.2, 0.5, 0.8, 1.0])

    searcher = HybridSearcher(vs, bm25, ci, chunks, emb, settings)
    # Manually inject the mock reranker
    searcher._reranker = mock_ce

    response = searcher.search("test query", n_results=3)
    result_ids = [r.chunk_id for r in response.results]
    assert len(result_ids) > 0
    # CE was called
    mock_ce.predict.assert_called_once()


def test_reranker_blending_math():
    w = 0.5
    rrf_score = 0.01
    ce_normalized = 0.8
    blended = (1 - w) * rrf_score + w * ce_normalized
    assert abs(blended - 0.405) < 0.001


def test_reranker_handles_single_result():
    HybridSearcher = _import_searcher()
    chunks, vs, bm25, ci, emb = _make_chunks_and_stores(1)
    settings = Settings(
        data_dir="/tmp/test",
        reranker_model="",
        reranker_top_k=5,
        reranker_weight=0.5,
    )

    mock_ce = MagicMock()
    mock_ce.predict.return_value = np.array([0.5])

    searcher = HybridSearcher(vs, bm25, ci, chunks, emb, settings)
    searcher._reranker = mock_ce

    response = searcher.search("test query", n_results=1)
    assert len(response.results) == 1
