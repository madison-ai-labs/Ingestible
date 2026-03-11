"""Tests for the CognitiveVault export adapter.

Validates the ChunkSet → CV bulk entries transformation without
hitting any external API. HTTP calls are tested with httpx mocking.

Run with:  pytest tests/test_cv_export.py -v
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest

from ingestible.adapters.cv_export import (
    CVConfig,
    ExportResult,
    chunkset_to_entries,
    export_to_cv,
    _source_path,
)
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_chunkset() -> ChunkSet:
    """Build a ChunkSet with all levels populated."""
    return ChunkSet(
        doc_id="test-doc",
        l0=L0Chunk(
            chunk_id="test-doc-L0",
            title="Test Document",
            author="Author",
            domain="testing",
            toc_summary="- Chapter 1",
            key_concepts=["chunking", "export"],
            total_pages=10,
            total_chapters=1,
            total_sections=1,
            total_passages=2,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id="ch1",
                title="Chapter 1",
                content="Chapter overview.",
                page_start=1,
                page_end=10,
                children_ids=["sec1"],
                chapter_summary="Covers export.",
                main_topics=["export", "adapters"],
            ),
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="sec1",
                title="Section 1",
                content="Section content.",
                parent_chapter_id="ch1",
                children_ids=["p0", "p1"],
                section_summary="Export basics.",
                concepts_introduced=["adapter pattern"],
            ),
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="p0",
                content="Passage zero content.",
                position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                parent_section_id="sec1",
                position_in_section="first",
                context_prefix="Chapter 1 > Section 1:",
                summary="First passage about export.",
                concepts=["export"],
                keywords=["export", "adapter"],
                difficulty_level="beginner",
            ),
            L3Chunk(
                chunk_id="p1",
                content="Passage one content.",
                position=ChunkPosition(chapter="ch1", section="sec1", index=1),
                parent_section_id="sec1",
                position_in_section="last",
                summary="Second passage.",
                keywords=["integration"],
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 1. Transformation: ChunkSet → CV entries
# ---------------------------------------------------------------------------

class TestChunksetToEntries:
    def test_produces_correct_count(self):
        """1 L0 + 1 L1 + 1 L2 + 2 L3 = 5 entries."""
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        assert len(entries) == 5

    def test_entries_ordered_by_level(self):
        """Entries must be ordered L0 → L1 → L2 → L3."""
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        levels = [e["chunkLevel"] for e in entries]
        assert levels == [0, 1, 2, 3, 3]

    def test_l0_entry_shape(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l0 = entries[0]

        assert l0["title"] == "Test Document"
        assert l0["chunkLevel"] == 0
        assert l0["chunkOrder"] == 0
        assert l0["entryType"] == "DOCUMENT"
        assert l0["sourcePath"] == "ingest:test-doc/test-doc-L0"
        assert "parentSourcePath" not in l0
        assert isinstance(l0["checksum"], str)
        assert len(l0["checksum"]) == 64
        assert "Author" in l0["content"]
        assert "chunking" in l0["tags"]

    def test_l1_references_l0_as_parent(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l1 = entries[1]

        assert l1["chunkLevel"] == 1
        assert l1["parentSourcePath"] == "ingest:test-doc/test-doc-L0"

    def test_l2_references_l1_as_parent(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l2 = entries[2]

        assert l2["chunkLevel"] == 2
        assert l2["parentSourcePath"] == "ingest:test-doc/ch1"

    def test_l3_references_l2_as_parent(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l3_entries = [e for e in entries if e["chunkLevel"] == 3]

        for l3 in l3_entries:
            assert l3["parentSourcePath"] == "ingest:test-doc/sec1"

    def test_l3_uses_summary_as_title(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l3 = entries[3]  # p0

        assert l3["title"] == "First passage about export."

    def test_l3_without_summary_uses_chunk_id(self):
        chunks = _make_chunkset()
        chunks.l3_chunks[1].summary = ""
        entries = chunkset_to_entries(chunks)
        l3 = entries[4]  # p1

        assert l3["title"] == "Passage p1"

    def test_context_prefix_prepended_to_l3_content(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l3 = entries[3]  # p0 has context_prefix

        assert l3["content"].startswith("Chapter 1 > Section 1:")

    def test_source_paths_are_unique(self):
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        paths = [e["sourcePath"] for e in entries]
        assert len(paths) == len(set(paths))

    def test_checksums_are_deterministic(self):
        chunks = _make_chunkset()
        entries_a = chunkset_to_entries(chunks)
        entries_b = chunkset_to_entries(chunks)

        for a, b in zip(entries_a, entries_b):
            assert a["checksum"] == b["checksum"]

    def test_l3_enrichment_fields_included(self):
        """L3 entries with enrichment data include an enrichment dict."""
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l3 = entries[3]  # p0 has summary, concepts, keywords

        assert "enrichment" in l3
        assert l3["enrichment"]["summary"] == "First passage about export."
        assert "hypotheticalQuestions" not in l3["enrichment"]  # empty list → omitted
        assert "export" in l3["enrichment"]["conceptTags"]
        assert "adapter" in l3["enrichment"]["conceptTags"]

    def test_l2_enrichment_fields_included(self):
        """L2 entries with section_summary include enrichment."""
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l2 = entries[2]

        assert "enrichment" in l2
        assert l2["enrichment"]["summary"] == "Export basics."
        assert "adapter pattern" in l2["enrichment"]["conceptTags"]

    def test_no_enrichment_when_empty(self):
        """Entries without enrichment data don't include the key."""
        chunks = _make_chunkset()
        entries = chunkset_to_entries(chunks)
        l0 = entries[0]

        assert "enrichment" not in l0

    def test_empty_chunkset_produces_one_entry(self):
        """Even an empty document has an L0."""
        chunks = ChunkSet(
            doc_id="empty",
            l0=L0Chunk(chunk_id="empty-L0", title="Empty"),
        )
        entries = chunkset_to_entries(chunks)
        assert len(entries) == 1
        assert entries[0]["chunkLevel"] == 0


# ---------------------------------------------------------------------------
# 2. HTTP export (mocked)
# ---------------------------------------------------------------------------

class TestExportToCv:
    def test_successful_export(self, monkeypatch):
        chunks = _make_chunkset()
        config = CVConfig(
            base_url="https://cv.test",
            api_key="test-key",
            vault_id="vault-1",
        )

        def mock_post(self, url, **kwargs):
            assert "/api/v1/vaults/vault-1/entries/bulk" in url
            assert kwargs["headers"]["Authorization"] == "Bearer test-key"
            body = kwargs["json"]
            assert len(body["entries"]) == 5
            assert body["deleteRemoved"] is False

            resp = httpx.Response(
                200,
                json={"created": 5, "updated": 0, "unchanged": 0, "deleted": 0},
                request=httpx.Request("POST", url),
            )
            return resp

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        result = export_to_cv(chunks, config)
        assert result.doc_id == "test-doc"
        assert result.created == 5
        assert result.error is None

    def test_http_error_returns_error_result(self, monkeypatch):
        chunks = _make_chunkset()
        config = CVConfig(
            base_url="https://cv.test",
            api_key="bad-key",
            vault_id="vault-1",
        )

        def mock_post(self, url, **kwargs):
            resp = httpx.Response(
                401,
                json={"detail": "Missing or invalid API key"},
                request=httpx.Request("POST", url),
            )
            resp.raise_for_status()

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        result = export_to_cv(chunks, config)
        assert result.error is not None
        assert "401" in result.error

    def test_connection_error_returns_error_result(self, monkeypatch):
        chunks = _make_chunkset()
        config = CVConfig(
            base_url="https://cv.unreachable",
            api_key="key",
            vault_id="vault-1",
        )

        def mock_post(self, url, **kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        result = export_to_cv(chunks, config)
        assert result.error is not None
        assert "connection" in result.error.lower()

    def test_delete_removed_flag_passed(self, monkeypatch):
        chunks = _make_chunkset()
        config = CVConfig(
            base_url="https://cv.test",
            api_key="key",
            vault_id="vault-1",
        )

        captured = {}

        def mock_post(self, url, **kwargs):
            captured["deleteRemoved"] = kwargs["json"]["deleteRemoved"]
            return httpx.Response(
                200,
                json={"created": 0, "updated": 0, "unchanged": 5, "deleted": 0},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)

        export_to_cv(chunks, config, delete_removed=True)
        assert captured["deleteRemoved"] is True
