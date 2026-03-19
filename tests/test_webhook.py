"""Tests for POST /webhooks/cv endpoint (P2).

Verifies HMAC signature validation, sourcePath parsing, chunk content
update, and selective re-enrichment trigger.
"""

from __future__ import annotations

import hashlib
import hmac
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
from ingestible.pipeline.stage6_storage import save_document, load_chunks


WEBHOOK_SECRET = "test-webhook-secret-42"


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


def _create_test_doc(settings: Settings, doc_id: str = "test-doc-wh") -> Path:
    l3 = L3Chunk(
        chunk_id=f"{doc_id}-p0",
        content="Original chunk content.",
        content_hash=hashlib.sha256(b"Original chunk content.").hexdigest(),
        position=ChunkPosition(chapter="Ch1", section="Sec1"),
        parent_section_id=f"{doc_id}-s1",
        summary="Original summary",
        concepts=["original"],
    )
    l2 = L2Chunk(
        chunk_id=f"{doc_id}-s1",
        title="Section 1",
        content="Section content",
        parent_chapter_id=f"{doc_id}-ch1",
        children_ids=[l3.chunk_id],
    )
    l1 = L1Chunk(
        chunk_id=f"{doc_id}-ch1",
        title="Chapter 1",
        content="Chapter content",
        children_ids=[l2.chunk_id],
    )
    l0 = L0Chunk(
        chunk_id=f"{doc_id}-L0",
        title="Webhook Test Doc",
        total_pages=1,
        total_chapters=1,
        total_sections=1,
        total_passages=1,
    )
    chunks = ChunkSet(
        doc_id=doc_id, l0=l0, l1_chunks=[l1], l2_chunks=[l2], l3_chunks=[l3],
    )
    root = StructureNode(id=doc_id, title="Webhook Test Doc", level=0)
    structure = DocumentStructure(doc_id=doc_id, title="Webhook Test Doc", root=root)
    save_document(structure, chunks, settings, content_hash="wh-hash")

    doc_dir = settings.documents_dir / doc_id
    embedder = _mock_embedder()
    build_indexes(chunks, doc_dir, embedder)
    return doc_dir


def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.fixture
def webhook_setup(tmp_path):
    """Set up test data dir and return configured TestClient for webhook tests."""
    settings = Settings(data_dir=tmp_path)
    doc_id = "test-doc-wh"
    doc_dir = _create_test_doc(settings, doc_id)
    mock_emb = _mock_embedder()

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
        "doc_id": doc_id,
        "doc_dir": doc_dir,
    }

    api_mod._settings = old_settings
    api_mod._embedder = old_embedder
    web_mod._settings = old_web_settings
    web_mod._embedder = old_web_embedder


class TestWebhookSignature:
    def test_missing_secret_returns_500(self, webhook_setup):
        body = json.dumps({"event": "entry.updated", "payload": {}}).encode()
        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": ""}, clear=False):
            resp = webhook_setup["client"].post(
                "/webhooks/cv",
                content=body,
                headers={"X-Webhook-Signature": "anything"},
            )
        assert resp.status_code == 500
        assert "not configured" in resp.json()["detail"]

    def test_invalid_signature_returns_401(self, webhook_setup):
        body = json.dumps({"event": "entry.updated", "payload": {}}).encode()
        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": WEBHOOK_SECRET}, clear=False):
            resp = webhook_setup["client"].post(
                "/webhooks/cv",
                content=body,
                headers={"X-Webhook-Signature": "bad-signature"},
            )
        assert resp.status_code == 401

    def test_valid_signature_accepted(self, webhook_setup):
        """Valid signature + non-ingest sourcePath → ignored (but accepted)."""
        payload = {
            "event": "entry.updated",
            "payload": {
                "entryId": "e1",
                "sourcePath": "manual:something",
                "content": "x",
                "checksum": "abc",
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body, WEBHOOK_SECRET)

        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": WEBHOOK_SECRET}, clear=False):
            resp = webhook_setup["client"].post(
                "/webhooks/cv",
                content=body,
                headers={"X-Webhook-Signature": sig},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"


class TestWebhookChunkUpdate:
    def test_updates_chunk_content(self, webhook_setup):
        """Webhook updates chunk content on disk and stores cv_checksum."""
        doc_id = webhook_setup["doc_id"]
        chunk_id = f"{doc_id}-p0"
        new_content = "Updated content from CV."

        payload = {
            "event": "entry.updated",
            "payload": {
                "entryId": "cv-entry-1",
                "sourcePath": f"ingest:{doc_id}/{chunk_id}",
                "content": new_content,
                "checksum": "cv-checksum-xyz",
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body, WEBHOOK_SECRET)

        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": WEBHOOK_SECRET}, clear=False):
            # Patch re_enrich to avoid needing real LLM keys
            with patch("ingestible.pipeline.re_enrich.re_enrich") as mock_re_enrich:
                resp = webhook_setup["client"].post(
                    "/webhooks/cv",
                    content=body,
                    headers={"X-Webhook-Signature": sig},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["doc_id"] == doc_id
        assert data["chunk_id"] == chunk_id

        # Verify chunk file was updated on disk
        chunks = load_chunks(webhook_setup["doc_dir"])
        target = next(c for c in chunks.l3_chunks if c.chunk_id == chunk_id)
        assert target.content == new_content
        assert target.content_hash == hashlib.sha256(new_content.encode()).hexdigest()

        # Verify cv_checksum stored in meta
        meta_path = webhook_setup["doc_dir"] / "meta.json"
        meta = json.loads(meta_path.read_text())
        assert meta["cv_checksums"][chunk_id] == "cv-checksum-xyz"

        # Verify re_enrich was called with correct args
        mock_re_enrich.assert_called_once_with(
            doc_id, webhook_setup["settings"], changed_chunk_ids={chunk_id},
        )

    def test_nonexistent_doc_returns_404(self, webhook_setup):
        payload = {
            "event": "entry.updated",
            "payload": {
                "entryId": "e1",
                "sourcePath": "ingest:nonexistent-doc/chunk-1",
                "content": "x",
                "checksum": "abc",
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body, WEBHOOK_SECRET)

        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": WEBHOOK_SECRET}, clear=False):
            resp = webhook_setup["client"].post(
                "/webhooks/cv",
                content=body,
                headers={"X-Webhook-Signature": sig},
            )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_nonexistent_chunk_returns_404(self, webhook_setup):
        doc_id = webhook_setup["doc_id"]
        payload = {
            "event": "entry.updated",
            "payload": {
                "entryId": "e1",
                "sourcePath": f"ingest:{doc_id}/nonexistent-chunk",
                "content": "x",
                "checksum": "abc",
            },
        }
        body = json.dumps(payload).encode()
        sig = _sign(body, WEBHOOK_SECRET)

        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": WEBHOOK_SECRET}, clear=False):
            resp = webhook_setup["client"].post(
                "/webhooks/cv",
                content=body,
                headers={"X-Webhook-Signature": sig},
            )
        assert resp.status_code == 404
        assert "chunk" in resp.json()["detail"].lower()

    def test_non_update_event_ignored(self, webhook_setup):
        payload = {"event": "entry.created", "payload": {}}
        body = json.dumps(payload).encode()
        sig = _sign(body, WEBHOOK_SECRET)

        with patch.dict("os.environ", {"INGEST_WEBHOOK_SECRET": WEBHOOK_SECRET}, clear=False):
            resp = webhook_setup["client"].post(
                "/webhooks/cv",
                content=body,
                headers={"X-Webhook-Signature": sig},
            )
        assert resp.status_code == 200
        assert resp.json()["status"] == "ignored"
