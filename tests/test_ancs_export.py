"""Tests for the ANCS export adapter.

Validates the ChunkSet → ANCS ChunkSetInput (camelCase) transformation —
especially that the typed knowledge_graph survives the trip, since that's the
layer the CV adapter drops. HTTP is mocked; no external ANCS needed.

Run with:  pytest tests/test_ancs_export.py -v
"""

from __future__ import annotations

import httpx

from ingestible.adapters.ancs_export import (
    ANCSConfig,
    chunkset_to_ancs_payload,
    export_to_ancs,
)
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.enrichment import KGTriple


def _make_chunkset() -> ChunkSet:
    return ChunkSet(
        doc_id="test-doc",
        l0=L0Chunk(
            chunk_id="test-doc-L0",
            title="Energy Memo",
            author="A",
            domain="kgtest",
            toc_summary="- Chapter 1",
            key_concepts=["grid"],
            total_pages=1,
            total_chapters=1,
            total_sections=1,
            total_passages=1,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id="ch1",
                title="Chapter 1",
                content="Overview.",
                main_topics=["energy"],
            ),
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="sec1",
                title="Section 1",
                content="Body.",
                parent_chapter_id="ch1",
                concepts_introduced=["reactor"],
            ),
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="p0",
                content="The Helios reactor powers the Aurora grid.",
                position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                parent_section_id="sec1",
                keywords=["helios"],
                kg_triples=[
                    KGTriple(
                        subject="Helios reactor",
                        subject_type="Technology",
                        predicate="powers",
                        object="Aurora grid",
                        object_type="Technology",
                        confidence=0.92,
                        source_chunk_id="p0",
                    ),
                ],
            ),
        ],
        knowledge_graph=[
            KGTriple(
                subject="Helios reactor",
                subject_type="Technology",
                predicate="powers",
                object="Aurora grid",
                object_type="Technology",
                confidence=0.92,
                source_chunk_id="p0",
            ),
        ],
    )


def test_payload_is_camelcase_and_full_hierarchy() -> None:
    body = chunkset_to_ancs_payload(_make_chunkset())
    assert body["docId"] == "test-doc"
    assert body["l0"]["tocSummary"] == "- Chapter 1"
    assert body["l0"]["keyConcepts"] == ["grid"]
    assert body["l1Chunks"][0]["mainTopics"] == ["energy"]
    assert body["l2Chunks"][0]["parentChapterId"] == "ch1"
    assert body["l3Chunks"][0]["parentSectionId"] == "sec1"
    assert body["l3Chunks"][0]["position"] == {"chapter": "ch1", "section": "sec1", "index": 0}


def test_knowledge_graph_carries_typed_triples() -> None:
    body = chunkset_to_ancs_payload(_make_chunkset())
    assert len(body["knowledgeGraph"]) == 1
    t = body["knowledgeGraph"][0]
    assert t == {
        "subject": "Helios reactor",
        "subjectType": "Technology",
        "predicate": "powers",
        "object": "Aurora grid",
        "objectType": "Technology",
        "confidence": 0.92,
        "sourceChunkId": "p0",
    }


def test_falls_back_to_per_l3_triples_when_no_doc_graph() -> None:
    cs = _make_chunkset()
    cs.knowledge_graph = []  # force fallback to L3.kg_triples
    body = chunkset_to_ancs_payload(cs)
    assert len(body["knowledgeGraph"]) == 1
    assert body["knowledgeGraph"][0]["predicate"] == "powers"


def test_source_uri_and_tenant_optional() -> None:
    body = chunkset_to_ancs_payload(_make_chunkset())
    assert "sourceUri" not in body
    assert "tenantId" not in body
    body2 = chunkset_to_ancs_payload(_make_chunkset(), source_uri="file://x", tenant_id="t1")
    assert body2["sourceUri"] == "file://x"
    assert body2["tenantId"] == "t1"


def test_export_posts_and_parses_result() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        import json as _json

        captured["body"] = _json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "docId": "test-doc",
                "memoryItemsCreated": 4,
                "entitiesCreated": 2,
                "hyperedgesCreated": 3,
                "kgTriplesIngested": 1,
            },
        )

    transport = httpx.MockTransport(handler)
    # Patch the client used inside export_to_ancs by monkeypatching httpx.Client
    orig_client = httpx.Client

    def client_factory(*args, **kwargs):
        kwargs["transport"] = transport
        return orig_client(*args, **kwargs)

    httpx.Client = client_factory  # type: ignore[assignment]
    try:
        cfg = ANCSConfig(base_url="http://ancs.local", api_key="secret")
        res = export_to_ancs(_make_chunkset(), cfg)
    finally:
        httpx.Client = orig_client  # type: ignore[assignment]

    assert res.error is None
    assert res.kg_triples_ingested == 1
    assert res.entities_created == 2
    assert captured["url"] == "http://ancs.local/memory/ingest-chunkset"
    assert captured["auth"] == "Bearer secret"
    assert captured["body"]["knowledgeGraph"][0]["subject"] == "Helios reactor"
