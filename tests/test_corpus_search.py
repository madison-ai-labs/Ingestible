"""Tests for WP 2.1 — Cross-document corpus search."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk, ChunkPosition
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.models.search import CorpusSearchResponse
from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
from ingestible.pipeline.stage6_storage import save_document
from ingestible.search.corpus import CorpusSearcher


def _make_doc(doc_id: str, title: str, content: str, settings: Settings):
    """Create a minimal ingested document for testing."""
    l3 = L3Chunk(
        chunk_id=f"{doc_id}-c1",
        content=content,
        position=ChunkPosition(chapter=title, section="Main"),
        parent_section_id=f"{doc_id}-s1",
    )
    l2 = L2Chunk(
        chunk_id=f"{doc_id}-s1",
        title="Main",
        content=content[:100],
        parent_chapter_id=f"{doc_id}-ch1",
        children_ids=[l3.chunk_id],
    )
    l1 = L1Chunk(
        chunk_id=f"{doc_id}-ch1",
        title=title,
        content=content[:100],
        children_ids=[l2.chunk_id],
    )
    l0 = L0Chunk(
        chunk_id=f"{doc_id}-L0",
        title=title,
        total_pages=1,
        total_chapters=1,
        total_sections=1,
        total_passages=1,
    )
    chunks = ChunkSet(
        doc_id=doc_id,
        l0=l0,
        l1_chunks=[l1],
        l2_chunks=[l2],
        l3_chunks=[l3],
    )
    root = StructureNode(id=doc_id, title=title, level=0, children=[])
    structure = DocumentStructure(doc_id=doc_id, title=title, root=root)

    # Save to disk (creates settings.documents_dir / doc_id)
    save_document(structure, chunks, settings, content_hash="test")

    # Build indexes in the same doc_dir
    doc_dir = settings.documents_dir / doc_id
    embedder = Embedder(settings)
    build_indexes(chunks, doc_dir, embedder)

    return chunks


@pytest.fixture
def corpus_setup(tmp_path: Path):
    """Set up a corpus with 3 test documents."""
    settings = Settings(data_dir=tmp_path)

    _make_doc("doc-alpha", "Alpha Document", "Machine learning is a subset of artificial intelligence.", settings)
    _make_doc("doc-beta", "Beta Document", "Neural networks are used in deep learning applications.", settings)
    _make_doc("doc-gamma", "Gamma Document", "Natural language processing enables text analysis.", settings)

    return settings


def test_corpus_searcher_discovers_docs(corpus_setup):
    """CorpusSearcher finds all ingested documents."""
    searcher = CorpusSearcher(corpus_setup)
    dirs = searcher._discover_doc_dirs()
    assert len(dirs) == 3


def test_corpus_searcher_filters_by_doc_ids(corpus_setup):
    """CorpusSearcher filters to specific doc_ids."""
    searcher = CorpusSearcher(corpus_setup)
    dirs = searcher._discover_doc_dirs(doc_ids=["doc-alpha", "doc-beta"])
    assert len(dirs) == 2
    assert {d.name for d in dirs} == {"doc-alpha", "doc-beta"}


def test_corpus_search_returns_results(corpus_setup):
    """Corpus search returns results from multiple documents."""
    searcher = CorpusSearcher(corpus_setup)
    response = searcher.search("machine learning", n_results=5)

    assert isinstance(response, CorpusSearchResponse)
    assert len(response.results) > 0
    assert response.documents_searched == 3
    # Results should have doc_id and doc_title populated
    for r in response.results:
        assert r.doc_id
        assert r.doc_title


def test_corpus_search_empty_corpus(tmp_path):
    """Corpus search with no documents returns empty response."""
    settings = Settings(data_dir=tmp_path)
    searcher = CorpusSearcher(settings)
    response = searcher.search("anything")
    assert response.results == []
    assert response.documents_searched == 0


def test_corpus_search_with_doc_filter(corpus_setup):
    """Corpus search filtered to specific docs only searches those."""
    searcher = CorpusSearcher(corpus_setup)
    response = searcher.search("learning", n_results=5, doc_ids=["doc-alpha"])
    assert response.documents_searched == 1
    for r in response.results:
        assert r.doc_id == "doc-alpha"
