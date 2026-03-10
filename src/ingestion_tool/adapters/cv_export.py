"""CognitiveVault adapter — export ChunkSets to CV's bulk entries API.

Transforms IngestionTool's hierarchical chunks (L0-L3) into the format
expected by CV's POST /api/v1/vaults/:vaultId/entries/bulk endpoint.

Usage:
    from ingestion_tool.adapters.cv_export import export_to_cv, CVConfig

    config = CVConfig(base_url="https://cv.example.com", api_key="...", vault_id="...")
    result = export_to_cv(chunks, config)

Hierarchy mapping:
    L0 (document)  → chunkLevel=0, parent of L1s
    L1 (chapter)   → chunkLevel=1, parent of L2s
    L2 (section)   → chunkLevel=2, parent of L3s
    L3 (passage)   → chunkLevel=3, leaf node

Parent resolution uses sourcePath: each chunk gets a deterministic
sourcePath like "ingest:{doc_id}/{chunk_id}" and references its parent
via parentSourcePath. CV's bulk endpoint resolves these to internal IDs.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from ingestion_tool.models.chunks import ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk

logger = logging.getLogger(__name__)

SOURCE_PREFIX = "ingest"


@dataclass
class CVConfig:
    """Configuration for CognitiveVault export."""

    base_url: str
    api_key: str
    vault_id: str
    timeout: float = 30.0


@dataclass
class ExportResult:
    """Result of a CV export operation."""

    doc_id: str
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    error: str | None = None


def _source_path(doc_id: str, chunk_id: str) -> str:
    """Deterministic sourcePath for a chunk. Used for upsert matching in CV."""
    return f"{SOURCE_PREFIX}:{doc_id}/{chunk_id}"


def _checksum(content: str) -> str:
    """SHA-256 of content, matching CV's checksum format."""
    return hashlib.sha256(content.encode()).hexdigest()


def _l0_to_entry(l0: L0Chunk, doc_id: str) -> dict[str, Any]:
    """Convert L0 (document overview) to a CV bulk entry."""
    content_parts = [l0.title]
    if l0.author:
        content_parts.append(f"Author: {l0.author}")
    if l0.domain:
        content_parts.append(f"Domain: {l0.domain}")
    if l0.toc_summary:
        content_parts.append(f"Table of Contents:\n{l0.toc_summary}")
    if l0.key_concepts:
        content_parts.append(f"Key concepts: {', '.join(l0.key_concepts)}")

    content = "\n\n".join(content_parts)

    return {
        "title": l0.title,
        "content": content,
        "entryType": "DOCUMENT",
        "tags": l0.key_concepts[:10],
        "sourcePath": _source_path(doc_id, l0.chunk_id),
        "checksum": _checksum(content),
        "chunkLevel": 0,
        "chunkOrder": 0,
    }


def _l1_to_entry(l1: L1Chunk, doc_id: str, order: int) -> dict[str, Any]:
    """Convert L1 (chapter) to a CV bulk entry."""
    content = l1.content
    if l1.chapter_summary:
        content = l1.chapter_summary + "\n\n" + content

    tags = list(l1.main_topics[:10])

    return {
        "title": l1.title,
        "content": content,
        "entryType": "DOCUMENT",
        "tags": tags,
        "sourcePath": _source_path(doc_id, l1.chunk_id),
        "checksum": _checksum(content),
        "chunkLevel": 1,
        "chunkOrder": order,
        "parentSourcePath": _source_path(doc_id, f"{doc_id}-L0"),
    }


def _l2_to_entry(l2: L2Chunk, doc_id: str, order: int) -> dict[str, Any]:
    """Convert L2 (section) to a CV bulk entry."""
    content = l2.content
    if l2.section_summary:
        content = l2.section_summary + "\n\n" + content

    tags = list(l2.concepts_introduced[:10])

    return {
        "title": l2.title,
        "content": content,
        "entryType": "DOCUMENT",
        "tags": tags,
        "sourcePath": _source_path(doc_id, l2.chunk_id),
        "checksum": _checksum(content),
        "chunkLevel": 2,
        "chunkOrder": order,
        "parentSourcePath": _source_path(doc_id, l2.parent_chapter_id),
    }


def _l3_to_entry(l3: L3Chunk, doc_id: str, order: int) -> dict[str, Any]:
    """Convert L3 (passage) to a CV bulk entry."""
    content = l3.content
    if l3.context_prefix:
        content = l3.context_prefix + "\n\n" + content

    title = l3.summary[:100] if l3.summary else f"Passage {l3.chunk_id}"

    tags = list(l3.keywords[:10])

    return {
        "title": title,
        "content": content,
        "entryType": "DOCUMENT",
        "tags": tags,
        "sourcePath": _source_path(doc_id, l3.chunk_id),
        "checksum": _checksum(content),
        "chunkLevel": 3,
        "chunkOrder": order,
        "parentSourcePath": _source_path(doc_id, l3.parent_section_id),
    }


def chunkset_to_entries(chunks: ChunkSet) -> list[dict[str, Any]]:
    """Transform a ChunkSet into a list of CV bulk entries.

    Entries are ordered by chunk level (0→3) so that parents are
    created before children in a single bulk request.

    Returns:
        List of dicts ready for CV's POST /entries/bulk payload.
    """
    doc_id = chunks.doc_id
    entries: list[dict[str, Any]] = []

    # L0 — document overview (always exactly one)
    entries.append(_l0_to_entry(chunks.l0, doc_id))

    # L1 — chapters
    for i, l1 in enumerate(chunks.l1_chunks):
        entries.append(_l1_to_entry(l1, doc_id, i))

    # L2 — sections
    for i, l2 in enumerate(chunks.l2_chunks):
        entries.append(_l2_to_entry(l2, doc_id, i))

    # L3 — passages
    for i, l3 in enumerate(chunks.l3_chunks):
        entries.append(_l3_to_entry(l3, doc_id, i))

    return entries


def export_to_cv(
    chunks: ChunkSet,
    config: CVConfig,
    delete_removed: bool = False,
) -> ExportResult:
    """Export a ChunkSet to CognitiveVault via the bulk entries API.

    Args:
        chunks: The ChunkSet to export.
        config: CV connection configuration.
        delete_removed: If True, CV deletes entries with sourcePaths
            not in this batch (cleans up removed chunks on re-ingest).

    Returns:
        ExportResult with counts from CV's response.
    """
    doc_id = chunks.doc_id
    entries = chunkset_to_entries(chunks)

    if not entries:
        return ExportResult(doc_id=doc_id)

    url = f"{config.base_url.rstrip('/')}/api/v1/vaults/{config.vault_id}/entries/bulk"

    logger.info(
        "Exporting %d entries for %s to CV vault %s",
        len(entries),
        doc_id,
        config.vault_id,
    )

    try:
        with httpx.Client(timeout=config.timeout) as client:
            resp = client.post(
                url,
                json={"entries": entries, "deleteRemoved": delete_removed},
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return ExportResult(
            doc_id=doc_id,
            created=data.get("created", 0),
            updated=data.get("updated", 0),
            unchanged=data.get("unchanged", 0),
            deleted=data.get("deleted", 0),
        )
    except httpx.HTTPStatusError as e:
        msg = f"CV API error {e.response.status_code}: {e.response.text[:200]}"
        logger.error(msg)
        return ExportResult(doc_id=doc_id, error=msg)
    except httpx.RequestError as e:
        msg = f"CV connection error: {e}"
        logger.error(msg)
        return ExportResult(doc_id=doc_id, error=msg)


def export_batch_to_cv(
    doc_ids: list[str],
    settings: Any,
    config: CVConfig,
    delete_removed: bool = False,
) -> list[ExportResult]:
    """Export multiple ingested documents to CognitiveVault.

    Loads each ChunkSet from disk and exports it.

    Args:
        doc_ids: List of document IDs to export.
        settings: IngestionTool Settings (for locating stored documents).
        config: CV connection configuration.
        delete_removed: If True, delete entries not in the batch.

    Returns:
        List of ExportResult, one per document.
    """
    from ingestion_tool.pipeline.stage6_storage import load_chunks

    results = []
    for doc_id in doc_ids:
        doc_dir = settings.documents_dir / doc_id
        if not doc_dir.exists():
            results.append(
                ExportResult(doc_id=doc_id, error=f"Document not found: {doc_id}")
            )
            continue

        chunks = load_chunks(doc_dir)
        result = export_to_cv(chunks, config, delete_removed=delete_removed)
        results.append(result)
        logger.info(
            "  %s: created=%d updated=%d unchanged=%d%s",
            doc_id,
            result.created,
            result.updated,
            result.unchanged,
            f" error={result.error}" if result.error else "",
        )

    return results
