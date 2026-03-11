"""ChunkSet contract tests — lock down the output shape that consumers depend on.

These tests protect the serialized contract of ChunkSet so that any downstream
system (ANCS adapter, vector DB exporter, MCP tool, etc.) can rely on the JSON
shape without surprises.

Run with:  pytest tests/test_chunkset_contract.py -v
"""

from __future__ import annotations

import json

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.pipeline.stage6_storage import load_chunks, save_document
from ingestible.models.document import DocumentStructure, StructureNode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_enriched_chunkset() -> tuple[DocumentStructure, ChunkSet]:
    """Build a ChunkSet with every enrichment field populated."""
    structure = DocumentStructure(
        doc_id="contract-doc",
        title="Contract Test Document",
        root=StructureNode(
            id="root", title="Contract Test Document", level=0, page_end=20,
            children=[
                StructureNode(
                    id="ch1", title="Chapter One", level=1,
                    page_start=1, page_end=20,
                    children=[
                        StructureNode(
                            id="sec1", title="Section 1", level=2,
                            content="Section one content.",
                            page_start=1, page_end=10,
                        ),
                    ],
                ),
            ],
        ),
    )

    chunks = ChunkSet(
        doc_id="contract-doc",
        l0=L0Chunk(
            chunk_id="contract-doc-L0",
            title="Contract Test Document",
            author="Test Author",
            domain="computer science",
            toc_summary="- Chapter One",
            key_concepts=["chunking", "retrieval", "embeddings"],
            total_pages=20,
            total_chapters=1,
            total_sections=1,
            total_passages=2,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id="ch1",
                title="Chapter One",
                content="Chapter one overview.",
                page_start=1,
                page_end=20,
                children_ids=["sec1"],
                chapter_summary="This chapter covers protocols.",
                main_topics=["protocols", "APIs"],
                learning_objectives=["Understand protocol design"],
                prerequisite_chapters=[],
                key_takeaways=["Protocols enable interoperability"],
            ),
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="sec1",
                title="Section 1",
                content="Section one content.",
                page_start=1,
                page_end=10,
                parent_chapter_id="ch1",
                children_ids=["p0", "p1"],
                section_summary="Covers the basics of protocol design.",
                key_points=["Typed interfaces", "Schema validation"],
                concepts_introduced=["schema", "typed interface"],
            ),
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="p0",
                content="Agents interact with tools through structured protocols.",
                page_start=1,
                page_end=5,
                position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                parent_section_id="sec1",
                position_in_section="first",
                context_prefix="Chapter One > Section 1:",
                summary="Describes how agents use structured protocols for tool interaction.",
                concepts=["agents", "tools", "protocols"],
                hypothetical_questions=["How do agents communicate with tools?"],
                keywords=["agent", "protocol", "tool"],
                difficulty_level="intermediate",
                depends_on=[],
                cross_references=["sec2"],
            ),
            L3Chunk(
                chunk_id="p1",
                content="Each tool exposes a typed interface with parameters and return values.",
                page_start=6,
                page_end=10,
                position=ChunkPosition(chapter="ch1", section="sec1", index=1),
                parent_section_id="sec1",
                position_in_section="last",
                context_prefix="Chapter One > Section 1:",
                summary="Tools expose typed interfaces for structured communication.",
                concepts=["typed interface", "parameters"],
                hypothetical_questions=["What does a tool interface look like?"],
                keywords=["interface", "parameters", "return values"],
                difficulty_level="beginner",
                depends_on=["p0"],
                cross_references=[],
            ),
        ],
    )
    return structure, chunks


# ---------------------------------------------------------------------------
# 1. Schema snapshot — catch any breaking changes to the ChunkSet shape
# ---------------------------------------------------------------------------

# To update: run the test, copy the extracted output from the failure message
CHUNKSET_SCHEMA_SNAPSHOT = {
    "doc_id": "string",
    "l0": {
        "chunk_id": "string",
        "title": "string",
        "author": "string",
        "domain": "string",
        "creation_date": "string",
        "source_language": "string",
        "toc_summary": "string",
        "key_concepts": "list[string]",
        "total_pages": "integer",
        "total_chapters": "integer",
        "total_sections": "integer",
        "total_passages": "integer",
    },
    "l1_chunks": {
        "chunk_id": "string",
        "title": "string",
        "content": "string",
        "page_start": "integer|null",
        "page_end": "integer|null",
        "children_ids": "list[string]",
        "chapter_summary": "string",
        "main_topics": "list[string]",
        "learning_objectives": "list[string]",
        "prerequisite_chapters": "list[string]",
        "key_takeaways": "list[string]",
    },
    "l2_chunks": {
        "chunk_id": "string",
        "title": "string",
        "content": "string",
        "page_start": "integer|null",
        "page_end": "integer|null",
        "parent_chapter_id": "string",
        "children_ids": "list[string]",
        "section_summary": "string",
        "key_points": "list[string]",
        "concepts_introduced": "list[string]",
    },
    "l3_chunks": {
        "chunk_id": "string",
        "content": "string",
        "page_start": "integer|null",
        "page_end": "integer|null",
        "position": {
            "chapter": "string",
            "section": "string",
            "index": "integer",
        },
        "parent_section_id": "string",
        "position_in_section": "enum[first,last,middle,only]",
        "context_prefix": "string",
        "summary": "string",
        "concepts": "list[string]",
        "hypothetical_questions": "list[string]",
        "keywords": "list[string]",
        "difficulty_level": "string",
        "depends_on": "list[string]",
        "cross_references": "list[string]",
    },
}


def _extract_field_types(schema: dict, defs: dict) -> dict:
    """Walk a JSON Schema and produce a simplified type map for comparison."""
    result = {}
    props = schema.get("properties", {})

    for name, prop in props.items():
        if "$ref" in prop:
            ref_name = prop["$ref"].split("/")[-1]
            ref_schema = defs[ref_name]
            result[name] = _extract_field_types(ref_schema, defs)
        elif prop.get("type") == "array":
            items = prop.get("items", {})
            if "$ref" in items:
                ref_name = items["$ref"].split("/")[-1]
                ref_schema = defs[ref_name]
                result[name] = _extract_field_types(ref_schema, defs)
            else:
                result[name] = f"list[{items.get('type', 'any')}]"
        elif "anyOf" in prop:
            types = []
            for option in prop["anyOf"]:
                types.append(option.get("type", "ref"))
            result[name] = "|".join(types)
        elif "enum" in prop:
            result[name] = f"enum[{','.join(str(v) for v in sorted(prop['enum']))}]"
        else:
            result[name] = prop.get("type", "unknown")

    return result


def test_schema_snapshot():
    """ChunkSet JSON Schema must match the frozen snapshot.

    If this fails, a field was added, removed, or changed type.
    Update CHUNKSET_SCHEMA_SNAPSHOT deliberately after verifying
    the change is backwards-compatible for consumers.
    """
    full_schema = ChunkSet.model_json_schema()
    defs = full_schema.get("$defs", {})
    extracted = _extract_field_types(full_schema, defs)

    assert extracted == CHUNKSET_SCHEMA_SNAPSHOT, (
        "ChunkSet schema changed. Diff:\n"
        f"  Expected keys: {sorted(CHUNKSET_SCHEMA_SNAPSHOT.keys())}\n"
        f"  Got keys:      {sorted(extracted.keys())}\n"
        f"  Full extracted: {json.dumps(extracted, indent=2)}"
    )


# ---------------------------------------------------------------------------
# 2. Enriched round-trip — all enrichment fields survive save/load
# ---------------------------------------------------------------------------

def test_enriched_roundtrip(tmp_path):
    """Every enrichment field on L0/L1/L2/L3 must survive save → load."""
    settings = Settings(data_dir=tmp_path)
    structure, chunks = _make_enriched_chunkset()

    doc_dir = save_document(structure, chunks, settings)
    loaded = load_chunks(doc_dir)

    # L0 enrichment
    assert loaded.l0.author == chunks.l0.author
    assert loaded.l0.domain == chunks.l0.domain
    assert loaded.l0.key_concepts == chunks.l0.key_concepts
    assert loaded.l0.toc_summary == chunks.l0.toc_summary

    # L1 enrichment
    orig_l1 = chunks.l1_chunks[0]
    loaded_l1 = loaded.l1_chunks[0]
    assert loaded_l1.chapter_summary == orig_l1.chapter_summary
    assert loaded_l1.main_topics == orig_l1.main_topics
    assert loaded_l1.learning_objectives == orig_l1.learning_objectives
    assert loaded_l1.prerequisite_chapters == orig_l1.prerequisite_chapters
    assert loaded_l1.key_takeaways == orig_l1.key_takeaways

    # L2 enrichment
    orig_l2 = chunks.l2_chunks[0]
    loaded_l2 = loaded.l2_chunks[0]
    assert loaded_l2.section_summary == orig_l2.section_summary
    assert loaded_l2.key_points == orig_l2.key_points
    assert loaded_l2.concepts_introduced == orig_l2.concepts_introduced

    # L3 enrichment — check both chunks
    for orig, reloaded in zip(
        sorted(chunks.l3_chunks, key=lambda c: c.chunk_id),
        sorted(loaded.l3_chunks, key=lambda c: c.chunk_id),
    ):
        assert reloaded.content == orig.content
        assert reloaded.context_prefix == orig.context_prefix
        assert reloaded.summary == orig.summary
        assert reloaded.concepts == orig.concepts
        assert reloaded.hypothetical_questions == orig.hypothetical_questions
        assert reloaded.keywords == orig.keywords
        assert reloaded.difficulty_level == orig.difficulty_level
        assert reloaded.depends_on == orig.depends_on
        assert reloaded.cross_references == orig.cross_references
        assert reloaded.position.chapter == orig.position.chapter
        assert reloaded.position.section == orig.position.section
        assert reloaded.position.index == orig.position.index
        assert reloaded.position_in_section == orig.position_in_section


# ---------------------------------------------------------------------------
# 3. API serialization — model_dump() produces the expected JSON shape
# ---------------------------------------------------------------------------

def test_api_serialization():
    """ChunkSet.model_dump() must produce JSON that a consumer can parse
    without knowledge of Pydantic — just raw dicts and lists."""
    _, chunks = _make_enriched_chunkset()
    data = chunks.model_dump()

    # Top level
    assert isinstance(data, dict)
    assert data["doc_id"] == "contract-doc"

    # L0 is a dict, not a Pydantic model
    assert isinstance(data["l0"], dict)
    assert data["l0"]["title"] == "Contract Test Document"
    assert isinstance(data["l0"]["key_concepts"], list)
    assert "chunking" in data["l0"]["key_concepts"]

    # L1 is a list of dicts
    assert isinstance(data["l1_chunks"], list)
    assert len(data["l1_chunks"]) == 1
    l1 = data["l1_chunks"][0]
    assert isinstance(l1, dict)
    assert l1["chunk_id"] == "ch1"
    assert isinstance(l1["main_topics"], list)
    assert l1["chapter_summary"] == "This chapter covers protocols."

    # L2 is a list of dicts
    assert isinstance(data["l2_chunks"], list)
    l2 = data["l2_chunks"][0]
    assert l2["parent_chapter_id"] == "ch1"
    assert isinstance(l2["key_points"], list)

    # L3 is a list of dicts with nested position dict
    assert isinstance(data["l3_chunks"], list)
    assert len(data["l3_chunks"]) == 2
    l3 = data["l3_chunks"][0]
    assert isinstance(l3, dict)
    assert isinstance(l3["position"], dict)
    assert l3["position"]["chapter"] == "ch1"
    assert l3["position"]["section"] == "sec1"
    assert isinstance(l3["position"]["index"], int)

    # Enrichment fields are plain types, not wrapped
    assert isinstance(l3["concepts"], list)
    assert isinstance(l3["hypothetical_questions"], list)
    assert isinstance(l3["keywords"], list)
    assert isinstance(l3["depends_on"], list)
    assert isinstance(l3["cross_references"], list)
    assert isinstance(l3["summary"], str)
    assert isinstance(l3["difficulty_level"], str)
    assert isinstance(l3["context_prefix"], str)

    # Verify it round-trips through JSON (no datetime, no custom types)
    serialized = json.dumps(data)
    deserialized = json.loads(serialized)
    assert deserialized == data
