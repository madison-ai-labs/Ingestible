"""Stage 3c — Contextual Chunking.

Generates a short context blurb for each L3 chunk using the LLM,
following Anthropic's contextual retrieval approach. The prefix is
stored on L3Chunk.context_prefix and prepended to content before
embedding (Stage 5).
"""

from __future__ import annotations

import asyncio
import logging

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet
from ingestible.models.document import DocumentStructure
from ingestible.utils.retry import retry_llm_call

logger = logging.getLogger(__name__)


async def add_context_prefixes(
    chunks: ChunkSet,
    structure: DocumentStructure,
    settings: Settings,
) -> ChunkSet:
    """Generate context blurbs for all L3 chunks via LLM."""
    from ingestible.pipeline.stage4_enrichment import _make_client

    client = _make_client(settings)
    sem = asyncio.Semaphore(settings.llm_concurrency)
    max_retries = settings.llm_max_retries
    base_delay = settings.llm_retry_base_delay

    # Build title lookup from structure tree
    title_map: dict[str, str] = {}
    for node in structure.root.walk():
        title_map[node.id] = node.title

    doc_title = structure.title

    tasks = []
    for chunk in chunks.l3_chunks:
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")
        tasks.append(
            _generate_context_blurb(
                chunk.content, doc_title, chapter_title, section_title, client, sem,
                max_retries=max_retries, base_delay=base_delay,
            )
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    set_count = 0
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.warning(
                "Context blurb failed for %s: %s",
                chunks.l3_chunks[i].chunk_id,
                result,
            )
            continue
        if result:
            chunks.l3_chunks[i].context_prefix = result
            set_count += 1

    logger.info("Set context_prefix on %d / %d chunks", set_count, len(chunks.l3_chunks))
    return chunks


async def _generate_context_blurb(
    content: str,
    doc_title: str,
    chapter_title: str,
    section_title: str,
    client,
    sem: asyncio.Semaphore,
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> str:
    """Generate a single-sentence context blurb for a chunk."""
    context_parts = [f"Document: {doc_title}"]
    if chapter_title:
        context_parts.append(f"Chapter: {chapter_title}")
    if section_title and section_title != chapter_title:
        context_parts.append(f"Section: {section_title}")
    context_str = "\n".join(context_parts)

    prompt = (
        f"Given the following document context and chunk, write a single sentence "
        f"(max 50 words) that situates this chunk within the broader document. "
        f"The sentence should help a reader understand what part of the document "
        f"this text comes from and what topic it covers.\n\n"
        f"CONTEXT:\n{context_str}\n\n"
        f"CHUNK:\n{content[:1000]}\n\n"
        f"Write ONLY the situating sentence, nothing else."
    )

    async with sem:
        # Use raw generate since we just need a text string, not structured JSON
        # Fall back to generate_json with a simple wrapper
        from pydantic import BaseModel

        class _Blurb(BaseModel):
            sentence: str

        result = await retry_llm_call(
            client.generate_json, prompt, _Blurb,
            max_retries=max_retries, base_delay=base_delay,
        )
        return result.sentence
