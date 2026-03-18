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
    Citation,
    CitationList,
    L0Enrichment,
    L1Enrichment,
    L2Enrichment,
    L3Enrichment,
)
from ingestible.profiles import ExtractionProfile

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


async def enrich_chunks(
    chunks: ChunkSet,
    settings: Settings,
    profile: ExtractionProfile | None = None,
) -> ChunkSet:
    """Enrich all chunks with LLM-generated metadata. Bottom-up: L3 → L2 → L1 → L0."""
    client = _make_client(settings)
    sem = asyncio.Semaphore(settings.llm_concurrency)
    prompt_suffix = profile.l3_prompt_suffix if profile else ""
    extract_citations = profile.extract_citations if profile else False

    # --- L3 enrichment ---
    logger.info("Enriching %d L3 chunks...", len(chunks.l3_chunks))
    l3_tasks = [
        _enrich_l3(c, client, sem, prompt_suffix=prompt_suffix, extract_citations=extract_citations)
        for c in chunks.l3_chunks
    ]
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
        chunk.cited_references = result.cited_references

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

    # --- L0 enrichment (now produces full digest) ---
    logger.info("Enriching L0 (document digest)...")
    try:
        l0_suffix = profile.l0_prompt_suffix if profile else ""
        l0_result = await _enrich_l0(chunks.l0, chunks, client, sem, prompt_suffix=l0_suffix)
        chunks.l0.domain = l0_result.domain
        chunks.l0.key_concepts = l0_result.key_concepts
        chunks.l0.executive_summary = l0_result.executive_summary
        chunks.l0.key_findings = l0_result.key_findings
        chunks.l0.methodology = l0_result.methodology
        chunks.l0.limitations = l0_result.limitations
        chunks.l0.document_type = l0_result.document_type
        chunks.l0.target_audience = l0_result.target_audience
    except Exception as e:
        logger.warning("L0 enrichment failed: %s", e)

    # --- Citation extraction (if profile enables it) ---
    if extract_citations:
        logger.info("Extracting citations...")
        try:
            citations = await _extract_citations(chunks, client, sem)
            chunks.citations = citations
        except Exception as e:
            logger.warning("Citation extraction failed: %s", e)

    return chunks


async def _enrich_l3(
    chunk: L3Chunk,
    client: LLMClient,
    sem: asyncio.Semaphore,
    prompt_suffix: str = "",
    extract_citations: bool = False,
) -> L3Enrichment:
    citation_instruction = ""
    if extract_citations:
        citation_instruction = (
            "\n- cited_references: citation markers found in this passage "
            '(e.g. "[1]", "[Smith2024]", "(Jones et al., 2023)"). '
            "Extract the exact markers as they appear."
        )

    suffix = f"\n\n{prompt_suffix}" if prompt_suffix else ""

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
- cross_references: other topics this connects to{citation_instruction}{suffix}"""

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
    chunk: L0Chunk,
    all_chunks: ChunkSet,
    client: LLMClient,
    sem: asyncio.Semaphore,
    prompt_suffix: str = "",
) -> L0Enrichment:
    chapter_summaries = []
    for c in all_chunks.l1_chunks:
        if c.chapter_summary:
            chapter_summaries.append(f"- {c.title}: {c.chapter_summary}")

    context = "\n".join(chapter_summaries) if chapter_summaries else chunk.toc_summary
    suffix = f"\n\n{prompt_suffix}" if prompt_suffix else ""

    prompt = f"""Analyze this document overview and generate a comprehensive digest.

DOCUMENT: {chunk.title}
CHAPTER SUMMARIES:
{context}

Generate JSON with:
- domain: the subject domain (e.g., "software engineering", "machine learning")
- key_concepts: the most important concepts across the entire document (10-20 items)
- executive_summary: 3-5 sentence overview of the entire document — what it is, what it covers, and why it matters
- key_findings: 5-10 main findings, claims, or contributions (ordered by importance)
- methodology: research methodology used (leave empty string if not applicable)
- limitations: known limitations or caveats (leave empty string if not applicable)
- document_type: one of "paper", "article", "documentation", "general"
- target_audience: who this document is intended for (1 sentence){suffix}"""

    async with sem:
        return await client.generate_json(prompt, L0Enrichment)


async def _extract_citations(
    chunks: ChunkSet, client: LLMClient, sem: asyncio.Semaphore
) -> list[Citation]:
    """Extract structured citations from the document.

    Looks for a references/bibliography section first, falls back to
    scanning the last L3 chunks.
    """
    # Find reference-like sections by title
    ref_content = ""
    for l2 in chunks.l2_chunks:
        title_lower = l2.title.lower()
        if any(kw in title_lower for kw in ("references", "bibliography", "works cited")):
            # Gather all L3 chunks under this section
            child_texts = [
                c.content for c in chunks.l3_chunks if c.parent_section_id == l2.chunk_id
            ]
            ref_content = "\n\n".join(child_texts)
            break

    # Fallback: use the last few L3 chunks (often contain references)
    if not ref_content and chunks.l3_chunks:
        tail = chunks.l3_chunks[-min(5, len(chunks.l3_chunks)):]
        ref_content = "\n\n".join(c.content for c in tail)

    if not ref_content.strip():
        return []

    # Truncate to avoid token limits
    ref_content = ref_content[:8000]

    prompt = f"""Extract structured citations from this references section.

TEXT:
{ref_content}

For each citation, extract:
- citation_id: the label/number as it appears (e.g. "[1]", "Smith2024")
- authors: list of author names
- title: the work's title
- year: publication year
- venue: journal, conference, or publisher name
- doi: DOI if present, empty string otherwise
- raw_text: the original citation text as it appears

Return a JSON object with a "citations" list. Only include items that are actual bibliographic references."""

    async with sem:
        result = await client.generate_json(prompt, CitationList)

    # Wire up inline_references from L3 cited_references
    citation_map = {c.citation_id: c for c in result.citations if c.citation_id}
    for l3 in chunks.l3_chunks:
        for ref_id in l3.cited_references:
            if ref_id in citation_map:
                citation_map[ref_id].inline_references.append(l3.chunk_id)

    return result.citations
