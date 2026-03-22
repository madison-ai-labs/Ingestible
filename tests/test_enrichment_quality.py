"""Enrichment quality tests — validate LLM enrichment output meets quality bar.

Uses a mock LLM client that returns realistic enrichment data, then validates
the output structure, content coherence, and enrichment propagation through
the L3 → L2 → L1 → L0 pipeline.

Run with:  pytest tests/test_enrichment_quality.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

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
    L0Enrichment,
    L1Enrichment,
    L2Enrichment,
    L3Enrichment,
)
from ingestible.pipeline.stage4_enrichment import enrich_chunks

# ---------------------------------------------------------------------------
# Realistic mock LLM client
# ---------------------------------------------------------------------------


def _mock_llm_client():
    """Return a mock LLM client that produces realistic enrichment output
    based on input content keywords."""

    async def generate_json(prompt: str, output_type):
        prompt_lower = prompt.lower()

        if output_type == L3Enrichment:
            concepts = []
            # Check ocean/marine first — some ocean chunks also mention "machine learning"
            if "ocean" in prompt_lower or "marine" in prompt_lower or "coral" in prompt_lower:
                concepts = ["marine biology", "ocean ecosystems", "biodiversity"]
                questions = [
                    "What is marine biodiversity?",
                    "How do ocean ecosystems function?",
                    "Why are coral reefs important?",
                ]
                keywords = ["ocean", "marine", "biodiversity", "coral"]
                difficulty = "beginner"
            elif "machine learning" in prompt_lower or "training" in prompt_lower:
                concepts = ["machine learning", "training data", "algorithms"]
                questions = [
                    "What is machine learning?",
                    "How do algorithms learn from data?",
                    "What types of training data exist?",
                ]
                keywords = ["machine", "learning", "training", "algorithm"]
                difficulty = "intermediate"
            else:
                concepts = ["general topic", "analysis"]
                questions = [
                    "What is this passage about?",
                    "What are the key points?",
                ]
                keywords = ["topic", "analysis"]
                difficulty = "beginner"

            return L3Enrichment(
                summary=f"This passage covers {', '.join(concepts[:2])}.",
                concepts=concepts,
                hypothetical_questions=questions,
                keywords=keywords,
                difficulty_level=difficulty,
                depends_on=[],
                cross_references=[],
                cited_references=[],
            )

        elif output_type == L2Enrichment:
            return L2Enrichment(
                section_summary="This section provides an overview of the topic.",
                key_points=["Point A", "Point B", "Point C"],
                concepts_introduced=["concept-alpha", "concept-beta"],
            )

        elif output_type == L1Enrichment:
            return L1Enrichment(
                chapter_summary="This chapter covers the foundational concepts.",
                main_topics=["foundations", "methodology"],
                learning_objectives=["Understand core principles"],
                prerequisite_chapters=[],
                key_takeaways=["Key insight about the domain"],
            )

        elif output_type == L0Enrichment:
            return L0Enrichment(
                domain="computer science",
                key_concepts=["machine learning", "data science", "algorithms"],
                executive_summary="A comprehensive overview of the field.",
                key_findings=["Finding one", "Finding two"],
                methodology="Survey and analysis",
                limitations="Limited to English-language sources",
                document_type="documentation",
                target_audience="Software engineers and data scientists",
            )

        raise ValueError(f"Unexpected output_type: {output_type}")

    client = AsyncMock()
    client.generate_json = generate_json
    return client


def _build_test_chunks() -> ChunkSet:
    """Build a ChunkSet with realistic content for enrichment testing."""
    return ChunkSet(
        doc_id="enrich-test",
        l0=L0Chunk(
            chunk_id="enrich-test-L0",
            title="ML Handbook",
            total_pages=50,
            total_chapters=2,
            total_sections=3,
            total_passages=4,
        ),
        l1_chunks=[
            L1Chunk(
                chunk_id="ch1",
                title="Fundamentals",
                content="Machine learning fundamentals chapter.",
                page_start=1,
                page_end=25,
                children_ids=["sec1", "sec2"],
            ),
            L1Chunk(
                chunk_id="ch2",
                title="Applications",
                content="Ocean and environmental applications.",
                page_start=26,
                page_end=50,
                children_ids=["sec3"],
            ),
        ],
        l2_chunks=[
            L2Chunk(
                chunk_id="sec1",
                title="Introduction to ML",
                content="Machine learning is a field of AI.",
                parent_chapter_id="ch1",
                children_ids=["p0", "p1"],
            ),
            L2Chunk(
                chunk_id="sec2",
                title="Training Methods",
                content="Training methods for models.",
                parent_chapter_id="ch1",
                children_ids=["p2"],
            ),
            L2Chunk(
                chunk_id="sec3",
                title="Marine Applications",
                content="Ocean monitoring with ML.",
                parent_chapter_id="ch2",
                children_ids=["p3"],
            ),
        ],
        l3_chunks=[
            L3Chunk(
                chunk_id="p0",
                content="Machine learning algorithms learn patterns from large datasets. "
                "Training data is essential for supervised learning approaches.",
                parent_section_id="sec1",
                position=ChunkPosition(chapter="ch1", section="sec1", index=0),
            ),
            L3Chunk(
                chunk_id="p1",
                content="Neural networks use backpropagation for training. "
                "Gradient descent optimizes the loss function iteratively.",
                parent_section_id="sec1",
                position=ChunkPosition(chapter="ch1", section="sec1", index=1),
            ),
            L3Chunk(
                chunk_id="p2",
                content="Transfer learning reuses pretrained model weights. "
                "Fine-tuning adapts models to new training tasks.",
                parent_section_id="sec2",
                position=ChunkPosition(chapter="ch1", section="sec2", index=0),
            ),
            L3Chunk(
                chunk_id="p3",
                content="Ocean monitoring uses machine learning for marine ecosystem analysis. "
                "Coral reef health is tracked using underwater sensors.",
                parent_section_id="sec3",
                position=ChunkPosition(chapter="ch2", section="sec3", index=0),
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEnrichmentQuality:
    @pytest.fixture
    def enriched_chunks(self, tmp_path):
        """Run the full enrichment pipeline with mock LLM and return result."""
        settings = Settings(
            data_dir=tmp_path,
            llm_concurrency=2,
            llm_max_retries=1,
            llm_retry_base_delay=0.0,
        )
        chunks = _build_test_chunks()
        client = _mock_llm_client()

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, settings))
        return result

    # --- L3 quality checks ---

    def test_l3_summaries_non_empty(self, enriched_chunks):
        """Every L3 chunk must have a non-empty summary after enrichment."""
        for c in enriched_chunks.l3_chunks:
            assert c.summary, f"L3 {c.chunk_id} has empty summary"
            assert len(c.summary) >= 10, f"L3 {c.chunk_id} summary too short: {c.summary!r}"

    def test_l3_summaries_not_boilerplate(self, enriched_chunks):
        """Summaries must not all be identical (sign of a broken LLM mock)."""
        summaries = [c.summary for c in enriched_chunks.l3_chunks]
        unique = set(summaries)
        # With 4 chunks spanning 2 topics, we should get at least 2 distinct summaries
        assert len(unique) >= 2, (
            f"Only {len(unique)} unique summaries across {len(summaries)} chunks — "
            "enrichment is producing identical output"
        )

    def test_l3_concepts_extracted(self, enriched_chunks):
        """Every L3 chunk should have at least 1 concept."""
        for c in enriched_chunks.l3_chunks:
            assert len(c.concepts) >= 1, f"L3 {c.chunk_id} has no concepts"

    def test_l3_hypothetical_questions(self, enriched_chunks):
        """Every L3 chunk should have 2+ hypothetical questions."""
        for c in enriched_chunks.l3_chunks:
            assert len(c.hypothetical_questions) >= 2, (
                f"L3 {c.chunk_id} has {len(c.hypothetical_questions)} questions, expected ≥2"
            )
            # Each question should end with a question mark
            for q in c.hypothetical_questions:
                assert q.endswith("?"), f"Question doesn't end with '?': {q!r}"

    def test_l3_keywords_present(self, enriched_chunks):
        """Every L3 chunk should have keywords."""
        for c in enriched_chunks.l3_chunks:
            assert len(c.keywords) >= 1, f"L3 {c.chunk_id} has no keywords"

    def test_l3_difficulty_valid(self, enriched_chunks):
        """Difficulty level must be one of the valid values."""
        valid_levels = {"beginner", "intermediate", "advanced"}
        for c in enriched_chunks.l3_chunks:
            assert c.difficulty_level in valid_levels, (
                f"L3 {c.chunk_id} has invalid difficulty: {c.difficulty_level!r}"
            )

    def test_l3_topic_coherence(self, enriched_chunks):
        """Chunks about ML should have ML-related concepts, ocean chunks should have ocean concepts."""
        for c in enriched_chunks.l3_chunks:
            content_lower = c.content.lower()
            concepts_joined = " ".join(c.concepts).lower()

            if "ocean" in content_lower or "marine" in content_lower:
                assert any(
                    term in concepts_joined
                    for term in ["marine", "ocean", "biodiversity", "ecosystem"]
                ), f"Ocean chunk {c.chunk_id} has no ocean-related concepts: {c.concepts}"
            elif "machine learning" in content_lower or "neural" in content_lower:
                assert any(
                    term in concepts_joined
                    for term in ["machine", "learning", "training", "algorithm"]
                ), f"ML chunk {c.chunk_id} has no ML-related concepts: {c.concepts}"

    # --- L2 quality checks ---

    def test_l2_section_summaries(self, enriched_chunks):
        """Every L2 chunk should have a section summary."""
        for c in enriched_chunks.l2_chunks:
            assert c.section_summary, f"L2 {c.chunk_id} has empty section_summary"

    def test_l2_key_points(self, enriched_chunks):
        """Every L2 chunk should have at least 1 key point."""
        for c in enriched_chunks.l2_chunks:
            assert len(c.key_points) >= 1, f"L2 {c.chunk_id} has no key_points"

    def test_l2_concepts_introduced(self, enriched_chunks):
        """Every L2 chunk should have concepts_introduced."""
        for c in enriched_chunks.l2_chunks:
            assert len(c.concepts_introduced) >= 1, f"L2 {c.chunk_id} has no concepts_introduced"

    # --- L1 quality checks ---

    def test_l1_chapter_summaries(self, enriched_chunks):
        """Every L1 chunk should have a chapter summary."""
        for c in enriched_chunks.l1_chunks:
            assert c.chapter_summary, f"L1 {c.chunk_id} has empty chapter_summary"
            assert len(c.chapter_summary) >= 20, f"L1 {c.chunk_id} chapter_summary too short"

    def test_l1_main_topics(self, enriched_chunks):
        """Every L1 chunk should have at least 1 main topic."""
        for c in enriched_chunks.l1_chunks:
            assert len(c.main_topics) >= 1, f"L1 {c.chunk_id} has no main_topics"

    def test_l1_learning_objectives(self, enriched_chunks):
        """Every L1 chunk should have learning objectives."""
        for c in enriched_chunks.l1_chunks:
            assert len(c.learning_objectives) >= 1, f"L1 {c.chunk_id} has no learning_objectives"

    def test_l1_key_takeaways(self, enriched_chunks):
        """Every L1 chunk should have key takeaways."""
        for c in enriched_chunks.l1_chunks:
            assert len(c.key_takeaways) >= 1, f"L1 {c.chunk_id} has no key_takeaways"

    # --- L0 quality checks ---

    def test_l0_domain(self, enriched_chunks):
        """L0 must have a domain."""
        assert enriched_chunks.l0.domain, "L0 has empty domain"

    def test_l0_key_concepts(self, enriched_chunks):
        """L0 must have at least 3 key concepts."""
        assert len(enriched_chunks.l0.key_concepts) >= 3, (
            f"L0 has only {len(enriched_chunks.l0.key_concepts)} key concepts"
        )

    def test_l0_executive_summary(self, enriched_chunks):
        """L0 must have a non-trivial executive summary."""
        assert enriched_chunks.l0.executive_summary, "L0 has empty executive_summary"
        assert len(enriched_chunks.l0.executive_summary) >= 20, "L0 executive_summary too short"

    def test_l0_key_findings(self, enriched_chunks):
        """L0 must have at least 1 key finding."""
        assert len(enriched_chunks.l0.key_findings) >= 1, "L0 has no key_findings"

    def test_l0_document_type_valid(self, enriched_chunks):
        """L0 document_type must be one of the expected values."""
        valid_types = {"paper", "article", "documentation", "general"}
        assert enriched_chunks.l0.document_type in valid_types, (
            f"L0 document_type invalid: {enriched_chunks.l0.document_type!r}"
        )

    def test_l0_target_audience(self, enriched_chunks):
        """L0 must have a target audience description."""
        assert enriched_chunks.l0.target_audience, "L0 has empty target_audience"

    # --- Cross-level consistency ---

    def test_enrichment_bottom_up_propagation(self, enriched_chunks):
        """L2 summaries should be available before L1 enrichment runs.

        Verify L1 has content that acknowledges section-level details.
        """
        for l1 in enriched_chunks.l1_chunks:
            # L1 should have a chapter_summary — this means L2 ran first
            assert l1.chapter_summary
            # The L2 chunks under this L1 should all have summaries
            child_l2s = [
                l2 for l2 in enriched_chunks.l2_chunks if l2.parent_chapter_id == l1.chunk_id
            ]
            for l2 in child_l2s:
                assert l2.section_summary, (
                    f"L2 {l2.chunk_id} under L1 {l1.chunk_id} missing summary"
                )

    def test_no_enrichment_failures(self, enriched_chunks):
        """No chunk should have '[enrichment failed]' as its summary."""
        for c in enriched_chunks.l3_chunks:
            assert c.summary != "[enrichment failed]", f"L3 {c.chunk_id} enrichment failed"
        for c in enriched_chunks.l2_chunks:
            assert c.section_summary != "[enrichment failed]", f"L2 {c.chunk_id} enrichment failed"
        for c in enriched_chunks.l1_chunks:
            assert c.chapter_summary != "[enrichment failed]", f"L1 {c.chunk_id} enrichment failed"


class TestContentTierSkipping:
    """T0/T1 content should skip LLM enrichment and use heuristic keywords."""

    def test_t0_chunk_gets_heuristic_keywords(self, tmp_path):
        """T0 (verbatim) chunks should get keywords from heuristic, not LLM."""
        settings = Settings(
            data_dir=tmp_path,
            llm_concurrency=1,
            llm_max_retries=1,
            llm_retry_base_delay=0.0,
        )
        chunks = ChunkSet(
            doc_id="tier-test",
            l0=L0Chunk(chunk_id="tier-test-L0", title="Code Doc", total_passages=1),
            l1_chunks=[
                L1Chunk(
                    chunk_id="ch1",
                    title="Code",
                    content="Code examples.",
                    children_ids=["sec1"],
                ),
            ],
            l2_chunks=[
                L2Chunk(
                    chunk_id="sec1",
                    title="Examples",
                    content="Code examples.",
                    parent_chapter_id="ch1",
                    children_ids=["p0"],
                ),
            ],
            l3_chunks=[
                L3Chunk(
                    chunk_id="p0",
                    content="def calculate_mean(values):\n    return sum(values) / len(values)",
                    parent_section_id="sec1",
                    position=ChunkPosition(chapter="ch1", section="sec1", index=0),
                    content_tier="T0",
                ),
            ],
        )

        client = _mock_llm_client()

        with patch("ingestible.pipeline.stage4_enrichment._make_client", return_value=client):
            result = asyncio.run(enrich_chunks(chunks, settings))

        t0_chunk = result.l3_chunks[0]
        # T0 should have keywords from heuristic (snake_case identifier)
        assert "calculate_mean" in t0_chunk.keywords, (
            f"T0 chunk missing heuristic keyword 'calculate_mean', got: {t0_chunk.keywords}"
        )
        # T0 should NOT have LLM-generated summary
        assert not t0_chunk.summary, (
            f"T0 chunk should not have LLM summary, got: {t0_chunk.summary!r}"
        )
