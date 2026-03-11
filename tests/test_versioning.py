"""Tests for WP 5.1 — Document Versioning."""

from __future__ import annotations

import json
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.chunks import ChunkPosition, ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestible.models.document import DocumentStructure, StructureNode
from ingestible.pipeline.stage6_storage import (
    archive_version,
    list_versions,
    save_document,
)


def _make_doc(doc_id: str = "test-doc") -> tuple[DocumentStructure, ChunkSet]:
    structure = DocumentStructure(
        doc_id=doc_id,
        title="Test",
        root=StructureNode(id="root", title="Test", level=0),
    )
    chunks = ChunkSet(
        doc_id=doc_id,
        l0=L0Chunk(chunk_id=f"{doc_id}-L0", title="Test"),
        l1_chunks=[],
        l2_chunks=[],
        l3_chunks=[],
    )
    return structure, chunks


def test_archive_creates_versioned_copy(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_doc()
    doc_dir = save_document(structure, chunks, settings, content_hash="abc123")

    version = archive_version(doc_dir)
    assert version == 1

    archive_dir = tmp_path / "documents" / "test-doc_v1"
    assert archive_dir.exists()
    assert (archive_dir / "meta.json").exists()


def test_list_versions_empty(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_doc()
    doc_dir = save_document(structure, chunks, settings)

    assert list_versions(doc_dir) == []


def test_list_versions_after_archive(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_doc()
    doc_dir = save_document(structure, chunks, settings, content_hash="hash1")

    archive_version(doc_dir)
    archive_version(doc_dir)

    versions = list_versions(doc_dir)
    assert len(versions) == 2
    assert versions[0]["version"] == 1
    assert versions[1]["version"] == 2


def test_version_number_in_meta(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_doc()
    doc_dir = save_document(structure, chunks, settings, content_hash="h1")
    archive_version(doc_dir)
    # Re-save (simulates re-ingest after archive)
    save_document(structure, chunks, settings, content_hash="h2")

    meta = json.loads((doc_dir / "meta.json").read_text())
    assert meta["version"] == 2


def test_archive_preserves_content_hash(tmp_path):
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_doc()
    doc_dir = save_document(structure, chunks, settings, content_hash="original_hash")
    archive_version(doc_dir)

    versions = list_versions(doc_dir)
    assert versions[0]["content_hash"] == "original_hash"
