"""Tests for Stage 3b — Quality Validation."""

from __future__ import annotations

from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.pipeline.stage3b_validation import validate_chunks


def _make_chunk(chunk_id: str, content: str, section_id: str = "sec1") -> L3Chunk:
    return L3Chunk(
        chunk_id=chunk_id,
        content=content,
        parent_section_id=section_id,
        position=ChunkPosition(chapter="ch1", section=section_id, index=0),
    )


def _make_chunkset(l3_chunks: list[L3Chunk], l2_children: list[str] | None = None) -> ChunkSet:
    l0 = L0Chunk(
        chunk_id="test-L0",
        title="Test",
        total_passages=len(l3_chunks),
    )
    l2 = L2Chunk(
        chunk_id="sec1",
        title="Section 1",
        content="",
        parent_chapter_id="ch1",
        children_ids=l2_children or [c.chunk_id for c in l3_chunks],
    )
    return ChunkSet(doc_id="test", l0=l0, l2_chunks=[l2], l3_chunks=l3_chunks)


def test_empty_chunk_removal():
    """Empty chunks are removed from the result."""
    chunks = [
        _make_chunk("c1", "Real content here about machine learning."),
        _make_chunk("c2", ""),
        _make_chunk("c3", "   "),
        _make_chunk("c4", "More real content about deep learning research."),
    ]
    cs = _make_chunkset(chunks)
    result, report = validate_chunks(cs)
    assert len(result.l3_chunks) == 2
    assert report.removed_empty == 2
    assert report.total_l3 == 4


def test_token_stats_accuracy():
    """Token stats are computed correctly on remaining chunks."""
    chunks = [
        _make_chunk("c1", "Short text."),
        _make_chunk("c2", "Another piece of slightly longer content for testing purposes."),
    ]
    cs = _make_chunkset(chunks)
    result, report = validate_chunks(cs)
    assert report.token_min > 0
    assert report.token_max >= report.token_min
    assert report.token_mean > 0
    assert report.token_median > 0


def test_l0_total_updated():
    """l0.total_passages is updated after removal."""
    chunks = [
        _make_chunk("c1", "Content."),
        _make_chunk("c2", ""),
    ]
    cs = _make_chunkset(chunks)
    result, report = validate_chunks(cs)
    assert result.l0.total_passages == 1


def test_l2_children_cleaned():
    """l2.children_ids should not contain IDs of removed chunks."""
    chunks = [
        _make_chunk("c1", "Content A."),
        _make_chunk("c2", ""),
    ]
    cs = _make_chunkset(chunks, l2_children=["c1", "c2"])
    result, report = validate_chunks(cs)
    assert "c2" not in result.l2_chunks[0].children_ids
    assert "c1" in result.l2_chunks[0].children_ids


def test_all_removed_edge_case():
    """If all chunks are empty, result should have 0 chunks and valid report."""
    chunks = [_make_chunk("c1", ""), _make_chunk("c2", "  ")]
    cs = _make_chunkset(chunks)
    result, report = validate_chunks(cs)
    assert len(result.l3_chunks) == 0
    assert report.removed_empty == 2
    assert result.l0.total_passages == 0
    assert report.token_mean == 0.0


def test_no_removal_when_all_valid():
    """When all chunks have content, none are removed."""
    chunks = [
        _make_chunk("c1", "First valid chunk content here."),
        _make_chunk("c2", "Second valid chunk content here."),
    ]
    cs = _make_chunkset(chunks)
    result, report = validate_chunks(cs)
    assert len(result.l3_chunks) == 2
    assert report.removed_empty == 0
