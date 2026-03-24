"""Tests for WP 2.3 — Export to portable formats."""

from __future__ import annotations

import json

import pytest

from ingestible.export import EXPORT_FORMATS, export_document
from ingestible.export.jsonl import export_jsonl
from ingestible.export.langchain import export_langchain
from ingestible.export.llamaindex import export_llamaindex
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.enrichment import KGTriple


@pytest.fixture
def sample_chunks() -> ChunkSet:
    return ChunkSet(
        doc_id="test-doc",
        l0=L0Chunk(chunk_id="test-doc-L0", title="Test Document", total_pages=5),
        l3_chunks=[
            L3Chunk(
                chunk_id="test-doc-c1",
                content="First chunk about machine learning.",
                summary="ML overview",
                position=ChunkPosition(chapter="Chapter 1", section="Intro"),
                page_start=1,
                page_end=1,
                concepts=["machine learning"],
                keywords=["ml", "ai"],
            ),
            L3Chunk(
                chunk_id="test-doc-c2",
                content="Second chunk about neural networks.",
                summary="NN overview",
                position=ChunkPosition(chapter="Chapter 2", section="Networks"),
                page_start=2,
                page_end=3,
                concepts=["neural networks"],
                keywords=["nn", "deep learning"],
            ),
        ],
    )


def test_export_formats_list():
    assert "jsonl" in EXPORT_FORMATS
    assert "parquet" in EXPORT_FORMATS
    assert "llamaindex" in EXPORT_FORMATS
    assert "langchain" in EXPORT_FORMATS


def test_export_invalid_format(sample_chunks, tmp_path):
    with pytest.raises(ValueError, match="Unknown export format"):
        export_document(sample_chunks, "invalid", tmp_path / "out.txt")


# --- JSONL ---


def test_jsonl_export(sample_chunks, tmp_path):
    out = tmp_path / "export.jsonl"
    result = export_jsonl(sample_chunks, out)

    assert result == out
    assert out.exists()

    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["id"] == "test-doc-c1"
    assert first["doc_id"] == "test-doc"
    assert first["content"] == "First chunk about machine learning."
    assert first["concepts"] == ["machine learning"]

    second = json.loads(lines[1])
    assert second["id"] == "test-doc-c2"


def test_jsonl_via_dispatch(sample_chunks, tmp_path):
    out = tmp_path / "export.jsonl"
    export_document(sample_chunks, "jsonl", out)
    assert out.exists()
    lines = out.read_text().strip().split("\n")
    assert len(lines) == 2


# --- LlamaIndex ---


def test_llamaindex_export(sample_chunks, tmp_path):
    out = tmp_path / "nodes.json"
    result = export_llamaindex(sample_chunks, out)

    assert result == out
    nodes = json.loads(out.read_text())
    assert len(nodes) == 2

    node = nodes[0]
    assert node["id_"] == "test-doc-c1"
    assert node["text"] == "First chunk about machine learning."
    assert node["metadata"]["doc_id"] == "test-doc"
    assert node["metadata"]["chapter"] == "Chapter 1"


# --- LangChain ---


def test_langchain_export(sample_chunks, tmp_path):
    out = tmp_path / "docs.json"
    result = export_langchain(sample_chunks, out)

    assert result == out
    docs = json.loads(out.read_text())
    assert len(docs) == 2

    doc = docs[0]
    assert doc["page_content"] == "First chunk about machine learning."
    assert doc["metadata"]["chunk_id"] == "test-doc-c1"
    assert doc["metadata"]["doc_id"] == "test-doc"


# --- Parquet ---


def test_parquet_export(sample_chunks, tmp_path):
    """Parquet export works when pyarrow is available."""
    try:
        import pyarrow  # noqa: F401
    except ImportError:
        pytest.skip("pyarrow not installed")

    out = tmp_path / "export.parquet"
    from ingestible.export.parquet import export_parquet

    result = export_parquet(sample_chunks, out)
    assert result == out
    assert out.exists()

    import pyarrow.parquet as pq

    table = pq.read_table(str(out))
    assert table.num_rows == 2
    assert "content" in table.column_names
    assert "doc_id" in table.column_names


# --- Complete ---


@pytest.fixture
def rich_chunks() -> ChunkSet:
    """ChunkSet with full hierarchy and KG triples."""
    return ChunkSet(
        doc_id="rich-doc",
        l0=L0Chunk(
            chunk_id="rich-doc-L0",
            title="Pixel Art Guide",
            author="Test Author",
            domain="pixel-art",
            document_type="guide",
            executive_summary="A guide to pixel art techniques.",
            key_concepts=["dithering", "anti-aliasing", "palette design"],
            total_pages=10,
            total_chapters=1,
            total_sections=1,
            total_passages=2,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id="rich-doc-ch1",
                title="Chapter 1: Fundamentals",
                content="Fundamentals of pixel art.",
                chapter_summary="Covers basics of pixel art.",
                main_topics=["dithering", "color theory"],
                children_ids=["rich-doc-s1"],
            ),
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="rich-doc-s1",
                title="Section 1: Dithering",
                content="Dithering techniques.",
                parent_chapter_id="rich-doc-ch1",
                section_summary="How to use dithering.",
                key_points=["Pattern dithering", "Error diffusion"],
                concepts_introduced=["ordered dithering", "Floyd-Steinberg"],
                children_ids=["rich-doc-c1", "rich-doc-c2"],
            ),
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="rich-doc-c1",
                content="Ordered dithering uses a Bayer matrix.",
                summary="Ordered dithering technique.",
                parent_section_id="rich-doc-s1",
                position=ChunkPosition(chapter="Chapter 1", section="Dithering"),
                page_start=1,
                page_end=1,
                concepts=["ordered dithering", "Bayer matrix"],
                keywords=["dithering", "pattern"],
                kg_triples=[
                    KGTriple(
                        subject="ordered dithering",
                        subject_type="Concept",
                        predicate="uses",
                        object="Bayer matrix",
                        object_type="Method",
                        confidence=0.9,
                        source_chunk_id="rich-doc-c1",
                    )
                ],
            ),
            L3Chunk(
                chunk_id="rich-doc-c2",
                content="Floyd-Steinberg distributes quantization error.",
                summary="Error diffusion dithering.",
                parent_section_id="rich-doc-s1",
                position=ChunkPosition(chapter="Chapter 1", section="Dithering"),
                page_start=2,
                page_end=2,
                concepts=["Floyd-Steinberg", "error diffusion"],
                keywords=["dithering", "quantization"],
            ),
        ],
        knowledge_graph=[
            KGTriple(
                subject="ordered dithering",
                subject_type="Concept",
                predicate="uses",
                object="Bayer matrix",
                object_type="Method",
                confidence=0.9,
                source_chunk_id="rich-doc-c1",
            ),
            KGTriple(
                subject="Floyd-Steinberg",
                subject_type="Method",
                predicate="is_a",
                object="error diffusion",
                object_type="Concept",
                confidence=0.95,
                source_chunk_id="rich-doc-c2",
            ),
        ],
    )


def test_complete_export(rich_chunks, tmp_path):
    from ingestible.export.complete import export_complete

    out = tmp_path / "export.json"
    result = export_complete(rich_chunks, out)

    assert result == out
    assert out.exists()

    data = json.loads(out.read_text())
    assert data["format"] == "ingestible-complete"
    assert data["version"] == 1
    assert data["doc_id"] == "rich-doc"
    assert data["title"] == "Pixel Art Guide"
    assert data["executive_summary"] == "A guide to pixel art techniques."
    assert "dithering" in data["key_concepts"]

    # Hierarchy
    assert len(data["chapters"]) == 1
    ch = data["chapters"][0]
    assert ch["title"] == "Chapter 1: Fundamentals"
    assert len(ch["sections"]) == 1

    sec = ch["sections"][0]
    assert sec["title"] == "Section 1: Dithering"
    assert len(sec["passages"]) == 2

    p1 = sec["passages"][0]
    assert p1["content"] == "Ordered dithering uses a Bayer matrix."
    assert "ordered dithering" in p1["concepts"]
    assert len(p1["kg_triples"]) == 1
    assert p1["kg_triples"][0]["predicate"] == "uses"

    # Knowledge graph
    kg = data["knowledge_graph"]
    assert len(kg["triples"]) == 2
    assert "ordered dithering" in kg["entities"]
    assert "bayer matrix" in kg["entities"]

    # Concepts
    assert data["concepts"]["total_unique"] > 0
    concept_names = [c["concept"] for c in data["concepts"]["by_frequency"]]
    assert "ordered dithering" in concept_names


def test_complete_via_dispatch(rich_chunks, tmp_path):
    out = tmp_path / "export.json"
    export_document(rich_chunks, "complete", out)
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["format"] == "ingestible-complete"


def test_complete_corpus_export(rich_chunks, sample_chunks, tmp_path):
    from ingestible.export.complete import export_complete_corpus

    out = tmp_path / "corpus.json"
    documents = [(rich_chunks, "Pixel Art Guide"), (sample_chunks, "Test Document")]
    result = export_complete_corpus(documents, out)

    assert result == out
    assert out.exists()

    data = json.loads(out.read_text())
    assert data["format"] == "ingestible-corpus"
    assert data["version"] == 1
    assert data["document_count"] == 2
    assert len(data["documents"]) == 2
    assert data["documents"][0]["doc_id"] == "rich-doc"
    assert data["documents"][1]["doc_id"] == "test-doc"

    # Corpus graph
    assert "corpus_graph" in data
    assert data["corpus_graph"]["total_entities"] > 0


def test_complete_format_in_formats_list():
    assert "complete" in EXPORT_FORMATS
