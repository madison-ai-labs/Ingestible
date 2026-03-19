"""WP 6.3 — API Endpoint Integration Tests.

FastAPI TestClient tests against all major endpoints.
Uses pre-populated fixture data dir and mocked Embedder.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage5_embedding import build_indexes
from ingestible.pipeline.stage6_storage import save_document


def _mock_embedder():
    """Create a mock Embedder with deterministic vectors."""
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


def _create_test_doc(settings: Settings, doc_id: str = "test-doc-abc123") -> Path:
    """Create a fully indexed test document in the data dir."""
    l3 = L3Chunk(
        chunk_id=f"{doc_id}-p0",
        content="Machine learning uses algorithms to learn from data and make predictions.",
        position=ChunkPosition(chapter="Introduction", section="Overview"),
        parent_section_id=f"{doc_id}-s1",
        summary="ML fundamentals overview.",
        keywords=["machine learning", "algorithms"],
    )
    l2 = L2Chunk(
        chunk_id=f"{doc_id}-s1",
        title="Overview",
        content="Overview of machine learning concepts.",
        parent_chapter_id=f"{doc_id}-ch1",
        children_ids=[l3.chunk_id],
    )
    l1 = L1Chunk(
        chunk_id=f"{doc_id}-ch1",
        title="Introduction",
        content="Introduction to ML.",
        children_ids=[l2.chunk_id],
    )
    l0 = L0Chunk(
        chunk_id=f"{doc_id}-L0",
        title="ML Handbook",
        total_pages=5,
        total_chapters=1,
        total_sections=1,
        total_passages=1,
    )
    chunks = ChunkSet(
        doc_id=doc_id, l0=l0, l1_chunks=[l1], l2_chunks=[l2], l3_chunks=[l3]
    )
    root = StructureNode(id=doc_id, title="ML Handbook", level=0)
    structure = DocumentStructure(doc_id=doc_id, title="ML Handbook", root=root)

    save_document(structure, chunks, settings, content_hash="abc123hash")

    doc_dir = settings.documents_dir / doc_id
    embedder = _mock_embedder()
    build_indexes(chunks, doc_dir, embedder)

    return doc_dir


@pytest.fixture
def api_setup(tmp_path):
    """Set up test data dir and return configured TestClient."""
    settings = Settings(data_dir=tmp_path)
    doc_dir = _create_test_doc(settings)
    mock_emb = _mock_embedder()

    # Patch the api module's singletons
    import ingestible.api as api_mod
    import ingestible.web as web_mod

    old_settings = api_mod._settings
    old_embedder = api_mod._embedder
    old_web_settings = web_mod._settings
    old_web_embedder = web_mod._embedder

    api_mod._settings = settings
    api_mod._embedder = mock_emb
    web_mod._settings = settings
    web_mod._embedder = mock_emb

    client = TestClient(api_mod.app)

    yield {
        "client": client,
        "settings": settings,
        "doc_id": "test-doc-abc123",
        "doc_dir": doc_dir,
        "mock_embedder": mock_emb,
    }

    # Restore
    api_mod._settings = old_settings
    api_mod._embedder = old_embedder
    web_mod._settings = old_web_settings
    web_mod._embedder = old_web_embedder


class TestHealthEndpoint:
    def test_health_returns_ok(self, api_setup):
        resp = api_setup["client"].get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["documents_count"] == 1


class TestDocumentsEndpoints:
    def test_list_documents(self, api_setup):
        resp = api_setup["client"].get("/documents")
        assert resp.status_code == 200
        docs = resp.json()
        assert len(docs) == 1
        assert docs[0]["doc_id"] == "test-doc-abc123"
        assert docs[0]["title"] == "ML Handbook"

    def test_get_document(self, api_setup):
        resp = api_setup["client"].get("/documents/test-doc-abc123")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "test-doc-abc123"
        assert data["title"] == "ML Handbook"
        assert data["total_pages"] == 5
        assert data["total_chunks"] == 1
        assert len(data["chapters"]) == 1

    def test_get_document_not_found(self, api_setup):
        resp = api_setup["client"].get("/documents/nonexistent")
        assert resp.status_code == 404

    def test_get_chunks(self, api_setup):
        resp = api_setup["client"].get("/documents/test-doc-abc123/chunks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "test-doc-abc123"
        assert len(data["l3_chunks"]) == 1

    def test_get_structure(self, api_setup):
        resp = api_setup["client"].get("/documents/test-doc-abc123/structure")
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "ML Handbook"

    def test_get_versions(self, api_setup):
        resp = api_setup["client"].get("/documents/test-doc-abc123/versions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == "test-doc-abc123"
        assert isinstance(data["versions"], list)


class TestSearchEndpoints:
    def test_document_search(self, api_setup):
        resp = api_setup["client"].post(
            "/documents/test-doc-abc123/search",
            json={"query": "machine learning", "n_results": 3},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert len(data["results"]) > 0

    def test_corpus_search(self, api_setup):
        resp = api_setup["client"].post(
            "/search",
            json={"query": "algorithms", "n_results": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert data["documents_searched"] >= 1


class TestIngestEndpoints:
    def test_ingest_small_markdown(self, api_setup):
        md_content = b"# Test\n\nHello world content for ingestion test."

        with patch(
            "ingestible.pipeline.stage5_embedding.Embedder",
            return_value=api_setup["mock_embedder"],
        ):
            resp = api_setup["client"].post(
                "/ingest",
                files={"file": ("test.md", io.BytesIO(md_content), "text/markdown")},
                data={"skip_enrichment": "true"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert "doc_id" in data
        assert data["title"] == "Test"
        assert data["enriched"] is False

    def test_ingest_stream_sse(self, api_setup):
        md_content = b"# Stream Test\n\nContent for SSE streaming test."

        with patch(
            "ingestible.pipeline.stage5_embedding.Embedder",
            return_value=api_setup["mock_embedder"],
        ):
            resp = api_setup["client"].post(
                "/ingest/stream",
                files={"file": ("stream.md", io.BytesIO(md_content), "text/markdown")},
                data={"skip_enrichment": "true"},
            )

        assert resp.status_code == 200
        # SSE format: "data: {...}\n\n"
        body = resp.text
        assert "data:" in body
        # Last event should have status=complete
        events = [
            line.replace("data: ", "")
            for line in body.strip().split("\n")
            if line.startswith("data:")
        ]
        assert len(events) > 0
        last = json.loads(events[-1])
        assert last["status"] == "complete"
        assert "doc_id" in last


class TestExportEndpoint:
    def test_export_jsonl(self, api_setup):
        resp = api_setup["client"].get(
            "/documents/test-doc-abc123/export?format=jsonl"
        )
        assert resp.status_code == 200
        # Should be JSONL content
        lines = resp.text.strip().split("\n")
        assert len(lines) > 0
        for line in lines:
            parsed = json.loads(line)
            assert "content" in parsed

    def test_export_invalid_format(self, api_setup):
        resp = api_setup["client"].get(
            "/documents/test-doc-abc123/export?format=xml"
        )
        assert resp.status_code == 400


class TestTokenEconomics:
    def test_economics_endpoint(self, api_setup):
        resp = api_setup["client"].get("/documents/test-doc-abc123/economics")
        assert resp.status_code == 200
        data = resp.json()
        assert "full_document_tokens" in data
        assert "l0_overview_tokens" in data
        assert "savings_percent" in data
