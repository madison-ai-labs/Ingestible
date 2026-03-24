"""Export to complete JSON — full L0–L3 hierarchy, KG triples, and concepts graph.

Produces a single self-contained JSON file suitable for embedding in other
applications. Unlike JSONL/Parquet exports (L3-only), this format preserves
the entire document structure and knowledge graph.
"""

from __future__ import annotations

import json
from pathlib import Path

from ingestible.models.chunks import ChunkSet


def export_complete(chunks: ChunkSet, output_path: Path, doc_title: str = "") -> Path:
    """Export the full chunk hierarchy + knowledge graph to a single JSON file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = _build_document(chunks, doc_title)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)

    return output_path


def export_complete_corpus(
    documents: list[tuple[ChunkSet, str]],
    output_path: Path,
) -> Path:
    """Export multiple documents into a single corpus-level JSON file.

    Args:
        documents: List of (ChunkSet, doc_title) tuples.
        output_path: Where to write the output.

    Returns:
        The output path.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    corpus = {
        "format": "ingestible-corpus",
        "version": 1,
        "document_count": len(documents),
        "documents": [_build_document(chunks, title) for chunks, title in documents],
        "corpus_graph": _build_corpus_graph(documents),
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(corpus, f, ensure_ascii=False, indent=2)

    return output_path


def _build_document(chunks: ChunkSet, doc_title: str) -> dict:
    """Build a complete document representation."""
    l0 = chunks.l0

    # Index L2 chunks by parent chapter for hierarchy nesting
    l2_by_chapter: dict[str, list] = {}
    for l2 in chunks.l2_chunks:
        l2_by_chapter.setdefault(l2.parent_chapter_id, []).append(l2)

    # Index L3 chunks by parent section for hierarchy nesting
    l3_by_section: dict[str, list] = {}
    for l3 in chunks.l3_chunks:
        l3_by_section.setdefault(l3.parent_section_id, []).append(l3)

    # Build hierarchical chapter → section → passage tree
    chapters = []
    for l1 in chunks.l1_chunks:
        sections = []
        for l2 in l2_by_chapter.get(l1.chunk_id, []):
            passages = []
            for l3 in l3_by_section.get(l2.chunk_id, []):
                passages.append(_serialize_l3(l3))
            sections.append(_serialize_l2(l2, passages))
        chapters.append(_serialize_l1(l1, sections))

    # Orphan passages (not under any section)
    orphan_passages = [
        _serialize_l3(l3) for l3 in l3_by_section.get("", [])
    ]

    # Collect all concepts across all levels
    all_concepts = _collect_concepts(chunks)

    return {
        "format": "ingestible-complete",
        "version": 1,
        "doc_id": chunks.doc_id,
        "title": doc_title or l0.title,
        "author": l0.author,
        "domain": l0.domain,
        "document_type": l0.document_type,
        "executive_summary": l0.executive_summary,
        "key_concepts": l0.key_concepts,
        "key_findings": l0.key_findings,
        "target_audience": l0.target_audience,
        "methodology": l0.methodology,
        "limitations": l0.limitations,
        "stats": {
            "total_pages": l0.total_pages,
            "total_chapters": l0.total_chapters or len(chunks.l1_chunks),
            "total_sections": l0.total_sections or len(chunks.l2_chunks),
            "total_passages": l0.total_passages or len(chunks.l3_chunks),
        },
        "chapters": chapters,
        "orphan_passages": orphan_passages,
        "knowledge_graph": _serialize_kg(chunks),
        "concepts": all_concepts,
        "citations": [
            {
                "citation_id": c.citation_id,
                "authors": c.authors,
                "title": c.title,
                "year": c.year,
                "venue": c.venue,
                "doi": c.doi,
            }
            for c in chunks.citations
        ],
    }


def _serialize_l1(l1, sections: list) -> dict:
    return {
        "id": l1.chunk_id,
        "level": 1,
        "title": l1.title,
        "summary": l1.chapter_summary,
        "main_topics": l1.main_topics,
        "key_takeaways": l1.key_takeaways,
        "page_start": l1.page_start,
        "page_end": l1.page_end,
        "sections": sections,
    }


def _serialize_l2(l2, passages: list) -> dict:
    return {
        "id": l2.chunk_id,
        "level": 2,
        "title": l2.title,
        "summary": l2.section_summary,
        "key_points": l2.key_points,
        "concepts_introduced": l2.concepts_introduced,
        "page_start": l2.page_start,
        "page_end": l2.page_end,
        "passages": passages,
    }


def _serialize_l3(l3) -> dict:
    result = {
        "id": l3.chunk_id,
        "level": 3,
        "content": l3.content,
        "summary": l3.summary,
        "concepts": l3.concepts,
        "keywords": l3.keywords,
        "page_start": l3.page_start,
        "page_end": l3.page_end,
    }
    if l3.hypothetical_questions:
        result["hypothetical_questions"] = l3.hypothetical_questions
    if l3.difficulty_level:
        result["difficulty_level"] = l3.difficulty_level
    if l3.depends_on:
        result["depends_on"] = l3.depends_on
    if l3.cross_references:
        result["cross_references"] = l3.cross_references
    if l3.kg_triples:
        result["kg_triples"] = [
            {
                "subject": t.subject,
                "predicate": t.predicate,
                "object": t.object,
                "confidence": t.confidence,
            }
            for t in l3.kg_triples
        ]
    if l3.content_tier != "T3":
        result["content_tier"] = l3.content_tier
    if l3.context_prefix:
        result["context_prefix"] = l3.context_prefix
    return result


def _serialize_kg(chunks: ChunkSet) -> dict:
    """Build a complete knowledge graph with entity index."""
    triples = chunks.knowledge_graph
    if not triples:
        return {"triples": [], "entities": {}}

    # Serialize triples
    triple_list = [
        {
            "subject": t.subject,
            "subject_type": t.subject_type,
            "predicate": t.predicate,
            "object": t.object,
            "object_type": t.object_type,
            "confidence": t.confidence,
            "source_chunk_id": t.source_chunk_id,
        }
        for t in triples
    ]

    # Build entity index: entity -> {type, relations, chunk_ids}
    entities: dict[str, dict] = {}
    for t in triples:
        for name, etype in [(t.subject, t.subject_type), (t.object, t.object_type)]:
            key = name.lower()
            if key not in entities:
                entities[key] = {
                    "name": name,
                    "type": etype,
                    "relations": [],
                    "source_chunks": set(),
                }
            if t.source_chunk_id:
                entities[key]["source_chunks"].add(t.source_chunk_id)

        subj_key = t.subject.lower()
        obj_key = t.object.lower()
        entities[subj_key]["relations"].append(
            {"predicate": t.predicate, "target": t.object, "direction": "outgoing"}
        )
        entities[obj_key]["relations"].append(
            {"predicate": t.predicate, "target": t.subject, "direction": "incoming"}
        )

    # Convert sets to lists for JSON serialization
    for entity in entities.values():
        entity["source_chunks"] = sorted(entity["source_chunks"])

    return {
        "triples": triple_list,
        "entities": entities,
    }


def _collect_concepts(chunks: ChunkSet) -> dict:
    """Build a concept frequency map across all levels."""
    concept_counts: dict[str, int] = {}
    concept_chunks: dict[str, list[str]] = {}

    # L0 concepts
    for c in chunks.l0.key_concepts:
        key = c.lower()
        concept_counts[key] = concept_counts.get(key, 0) + 1

    # L2 concepts
    for l2 in chunks.l2_chunks:
        for c in l2.concepts_introduced:
            key = c.lower()
            concept_counts[key] = concept_counts.get(key, 0) + 1
            concept_chunks.setdefault(key, []).append(l2.chunk_id)

    # L3 concepts
    for l3 in chunks.l3_chunks:
        for c in l3.concepts:
            key = c.lower()
            concept_counts[key] = concept_counts.get(key, 0) + 1
            concept_chunks.setdefault(key, []).append(l3.chunk_id)

    # Sort by frequency descending
    sorted_concepts = sorted(concept_counts.items(), key=lambda x: -x[1])

    return {
        "by_frequency": [
            {"concept": name, "count": count, "chunks": concept_chunks.get(name, [])}
            for name, count in sorted_concepts
        ],
        "total_unique": len(sorted_concepts),
    }


def _build_corpus_graph(documents: list[tuple[ChunkSet, str]]) -> dict:
    """Build a cross-document entity graph for the corpus."""
    # Merge all KG triples across documents, tracking which doc each came from
    entity_docs: dict[str, set[str]] = {}

    for chunks, _ in documents:
        for t in chunks.knowledge_graph:
            subj_key = t.subject.lower()
            obj_key = t.object.lower()
            entity_docs.setdefault(subj_key, set()).add(chunks.doc_id)
            entity_docs.setdefault(obj_key, set()).add(chunks.doc_id)

    # Find entities that appear in multiple documents (cross-document links)
    shared_entities = {
        name: sorted(docs) for name, docs in entity_docs.items() if len(docs) > 1
    }

    return {
        "shared_entities": shared_entities,
        "total_entities": len(entity_docs),
        "cross_document_entities": len(shared_entities),
    }
