"""Re-enrichment without re-parsing — WP 2.2.

Loads existing chunks from disk, re-runs Stage 3c (contextual) + Stage 4
(enrichment) + Stage 5 (embedding) + Stage 6 (save). Skips parse/structure/chunk.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet
from ingestible.pipeline.stage5_embedding import Embedder, build_indexes
from ingestible.pipeline.stage6_storage import (
    load_chunks,
    load_document_meta,
    load_structure,
    save_document,
)

logger = logging.getLogger(__name__)


def re_enrich(
    doc_id: str,
    settings: Settings,
    changed_chunk_ids: set[str] | None = None,
) -> Path:
    """Re-run enrichment + embedding on an already-ingested document.

    If ``changed_chunk_ids`` is provided, only those L3 chunks are re-enriched.
    All others keep their existing enrichment. This is used by the webhook handler
    to selectively re-enrich chunks that were edited in CognitiveVault.

    Returns the document directory.
    """
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        raise FileNotFoundError(f"Document not found: {doc_id}")

    logger.info("=== Re-enriching %s ===", doc_id)

    # Load existing data
    structure = load_structure(doc_dir)
    chunks = load_chunks(doc_dir)
    meta = load_document_meta(doc_dir)
    content_hash = meta.get("content_hash", "")

    # Resolve extraction profile
    stored_profile = meta.get("extraction_profile", settings.extraction_profile)
    if stored_profile == "auto":
        stored_profile = "general"
    from ingestible.profiles import PROFILES

    profile = PROFILES.get(stored_profile, PROFILES["general"])

    # Build a "previous" ChunkSet for selective re-enrichment.
    # When changed_chunk_ids is given, we treat unchanged chunks as "previous"
    # so enrich_chunks() will copy their enrichment instead of calling the LLM.
    previous_chunks: ChunkSet | None = None
    if changed_chunk_ids is not None:
        # Deep-copy the current chunks as "previous" — they have enrichment data.
        # Then clear enrichment only on the changed chunks so they get re-enriched.
        previous_chunks = chunks.model_copy(deep=True)
        for c in chunks.l3_chunks:
            if c.chunk_id in changed_chunk_ids:
                # Mutate content_hash so it won't match the previous version
                c.content_hash = ""
                # Clear enrichment so stale data doesn't persist if LLM fails
                c.summary = ""
                c.concepts = []
                c.hypothetical_questions = []
                c.keywords = []
                c.difficulty_level = ""
                c.depends_on = []
                c.cross_references = []
                c.cited_references = []
    else:
        # Full re-enrichment: clear all enrichment fields
        for c in chunks.l3_chunks:
            c.summary = ""
            c.concepts = []
            c.hypothetical_questions = []
            c.keywords = []
            c.difficulty_level = ""
            c.depends_on = []
            c.cross_references = []
            c.cited_references = []
            c.context_prefix = ""

        for c in chunks.l2_chunks:
            c.section_summary = ""
            c.key_points = []
            c.concepts_introduced = []

        for c in chunks.l1_chunks:
            c.chapter_summary = ""
            c.main_topics = []
            c.learning_objectives = []
            c.prerequisite_chapters = []
            c.key_takeaways = []

        # Clear L0 digest fields
        chunks.l0.executive_summary = ""
        chunks.l0.key_findings = []
        chunks.l0.methodology = ""
        chunks.l0.limitations = ""
        chunks.l0.document_type = ""
        chunks.l0.target_audience = ""
        chunks.l0.domain = ""
        chunks.l0.key_concepts = []
        chunks.citations = []

    step = 0
    total = 3  # contextual + enrich + embed/save
    if settings.contextual_chunking:
        total += 1

    def _log(msg: str) -> None:
        nonlocal step
        step += 1
        logger.info("[%d/%d] %s", step, total, msg)

    # Stage 3c: Contextual chunking (if enabled)
    if settings.contextual_chunking:
        _log("Adding contextual prefixes...")
        try:
            from ingestible.pipeline.stage3c_contextual import add_context_prefixes

            chunks = asyncio.run(add_context_prefixes(chunks, structure, settings))
        except Exception as e:
            logger.warning("Contextual chunking failed, continuing without it: %s", e)

    # Stage 4: Enrichment
    _log("LLM enrichment...")
    try:
        from ingestible.pipeline.stage4_enrichment import enrich_chunks

        chunks = asyncio.run(enrich_chunks(
            chunks, settings, profile=profile,
            previous_chunks=previous_chunks,
        ))
    except Exception as e:
        logger.warning("Enrichment failed, continuing without it: %s", e)

    # Stage 5: Embedding & indexing
    _log("Building indexes...")
    embedder = Embedder(settings)
    build_indexes(chunks, doc_dir, embedder)

    # Stage 6: Storage
    _log("Saving to disk...")
    doc_dir = save_document(structure, chunks, settings, content_hash=content_hash)

    logger.info("=== Re-enrichment complete for %s ===", doc_id)
    return doc_dir
