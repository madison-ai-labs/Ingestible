"""Output integrity tests — verify nothing is lost in the output directory.

Checks that every chunk, chapter, and section from the in-memory model
is faithfully persisted and can be loaded back without data loss.

Run with:  pytest tests/test_output_integrity.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

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
from ingestible.pipeline.stage3_chunking import chunk_document
from ingestible.pipeline.stage6_storage import (
    load_chunks,
    load_document_meta,
    load_structure,
    save_document,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_rich_document() -> tuple[DocumentStructure, ChunkSet]:
    """Create a document with multiple chapters, sections, passages, and orphans."""
    structure = DocumentStructure(
        doc_id="integrity-doc",
        title="Integrity Test Document",
        root=StructureNode(
            id="root", title="Integrity Test Document", level=0, page_end=30,
            children=[
                StructureNode(
                    id="ch1", title="Chapter One", level=1,
                    page_start=1, page_end=15,
                    children=[
                        StructureNode(id="sec1a", title="Section 1A", level=2,
                                      content="Content of section 1A", page_start=1, page_end=5),
                        StructureNode(id="sec1b", title="Section 1B", level=2,
                                      content="Content of section 1B", page_start=6, page_end=10),
                        StructureNode(id="sec1c", title="Section 1C", level=2,
                                      content="Content of section 1C", page_start=11, page_end=15),
                    ],
                ),
                StructureNode(
                    id="ch2", title="Chapter Two", level=1,
                    page_start=16, page_end=30,
                    children=[
                        StructureNode(id="sec2a", title="Section 2A", level=2,
                                      content="Content of section 2A", page_start=16, page_end=22),
                        StructureNode(id="sec2b", title="Section 2B", level=2,
                                      content="Content of section 2B", page_start=23, page_end=30),
                    ],
                ),
            ],
        ),
    )

    chunks = ChunkSet(
        doc_id="integrity-doc",
        l0=L0Chunk(
            chunk_id="integrity-doc-L0",
            title="Integrity Test Document",
            total_pages=30,
            total_chapters=2,
            total_sections=5,
            total_passages=7,
        ),
        l1_chunks=[
            L1Chunk(chunk_id="ch1", title="Chapter One", content="Chapter 1 overview",
                    page_start=1, page_end=15, children_ids=["sec1a", "sec1b", "sec1c"]),
            L1Chunk(chunk_id="ch2", title="Chapter Two", content="Chapter 2 overview",
                    page_start=16, page_end=30, children_ids=["sec2a", "sec2b"]),
        ],
        l2_chunks=[
            L2Chunk(chunk_id="sec1a", title="Section 1A", content="Content of section 1A",
                    parent_chapter_id="ch1", children_ids=["p1", "p2"]),
            L2Chunk(chunk_id="sec1b", title="Section 1B", content="Content of section 1B",
                    parent_chapter_id="ch1", children_ids=["p3"]),
            L2Chunk(chunk_id="sec1c", title="Section 1C", content="Content of section 1C",
                    parent_chapter_id="ch1", children_ids=["p4"]),
            L2Chunk(chunk_id="sec2a", title="Section 2A", content="Content of section 2A",
                    parent_chapter_id="ch2", children_ids=["p5"]),
            L2Chunk(chunk_id="sec2b", title="Section 2B", content="Content of section 2B",
                    parent_chapter_id="ch2", children_ids=["p6"]),
        ],
        l3_chunks=[
            L3Chunk(chunk_id="p1", content="Passage one about protocols.",
                    parent_section_id="sec1a",
                    position=ChunkPosition(chapter="ch1", section="sec1a", index=0)),
            L3Chunk(chunk_id="p2", content="Passage two about implementations.",
                    parent_section_id="sec1a",
                    position=ChunkPosition(chapter="ch1", section="sec1a", index=1)),
            L3Chunk(chunk_id="p3", content="Passage three about testing.",
                    parent_section_id="sec1b",
                    position=ChunkPosition(chapter="ch1", section="sec1b", index=0)),
            L3Chunk(chunk_id="p4", content="Passage four about deployment.",
                    parent_section_id="sec1c",
                    position=ChunkPosition(chapter="ch1", section="sec1c", index=0)),
            L3Chunk(chunk_id="p5", content="Passage five about monitoring.",
                    parent_section_id="sec2a",
                    position=ChunkPosition(chapter="ch2", section="sec2a", index=0)),
            L3Chunk(chunk_id="p6", content="Passage six about scaling.",
                    parent_section_id="sec2b",
                    position=ChunkPosition(chapter="ch2", section="sec2b", index=0)),
            # Orphan: no matching section
            L3Chunk(chunk_id="p-orphan", content="Orphan passage with no section.",
                    parent_section_id="nonexistent",
                    position=ChunkPosition(chapter="ch1", section="nonexistent", index=0)),
        ],
    )
    return structure, chunks


# ---------------------------------------------------------------------------
# Integrity: meta.json completeness
# ---------------------------------------------------------------------------

def test_meta_json_completeness(tmp_path):
    """meta.json must contain all expected keys with correct values."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)

    meta = load_document_meta(doc_dir)

    assert meta["doc_id"] == "integrity-doc"
    assert meta["title"] == "Integrity Test Document"
    assert meta["total_pages"] == 30
    assert meta["total_chapters"] == 2
    assert meta["total_sections"] == 5
    assert meta["total_passages"] == 7
    assert "ingestion_date" in meta
    assert "l0" in meta


# ---------------------------------------------------------------------------
# Integrity: structure.json round-trip
# ---------------------------------------------------------------------------

def test_structure_json_roundtrip(tmp_path):
    """structure.json must faithfully reproduce the document tree."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    save_document(structure, chunks, settings)

    doc_dir = settings.documents_dir / chunks.doc_id
    loaded = load_structure(doc_dir)

    assert loaded.doc_id == structure.doc_id
    assert loaded.title == structure.title
    assert loaded.root.id == structure.root.id

    original_nodes = list(structure.root.walk())
    loaded_nodes = list(loaded.root.walk())
    assert len(loaded_nodes) == len(original_nodes)

    for orig, load in zip(original_nodes, loaded_nodes):
        assert load.id == orig.id
        assert load.title == orig.title
        assert load.level == orig.level


# ---------------------------------------------------------------------------
# Integrity: every chapter has a directory and meta.json
# ---------------------------------------------------------------------------

def test_all_chapters_persisted(tmp_path):
    """Every L1 chunk must have a corresponding chapters/<id>/meta.json."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)

    chapters_dir = doc_dir / "chapters"
    assert chapters_dir.exists()

    persisted_chapter_ids = {d.name for d in chapters_dir.iterdir() if d.is_dir()}
    expected_chapter_ids = {ch.chunk_id for ch in chunks.l1_chunks}

    assert persisted_chapter_ids == expected_chapter_ids, (
        f"Missing chapters: {expected_chapter_ids - persisted_chapter_ids}, "
        f"Extra chapters: {persisted_chapter_ids - expected_chapter_ids}"
    )

    for ch in chunks.l1_chunks:
        meta_path = chapters_dir / ch.chunk_id / "meta.json"
        assert meta_path.exists(), f"Missing meta.json for chapter {ch.chunk_id}"
        data = json.loads(meta_path.read_text())
        assert data["chunk_id"] == ch.chunk_id
        assert data["title"] == ch.title


# ---------------------------------------------------------------------------
# Integrity: every section has a directory and meta.json
# ---------------------------------------------------------------------------

def test_all_sections_persisted(tmp_path):
    """Every L2 chunk must have a corresponding sections/<id>/meta.json under its chapter."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)

    for sec in chunks.l2_chunks:
        sec_dir = doc_dir / "chapters" / sec.parent_chapter_id / "sections" / sec.chunk_id
        assert sec_dir.exists(), f"Missing section dir: {sec.chunk_id}"

        meta_path = sec_dir / "meta.json"
        assert meta_path.exists(), f"Missing meta.json for section {sec.chunk_id}"
        data = json.loads(meta_path.read_text())
        assert data["chunk_id"] == sec.chunk_id
        assert data["title"] == sec.title
        assert data["parent_chapter_id"] == sec.parent_chapter_id


# ---------------------------------------------------------------------------
# Integrity: every L3 passage is persisted
# ---------------------------------------------------------------------------

def test_all_passages_persisted(tmp_path):
    """Every L3 chunk must exist as a JSON file on disk."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)

    # Collect all chunk JSON files from disk
    all_chunk_files = list(doc_dir.rglob("chunks/*.json"))
    persisted_ids = {json.loads(f.read_text())["chunk_id"] for f in all_chunk_files}
    expected_ids = {c.chunk_id for c in chunks.l3_chunks}

    assert persisted_ids == expected_ids, (
        f"Missing passages: {expected_ids - persisted_ids}, "
        f"Extra passages: {persisted_ids - expected_ids}"
    )


# ---------------------------------------------------------------------------
# Integrity: orphan passages end up in doc_dir/chunks/
# ---------------------------------------------------------------------------

def test_orphan_passages_stored(tmp_path):
    """Passages with no matching section go into doc_dir/chunks/."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)

    orphan_dir = doc_dir / "chunks"
    assert orphan_dir.exists(), "Orphan chunks/ directory should exist"

    orphan_files = list(orphan_dir.glob("*.json"))
    assert len(orphan_files) >= 1, "Expected at least one orphan passage"

    orphan_data = json.loads(orphan_files[0].read_text())
    assert orphan_data["chunk_id"] == "p-orphan"


# ---------------------------------------------------------------------------
# Integrity: content preservation (no truncation or corruption)
# ---------------------------------------------------------------------------

def test_passage_content_preserved(tmp_path):
    """Every passage's content must survive the save/load cycle byte-for-byte."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)
    loaded = load_chunks(doc_dir)

    original_map = {c.chunk_id: c.content for c in chunks.l3_chunks}
    loaded_map = {c.chunk_id: c.content for c in loaded.l3_chunks}

    assert set(original_map.keys()) == set(loaded_map.keys()), "Chunk IDs differ"

    for cid in original_map:
        assert loaded_map[cid] == original_map[cid], (
            f"Content mismatch for chunk {cid}: "
            f"expected {len(original_map[cid])} chars, got {len(loaded_map[cid])} chars"
        )


# ---------------------------------------------------------------------------
# Integrity: chapter/section counts match L0 metadata
# ---------------------------------------------------------------------------

def test_counts_match_metadata(tmp_path):
    """The L0 counts must match the actual number of chunks at each level."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_rich_document()
    doc_dir = save_document(structure, chunks, settings)
    loaded = load_chunks(doc_dir)

    meta = load_document_meta(doc_dir)
    assert meta["total_chapters"] == len(loaded.l1_chunks)
    assert meta["total_sections"] == len(loaded.l2_chunks)
    assert meta["total_passages"] == len(loaded.l3_chunks)


# ---------------------------------------------------------------------------
# Integrity: full pipeline chunking → storage → reload
# ---------------------------------------------------------------------------

def test_pipeline_roundtrip_no_loss(tmp_path):
    """Run chunking + storage + reload and verify nothing is lost."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)

    paragraphs = "\n\n".join([
        "Autonomous agents interact with tools through structured protocols.",
        "Each tool exposes a typed interface with parameters and return values.",
        "The orchestrator routes requests to the appropriate tool server.",
        "Results are validated against the schema before being returned.",
        "Error handling follows a retry-with-backoff strategy for transient failures.",
        "Observability is built in via structured logging at each stage.",
    ])

    sections = [
        StructureNode(id=f"sec{i}", title=f"Section {i}", level=2,
                      content=paragraphs, page_start=i * 5, page_end=i * 5 + 4)
        for i in range(4)
    ]
    root = StructureNode(
        id="root", title="Pipeline Test", level=0, page_end=20,
        children=[
            StructureNode(id="ch1", title="Only Chapter", level=1,
                          page_start=1, page_end=20, children=sections),
        ],
    )
    structure = DocumentStructure(doc_id="pipeline-rt", title="Pipeline Test", root=root)

    # Stage 3: chunk
    chunks = chunk_document(structure, settings)

    assert chunks.l0.total_chapters == len(chunks.l1_chunks)
    assert chunks.l0.total_sections == len(chunks.l2_chunks)
    assert chunks.l0.total_passages == len(chunks.l3_chunks)

    # Stage 6: save
    doc_dir = save_document(structure, chunks, settings)

    # Reload and compare
    loaded = load_chunks(doc_dir)
    loaded_structure = load_structure(doc_dir)

    assert loaded.doc_id == chunks.doc_id
    assert len(loaded.l1_chunks) == len(chunks.l1_chunks)
    assert len(loaded.l2_chunks) == len(chunks.l2_chunks)
    assert len(loaded.l3_chunks) == len(chunks.l3_chunks)

    assert loaded_structure.title == structure.title
    assert len(list(loaded_structure.root.walk())) == len(list(structure.root.walk()))

    # Verify no content was lost
    for orig, reloaded in zip(
        sorted(chunks.l3_chunks, key=lambda c: c.chunk_id),
        sorted(loaded.l3_chunks, key=lambda c: c.chunk_id),
    ):
        assert reloaded.chunk_id == orig.chunk_id
        assert reloaded.content == orig.content
        assert reloaded.parent_section_id == orig.parent_section_id


# ---------------------------------------------------------------------------
# Integrity: hierarchy linkage — every L3 points to a valid L2, every L2 to L1
# ---------------------------------------------------------------------------

def test_hierarchy_linkage_valid(tmp_path):
    """Every L3 chunk's parent_section_id must exist in L2 IDs,
    and every L2 chunk's parent_chapter_id must exist in L1 IDs."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)

    paragraphs = "\n\n".join([
        "Autonomous agents interact with tools through structured protocols.",
        "Each tool exposes a typed interface with parameters and return values.",
        "The orchestrator routes requests to the appropriate tool server.",
        "Results are validated against the schema before being returned.",
        "Error handling follows a retry-with-backoff strategy for transient failures.",
        "Observability is built in via structured logging at each stage.",
    ])

    sections = [
        StructureNode(id=f"sec{i}", title=f"Section {i}", level=2,
                      content=paragraphs, page_start=i * 5, page_end=i * 5 + 4)
        for i in range(4)
    ]
    root = StructureNode(
        id="root", title="Linkage Test", level=0, page_end=20,
        children=[
            StructureNode(id="ch1", title="Chapter One", level=1,
                          page_start=1, page_end=20, children=sections),
        ],
    )
    structure = DocumentStructure(doc_id="linkage-test", title="Linkage Test", root=root)
    chunks = chunk_document(structure, settings)

    l2_ids = {c.chunk_id for c in chunks.l2_chunks}
    l1_ids = {c.chunk_id for c in chunks.l1_chunks}

    for c in chunks.l3_chunks:
        assert c.parent_section_id in l2_ids, (
            f"L3 chunk {c.chunk_id} references non-existent L2 section {c.parent_section_id}"
        )

    for c in chunks.l2_chunks:
        assert c.parent_chapter_id in l1_ids, (
            f"L2 chunk {c.chunk_id} references non-existent L1 chapter {c.parent_chapter_id}"
        )


# ---------------------------------------------------------------------------
# Integrity: content coverage — no significant text loss during chunking
# ---------------------------------------------------------------------------

def test_content_coverage_no_loss(tmp_path):
    """L3 chunk output must cover at least 90% of leaf input chars."""
    settings = Settings(data_dir=tmp_path, max_chunk_tokens=500, min_chunk_tokens=100)

    paragraphs = "\n\n".join([
        "Autonomous agents interact with tools through structured protocols.",
        "Each tool exposes a typed interface with parameters and return values.",
        "The orchestrator routes requests to the appropriate tool server.",
        "Results are validated against the schema before being returned.",
    ])

    sections = [
        StructureNode(id=f"sec{i}", title=f"Section {i}", level=2,
                      content=paragraphs, page_start=i * 5, page_end=i * 5 + 4)
        for i in range(3)
    ]
    root = StructureNode(
        id="root", title="Coverage Test", level=0, page_end=15,
        children=[
            StructureNode(id="ch1", title="Chapter One", level=1,
                          page_start=1, page_end=15, children=sections),
        ],
    )
    structure = DocumentStructure(doc_id="coverage-test", title="Coverage Test", root=root)
    chunks = chunk_document(structure, settings)

    input_chars = sum(
        len(node.content)
        for node in structure.root.walk()
        if node.content and node.level >= 2
    )
    output_chars = sum(len(c.content) for c in chunks.l3_chunks)
    ratio = output_chars / input_chars if input_chars else 0.0

    assert ratio >= 0.9, (
        f"Content coverage too low: {ratio:.4f} ({output_chars} output chars / {input_chars} input chars)"
    )
