"""Tests for WP 2.3 — Export to portable formats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestible.export import EXPORT_FORMATS, export_document
from ingestible.export.jsonl import export_jsonl
from ingestible.export.llamaindex import export_llamaindex
from ingestible.export.langchain import export_langchain
from ingestible.models.chunks import ChunkSet, L0Chunk, L3Chunk, ChunkPosition


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
        import pyarrow
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
