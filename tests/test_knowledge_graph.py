"""Tests for Knowledge Graph / Entity Extraction (Stage 4 enrichment option).

Verifies:
- KG triples are extracted from L3 chunks when enabled
- Triples are deduplicated at the document level
- Per-chunk triples are stored on L3Chunk.kg_triples
- Document-level triples are stored on ChunkSet.knowledge_graph
- Selective re-enrichment copies KG data for unchanged chunks
- Storage round-trip preserves knowledge_graph.json
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.enrichment import (
    KGTriple,
    KGTripleList,
    L0Enrichment,
    L1Enrichment,
    L2Enrichment,
    L3Enrichment,
)
from ingestible.pipeline.stage4_enrichment import enrich_chunks
from ingestible.profiles import ExtractionProfile


def _make_chunks(num_l3: int = 2) -> ChunkSet:
    doc_id = "kg-test"
    l3_chunks = [
        L3Chunk(
            chunk_id=f"{doc_id}-p{i}",
            content=f"Passage {i} discusses transformers and attention mechanisms.",
            content_hash=f"hash{i}",
            position=ChunkPosition(chapter="Ch1", section="Sec1"),
            parent_section_id=f"{doc_id}-s1",
        )
        for i in range(num_l3)
    ]
    return ChunkSet(
        doc_id=doc_id,
        l0=L0Chunk(
            chunk_id=f"{doc_id}-L0",
            title="KG Test Doc",
            total_pages=1,
            total_chapters=1,
            total_sections=1,
            total_passages=num_l3,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id=f"{doc_id}-ch1",
                title="Ch1",
                content="Chapter.",
                children_ids=[f"{doc_id}-s1"],
            )
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id=f"{doc_id}-s1",
                title="Sec1",
                content="Section.",
                parent_chapter_id=f"{doc_id}-ch1",
                children_ids=[c.chunk_id for c in l3_chunks],
            )
        ],
        l3_chunks=l3_chunks,
    )


def _settings() -> Settings:
    return Settings(
        llm_provider="openai",
        openai_api_key="test-key",
        llm_concurrency=1,
        extract_knowledge_graph=True,
    )


def _kg_profile() -> ExtractionProfile:
    return ExtractionProfile(
        name="paper",
        extract_knowledge_graph=True,
    )


def _mock_client_with_kg():
    """Mock LLM client that returns KG triples for L3 and valid results for other levels."""
    client = AsyncMock()
    call_idx = {"l3": 0}

    async def fake_generate(prompt, output_type):
        name = output_type.__name__
        if name == "L3Enrichment":
            return L3Enrichment(
                summary="Summary",
                concepts=["transformers"],
                keywords=["attention"],
            )
        if name == "KGTripleList":
            idx = call_idx["l3"]
            call_idx["l3"] += 1
            triples = [
                KGTriple(
                    subject="Transformer",
                    subject_type="Method",
                    predicate="uses",
                    object="Attention",
                    object_type="Concept",
                    confidence=0.9,
                ),
            ]
            # Second chunk adds a duplicate + a unique triple
            if idx >= 1:
                triples.append(
                    KGTriple(
                        subject="Transformer",
                        subject_type="Method",
                        predicate="uses",
                        object="Attention",
                        object_type="Concept",
                        confidence=1.0,  # higher confidence duplicate
                    )
                )
                triples.append(
                    KGTriple(
                        subject="BERT",
                        subject_type="Method",
                        predicate="is_a",
                        object="Transformer",
                        object_type="Method",
                        confidence=0.95,
                    )
                )
            return KGTripleList(triples=triples)
        if name == "L2Enrichment":
            return L2Enrichment(section_summary="Sec summary")
        if name == "L1Enrichment":
            return L1Enrichment(chapter_summary="Ch summary")
        if name == "L0Enrichment":
            return L0Enrichment(domain="ML", executive_summary="About ML")
        return output_type()

    client.generate_json.side_effect = fake_generate
    return client


class TestKGExtraction:
    """Core KG extraction tests."""

    def test_kg_triples_extracted_when_enabled(self):
        """KG triples are extracted and stored on chunks + ChunkSet."""
        chunks = _make_chunks(num_l3=2)
        client = _mock_client_with_kg()
        profile = _kg_profile()

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client), \
             patch("ingestible.pipeline.stage4_enrichment._make_cheap_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), profile=profile))

        # Per-chunk triples stored
        assert len(result.l3_chunks[0].kg_triples) >= 1
        assert result.l3_chunks[0].kg_triples[0].subject == "Transformer"
        assert result.l3_chunks[0].kg_triples[0].source_chunk_id == "kg-test-p0"

        # Document-level deduplicated triples
        assert (
            len(result.knowledge_graph) == 2
        )  # "Transformer uses Attention" + "BERT is_a Transformer"

    def test_kg_deduplication_keeps_highest_confidence(self):
        """Duplicate triples are deduplicated, keeping highest confidence."""
        chunks = _make_chunks(num_l3=2)
        client = _mock_client_with_kg()
        profile = _kg_profile()

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client), \
             patch("ingestible.pipeline.stage4_enrichment._make_cheap_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), profile=profile))

        # Find the "Transformer uses Attention" triple
        tu = [
            t
            for t in result.knowledge_graph
            if t.subject.lower() == "transformer" and t.predicate.lower() == "uses"
        ]
        assert len(tu) == 1
        assert tu[0].confidence == 1.0  # highest confidence kept

    def test_kg_not_extracted_when_disabled(self):
        """When extract_knowledge_graph is False, no KG extraction occurs."""
        chunks = _make_chunks(num_l3=2)
        client = _mock_client_with_kg()
        profile = ExtractionProfile(name="general", extract_knowledge_graph=False)
        settings = Settings(
            llm_provider="openai",
            openai_api_key="test-key",
            llm_concurrency=1,
            extract_knowledge_graph=False,
        )

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client), \
             patch("ingestible.pipeline.stage4_enrichment._make_cheap_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, settings, profile=profile))

        assert result.knowledge_graph == []
        for c in result.l3_chunks:
            assert c.kg_triples == []

    def test_kg_enabled_via_settings_override(self):
        """extract_knowledge_graph in Settings enables KG even if profile doesn't."""
        chunks = _make_chunks(num_l3=1)
        client = _mock_client_with_kg()
        profile = ExtractionProfile(name="general", extract_knowledge_graph=False)
        settings = Settings(
            llm_provider="openai",
            openai_api_key="test-key",
            llm_concurrency=1,
            extract_knowledge_graph=True,
        )

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client), \
             patch("ingestible.pipeline.stage4_enrichment._make_cheap_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, settings, profile=profile))

        assert len(result.knowledge_graph) >= 1


class TestKGSelectiveReEnrichment:
    """KG triples with selective re-enrichment."""

    def test_kg_reused_when_all_unchanged(self):
        """When all L3 are unchanged, KG triples are copied from previous."""
        chunks = _make_chunks(num_l3=2)
        previous = chunks.model_copy(deep=True)

        # Populate previous with enrichment + KG
        for c in previous.l3_chunks:
            c.summary = "Previous summary"
            c.kg_triples = [
                KGTriple(
                    subject="X",
                    predicate="relates_to",
                    object="Y",
                    source_chunk_id=c.chunk_id,
                )
            ]
        previous.knowledge_graph = [
            KGTriple(subject="X", predicate="relates_to", object="Y"),
        ]
        previous.l0.executive_summary = "Prev"
        previous.l0.domain = "test"
        for c in previous.l2_chunks:
            c.section_summary = "Prev sec"
        for c in previous.l1_chunks:
            c.chapter_summary = "Prev ch"

        client = _mock_client_with_kg()
        profile = _kg_profile()

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client), \
             patch("ingestible.pipeline.stage4_enrichment._make_cheap_client", return_value=client):
            result = asyncio.run(
                enrich_chunks(
                    chunks,
                    _settings(),
                    profile=profile,
                    previous_chunks=previous,
                )
            )

        # KG copied from previous (no LLM calls)
        assert len(result.knowledge_graph) == 1
        assert result.knowledge_graph[0].subject == "X"
        # Per-chunk triples also copied
        assert len(result.l3_chunks[0].kg_triples) == 1


class TestKGStorageRoundTrip:
    """KG triples survive save/load cycle."""

    def test_kg_roundtrip(self, tmp_path):
        from ingestible.models.document import DocumentStructure, StructureNode
        from ingestible.pipeline.stage6_storage import load_chunks, save_document

        chunks = _make_chunks(num_l3=1)
        chunks.l3_chunks[0].kg_triples = [
            KGTriple(
                subject="Python",
                subject_type="Technology",
                predicate="is_a",
                object="Programming Language",
                object_type="Concept",
                confidence=1.0,
                source_chunk_id="kg-test-p0",
            ),
        ]
        chunks.knowledge_graph = [
            KGTriple(
                subject="Python",
                subject_type="Technology",
                predicate="is_a",
                object="Programming Language",
                object_type="Concept",
                confidence=1.0,
                source_chunk_id="kg-test-p0",
            ),
        ]

        structure = DocumentStructure(
            doc_id="kg-test",
            title="KG Test",
            root=StructureNode(id="kg-test", title="KG Test", level=0),
        )
        settings = Settings(data_dir=tmp_path)
        doc_dir = save_document(structure, chunks, settings)

        # knowledge_graph.json written
        kg_path = doc_dir / "knowledge_graph.json"
        assert kg_path.exists()
        kg_data = json.loads(kg_path.read_text())
        assert len(kg_data["triples"]) == 1
        assert kg_data["triples"][0]["subject"] == "Python"

        # Load roundtrip
        loaded = load_chunks(doc_dir)
        assert len(loaded.knowledge_graph) == 1
        assert loaded.knowledge_graph[0].subject == "Python"
        assert loaded.knowledge_graph[0].confidence == 1.0

        # Per-chunk triples also roundtrip
        assert len(loaded.l3_chunks[0].kg_triples) == 1
        assert loaded.l3_chunks[0].kg_triples[0].predicate == "is_a"
