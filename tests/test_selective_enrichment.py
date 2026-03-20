"""Tests for selective re-enrichment (P0).

Verifies that unchanged L3 chunks skip LLM enrichment by copying fields
from the previous version, and that L2/L1/L0 enrichment is skipped when
all L3 chunks are unchanged.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from ingestible.config import Settings
from ingestible.models.chunks import (
    ChunkPosition,
    ChunkSet,
    L0Chunk,
    L1Chunk,
    L2Chunk,
    L3Chunk,
)
from ingestible.models.enrichment import L3Enrichment
from ingestible.pipeline.stage4_enrichment import enrich_chunks


def _make_chunks(doc_id: str = "test-doc", num_l3: int = 3) -> ChunkSet:
    """Build a minimal ChunkSet with N L3 chunks."""
    l3_chunks = []
    for i in range(num_l3):
        l3_chunks.append(
            L3Chunk(
                chunk_id=f"{doc_id}-p{i}",
                content=f"Content of passage {i}.",
                content_hash=f"hash{i}",
                position=ChunkPosition(chapter="Ch1", section="Sec1"),
                parent_section_id=f"{doc_id}-s1",
            )
        )

    l2 = L2Chunk(
        chunk_id=f"{doc_id}-s1",
        title="Section 1",
        content="Section content",
        parent_chapter_id=f"{doc_id}-ch1",
        children_ids=[c.chunk_id for c in l3_chunks],
    )
    l1 = L1Chunk(
        chunk_id=f"{doc_id}-ch1",
        title="Chapter 1",
        content="Chapter content",
        children_ids=[l2.chunk_id],
    )
    l0 = L0Chunk(
        chunk_id=f"{doc_id}-L0",
        title="Test Doc",
        total_pages=1,
        total_chapters=1,
        total_sections=1,
        total_passages=num_l3,
    )
    return ChunkSet(
        doc_id=doc_id,
        l0=l0,
        l1_chunks=[l1],
        l2_chunks=[l2],
        l3_chunks=l3_chunks,
    )


def _make_enriched_previous(chunks: ChunkSet) -> ChunkSet:
    """Deep-copy a ChunkSet and add enrichment fields to simulate a previous run."""
    prev = chunks.model_copy(deep=True)
    for c in prev.l3_chunks:
        c.summary = f"Previous summary for {c.chunk_id}"
        c.concepts = ["concept-a", "concept-b"]
        c.hypothetical_questions = ["Q1?", "Q2?"]
        c.keywords = ["keyword"]
        c.difficulty_level = "intermediate"
    for c in prev.l2_chunks:
        c.section_summary = "Previous section summary"
        c.key_points = ["point1"]
    for c in prev.l1_chunks:
        c.chapter_summary = "Previous chapter summary"
        c.main_topics = ["topic1"]
    prev.l0.executive_summary = "Previous executive summary"
    prev.l0.domain = "testing"
    prev.l0.key_concepts = ["concept-a"]
    return prev


def _mock_llm_client():
    """Create a mock LLM client that counts calls."""
    client = AsyncMock()

    async def fake_generate(prompt, output_type):
        if output_type.__name__ == "L3Enrichment":
            return L3Enrichment(
                summary="New LLM summary",
                concepts=["new-concept"],
                hypothetical_questions=["New Q?"],
                keywords=["new-kw"],
                difficulty_level="beginner",
                depends_on=[],
                cross_references=[],
                cited_references=[],
            )
        # Return a minimal valid instance for any other type
        return output_type.model_validate(
            {k: "" if f.annotation is str else [] for k, f in output_type.model_fields.items()}
        )

    client.generate_json.side_effect = fake_generate
    return client


def _settings() -> Settings:
    return Settings(
        llm_provider="openai",
        openai_api_key="test-key",
        llm_concurrency=1,
    )


class TestSelectiveEnrichmentL3:
    """Tests for L3 chunk skip logic."""

    def test_all_unchanged_skips_all_llm_calls(self):
        """When all L3 hashes match previous, zero LLM calls for L3."""
        chunks = _make_chunks(num_l3=3)
        previous = _make_enriched_previous(chunks)
        client = _mock_llm_client()

        from unittest.mock import patch

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), previous_chunks=previous))

        # All L3 chunks should have copied enrichment, no LLM calls for L3
        for c in result.l3_chunks:
            assert c.summary.startswith("Previous summary for")
            assert c.concepts == ["concept-a", "concept-b"]

        # No generate_json calls at all (L2/L1/L0 also skipped)
        assert client.generate_json.call_count == 0

    def test_some_changed_only_enriches_changed(self):
        """When 1 of 3 L3 chunks changed, only 1 LLM call for L3."""
        chunks = _make_chunks(num_l3=3)
        previous = _make_enriched_previous(chunks)

        # Change one chunk's hash to simulate content change
        chunks.l3_chunks[1].content_hash = "changed-hash"

        client = _mock_llm_client()

        from unittest.mock import patch

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), previous_chunks=previous))

        # Unchanged chunks got previous enrichment
        assert result.l3_chunks[0].summary == "Previous summary for test-doc-p0"
        assert result.l3_chunks[2].summary == "Previous summary for test-doc-p2"

        # Changed chunk got new LLM enrichment
        assert result.l3_chunks[1].summary == "New LLM summary"
        assert result.l3_chunks[1].concepts == ["new-concept"]

    def test_no_previous_enriches_all(self):
        """Without previous_chunks, all L3 chunks get LLM enrichment."""
        chunks = _make_chunks(num_l3=2)
        client = _mock_llm_client()

        from unittest.mock import patch

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), previous_chunks=None))

        for c in result.l3_chunks:
            assert c.summary == "New LLM summary"

        # L3 calls + L2 + L1 + L0 = at least 2 + 3
        assert client.generate_json.call_count >= 2

    def test_previous_without_enrichment_not_reused(self):
        """Previous chunks without enrichment (empty summary) are NOT reused."""
        chunks = _make_chunks(num_l3=2)
        previous = chunks.model_copy(deep=True)
        # Previous has matching hashes but no enrichment (empty summary)

        client = _mock_llm_client()

        from unittest.mock import patch

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), previous_chunks=previous))

        # Should have called LLM since previous had no enrichment
        for c in result.l3_chunks:
            assert c.summary == "New LLM summary"


class TestSelectiveEnrichmentUpperLevels:
    """Tests for L2/L1/L0 skip logic when all L3 are unchanged."""

    def test_all_l3_unchanged_copies_upper_enrichment(self):
        """When all L3 unchanged, L2/L1/L0 enrichment is copied, not re-computed."""
        chunks = _make_chunks(num_l3=2)
        previous = _make_enriched_previous(chunks)
        client = _mock_llm_client()

        from unittest.mock import patch

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, _settings(), previous_chunks=previous))

        # L2
        assert result.l2_chunks[0].section_summary == "Previous section summary"
        assert result.l2_chunks[0].key_points == ["point1"]

        # L1
        assert result.l1_chunks[0].chapter_summary == "Previous chapter summary"

        # L0
        assert result.l0.executive_summary == "Previous executive summary"
        assert result.l0.domain == "testing"

        # Zero LLM calls total
        assert client.generate_json.call_count == 0

    def test_some_l3_changed_re_enriches_upper(self):
        """When some L3 changed, L2/L1/L0 are re-enriched (not copied)."""
        chunks = _make_chunks(num_l3=3)
        previous = _make_enriched_previous(chunks)
        chunks.l3_chunks[0].content_hash = "changed"

        client = _mock_llm_client()

        from unittest.mock import patch

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            asyncio.run(enrich_chunks(chunks, _settings(), previous_chunks=previous))

        # L2/L1/L0 should have been re-enriched via LLM
        # 1 L3 + 1 L2 + 1 L1 + 1 L0 = 4 calls
        assert client.generate_json.call_count == 4


class TestTargetedReEnrichment:
    """Tests for re_enrich() with changed_chunk_ids."""

    def test_targeted_re_enrich_only_changes_specified_chunks(self, tmp_path):
        """re_enrich with changed_chunk_ids only re-enriches those chunks."""
        from ingestible.models.document import DocumentStructure, StructureNode
        from ingestible.pipeline.re_enrich import re_enrich
        from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
        from ingestible.pipeline.stage6_storage import load_chunks, save_document

        doc_id = "test-doc"
        settings = Settings(data_dir=tmp_path)

        # Create doc with 2 enriched L3 chunks
        chunks = _make_chunks(doc_id=doc_id, num_l3=2)
        for c in chunks.l3_chunks:
            c.summary = f"Original summary for {c.chunk_id}"
            c.concepts = ["original"]
            c.content_hash = f"hash-{c.chunk_id}"

        root = StructureNode(id=doc_id, title="Test Doc", level=0)
        structure = DocumentStructure(doc_id=doc_id, title="Test Doc", root=root)
        save_document(structure, chunks, settings, content_hash="abc")

        embedder = Embedder(settings)
        doc_dir = settings.documents_dir / doc_id
        build_indexes(chunks, doc_dir, embedder)

        # Target only chunk p0 for re-enrichment
        # Enrichment will fail (no real LLM key), but p1 should keep its summary
        # because it's treated as "unchanged" via the synthetic previous_chunks
        result_dir = re_enrich(doc_id, settings, changed_chunk_ids={f"{doc_id}-p0"})
        result = load_chunks(result_dir)

        # p1 should keep original summary (unchanged, copied from "previous")
        assert result.l3_chunks[1].summary == f"Original summary for {doc_id}-p1"
        assert result.l3_chunks[1].concepts == ["original"]

        # p0 summary should indicate failure (enrichment failed, no LLM key)
        assert result.l3_chunks[0].summary in ("", "[enrichment failed]")

    def test_full_re_enrich_clears_all(self, tmp_path):
        """re_enrich without changed_chunk_ids clears all enrichment."""
        from ingestible.models.document import DocumentStructure, StructureNode
        from ingestible.pipeline.re_enrich import re_enrich
        from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
        from ingestible.pipeline.stage6_storage import load_chunks, save_document

        doc_id = "test-doc"
        settings = Settings(data_dir=tmp_path)

        chunks = _make_chunks(doc_id=doc_id, num_l3=2)
        for c in chunks.l3_chunks:
            c.summary = "Should be cleared"
            c.content_hash = f"hash-{c.chunk_id}"

        root = StructureNode(id=doc_id, title="Test Doc", level=0)
        structure = DocumentStructure(doc_id=doc_id, title="Test Doc", root=root)
        save_document(structure, chunks, settings, content_hash="abc")

        embedder = Embedder(settings)
        build_indexes(chunks, settings.documents_dir / doc_id, embedder)

        result_dir = re_enrich(doc_id, settings)
        result = load_chunks(result_dir)

        # All enrichment cleared (LLM call fails, no key)
        for c in result.l3_chunks:
            assert c.summary in ("", "[enrichment failed]")
