"""WP 6.2 — End-to-end Smoke Test.

Full pipeline integration test: ingest fixtures → search → export → re-enrich.
Uses mocked Embedder and LLM to avoid external dependencies.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet


@pytest.fixture
def fixtures_dir(tmp_path: Path) -> Path:
    """Create 3 test fixture files."""
    # Markdown
    md = tmp_path / "notes.md"
    md.write_text(
        "# Machine Learning Notes\n\n"
        "## Supervised Learning\n\n"
        "Supervised learning uses labeled data to train models. "
        "Common algorithms include linear regression, decision trees, "
        "and support vector machines.\n\n"
        "## Unsupervised Learning\n\n"
        "Unsupervised learning finds patterns in unlabeled data. "
        "Clustering and dimensionality reduction are key techniques.\n"
    )

    # Plain text
    txt = tmp_path / "readme.txt"
    txt.write_text(
        "Getting Started Guide\n\n"
        "This document explains how to set up the development environment. "
        "You need Python 3.11 or newer and pip installed on your system. "
        "Clone the repository and run pip install to get started.\n"
    )

    # CSV
    csv = tmp_path / "metrics.csv"
    csv.write_text(
        "model,accuracy,precision,recall\n"
        "logistic_regression,0.85,0.82,0.88\n"
        "random_forest,0.91,0.89,0.93\n"
        "neural_network,0.94,0.92,0.95\n"
    )

    return tmp_path


def _mock_embedder():
    """Create a mock Embedder that returns deterministic vectors."""
    embedder = MagicMock()
    dim = 64

    def embed_passages(texts):
        vecs = []
        for t in texts:
            rng = np.random.RandomState(hash(t) % 2**31)
            vec = rng.randn(dim).astype(np.float32)
            vec /= np.linalg.norm(vec)
            vecs.append(vec.tolist())
        return vecs

    def embed_query(query):
        rng = np.random.RandomState(hash(query) % 2**31)
        vec = rng.randn(dim).astype(np.float32)
        vec /= np.linalg.norm(vec)
        return vec.tolist()

    embedder.embed_passages.side_effect = embed_passages
    embedder.embed_query.side_effect = embed_query
    return embedder


class TestE2ESmoke:
    def test_ingest_search_export_reenrich(self, fixtures_dir, tmp_path):
        """Full pipeline: ingest 3 files → search → export → re-enrich."""
        data_dir = tmp_path / "data"
        settings = Settings(data_dir=data_dir, cleaning_enabled=True, checkpoint_enabled=False)

        mock_emb = _mock_embedder()

        # --- Step 1: Batch ingest with mocked embedder ---
        # Patch Embedder where it's imported: both in orchestrator and stage5
        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
        ):
            from ingestible.pipeline.batch import ingest_batch

            report = ingest_batch(
                str(fixtures_dir),
                settings,
                skip_enrichment=True,
                recursive=False,
            )

        assert report.succeeded == 3, (
            f"Expected 3 succeeded, got {report.succeeded}. Failures: {[r.error for r in report.results if r.error]}"
        )
        assert report.failed == 0

        # --- Step 2: Verify documents on disk ---
        from ingestible.pipeline.stage6_storage import list_documents, load_chunks

        docs = list_documents(settings)
        assert len(docs) == 3

        # Load chunks from each doc
        all_chunks: dict[str, ChunkSet] = {}
        for d in docs:
            doc_dir = settings.documents_dir / d["doc_id"]
            chunks = load_chunks(doc_dir)
            all_chunks[d["doc_id"]] = chunks
            assert len(chunks.l3_chunks) > 0, f"No passages for {d['doc_id']}"

        # --- Step 3: Corpus search with mocked embedder ---
        # The indexes on disk were built with mock embedder (64-dim),
        # so we also need to use the same mock for search queries
        from ingestible.search.corpus import CorpusSearcher

        searcher = CorpusSearcher(settings, embedder=mock_emb)
        response = searcher.search("machine learning", n_results=5)

        assert response.documents_searched == 3
        assert len(response.results) > 0

        # --- Step 4: Export one doc to JSONL ---
        from ingestible.export import export_document

        first_doc_id = docs[0]["doc_id"]
        first_chunks = all_chunks[first_doc_id]
        export_path = tmp_path / "export.jsonl"
        export_document(first_chunks, "jsonl", export_path, doc_title=docs[0].get("title", ""))

        assert export_path.exists()
        lines = export_path.read_text().strip().split("\n")
        assert len(lines) > 0
        # Each line should be valid JSON
        for line in lines:
            parsed = json.loads(line)
            assert "content" in parsed

        # --- Step 5: Re-enrich with mocked LLM ---
        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.re_enrich.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage4_enrichment.enrich_chunks") as mock_enrich,
        ):
            # Mock enrichment: add dummy summaries to L3 chunks
            async def fake_enrich(chunks, settings, **kwargs):
                for c in chunks.l3_chunks:
                    c.summary = f"Summary of {c.chunk_id}"
                return chunks

            mock_enrich.side_effect = fake_enrich

            from ingestible.pipeline.re_enrich import re_enrich

            re_doc_dir = re_enrich(first_doc_id, settings)

        # Verify re-enriched chunks have summaries
        re_chunks = load_chunks(re_doc_dir)
        for c in re_chunks.l3_chunks:
            assert c.summary.startswith("Summary of "), (
                f"Expected enriched summary, got: {c.summary}"
            )

        # --- Step 6: Re-search after enrichment ---
        searcher2 = CorpusSearcher(settings, embedder=mock_emb)
        response2 = searcher2.search("supervised learning", n_results=3)

        assert response2.documents_searched == 3
        assert len(response2.results) > 0

    def test_ingest_single_file(self, fixtures_dir, tmp_path):
        """Single file ingestion works end-to-end."""
        data_dir = tmp_path / "data"
        settings = Settings(data_dir=data_dir, checkpoint_enabled=False)

        mock_emb = _mock_embedder()

        with (
            patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
            patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
        ):
            from ingestible.pipeline.orchestrator import ingest

            doc_dir = ingest(
                fixtures_dir / "notes.md",
                settings,
                skip_enrichment=True,
            )

        assert doc_dir.exists()
        meta_path = doc_dir / "meta.json"
        assert meta_path.exists()

        meta = json.loads(meta_path.read_text())
        assert meta["title"] == "Machine Learning Notes"
        assert meta["total_pages"] == 1
