"""Tests for WP 2.2 — Re-enrichment without re-parsing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from ingestible.config import Settings
from ingestible.models.chunks import ChunkPosition, ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.re_enrich import re_enrich
from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
from ingestible.pipeline.stage6_storage import load_chunks, save_document


def _setup_doc(tmp_path: Path, doc_id: str = "test-doc") -> Settings:
    """Create a minimal ingested document."""
    settings = Settings(data_dir=tmp_path)

    l3 = L3Chunk(
        chunk_id=f"{doc_id}-c1",
        content="Machine learning is a subset of AI.",
        summary="Old summary that should be cleared",
        concepts=["ml"],
        position=ChunkPosition(chapter="Ch1", section="Sec1"),
        parent_section_id=f"{doc_id}-s1",
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
        title="Test Doc",
        total_pages=1,
        total_chapters=1,
        total_sections=1,
        total_passages=1,
    )
    chunks = ChunkSet(doc_id=doc_id, l0=l0, l1_chunks=[l1], l2_chunks=[l2], l3_chunks=[l3])
    root = StructureNode(id=doc_id, title="Test Doc", level=0)
    structure = DocumentStructure(doc_id=doc_id, title="Test Doc", root=root)

    save_document(structure, chunks, settings, content_hash="abc123")

    # Build indexes
    embedder = Embedder(settings)
    doc_dir = settings.documents_dir / doc_id
    build_indexes(chunks, doc_dir, embedder)

    return settings


def test_re_enrich_clears_old_enrichment(tmp_path):
    """Re-enrichment clears old enrichment fields before re-running.

    Mocks enrich_chunks to raise so the test controls failure independently
    of whether API keys are present in the environment.
    """
    settings = _setup_doc(tmp_path)
    doc_id = "test-doc"

    # Verify old enrichment exists
    doc_dir = settings.documents_dir / doc_id
    old_chunks = load_chunks(doc_dir)
    assert old_chunks.l3_chunks[0].summary == "Old summary that should be cleared"

    # Force enrichment to fail so we can verify fields were cleared beforehand
    with patch(
        "ingestible.pipeline.stage4_enrichment.enrich_chunks", side_effect=RuntimeError("no keys")
    ):
        result_dir = re_enrich(doc_id, settings)

    assert result_dir.exists()

    # Old summary was cleared before enrichment ran; failure left it empty
    new_chunks = load_chunks(result_dir)
    assert new_chunks.l3_chunks[0].content == "Machine learning is a subset of AI."
    assert new_chunks.l3_chunks[0].summary in ("", "[enrichment failed]")


def test_re_enrich_preserves_content(tmp_path):
    """Re-enrichment doesn't modify chunk content."""
    settings = _setup_doc(tmp_path)
    result_dir = re_enrich("test-doc", settings)
    chunks = load_chunks(result_dir)
    assert chunks.l3_chunks[0].content == "Machine learning is a subset of AI."
    assert chunks.doc_id == "test-doc"


def test_re_enrich_missing_doc(tmp_path):
    """Re-enrichment raises for missing document."""
    settings = Settings(data_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="not found"):
        re_enrich("nonexistent-doc", settings)


def test_re_enrich_preserves_structure(tmp_path):
    """Re-enrichment preserves the document hierarchy."""
    settings = _setup_doc(tmp_path)
    result_dir = re_enrich("test-doc", settings)
    chunks = load_chunks(result_dir)

    assert len(chunks.l1_chunks) == 1
    assert len(chunks.l2_chunks) == 1
    assert len(chunks.l3_chunks) == 1
    assert chunks.l1_chunks[0].title == "Chapter 1"
