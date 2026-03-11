"""Stage 4 — LLM Enrichment.

Abstract LLMClient interface with Anthropic (default) and OpenAI implementations.
Enriches chunks bottom-up: L3 → L2 → L1 → L0.
Uses async + Semaphore for concurrency control.

Anthropic client uses tool_use for structured JSON output — the tool's input_schema
enforces the Pydantic model, so there are no parsing failures from free-text responses.
OpenAI client uses json_schema response_format (structured output).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol, TypeVar

from pydantic import BaseModel

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestible.models.enrichment import (
    L0Enrichment,
    L1Enrichment,
    L2Enrichment,
    L3Enrichment,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    async def generate_json(self, prompt: str, output_type: type[T]) -> T: ...


class OpenAIClient:
    """Default LLM client. Uses openai.AsyncOpenAI with structured output."""

    def __init__(self, api_key: str, model: str):
        import openai

        self._client = openai.AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate_json(self, prompt: str, output_type: type[T]) -> T:
        schema = output_type.model_json_schema()
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": output_type.__name__,
                    "schema": schema,
                    "strict": True,
                },
            },
            temperature=0.3,
        )
        raw = response.choices[0].message.content
        return output_type.model_validate_json(raw)


class AnthropicClient:
    """Default LLM client using Anthropic API with tool_use for structured output."""

    def __init__(self, api_key: str, model: str):
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def generate_json(self, prompt: str, output_type: type[T]) -> T:
        schema = output_type.model_json_schema()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            tools=[{
                "name": "output",
                "description": "Structured output matching the requested schema",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": "output"},
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        return output_type.model_validate(tool_block.input)


def _make_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "anthropic":
        if settings.anthropic_api_key:
            return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)
        # Graceful fallback: if no Anthropic key but OpenAI key exists, use OpenAI
        if settings.openai_api_key:
            logger.info("No INGEST_ANTHROPIC_API_KEY set, falling back to OpenAI")
            return OpenAIClient(settings.openai_api_key, settings.openai_model)
        raise ValueError(
            "INGEST_ANTHROPIC_API_KEY is required (or set INGEST_OPENAI_API_KEY as fallback)"
        )
    else:
        if settings.openai_api_key:
            return OpenAIClient(settings.openai_api_key, settings.openai_model)
        if settings.anthropic_api_key:
            logger.info("No INGEST_OPENAI_API_KEY set, falling back to Anthropic")
            return AnthropicClient(settings.anthropic_api_key, settings.anthropic_model)
        raise ValueError(
            "INGEST_OPENAI_API_KEY is required (or set INGEST_ANTHROPIC_API_KEY as fallback)"
        )


async def enrich_chunks(chunks: ChunkSet, settings: Settings) -> ChunkSet:
    """Enrich all chunks with LLM-generated metadata. Bottom-up: L3 → L2 → L1 → L0."""
    client = _make_client(settings)
    sem = asyncio.Semaphore(settings.llm_concurrency)

    # --- L3 enrichment ---
    logger.info("Enriching %d L3 chunks...", len(chunks.l3_chunks))
    l3_tasks = [_enrich_l3(c, client, sem) for c in chunks.l3_chunks]
    enriched_l3 = await asyncio.gather(*l3_tasks, return_exceptions=True)

    for i, result in enumerate(enriched_l3):
        if isinstance(result, Exception):
            logger.warning("L3 enrichment failed for %s: %s", chunks.l3_chunks[i].chunk_id, result)
            continue
        chunk = chunks.l3_chunks[i]
        chunk.summary = result.summary
        chunk.concepts = result.concepts
        chunk.hypothetical_questions = result.hypothetical_questions
        chunk.keywords = result.keywords
        chunk.difficulty_level = result.difficulty_level
        chunk.depends_on = result.depends_on
        chunk.cross_references = result.cross_references

    # --- L2 enrichment ---
    logger.info("Enriching %d L2 chunks...", len(chunks.l2_chunks))
    l2_tasks = [_enrich_l2(c, chunks, client, sem) for c in chunks.l2_chunks]
    enriched_l2 = await asyncio.gather(*l2_tasks, return_exceptions=True)

    for i, result in enumerate(enriched_l2):
        if isinstance(result, Exception):
            logger.warning("L2 enrichment failed for %s: %s", chunks.l2_chunks[i].chunk_id, result)
            continue
        chunk = chunks.l2_chunks[i]
        chunk.section_summary = result.section_summary
        chunk.key_points = result.key_points
        chunk.concepts_introduced = result.concepts_introduced

    # --- L1 enrichment ---
    logger.info("Enriching %d L1 chunks...", len(chunks.l1_chunks))
    l1_tasks = [_enrich_l1(c, chunks, client, sem) for c in chunks.l1_chunks]
    enriched_l1 = await asyncio.gather(*l1_tasks, return_exceptions=True)

    for i, result in enumerate(enriched_l1):
        if isinstance(result, Exception):
            logger.warning("L1 enrichment failed for %s: %s", chunks.l1_chunks[i].chunk_id, result)
            continue
        chunk = chunks.l1_chunks[i]
        chunk.chapter_summary = result.chapter_summary
        chunk.main_topics = result.main_topics
        chunk.learning_objectives = result.learning_objectives
        chunk.prerequisite_chapters = result.prerequisite_chapters
        chunk.key_takeaways = result.key_takeaways

    # --- L0 enrichment ---
    logger.info("Enriching L0...")
    try:
        l0_result = await _enrich_l0(chunks.l0, chunks, client, sem)
        chunks.l0.domain = l0_result.domain
        chunks.l0.key_concepts = l0_result.key_concepts
    except Exception as e:
        logger.warning("L0 enrichment failed: %s", e)

    return chunks


async def _enrich_l3(
    chunk: L3Chunk, client: LLMClient, sem: asyncio.Semaphore
) -> L3Enrichment:
    prompt = f"""Analyze this text passage and generate structured metadata.

PASSAGE:
{chunk.content}

Generate JSON with these fields:
- summary: 2-3 sentence summary of what this passage covers
- concepts: key concepts discussed (extractive, actual terms from the text)
- hypothetical_questions: 3-5 questions a reader might ask that this passage answers
- keywords: specific terms that appear in the text (for search)
- difficulty_level: "beginner", "intermediate", or "advanced"
- depends_on: concepts this assumes the reader already knows
- cross_references: other topics this connects to"""

    async with sem:
        return await client.generate_json(prompt, L3Enrichment)


async def _enrich_l2(
    chunk: L2Chunk, all_chunks: ChunkSet, client: LLMClient, sem: asyncio.Semaphore
) -> L2Enrichment:
    child_summaries = []
    for c in all_chunks.l3_chunks:
        if c.parent_section_id == chunk.chunk_id and c.summary:
            child_summaries.append(f"- {c.summary}")

    child_context = "\n".join(child_summaries) if child_summaries else chunk.content[:2000]

    prompt = f"""Analyze this section and generate structured metadata.

SECTION: {chunk.title}
CONTENT SUMMARIES:
{child_context}

Generate JSON with:
- section_summary: 1-2 sentence summary
- key_points: main points covered
- concepts_introduced: new concepts defined in this section"""

    async with sem:
        return await client.generate_json(prompt, L2Enrichment)


async def _enrich_l1(
    chunk: L1Chunk, all_chunks: ChunkSet, client: LLMClient, sem: asyncio.Semaphore
) -> L1Enrichment:
    section_summaries = []
    for s in all_chunks.l2_chunks:
        if s.parent_chapter_id == chunk.chunk_id and s.section_summary:
            section_summaries.append(f"- {s.title}: {s.section_summary}")

    section_context = "\n".join(section_summaries) if section_summaries else chunk.content[:3000]

    prompt = f"""Analyze this chapter and generate structured metadata.

CHAPTER: {chunk.title}
SECTION SUMMARIES:
{section_context}

Generate JSON with:
- chapter_summary: comprehensive 3-5 sentence summary
- main_topics: list of main topics covered
- learning_objectives: what the reader learns from this chapter
- prerequisite_chapters: any prior knowledge or chapters required
- key_takeaways: the most important points"""

    async with sem:
        return await client.generate_json(prompt, L1Enrichment)


async def _enrich_l0(
    chunk: L0Chunk, all_chunks: ChunkSet, client: LLMClient, sem: asyncio.Semaphore
) -> L0Enrichment:
    chapter_summaries = []
    for c in all_chunks.l1_chunks:
        if c.chapter_summary:
            chapter_summaries.append(f"- {c.title}: {c.chapter_summary}")

    context = "\n".join(chapter_summaries) if chapter_summaries else chunk.toc_summary

    prompt = f"""Analyze this document overview and generate metadata.

DOCUMENT: {chunk.title}
CHAPTER SUMMARIES:
{context}

Generate JSON with:
- domain: the subject domain of this document (e.g., "software engineering", "machine learning")
- key_concepts: the most important concepts across the entire document (10-20 items)"""

    async with sem:
        return await client.generate_json(prompt, L0Enrichment)
