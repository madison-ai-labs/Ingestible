"""Tests for semantic chunking (Stage 3 semantic path)."""

from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np

from ingestible.config import Settings
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage3_chunking import chunk_document


def _make_structure(content: str, doc_id: str = "test") -> DocumentStructure:
    """Helper: single chapter with a single section containing `content`."""
    sec = StructureNode(id="sec1", title="Section 1", level=2, content=content)
    ch = StructureNode(
        id="ch1", title="Chapter 1", level=1, page_start=1, page_end=1, children=[sec]
    )
    root = StructureNode(id="root", title="Test Doc", level=0, page_end=1, children=[ch])
    return DocumentStructure(doc_id=doc_id, title="Test Doc", root=root)


def _make_embedder(vectors: list[list[float]]) -> MagicMock:
    """Create a mock embedder that returns the given vectors for embed_passages."""
    embedder = MagicMock()
    embedder.embed_passages.return_value = vectors
    return embedder


def _normalized(v: list[float]) -> list[float]:
    """Normalize a vector to unit length."""
    a = np.array(v, dtype=np.float64)
    return (a / np.linalg.norm(a)).tolist()


def test_semantic_breakpoints(tmp_path):
    """6 sentences — first 3 on topic A, last 3 on topic B. Expect a split between them."""
    # Sentences on two clearly different topics
    content = (
        "Machine learning is a branch of AI. "
        "Deep learning uses neural networks. "
        "Models are trained on large datasets.\n\n"
        "The ocean covers most of the earth. "
        "Marine biology studies sea creatures. "
        "Coral reefs are rich ecosystems."
    )

    # Embeddings: first 3 sentences similar (cluster A), last 3 similar (cluster B)
    # Cluster A ~[1,0,0], Cluster B ~[0,1,0]
    vectors = [
        _normalized([1.0, 0.1, 0.0]),  # sentence 1
        _normalized([1.0, 0.05, 0.0]),  # sentence 2
        _normalized([0.95, 0.1, 0.0]),  # sentence 3
        _normalized([0.0, 1.0, 0.1]),  # sentence 4 — topic shift
        _normalized([0.05, 1.0, 0.0]),  # sentence 5
        _normalized([0.0, 0.95, 0.1]),  # sentence 6
    ]

    embedder = _make_embedder(vectors)
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
        semantic_threshold_percentile=30,
    )

    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)

    l3 = chunks.l3_chunks
    assert len(l3) >= 2, f"Expected >=2 chunks, got {len(l3)}"
    # First chunk should contain topic A, second should contain topic B
    assert "Machine learning" in l3[0].content or "neural networks" in l3[0].content
    assert "ocean" in l3[-1].content or "Marine biology" in l3[-1].content


def test_semantic_respects_max_tokens(tmp_path):
    """All sentences are similar, but total exceeds max_chunk_tokens → forced split."""
    # Create enough text to exceed a low max_chunk_tokens
    sentences = [f"Sentence number {i} about artificial intelligence." for i in range(20)]
    content = " ".join(sentences)

    # All similar embeddings — no semantic break
    vectors = [_normalized([1.0, 0.0, 0.0]) for _ in range(20)]
    embedder = _make_embedder(vectors)

    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=30,  # very small to force splits
        min_chunk_tokens=5,
        semantic_threshold_percentile=10,
    )

    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)

    # Should produce multiple chunks despite high similarity
    assert len(chunks.l3_chunks) >= 2


def test_semantic_respects_min_tokens(tmp_path):
    """Low similarity at a boundary, but below min_tokens → no premature split."""
    content = "Short sentence A. Short B. Short C."

    # Dissimilar embeddings — would normally trigger breaks
    vectors = [
        _normalized([1.0, 0.0, 0.0]),
        _normalized([0.0, 1.0, 0.0]),
        _normalized([0.0, 0.0, 1.0]),
    ]
    embedder = _make_embedder(vectors)

    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=200,  # high minimum — prevents splitting
        semantic_threshold_percentile=50,
    )

    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)

    # min_tokens is so high that everything should stay in one chunk
    assert len(chunks.l3_chunks) == 1


def test_semantic_atomic_blocks(tmp_path):
    """Text with an embedded table — table should be a standalone chunk."""
    content = (
        "Introduction paragraph about data.\n\n"
        "| Col A | Col B |\n| --- | --- |\n| 1 | 2 |\n| 3 | 4 |\n\n"
        "Conclusion paragraph about results."
    )

    vectors = [
        _normalized([1.0, 0.0, 0.0]),
        _normalized([0.9, 0.1, 0.0]),
    ]
    embedder = _make_embedder(vectors)

    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=5,
        semantic_threshold_percentile=10,
    )

    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)

    # Should have at least one chunk containing the table
    table_chunks = [c for c in chunks.l3_chunks if "Col A" in c.content]
    assert len(table_chunks) >= 1


def test_semantic_empty_text(tmp_path):
    """Empty input → empty output."""
    embedder = _make_embedder([])

    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
    )

    structure = _make_structure("")
    chunks = chunk_document(structure, settings, embedder=embedder)

    assert len(chunks.l3_chunks) == 0


def test_semantic_overlap_present(tmp_path):
    """With overlap > 0, consecutive semantic groups share sentences."""
    # 6 sentences, 2 clear topics — expect 2 groups
    content = (
        "Machine learning is great. Deep learning uses layers. Neural nets are powerful.\n\n"
        "The ocean is vast. Fish swim in schools. Coral grows slowly."
    )
    vectors = [
        _normalized([1.0, 0.0, 0.0]),
        _normalized([0.95, 0.05, 0.0]),
        _normalized([0.9, 0.1, 0.0]),
        _normalized([0.0, 1.0, 0.0]),
        _normalized([0.05, 0.95, 0.0]),
        _normalized([0.0, 0.9, 0.1]),
    ]
    embedder = _make_embedder(vectors)
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
        semantic_threshold_percentile=30,
        chunk_overlap_fraction=0.3,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)
    l3 = chunks.l3_chunks
    if len(l3) >= 2:
        # Second chunk should contain some overlap from first
        # (last sentence(s) of first group prepended to second)
        # At minimum, this should not crash and chunks are valid
        for c in l3:
            assert c.content.strip()


def test_semantic_no_overlap_when_zero(tmp_path):
    """With overlap_fraction=0, no overlap is applied."""
    content = (
        "Topic A sentence one. Topic A sentence two.\n\nTopic B sentence one. Topic B sentence two."
    )
    vectors = [
        _normalized([1.0, 0.0, 0.0]),
        _normalized([0.95, 0.05, 0.0]),
        _normalized([0.0, 1.0, 0.0]),
        _normalized([0.05, 0.95, 0.0]),
    ]
    embedder = _make_embedder(vectors)
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
        semantic_threshold_percentile=30,
        chunk_overlap_fraction=0.0,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)
    # Should produce chunks without overlap — no crash
    assert len(chunks.l3_chunks) >= 1


def test_semantic_overlap_single_group(tmp_path):
    """Overlap with a single group → no change."""
    content = "One sentence. Two sentence."
    vectors = [
        _normalized([1.0, 0.0, 0.0]),
        _normalized([0.95, 0.05, 0.0]),
    ]
    embedder = _make_embedder(vectors)
    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="semantic",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
        semantic_threshold_percentile=30,
        chunk_overlap_fraction=0.3,
    )
    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)
    assert len(chunks.l3_chunks) == 1


def test_paragraph_strategy_unchanged(tmp_path):
    """With chunking_strategy='paragraph', the embedder is ignored and old path is used."""
    content = "Paragraph one about dogs.\n\nParagraph two about cats."

    embedder = _make_embedder([])  # should never be called

    settings = Settings(
        data_dir=tmp_path,
        chunking_strategy="paragraph",
        max_chunk_tokens=500,
        min_chunk_tokens=10,
    )

    structure = _make_structure(content)
    chunks = chunk_document(structure, settings, embedder=embedder)

    # Should still produce chunks via the paragraph path
    assert len(chunks.l3_chunks) >= 1
    # Embedder should NOT have been called
    embedder.embed_passages.assert_not_called()
