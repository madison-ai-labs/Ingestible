"""ANCS adapter — export ChunkSets to ANCS' POST /memory/ingest-chunkset.

Unlike the CognitiveVault adapter (which flattens the hierarchy into entries),
ANCS already knows how to turn a ChunkSet into memory items + entities +
hyperedges server-side. We only reshape Ingestible's snake_case Pydantic models
into the camelCase `ChunkSetInput` ANCS expects — and, crucially, we carry the
typed `knowledge_graph` (subject—predicate→object triples). ANCS materializes
each triple as a real semantic hyperedge, which is what its retrieval traverses
for multi-hop over lexically-distant facts. The CV path drops that layer; this
one does not.

Usage:
    from ingestible.adapters.ancs_export import export_to_ancs, ANCSConfig

    cfg = ANCSConfig(base_url="http://localhost:8088", api_key="...")
    result = export_to_ancs(chunks, cfg)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from ingestible.models.chunks import ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestible.models.enrichment import KGTriple

logger = logging.getLogger(__name__)


@dataclass
class ANCSConfig:
    """Connection config for ANCS chunkset ingest."""

    base_url: str
    api_key: str
    source_uri: str | None = None  # provenance; ties items back to the source
    tenant_id: str | None = None  # usually derived server-side from api_key
    timeout: float = 60.0


@dataclass
class ANCSIngestResult:
    """Result of an ANCS chunkset ingest (mirrors ChunkSetIngestResult)."""

    doc_id: str
    memory_items_created: int = 0
    entities_created: int = 0
    hyperedges_created: int = 0
    kg_triples_ingested: int = 0
    error: str | None = None


def _l0_payload(l0: L0Chunk) -> dict[str, Any]:
    return {
        "chunkId": l0.chunk_id,
        "title": l0.title,
        "author": l0.author,
        "domain": l0.domain,
        "tocSummary": l0.toc_summary,
        "keyConcepts": l0.key_concepts,
        "totalPages": l0.total_pages,
        "totalChapters": l0.total_chapters,
        "totalSections": l0.total_sections,
        "totalPassages": l0.total_passages,
    }


def _l1_payload(l1: L1Chunk) -> dict[str, Any]:
    return {
        "chunkId": l1.chunk_id,
        "title": l1.title,
        "content": l1.content,
        "pageStart": l1.page_start,
        "pageEnd": l1.page_end,
        "childrenIds": l1.children_ids,
        "chapterSummary": l1.chapter_summary,
        "mainTopics": l1.main_topics,
        "learningObjectives": l1.learning_objectives,
        "prerequisiteChapters": l1.prerequisite_chapters,
        "keyTakeaways": l1.key_takeaways,
    }


def _l2_payload(l2: L2Chunk) -> dict[str, Any]:
    return {
        "chunkId": l2.chunk_id,
        "title": l2.title,
        "content": l2.content,
        "pageStart": l2.page_start,
        "pageEnd": l2.page_end,
        "parentChapterId": l2.parent_chapter_id,
        "childrenIds": l2.children_ids,
        "sectionSummary": l2.section_summary,
        "keyPoints": l2.key_points,
        "conceptsIntroduced": l2.concepts_introduced,
    }


def _l3_payload(l3: L3Chunk) -> dict[str, Any]:
    return {
        "chunkId": l3.chunk_id,
        "content": l3.content,
        "pageStart": l3.page_start,
        "pageEnd": l3.page_end,
        "position": {
            "chapter": l3.position.chapter,
            "section": l3.position.section,
            "index": l3.position.index,
        },
        "parentSectionId": l3.parent_section_id,
        "positionInSection": l3.position_in_section,
        "contextPrefix": l3.context_prefix,
        "summary": l3.summary,
        "concepts": l3.concepts,
        "hypotheticalQuestions": l3.hypothetical_questions,
        "keywords": l3.keywords,
        "difficultyLevel": l3.difficulty_level,
        "dependsOn": l3.depends_on,
        "crossReferences": l3.cross_references,
    }


def _triple_payload(t: KGTriple) -> dict[str, Any]:
    return {
        "subject": t.subject,
        "subjectType": t.subject_type,
        "predicate": t.predicate,
        "object": t.object,
        "objectType": t.object_type,
        "confidence": t.confidence,
        "sourceChunkId": t.source_chunk_id,
    }


def _collect_triples(chunks: ChunkSet) -> list[KGTriple]:
    """Prefer the document-level (deduped) graph; fall back to per-L3 triples."""
    if chunks.knowledge_graph:
        return list(chunks.knowledge_graph)
    collected: list[KGTriple] = []
    for l3 in chunks.l3_chunks:
        collected.extend(l3.kg_triples)
    return collected


def chunkset_to_ancs_payload(
    chunks: ChunkSet,
    source_uri: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    """Reshape a ChunkSet into ANCS' camelCase ChunkSetInput body."""
    body: dict[str, Any] = {
        "docId": chunks.doc_id,
        "l0": _l0_payload(chunks.l0),
        "l1Chunks": [_l1_payload(c) for c in chunks.l1_chunks],
        "l2Chunks": [_l2_payload(c) for c in chunks.l2_chunks],
        "l3Chunks": [_l3_payload(c) for c in chunks.l3_chunks],
        "knowledgeGraph": [_triple_payload(t) for t in _collect_triples(chunks)],
    }
    if source_uri is not None:
        body["sourceUri"] = source_uri
    if tenant_id is not None:
        body["tenantId"] = tenant_id
    return body


def export_to_ancs(chunks: ChunkSet, config: ANCSConfig) -> ANCSIngestResult:
    """Export a ChunkSet to ANCS via POST /memory/ingest-chunkset.

    ANCS builds the memory items, entities, and hyperedges (including the
    semantic KG edges) server-side. Returns the counts ANCS reports.
    """
    doc_id = chunks.doc_id
    body = chunkset_to_ancs_payload(chunks, config.source_uri, config.tenant_id)
    url = f"{config.base_url.rstrip('/')}/memory/ingest-chunkset"

    logger.info(
        "Exporting ChunkSet %s to ANCS (%d L3, %d triples)",
        doc_id,
        len(body["l3Chunks"]),
        len(body["knowledgeGraph"]),
    )

    try:
        with httpx.Client(timeout=config.timeout) as client:
            resp = client.post(
                url,
                json=body,
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return ANCSIngestResult(
            doc_id=doc_id,
            memory_items_created=data.get("memoryItemsCreated", 0),
            entities_created=data.get("entitiesCreated", 0),
            hyperedges_created=data.get("hyperedgesCreated", 0),
            kg_triples_ingested=data.get("kgTriplesIngested", 0),
        )
    except httpx.HTTPStatusError as e:
        msg = f"ANCS API error {e.response.status_code}: {e.response.text[:200]}"
        logger.error(msg)
        return ANCSIngestResult(doc_id=doc_id, error=msg)
    except httpx.RequestError as e:
        msg = f"ANCS connection error: {e}"
        logger.error(msg)
        return ANCSIngestResult(doc_id=doc_id, error=msg)
