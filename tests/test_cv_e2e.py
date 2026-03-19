"""WP 7.3 — CognitiveVault E2E Test.

Unlike test_cv_export.py (manually constructed ChunkSet), this test goes through
the real pipeline: ingest .md fixture → load chunks → export_to_cv() with mocked
httpx → assert correct L0→L1→L2→L3 parent chain in request body.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import numpy as np
import pytest

from ingestible.adapters.cv_export import CVConfig, export_to_cv
from ingestible.config import Settings
from ingestible.pipeline.stage6_storage import load_chunks


def _mock_embedder():
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


@pytest.fixture
def ingested_doc(tmp_path):
    """Ingest a real .md file through the pipeline and return (settings, doc_dir)."""
    md_file = tmp_path / "cv_test.md"
    md_file.write_text(
        "# CognitiveVault Integration\n\n"
        "## Architecture\n\n"
        "The system uses a hierarchical chunking approach with four levels. "
        "L0 represents the document overview, L1 chapters, L2 sections, "
        "and L3 passages.\n\n"
        "## Implementation\n\n"
        "Each level maps to a CognitiveVault entry with parent references "
        "maintaining the hierarchy chain from document to passage.\n"
    )

    settings = Settings(data_dir=tmp_path / "data", checkpoint_enabled=False)
    mock_emb = _mock_embedder()

    with (
        patch("ingestible.pipeline.orchestrator.Embedder", return_value=mock_emb),
        patch("ingestible.pipeline.stage5_embedding.Embedder", return_value=mock_emb),
    ):
        from ingestible.pipeline.orchestrator import ingest

        doc_dir = ingest(md_file, settings, skip_enrichment=True)

    return settings, doc_dir


class TestCognitiveVaultE2E:
    def test_pipeline_to_cv_export_parent_chain(self, ingested_doc, monkeypatch):
        """Ingest real .md → load chunks → export to CV → verify parent chain."""
        settings, doc_dir = ingested_doc

        chunks = load_chunks(doc_dir)
        assert len(chunks.l1_chunks) > 0
        assert len(chunks.l3_chunks) > 0

        config = CVConfig(
            base_url="https://cv.test",
            api_key="test-key",
            vault_id="vault-1",
        )

        captured_entries = []

        def mock_post(self, url, **kwargs):
            captured_entries.extend(kwargs["json"]["entries"])
            return httpx.Response(
                200,
                json={"created": len(kwargs["json"]["entries"]), "updated": 0, "unchanged": 0, "deleted": 0},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        result = export_to_cv(chunks, config)
        assert result.error is None
        assert result.created > 0

        # --- Verify hierarchy ---
        by_level = {}
        for e in captured_entries:
            by_level.setdefault(e["chunkLevel"], []).append(e)

        # Must have L0, L1, L2, L3
        assert 0 in by_level, "Missing L0 entries"
        assert 1 in by_level, "Missing L1 entries"
        assert 2 in by_level, "Missing L2 entries"
        assert 3 in by_level, "Missing L3 entries"

        # L0 has no parent
        l0 = by_level[0][0]
        assert "parentSourcePath" not in l0

        # Build sourcePath → entry map
        by_path = {e["sourcePath"]: e for e in captured_entries}

        # L1 → parent is L0
        for l1 in by_level[1]:
            assert l1["parentSourcePath"] == l0["sourcePath"], (
                f"L1 parent should be L0, got {l1['parentSourcePath']}"
            )

        # L2 → parent is an L1
        l1_paths = {e["sourcePath"] for e in by_level[1]}
        for l2 in by_level[2]:
            assert l2["parentSourcePath"] in l1_paths, (
                f"L2 parent should be L1, got {l2['parentSourcePath']}"
            )

        # L3 → parent is an L2
        l2_paths = {e["sourcePath"] for e in by_level[2]}
        for l3 in by_level[3]:
            assert l3["parentSourcePath"] in l2_paths, (
                f"L3 parent should be L2, got {l3['parentSourcePath']}"
            )

    def test_exported_entries_have_content(self, ingested_doc, monkeypatch):
        """All exported entries have non-empty content."""
        settings, doc_dir = ingested_doc
        chunks = load_chunks(doc_dir)

        config = CVConfig(
            base_url="https://cv.test",
            api_key="test-key",
            vault_id="vault-1",
        )

        captured_entries = []

        def mock_post(self, url, **kwargs):
            captured_entries.extend(kwargs["json"]["entries"])
            return httpx.Response(
                200,
                json={"created": len(kwargs["json"]["entries"]), "updated": 0, "unchanged": 0, "deleted": 0},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        export_to_cv(chunks, config)

        for entry in captured_entries:
            assert entry.get("title"), f"Entry {entry['sourcePath']} has empty title"
            assert entry.get("checksum"), f"Entry {entry['sourcePath']} has empty checksum"
            # L0 and L3 must have content; L1/L2 may be empty (structure-only chapters)
            if entry["chunkLevel"] in (0, 3):
                assert entry.get("content"), f"L{entry['chunkLevel']} entry {entry['sourcePath']} has empty content"

    def test_source_paths_are_all_unique(self, ingested_doc, monkeypatch):
        """All sourcePaths across all entries must be unique."""
        settings, doc_dir = ingested_doc
        chunks = load_chunks(doc_dir)

        config = CVConfig(
            base_url="https://cv.test",
            api_key="test-key",
            vault_id="vault-1",
        )

        captured_entries = []

        def mock_post(self, url, **kwargs):
            captured_entries.extend(kwargs["json"]["entries"])
            return httpx.Response(
                200,
                json={"created": len(kwargs["json"]["entries"]), "updated": 0, "unchanged": 0, "deleted": 0},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        export_to_cv(chunks, config)

        paths = [e["sourcePath"] for e in captured_entries]
        assert len(paths) == len(set(paths)), f"Duplicate sourcePaths found: {[p for p in paths if paths.count(p) > 1]}"
