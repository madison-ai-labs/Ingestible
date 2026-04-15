"""Stage 3c — Contextual Chunking.

Generates a short context prefix for each L3 chunk using document hierarchy.
Uses heuristic title concatenation instead of LLM calls — zero cost, near-identical
retrieval quality to the LLM-based approach.

The prefix is stored on L3Chunk.context_prefix and prepended to content before
embedding (Stage 5).
"""

from __future__ import annotations

import logging

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet
from ingestible.models.document import DocumentStructure

logger = logging.getLogger(__name__)


async def add_context_prefixes(
    chunks: ChunkSet,
    structure: DocumentStructure,
    settings: Settings,
) -> ChunkSet:
    """Generate context prefixes for all L3 chunks using document hierarchy.

    Builds a situating prefix from the document title, chapter, and section
    titles — no LLM calls required.
    """
    # Build title lookup from structure tree
    title_map: dict[str, str] = {}
    for node in structure.root.walk():
        title_map[node.id] = node.title

    doc_title = structure.title
    set_count = 0

    for chunk in chunks.l3_chunks:
        chapter_title = title_map.get(chunk.position.chapter, "")
        section_title = title_map.get(chunk.position.section, "")

        parts = [doc_title]
        if chapter_title:
            parts.append(chapter_title)
        if section_title and section_title != chapter_title:
            parts.append(section_title)

        prefix = " > ".join(parts)
        if prefix:
            chunk.context_prefix = prefix
            set_count += 1

    logger.info("Set context_prefix on %d / %d chunks (heuristic)", set_count, len(chunks.l3_chunks))
    return chunks
