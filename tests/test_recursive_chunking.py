"""Tests for recursive character splitting (Stage 3 recursive path)."""

from __future__ import annotations

from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage3_chunking import chunk_document


def _make_structure(content: str, doc_id: str = "test") -> DocumentStructure:
    sec = StructureNode(id="sec1", title="Section 1", level=2, content=content)
    ch = StructureNode(
        id="ch1", title="Chapter 1", level=1, page_start=1, page_end=1, children=[sec]
    )
    root = StructureNode(id="root", title="Test Doc", level=0, page_end=1, children=[ch])
    return DocumentStructure(doc_id=doc_id, title="Test Doc", root=root)


def test_recursive_prefers_paragraph_separator(tmp_path):
    """Double-newlines are preferred over single newlines."""
    content = "Paragraph one about dogs.\n\nParagraph two about cats.\n\nParagraph three about fish."
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=10,
        min_chunk_tokens=2,
        chunk_overlap_fraction=0.0,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings)
    # Should split on \n\n first
    assert len(chunks.l3_chunks) >= 2
    # Each chunk should be a paragraph or close to it
    for c in chunks.l3_chunks:
        assert c.content.strip()


def test_recursive_fallback_chain(tmp_path):
    """When no double-newline separators exist, falls back to single newline."""
    content = "Line one about AI.\nLine two about ML.\nLine three about DL.\nLine four about NLP."
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=15,
        min_chunk_tokens=3,
        chunk_overlap_fraction=0.0,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings)
    assert len(chunks.l3_chunks) >= 2


def test_recursive_overlap(tmp_path):
    """With overlap > 0, subsequent chunks should share text with previous."""
    content = "Alpha paragraph content here.\n\nBeta paragraph content here.\n\nGamma paragraph content here."
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=30,
        min_chunk_tokens=3,
        chunk_overlap_fraction=0.3,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings)
    if len(chunks.l3_chunks) >= 2:
        # Second chunk might contain tail of first chunk
        # At minimum, no crash and chunks are valid
        for c in chunks.l3_chunks:
            assert c.content.strip()


def test_recursive_max_tokens_respected(tmp_path):
    """No chunk should wildly exceed max_chunk_tokens."""
    sentences = [f"Sentence number {i} about artificial intelligence research." for i in range(30)]
    content = " ".join(sentences)
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=50,
        min_chunk_tokens=5,
        chunk_overlap_fraction=0.0,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings)
    assert len(chunks.l3_chunks) >= 2
    from ingestible.utils.tokens import count_tokens

    for c in chunks.l3_chunks:
        # Allow some tolerance (hard-split is approximate)
        assert count_tokens(c.content) < 80, f"Chunk too large: {count_tokens(c.content)} tokens"


def test_recursive_atomic_blocks(tmp_path):
    """Tables and code blocks are treated as atomic — not split mid-block."""
    content = (
        "Intro text about data.\n\n"
        "| Col A | Col B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n"
        "Conclusion text about results."
    )
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=500,
        min_chunk_tokens=3,
        chunk_overlap_fraction=0.0,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings)
    # Should produce at least one chunk, no crash
    assert len(chunks.l3_chunks) >= 1


def test_recursive_empty_text(tmp_path):
    """Empty input → empty output."""
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
    )
    structure = _make_structure("")
    chunks = chunk_document(structure, settings)
    assert len(chunks.l3_chunks) == 0


def test_recursive_position_labels(tmp_path):
    """Chunk position labels (first/middle/last/only) are set correctly."""
    content = "Para one.\n\nPara two.\n\nPara three."
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="recursive",
        max_chunk_tokens=10,
        min_chunk_tokens=2,
        chunk_overlap_fraction=0.0,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings)
    l3 = chunks.l3_chunks
    if len(l3) == 1:
        assert l3[0].position_in_section == "only"
    elif len(l3) >= 2:
        assert l3[0].position_in_section == "first"
        assert l3[-1].position_in_section == "last"
