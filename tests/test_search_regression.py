"""Search regression tests — CI-friendly quality gates.

Ingests a small fixture document, runs eval with default settings, and asserts
minimum quality thresholds. Catches weight regressions and search algorithm
changes automatically.

Also tests the exact-match term boost feature.

Run with:  pytest tests/test_search_regression.py -v
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from ingestible.config import Settings
from ingestible.eval import EvalQuery, evaluate_document
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L3Chunk,
)
from ingestible.search.bm25_store import BM25Store
from ingestible.search.concept_index import ConceptIndex
from ingestible.search.hybrid import HybridSearcher

# ---------------------------------------------------------------------------
# Shared mock embedder (deterministic, hash-seeded per text)
# ---------------------------------------------------------------------------


def _mock_embedder(dim: int = 64):
    init_rng = np.random.RandomState(42)
    centres = {}
    for topic in ["ml", "ocean", "roman", "generic"]:
        c = init_rng.randn(dim).astype(np.float32)
        c /= np.linalg.norm(c)
        centres[topic] = c

    topic_kw = {
        "ml": ["learning", "neural", "training", "gradient", "model"],
        "ocean": ["ocean", "marine", "reef", "coral", "water"],
        "roman": ["roman", "colosseum", "arch", "aqueduct", "concrete"],
    }

    def _classify(text):
        t = text.lower()
        for topic, kws in topic_kw.items():
            if any(k in t for k in kws):
                return topic
        return "generic"

    def _embed(text, noise_scale):
        base = centres[_classify(text)]
        rng = np.random.RandomState(hash(text) % (2**31))
        v = base + rng.randn(dim).astype(np.float32) * noise_scale
        v /= np.linalg.norm(v)
        return v.tolist()

    embedder = MagicMock()
    embedder.embed_passages.side_effect = lambda texts: [_embed(t, 0.08) for t in texts]
    embedder.embed_query.side_effect = lambda q: _embed(q, 0.01)
    return embedder


# ---------------------------------------------------------------------------
# Fixture document
# ---------------------------------------------------------------------------

_FIXTURE_MD = """\
# Multi-Topic Survey

## Machine Learning

Supervised learning uses labeled training data to build predictive models.
Neural networks learn via backpropagation and gradient descent optimization.
Classification assigns inputs to discrete categories using learned boundaries.

## Marine Biology

The ocean covers seventy percent of earth's surface area globally.
Coral reefs support extraordinary biodiversity in tropical waters.
Marine plankton produce roughly half of the world's atmospheric oxygen.

## Roman Engineering

Roman engineers pioneered arches and concrete construction techniques.
The Colosseum seated fifty thousand spectators for gladiatorial events.
Roman aqueducts transported fresh water using gravity over long distances.
"""


# ---------------------------------------------------------------------------
# P2: CI quality gate — default weights must meet minimum thresholds
# ---------------------------------------------------------------------------


class TestSearchQualityGate:
    """CI-friendly test: ingest fixture, eval, assert quality floor."""

    def test_default_weights_meet_quality_bar(self, tmp_path):
        """Default search settings must achieve minimum MRR and NDCG."""
        data_dir = tmp_path / "data"
        settings = Settings(
            data_dir=data_dir,
            checkpoint_enabled=False,
            max_chunk_tokens=150,
            min_chunk_tokens=20,
        )
        mock_emb = _mock_embedder()

        md = tmp_path / "survey.md"
        md.write_text(_FIXTURE_MD)

        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
        ):
            from ingestible.pipeline.orchestrator import ingest

            doc_dir = ingest(md, settings, skip_enrichment=True)

        from ingestible.pipeline.stage6_storage import load_chunks

        chunks = load_chunks(doc_dir)

        # Build queries matched to chunks by content
        ml_ids = [c.chunk_id for c in chunks.l3_chunks if "learning" in c.content.lower()]
        ocean_ids = [c.chunk_id for c in chunks.l3_chunks if "ocean" in c.content.lower()]
        roman_ids = [c.chunk_id for c in chunks.l3_chunks if "roman" in c.content.lower()]

        queries = [
            EvalQuery(query="How do neural networks learn?", expected_chunk_ids=ml_ids),
            EvalQuery(query="What are coral reefs?", expected_chunk_ids=ocean_ids),
            EvalQuery(query="How did Romans build aqueducts?", expected_chunk_ids=roman_ids),
        ]

        with patch("ingestible.eval.Embedder", return_value=mock_emb):
            report = evaluate_document(doc_dir.name, settings, queries=queries, k=5)

        # Quality gates
        assert report.hit_rate >= 0.6, f"Hit rate {report.hit_rate:.0%} below CI threshold (60%)"
        assert report.mrr >= 0.5, f"MRR {report.mrr:.4f} below CI threshold (0.50)"
        assert report.mean_ndcg_at_k >= 0.3, (
            f"NDCG@5 {report.mean_ndcg_at_k:.4f} below CI threshold (0.30)"
        )

    def test_default_weights_are_bm25_dominant(self):
        """Default weights must have BM25 weight >= vector weight."""
        settings = Settings()
        assert settings.bm25_weight >= settings.vector_weight, (
            f"BM25 weight ({settings.bm25_weight}) should be >= vector weight "
            f"({settings.vector_weight}) per quality audit findings"
        )

    def test_weights_sum_close_to_one(self):
        """Vector + BM25 weights should sum to ~1.0."""
        settings = Settings()
        total = settings.vector_weight + settings.bm25_weight
        assert 0.9 <= total <= 1.1, f"Weights sum to {total}, expected ~1.0"


# ---------------------------------------------------------------------------
# P3: Exact-match term boost tests
# ---------------------------------------------------------------------------


class TestExactMatchBoost:
    """Verify the exact-match term boost improves entity/acronym queries."""

    def _build_searcher(self, chunks, embedder, settings, dim=64):
        """Build a HybridSearcher from chunks with real BM25 + mock vector."""
        from ingestible.search.vector_store import VectorStore

        # Build BM25
        bm25 = BM25Store()
        bm25.add_documents(
            [c.chunk_id for c in chunks.l3_chunks],
            [c.content for c in chunks.l3_chunks],
        )
        bm25.build()

        # Build concept index
        concepts = ConceptIndex()
        for c in chunks.l3_chunks:
            words = set(c.content.lower().split())
            concepts.add_many([w for w in words if len(w) >= 6], c.chunk_id)

        # Build vector store
        import tempfile
        from pathlib import Path

        tmp = Path(tempfile.mkdtemp())
        vs = VectorStore(tmp / "chroma")
        vecs = embedder.embed_passages([c.content for c in chunks.l3_chunks])
        vs.add_embeddings(
            ids=[c.chunk_id for c in chunks.l3_chunks],
            embeddings=vecs,
            metadatas=[
                {
                    "chunk_id": c.chunk_id,
                    "chapter": c.position.chapter,
                    "section": c.position.section,
                    "version_status": "current",
                }
                for c in chunks.l3_chunks
            ],
        )

        return HybridSearcher(vs, bm25, concepts, chunks, embedder, settings)

    def test_exact_match_boosts_entity_queries(self, tmp_path):
        """Chunks containing exact query terms should rank higher."""
        chunks = ChunkSet(
            doc_id="entity-test",
            l0=L0Chunk(chunk_id="entity-test-L0", title="Test"),
            l3_chunks=[
                L3Chunk(
                    chunk_id="generic",
                    content=(
                        "Machine learning models process large datasets. "
                        "Training requires significant computational resources "
                        "and careful hyperparameter selection."
                    ),
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                ),
                L3Chunk(
                    chunk_id="dpr-specific",
                    content=(
                        "DPR achieves strong performance on in-domain datasets "
                        "but shows degradation on out-of-domain benchmarks. "
                        "The DPR retriever uses dual encoders for dense passage retrieval."
                    ),
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=1),
                ),
                L3Chunk(
                    chunk_id="also-relevant",
                    content=(
                        "Retrieval models can struggle with domain shift. "
                        "Performance on out-of-domain data often drops significantly "
                        "compared to in-domain evaluation results."
                    ),
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=2),
                ),
            ],
        )

        emb = _mock_embedder()
        settings = Settings(data_dir=tmp_path, exact_match_boost=0.003)
        searcher = self._build_searcher(chunks, emb, settings)

        # Query with entity name "DPR"
        response = searcher.search("DPR performance on out-of-domain datasets")
        result_ids = [r.chunk_id for r in response.results]

        # The DPR-specific chunk should rank first or second
        assert "dpr-specific" in result_ids[:2], f"DPR chunk should be in top 2, got: {result_ids}"

        # The "exact" source should appear for the DPR chunk
        dpr_result = next(r for r in response.results if r.chunk_id == "dpr-specific")
        assert "exact" in dpr_result.match_sources, (
            f"DPR chunk should have 'exact' match source, got: {dpr_result.match_sources}"
        )

    def test_boost_disabled_when_zero(self, tmp_path):
        """Setting exact_match_boost=0 should disable the feature."""
        chunks = ChunkSet(
            doc_id="boost-off",
            l0=L0Chunk(chunk_id="boost-off-L0", title="Test"),
            l3_chunks=[
                L3Chunk(
                    chunk_id="c1",
                    content="DPR performs well on NQ and TriviaQA benchmarks.",
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                ),
                L3Chunk(
                    chunk_id="c2",
                    content="Retrieval models use dense embeddings for matching.",
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=1),
                ),
            ],
        )

        emb = _mock_embedder()
        settings = Settings(data_dir=tmp_path, exact_match_boost=0.0)
        searcher = self._build_searcher(chunks, emb, settings)

        response = searcher.search("DPR benchmark performance")

        # No "exact" source should appear when boost is 0
        for r in response.results:
            assert "exact" not in r.match_sources, (
                f"Chunk {r.chunk_id} should not have 'exact' source when boost=0"
            )

    def test_boost_requires_minimum_term_overlap(self, tmp_path):
        """Boost only applies when >= 2 query terms match (avoids noise)."""
        chunks = ChunkSet(
            doc_id="overlap-test",
            l0=L0Chunk(chunk_id="overlap-test-L0", title="Test"),
            l3_chunks=[
                L3Chunk(
                    chunk_id="one-match",
                    content="The DPR model was introduced in 2020 for open-domain QA.",
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                ),
            ],
        )

        emb = _mock_embedder()
        settings = Settings(data_dir=tmp_path, exact_match_boost=0.003)
        searcher = self._build_searcher(chunks, emb, settings)

        # Query with only 1 matching term ("DPR") — boost should NOT apply
        response = searcher.search("DPR")  # single short term, won't pass len>=3 filter
        # Even "DPR xyz" — only "DPR" and "xyz" match, but "xyz" isn't in the chunk
        response = searcher.search("DPR xyz")
        for r in response.results:
            assert "exact" not in r.match_sources, (
                "Single-term overlap should not trigger exact boost"
            )
