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
    KGTriple,
    KGTripleList,
    L0Enrichment,
    L1Enrichment,
    L2Enrichment,
    L3Enrichment,
)
from ingestible.profiles import ExtractionProfile
from ingestible.utils.retry import retry_llm_call

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


class LLMClient(Protocol):
    async def generate_json(self, prompt: str, output_type: type[T]) -> T: ...


class OpenAIClient:
    """Default LLM client. Uses openai.AsyncOpenAI with structured output."""

    def __init__(self, api_key: str, model: str, timeout: int = 120):
        import openai

        self._client = openai.AsyncOpenAI(api_key=api_key, timeout=timeout)
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

    def __init__(self, api_key: str, model: str, timeout: int = 120):
        import anthropic

        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
        self._model = model

    async def generate_json(self, prompt: str, output_type: type[T]) -> T:
        schema = output_type.model_json_schema()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            tools=[
                {
                    "name": "output",
                    "description": "Structured output matching the requested schema",
                    "input_schema": schema,
                }
            ],
            tool_choice={"type": "tool", "name": "output"},
        )
        tool_block = next((b for b in response.content if b.type == "tool_use"), None)
        if tool_block is None:
            raise ValueError(
                f"Anthropic response contained no tool_use block. "
                f"Content types: {[b.type for b in response.content]}"
            )
        return output_type.model_validate(tool_block.input)


def _make_client(settings: Settings) -> LLMClient:
    timeout = settings.llm_timeout
    if settings.llm_provider == "anthropic":
        if settings.anthropic_api_key:
            return AnthropicClient(
                settings.anthropic_api_key, settings.anthropic_model, timeout=timeout
            )
        # Graceful fallback: if no Anthropic key but OpenAI key exists, use OpenAI
        if settings.openai_api_key:
            logger.info("No INGEST_ANTHROPIC_API_KEY set, falling back to OpenAI")
            return OpenAIClient(settings.openai_api_key, settings.openai_model, timeout=timeout)
        raise ValueError(
            "INGEST_ANTHROPIC_API_KEY is required (or set INGEST_OPENAI_API_KEY as fallback)"
        )
    else:
        if settings.openai_api_key:
            return OpenAIClient(settings.openai_api_key, settings.openai_model, timeout=timeout)
        if settings.anthropic_api_key:
            logger.info("No INGEST_OPENAI_API_KEY set, falling back to Anthropic")
            return AnthropicClient(
                settings.anthropic_api_key, settings.anthropic_model, timeout=timeout
            )
        raise ValueError(
            "INGEST_OPENAI_API_KEY is required (or set INGEST_ANTHROPIC_API_KEY as fallback)"
        )


async def enrich_chunks(
    chunks: ChunkSet,
    settings: Settings,
    profile: ExtractionProfile | None = None,
    previous_chunks: ChunkSet | None = None,
) -> ChunkSet:
    """Enrich all chunks with LLM-generated metadata. Bottom-up: L3 → L2 → L1 → L0.

    If ``previous_chunks`` is provided, unchanged L3 chunks (by content_hash)
    copy enrichment fields from the previous version instead of calling the LLM.
    When ALL L3 chunks are unchanged, L2/L1/L0 enrichment is also skipped.
    """
    client = _make_client(settings)
    sem = asyncio.Semaphore(settings.llm_concurrency)
    max_retries = settings.llm_max_retries
    base_delay = settings.llm_retry_base_delay
    prompt_suffix = profile.l3_prompt_suffix if profile else ""
    extract_citations = profile.extract_citations if profile else False
    extract_kg = settings.extract_knowledge_graph or (
        profile.extract_knowledge_graph if profile else False
    )

    # Build lookup of previous L3 enrichment by content_hash
    prev_by_hash: dict[str, L3Chunk] = {}
    if previous_chunks:
        prev_by_hash = {
            c.content_hash: c
            for c in previous_chunks.l3_chunks
            if c.content_hash and c.summary  # only reuse if actually enriched
        }

    # --- L3 enrichment ---
    logger.info("Enriching %d L3 chunks...", len(chunks.l3_chunks))
    skipped = 0
    l3_to_enrich: list[tuple[int, L3Chunk]] = []

    for i, chunk in enumerate(chunks.l3_chunks):
        # T0/T1 chunks skip full enrichment — only extract keywords heuristically
        if chunk.content_tier in ("T0", "T1"):
            chunk.keywords = _extract_keywords_heuristic(chunk.content)
            skipped += 1
            continue

        prev = prev_by_hash.get(chunk.content_hash) if chunk.content_hash else None
        if prev is not None:
            # Copy enrichment fields from previous version
            chunk.summary = prev.summary
            chunk.concepts = prev.concepts
            chunk.hypothetical_questions = prev.hypothetical_questions
            chunk.keywords = prev.keywords
            chunk.difficulty_level = prev.difficulty_level
            chunk.depends_on = prev.depends_on
            chunk.cross_references = prev.cross_references
            chunk.cited_references = prev.cited_references
            chunk.kg_triples = prev.kg_triples
            skipped += 1
        else:
            l3_to_enrich.append((i, chunk))

    if skipped:
        logger.info(
            "Skipping enrichment for %d/%d unchanged L3 chunks",
            skipped,
            len(chunks.l3_chunks),
        )

    if l3_to_enrich:
        l3_tasks = [
            _enrich_l3(
                c,
                client,
                sem,
                prompt_suffix=prompt_suffix,
                extract_citations=extract_citations,
                max_retries=max_retries,
                base_delay=base_delay,
            )
            for _, c in l3_to_enrich
        ]
        enriched_l3 = await asyncio.gather(*l3_tasks, return_exceptions=True)

        for j, result in enumerate(enriched_l3):
            idx, chunk = l3_to_enrich[j]
            if isinstance(result, Exception):
                logger.warning("L3 enrichment failed for %s: %s", chunk.chunk_id, result)
                chunk.summary = "[enrichment failed]"
                continue
            chunk.summary = result.summary
            chunk.concepts = result.concepts
            chunk.hypothetical_questions = result.hypothetical_questions
            chunk.keywords = result.keywords
            chunk.difficulty_level = result.difficulty_level
            chunk.depends_on = result.depends_on
            chunk.cross_references = result.cross_references
            chunk.cited_references = result.cited_references

    # If ALL L3 chunks were unchanged, skip L2/L1/L0 enrichment entirely
    all_l3_skipped = skipped == len(chunks.l3_chunks) and len(chunks.l3_chunks) > 0
    if all_l3_skipped and previous_chunks:
        logger.info("All L3 chunks unchanged — copying L2/L1/L0 enrichment from previous version")
        _copy_upper_enrichment(chunks, previous_chunks)
    else:
        # --- L2 enrichment ---
        logger.info("Enriching %d L2 chunks...", len(chunks.l2_chunks))
        l2_tasks = [
            _enrich_l2(c, chunks, client, sem, max_retries=max_retries, base_delay=base_delay)
            for c in chunks.l2_chunks
        ]
        enriched_l2 = await asyncio.gather(*l2_tasks, return_exceptions=True)

        for i, result in enumerate(enriched_l2):
            if isinstance(result, Exception):
                logger.warning(
                    "L2 enrichment failed for %s: %s", chunks.l2_chunks[i].chunk_id, result
                )
                chunks.l2_chunks[i].section_summary = "[enrichment failed]"
                continue
            chunk = chunks.l2_chunks[i]
            chunk.section_summary = result.section_summary
            chunk.key_points = result.key_points
            chunk.concepts_introduced = result.concepts_introduced

        # --- L1 enrichment ---
        logger.info("Enriching %d L1 chunks...", len(chunks.l1_chunks))
        l1_tasks = [
            _enrich_l1(c, chunks, client, sem, max_retries=max_retries, base_delay=base_delay)
            for c in chunks.l1_chunks
        ]
        enriched_l1 = await asyncio.gather(*l1_tasks, return_exceptions=True)

        for i, result in enumerate(enriched_l1):
            if isinstance(result, Exception):
                logger.warning(
                    "L1 enrichment failed for %s: %s", chunks.l1_chunks[i].chunk_id, result
                )
                chunks.l1_chunks[i].chapter_summary = "[enrichment failed]"
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
            l0_result = await _enrich_l0(
                chunks.l0,
                chunks,
                client,
                sem,
                prompt_suffix=l0_suffix,
                max_retries=max_retries,
                base_delay=base_delay,
            )
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

    # --- Knowledge graph extraction (if enabled) ---
    if extract_kg:
        if all_l3_skipped and previous_chunks and previous_chunks.knowledge_graph:
            logger.info(
                "Reusing %d KG triples from previous version",
                len(previous_chunks.knowledge_graph),
            )
            chunks.knowledge_graph = previous_chunks.knowledge_graph
        else:
            logger.info("Extracting knowledge graph triples...")
            try:
                kg_triples = await _extract_kg_triples(
                    chunks, client, sem, max_retries=max_retries, base_delay=base_delay
                )
                chunks.knowledge_graph = kg_triples
            except Exception as e:
                logger.warning("Knowledge graph extraction failed: %s", e)

    # --- Citation extraction (if profile enables it) ---
    if extract_citations:
        if all_l3_skipped and previous_chunks and previous_chunks.citations:
            logger.info(
                "Reusing %d citations from previous version", len(previous_chunks.citations)
            )
            chunks.citations = previous_chunks.citations
        else:
            logger.info("Extracting citations...")
            try:
                citations = await _extract_citations(
                    chunks, client, sem, max_retries=max_retries, base_delay=base_delay
                )
                chunks.citations = citations
            except Exception as e:
                logger.warning("Citation extraction failed: %s", e)

    return chunks


def _copy_upper_enrichment(chunks: ChunkSet, previous: ChunkSet) -> None:
    """Copy L2/L1/L0 enrichment fields from previous ChunkSet by chunk_id."""
    prev_l2 = {c.chunk_id: c for c in previous.l2_chunks}
    for c in chunks.l2_chunks:
        p = prev_l2.get(c.chunk_id)
        if p:
            c.section_summary = p.section_summary
            c.key_points = p.key_points
            c.concepts_introduced = p.concepts_introduced

    prev_l1 = {c.chunk_id: c for c in previous.l1_chunks}
    for c in chunks.l1_chunks:
        p = prev_l1.get(c.chunk_id)
        if p:
            c.chapter_summary = p.chapter_summary
            c.main_topics = p.main_topics
            c.learning_objectives = p.learning_objectives
            c.prerequisite_chapters = p.prerequisite_chapters
            c.key_takeaways = p.key_takeaways

    # L0
    chunks.l0.domain = previous.l0.domain
    chunks.l0.key_concepts = previous.l0.key_concepts
    chunks.l0.executive_summary = previous.l0.executive_summary
    chunks.l0.key_findings = previous.l0.key_findings
    chunks.l0.methodology = previous.l0.methodology
    chunks.l0.limitations = previous.l0.limitations
    chunks.l0.document_type = previous.l0.document_type
    chunks.l0.target_audience = previous.l0.target_audience


def _extract_keywords_heuristic(text: str) -> list[str]:
    """Extract keywords from code/structural content without LLM calls."""
    import re

    words = set()
    # CamelCase identifiers
    words.update(re.findall(r"\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b", text))
    # snake_case identifiers
    words.update(re.findall(r"\b[a-z]+(?:_[a-z]+)+\b", text))
    # Capitalized terms (class names, proper nouns)
    words.update(w for w in text.split() if len(w) > 3 and w.isalpha() and w[0].isupper())
    # Deduplicate and limit
    return sorted(words)[:20]


async def _enrich_l3(
    chunk: L3Chunk,
    client: LLMClient,
    sem: asyncio.Semaphore,
    prompt_suffix: str = "",
    extract_citations: bool = False,
    max_retries: int = 3,
    base_delay: float = 1.0,
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
        return await retry_llm_call(
            client.generate_json,
            prompt,
            L3Enrichment,
            max_retries=max_retries,
            base_delay=base_delay,
        )


async def _enrich_l2(
    chunk: L2Chunk,
    all_chunks: ChunkSet,
    client: LLMClient,
    sem: asyncio.Semaphore,
    max_retries: int = 3,
    base_delay: float = 1.0,
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
        return await retry_llm_call(
            client.generate_json,
            prompt,
            L2Enrichment,
            max_retries=max_retries,
            base_delay=base_delay,
        )


async def _enrich_l1(
    chunk: L1Chunk,
    all_chunks: ChunkSet,
    client: LLMClient,
    sem: asyncio.Semaphore,
    max_retries: int = 3,
    base_delay: float = 1.0,
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
        return await retry_llm_call(
            client.generate_json,
            prompt,
            L1Enrichment,
            max_retries=max_retries,
            base_delay=base_delay,
        )


async def _enrich_l0(
    chunk: L0Chunk,
    all_chunks: ChunkSet,
    client: LLMClient,
    sem: asyncio.Semaphore,
    prompt_suffix: str = "",
    max_retries: int = 3,
    base_delay: float = 1.0,
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
        return await retry_llm_call(
            client.generate_json,
            prompt,
            L0Enrichment,
            max_retries=max_retries,
            base_delay=base_delay,
        )


async def _extract_citations(
    chunks: ChunkSet,
    client: LLMClient,
    sem: asyncio.Semaphore,
    max_retries: int = 3,
    base_delay: float = 1.0,
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
        tail = chunks.l3_chunks[-min(5, len(chunks.l3_chunks)) :]
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
        result = await retry_llm_call(
            client.generate_json,
            prompt,
            CitationList,
            max_retries=max_retries,
            base_delay=base_delay,
        )

    # Wire up inline_references from L3 cited_references
    citation_map = {c.citation_id: c for c in result.citations if c.citation_id}
    for l3 in chunks.l3_chunks:
        for ref_id in l3.cited_references:
            if ref_id in citation_map:
                citation_map[ref_id].inline_references.append(l3.chunk_id)

    return result.citations


async def _extract_kg_triples_for_chunk(
    chunk: L3Chunk,
    client: LLMClient,
    sem: asyncio.Semaphore,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> list[KGTriple]:
    """Extract knowledge graph triples from a single L3 chunk."""
    prompt = f"""Extract entity-relationship triples from this text passage for knowledge graph construction.

PASSAGE:
{chunk.content}

For each relationship you identify, extract a triple:
- subject: the source entity (a specific named entity, concept, or method)
- subject_type: entity type (e.g. "Person", "Concept", "Method", "Organization", "Technology", "Dataset", "Metric")
- predicate: the relationship (use concise verb phrases like "uses", "is_a", "part_of", "improves", "depends_on", "authored_by", "evaluated_on", "outperforms", "implements", "extends", "causes", "enables", "requires")
- object: the target entity
- object_type: entity type (same categories as subject_type)
- confidence: 0.0-1.0, how explicitly stated the relationship is (1.0 = directly stated, 0.5 = implied)

Rules:
- Extract only meaningful, specific relationships — skip vague or trivial ones
- Normalize entity names: use the most complete form mentioned (e.g. "Transformer architecture" not just "Transformer")
- Prefer canonical relationship predicates from the list above when they fit
- Return an empty triples list if no meaningful relationships exist"""

    async with sem:
        result = await retry_llm_call(
            client.generate_json,
            prompt,
            KGTripleList,
            max_retries=max_retries,
            base_delay=base_delay,
        )

    # Tag each triple with the source chunk
    for triple in result.triples:
        triple.source_chunk_id = chunk.chunk_id
    return result.triples


async def _extract_kg_triples(
    chunks: ChunkSet,
    client: LLMClient,
    sem: asyncio.Semaphore,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> list[KGTriple]:
    """Extract knowledge graph triples from all L3 chunks, deduplicate, and return."""
    tasks = [
        _extract_kg_triples_for_chunk(
            chunk, client, sem, max_retries=max_retries, base_delay=base_delay
        )
        for chunk in chunks.l3_chunks
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_triples: list[KGTriple] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(
                "KG extraction failed for %s: %s",
                chunks.l3_chunks[i].chunk_id,
                result,
            )
            continue
        # Store per-chunk triples on the chunk itself
        chunks.l3_chunks[i].kg_triples = result
        all_triples.extend(result)

    # Deduplicate: same (subject, predicate, object) keeps highest confidence
    seen: dict[tuple[str, str, str], KGTriple] = {}
    for triple in all_triples:
        key = (triple.subject.lower(), triple.predicate.lower(), triple.object.lower())
        existing = seen.get(key)
        if existing is None or triple.confidence > existing.confidence:
            seen[key] = triple

    deduped = list(seen.values())
    logger.info(
        "Extracted %d KG triples (%d unique) from %d chunks",
        len(all_triples),
        len(deduped),
        len(chunks.l3_chunks),
    )
    return deduped
