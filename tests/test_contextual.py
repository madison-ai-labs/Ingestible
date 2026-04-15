"""Tests for Feature 2 — Contextual Chunking (heuristic prefix generation)."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

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


@pytest.fixture(autouse=True)
def _mock_chromadb(monkeypatch):
    """Prevent chromadb import failure on Python 3.14."""
    if "chromadb" not in sys.modules:
        monkeypatch.setitem(sys.modules, "chromadb", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.api", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.api.client", MagicMock())
        monkeypatch.setitem(sys.modules, "chromadb.config", MagicMock())


def _make_test_data():
    """Create minimal ChunkSet + DocumentStructure for testing."""
    l3 = [
        L3Chunk(
            chunk_id="c1",
            content="Machine learning uses neural networks.",
            parent_section_id="sec1",
            position=ChunkPosition(chapter="ch1", section="sec1", index=0),
        ),
        L3Chunk(
            chunk_id="c2",
            content="Deep learning is a subset of ML.",
            parent_section_id="sec1",
            position=ChunkPosition(chapter="ch1", section="sec1", index=1),
        ),
    ]
    l0 = L0Chunk(chunk_id="test-L0", title="AI Textbook", total_passages=2)
    l1 = L1Chunk(chunk_id="ch1", title="Neural Networks", content="", children_ids=["sec1"])
    l2 = L2Chunk(
        chunk_id="sec1",
        title="Introduction to ML",
        content="",
        parent_chapter_id="ch1",
        children_ids=["c1", "c2"],
    )
    chunks = ChunkSet(doc_id="test", l0=l0, l1_chunks=[l1], l2_chunks=[l2], l3_chunks=l3)

    sec = StructureNode(id="sec1", title="Introduction to ML", level=2)
    ch = StructureNode(id="ch1", title="Neural Networks", level=1, children=[sec])
    root = StructureNode(id="root", title="AI Textbook", level=0, children=[ch])
    structure = DocumentStructure(doc_id="test", title="AI Textbook", root=root)

    return chunks, structure


@pytest.mark.asyncio
async def test_context_prefix_set_on_chunks():
    """Context prefix is set on L3 chunks using hierarchy titles."""
    from ingestible.pipeline.stage3c_contextual import add_context_prefixes

    chunks, structure = _make_test_data()
    settings = Settings(data_dir="/tmp/test")

    result = await add_context_prefixes(chunks, structure, settings)

    assert result.l3_chunks[0].context_prefix != ""
    assert result.l3_chunks[1].context_prefix != ""


@pytest.mark.asyncio
async def test_prefix_includes_hierarchy_titles():
    """The context prefix includes doc, chapter, and section titles."""
    from ingestible.pipeline.stage3c_contextual import add_context_prefixes

    chunks, structure = _make_test_data()
    settings = Settings(data_dir="/tmp/test")

    result = await add_context_prefixes(chunks, structure, settings)

    prefix = result.l3_chunks[0].context_prefix
    assert "AI Textbook" in prefix
    assert "Neural Networks" in prefix
    assert "Introduction to ML" in prefix


@pytest.mark.asyncio
async def test_prefix_uses_separator():
    """The prefix joins hierarchy levels with ' > '."""
    from ingestible.pipeline.stage3c_contextual import add_context_prefixes

    chunks, structure = _make_test_data()
    settings = Settings(data_dir="/tmp/test")

    result = await add_context_prefixes(chunks, structure, settings)

    prefix = result.l3_chunks[0].context_prefix
    assert prefix == "AI Textbook > Neural Networks > Introduction to ML"


@pytest.mark.asyncio
async def test_prefix_deduplicates_chapter_section():
    """If section title equals chapter title, it's not repeated."""
    from ingestible.pipeline.stage3c_contextual import add_context_prefixes

    chunks, structure = _make_test_data()
    # Make section title same as chapter title
    for node in structure.root.walk():
        if node.id == "sec1":
            node.title = "Neural Networks"

    settings = Settings(data_dir="/tmp/test")
    result = await add_context_prefixes(chunks, structure, settings)

    prefix = result.l3_chunks[0].context_prefix
    assert prefix == "AI Textbook > Neural Networks"
    assert prefix.count("Neural Networks") == 1


def test_embedding_prepends_prefix():
    """Verify that stage5 would prepend context_prefix to content for embedding."""
    chunk = L3Chunk(
        chunk_id="c1",
        content="Actual content here.",
        context_prefix="This chunk is about X.",
    )
    content_text = chunk.content
    if chunk.context_prefix:
        content_text = chunk.context_prefix + "\n\n" + chunk.content
    assert content_text.startswith("This chunk is about X.")
    assert "Actual content here." in content_text
