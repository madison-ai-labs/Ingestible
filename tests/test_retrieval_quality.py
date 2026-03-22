"""End-to-end retrieval quality tests.

Ingests a document with mock embeddings, builds search indexes, then evaluates
retrieval quality against known Q&A pairs with metric thresholds.

Also tests the NDCG metric and the eval framework against a live searcher.

Run with:  pytest tests/test_retrieval_quality.py -v -s
"""

from __future__ import annotations

import math
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ingestible.config import Settings
from ingestible.eval import (
    EvalQuery,
    EvalReport,
    EvalResult,
    _ndcg_at_k,
    evaluate_document,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _deterministic_embedder(dim: int = 64):
    """Mock embedder that produces topic-clustered vectors."""
    rng = np.random.RandomState(42)

    # 4 topic cluster centers
    centers = {}
    for topic in ["ml", "ocean", "roman", "generic"]:
        c = rng.randn(dim).astype(np.float32)
        c /= np.linalg.norm(c)
        centers[topic] = c

    topic_keywords = {
        "ml": ["learning", "neural", "training", "gradient", "model", "supervised"],
        "ocean": ["ocean", "marine", "reef", "fish", "water", "coral"],
        "roman": ["roman", "colosseum", "arch", "aqueduct", "concrete", "gladiat"],
    }

    def _classify(text: str) -> str:
        t = text.lower()
        for topic, keywords in topic_keywords.items():
            if any(k in t for k in keywords):
                return topic
        return "generic"

    def embed_passages(texts):
        vecs = []
        for t in texts:
            topic = _classify(t)
            base = centers[topic]
            noise = rng.randn(dim).astype(np.float32) * 0.08
            v = base + noise
            v /= np.linalg.norm(v)
            vecs.append(v.tolist())
        return vecs

    def embed_query(query):
        topic = _classify(query)
        base = centers[topic]
        noise = rng.randn(dim).astype(np.float32) * 0.03
        v = base + noise
        v /= np.linalg.norm(v)
        return v.tolist()

    embedder = MagicMock()
    embedder.embed_passages.side_effect = embed_passages
    embedder.embed_query.side_effect = embed_query
    return embedder


# ---------------------------------------------------------------------------
# NDCG unit tests
# ---------------------------------------------------------------------------


class TestNDCG:
    def test_perfect_retrieval(self):
        """All relevant docs at top positions should give NDCG = 1.0."""
        retrieved = ["a", "b", "c", "d", "e"]
        expected = {"a", "b"}
        ndcg = _ndcg_at_k(retrieved, expected, 5)
        assert ndcg == pytest.approx(1.0)

    def test_no_relevant_results(self):
        """No relevant docs in results should give NDCG = 0.0."""
        retrieved = ["x", "y", "z"]
        expected = {"a", "b"}
        ndcg = _ndcg_at_k(retrieved, expected, 3)
        assert ndcg == 0.0

    def test_relevant_at_bottom(self):
        """Relevant doc at position 5 should give lower NDCG than position 1."""
        expected = {"a"}
        ndcg_top = _ndcg_at_k(["a", "x", "y", "z", "w"], expected, 5)
        ndcg_bottom = _ndcg_at_k(["x", "y", "z", "w", "a"], expected, 5)
        assert ndcg_top > ndcg_bottom
        assert ndcg_top == pytest.approx(1.0)

    def test_empty_results(self):
        ndcg = _ndcg_at_k([], {"a"}, 5)
        assert ndcg == 0.0

    def test_empty_expected(self):
        ndcg = _ndcg_at_k(["a", "b"], set(), 5)
        assert ndcg == 0.0

    def test_partial_relevance_ordering(self):
        """Two relevant docs: one at pos 1 and one at pos 3 vs both at pos 1-2."""
        expected = {"a", "b"}
        ndcg_spread = _ndcg_at_k(["a", "x", "b", "y", "z"], expected, 5)
        ndcg_packed = _ndcg_at_k(["a", "b", "x", "y", "z"], expected, 5)
        assert ndcg_packed > ndcg_spread
        assert ndcg_packed == pytest.approx(1.0)

    def test_matches_manual_computation(self):
        """Verify against hand-calculated NDCG for a specific case."""
        # Relevant: {a, b}, Retrieved: [x, a, y, b, z]
        # DCG = 0/log2(2) + 1/log2(3) + 0/log2(4) + 1/log2(5) = 0.6309 + 0.4307 = 1.0616
        # IDCG = 1/log2(2) + 1/log2(3) = 1.0 + 0.6309 = 1.6309
        # NDCG = 1.0616 / 1.6309 = 0.6510
        ndcg = _ndcg_at_k(["x", "a", "y", "b", "z"], {"a", "b"}, 5)
        expected = (1.0 / math.log2(3) + 1.0 / math.log2(5)) / (
            1.0 / math.log2(2) + 1.0 / math.log2(3)
        )
        assert ndcg == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# EvalReport includes NDCG
# ---------------------------------------------------------------------------


class TestEvalReportNDCG:
    def test_report_contains_ndcg(self):
        report = EvalReport(
            doc_id="test",
            total_queries=2,
            k=5,
            hit_rate=1.0,
            mrr=0.75,
            mean_precision_at_k=0.4,
            mean_recall_at_k=0.8,
            mean_ndcg_at_k=0.85,
        )
        d = report.to_dict()
        assert "mean_ndcg_at_k" in d
        assert d["mean_ndcg_at_k"] == 0.85

        summary = report.summary()
        assert "NDCG" in summary
        assert "0.8500" in summary


# ---------------------------------------------------------------------------
# E2E retrieval quality with mock embeddings
# ---------------------------------------------------------------------------


class TestRetrievalQuality:
    def test_topical_retrieval_hits(self, tmp_path):
        """Queries about a specific topic should retrieve chunks from that topic.

        Ingests a 3-topic document, builds indexes with mock embedder,
        then runs topic-specific queries and checks hit rate.
        """
        data_dir = tmp_path / "data"
        settings = Settings(
            data_dir=data_dir,
            cleaning_enabled=True,
            checkpoint_enabled=False,
            max_chunk_tokens=200,
            min_chunk_tokens=30,
        )

        mock_emb = _deterministic_embedder()

        # Build a markdown doc with 3 topics
        md = tmp_path / "topics.md"
        md.write_text(
            "# Knowledge Survey\n\n"
            "## Machine Learning\n\n"
            "Machine learning algorithms learn patterns from training data. "
            "Supervised learning uses labeled examples. Neural networks use "
            "backpropagation to adjust weights. Gradient descent optimizes "
            "the loss function iteratively.\n\n"
            "## Marine Biology\n\n"
            "The ocean covers seventy percent of earth's surface. Marine "
            "ecosystems support biodiversity in tropical coral reefs. "
            "Ocean currents distribute heat globally and regulate climate.\n\n"
            "## Roman Architecture\n\n"
            "Ancient Roman architecture pioneered arches and concrete. "
            "The Colosseum seated fifty thousand spectators. Roman aqueducts "
            "transported water using gravity alone.\n"
        )

        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
        ):
            from ingestible.pipeline.orchestrator import ingest

            doc_dir = ingest(md, settings, skip_enrichment=True)

        # Build queries with expected chunk mapping
        from ingestible.pipeline.stage6_storage import load_chunks

        chunks = load_chunks(doc_dir)

        # Map sections to chunk IDs
        ml_chunks = [c.chunk_id for c in chunks.l3_chunks if c.parent_section_id == "ch0-sec0"]
        ocean_chunks = [c.chunk_id for c in chunks.l3_chunks if c.parent_section_id == "ch0-sec1"]
        roman_chunks = [c.chunk_id for c in chunks.l3_chunks if c.parent_section_id == "ch0-sec2"]

        # If the chunker used different section IDs, fall back to content matching
        if not ml_chunks:
            ml_chunks = [c.chunk_id for c in chunks.l3_chunks if "learning" in c.content.lower()]
        if not ocean_chunks:
            ocean_chunks = [c.chunk_id for c in chunks.l3_chunks if "ocean" in c.content.lower()]
        if not roman_chunks:
            roman_chunks = [c.chunk_id for c in chunks.l3_chunks if "roman" in c.content.lower()]

        queries = [
            EvalQuery(
                query="How do neural networks learn from training data?",
                expected_chunk_ids=ml_chunks,
            ),
            EvalQuery(
                query="What percentage of earth does the ocean cover?",
                expected_chunk_ids=ocean_chunks,
            ),
            EvalQuery(
                query="How did Romans build aqueducts?",
                expected_chunk_ids=roman_chunks,
            ),
        ]

        # Run eval — must also patch Embedder in eval module
        doc_id = doc_dir.name
        with patch("ingestible.eval.Embedder", return_value=mock_emb):
            report = evaluate_document(doc_id, settings, queries=queries, k=5)

        print("\n--- Retrieval Quality ---")
        print(report.summary())

        # Thresholds: with topic-clustered embeddings, we expect decent retrieval
        assert report.hit_rate >= 0.5, f"Hit rate too low: {report.hit_rate:.2f}"
        assert report.mrr >= 0.3, f"MRR too low: {report.mrr:.4f}"
        assert report.mean_ndcg_at_k >= 0.3, (
            f"NDCG@5 too low: {report.mean_ndcg_at_k:.4f} (minimum 0.30)"
        )

    def test_eval_report_fields_populated(self, tmp_path):
        """Verify evaluate_document returns fully populated EvalReport."""
        data_dir = tmp_path / "data"
        settings = Settings(data_dir=data_dir, checkpoint_enabled=False)
        mock_emb = _deterministic_embedder()

        md = tmp_path / "simple.md"
        md.write_text(
            "# Test Document\n\n"
            "## Section One\n\n"
            "Machine learning models require training data to learn patterns.\n"
        )

        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
        ):
            from ingestible.pipeline.orchestrator import ingest

            doc_dir = ingest(md, settings, skip_enrichment=True)

        from ingestible.pipeline.stage6_storage import load_chunks

        chunks = load_chunks(doc_dir)
        all_ids = [c.chunk_id for c in chunks.l3_chunks]

        queries = [
            EvalQuery(query="How do ML models learn?", expected_chunk_ids=all_ids),
        ]

        with patch("ingestible.eval.Embedder", return_value=mock_emb):
            report = evaluate_document(doc_dir.name, settings, queries=queries, k=3)

        assert report.total_queries == 1
        assert report.k == 3
        assert len(report.results) == 1
        assert isinstance(report.results[0], EvalResult)
        assert report.results[0].ndcg_at_k >= 0.0
        assert report.mean_ndcg_at_k >= 0.0

        # to_dict round-trips
        d = report.to_dict()
        assert "mean_ndcg_at_k" in d
        assert isinstance(d["mean_ndcg_at_k"], float)
