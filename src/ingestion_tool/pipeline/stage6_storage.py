"""Stage 6 — Storage.

Saves and loads the complete document data as a JSON file hierarchy:
  documents/{doc_id}/
    meta.json
    structure.json
    chapters/{chapter_id}/
      meta.json
      sections/{section_id}/
        meta.json
        chunks/{chunk_id}.json
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ingestion_tool.config import Settings
from ingestion_tool.models.chunks import ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestion_tool.models.document import DocumentStructure

logger = logging.getLogger(__name__)


def save_document(
    structure: DocumentStructure,
    chunks: ChunkSet,
    settings: Settings,
    content_hash: str = "",
) -> Path:
    """Persist a processed document to disk as a JSON file hierarchy."""
    doc_dir = settings.documents_dir / chunks.doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    # meta.json
    meta = {
        "doc_id": chunks.doc_id,
        "title": structure.title,
        "total_pages": chunks.l0.total_pages,
        "total_chapters": chunks.l0.total_chapters,
        "total_sections": chunks.l0.total_sections,
        "total_passages": chunks.l0.total_passages,
        "ingestion_date": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "l0": chunks.l0.model_dump(),
    }
    _write_json(doc_dir / "meta.json", meta)

    # structure.json
    _write_json(doc_dir / "structure.json", structure.model_dump())

    # Chapter hierarchy
    for ch in chunks.l1_chunks:
        ch_dir = doc_dir / "chapters" / ch.chunk_id
        ch_dir.mkdir(parents=True, exist_ok=True)
        _write_json(ch_dir / "meta.json", ch.model_dump())

        # Sections under this chapter
        ch_sections = [s for s in chunks.l2_chunks if s.parent_chapter_id == ch.chunk_id]
        for sec in ch_sections:
            sec_dir = ch_dir / "sections" / sec.chunk_id
            sec_dir.mkdir(parents=True, exist_ok=True)
            _write_json(sec_dir / "meta.json", sec.model_dump())

            # Passages under this section
            sec_passages = [
                p for p in chunks.l3_chunks if p.parent_section_id == sec.chunk_id
            ]
            if sec_passages:
                chunks_dir = sec_dir / "chunks"
                chunks_dir.mkdir(parents=True, exist_ok=True)
                for passage in sec_passages:
                    _write_json(chunks_dir / f"{passage.chunk_id}.json", passage.model_dump())

    # Orphan passages (not under a section)
    all_sectioned = {
        p.chunk_id
        for s in chunks.l2_chunks
        for p in chunks.l3_chunks
        if p.parent_section_id == s.chunk_id
    }
    orphans = [p for p in chunks.l3_chunks if p.chunk_id not in all_sectioned]
    if orphans:
        orphan_dir = doc_dir / "chunks"
        orphan_dir.mkdir(parents=True, exist_ok=True)
        for p in orphans:
            _write_json(orphan_dir / f"{p.chunk_id}.json", p.model_dump())

    logger.info("Saved document to %s", doc_dir)
    return doc_dir


def load_document_meta(doc_dir: Path) -> dict:
    """Load meta.json for a document."""
    return _read_json(doc_dir / "meta.json")


def load_chunks(doc_dir: Path) -> ChunkSet:
    """Reconstruct a ChunkSet from the stored file hierarchy."""
    meta = _read_json(doc_dir / "meta.json")
    doc_id = meta["doc_id"]

    l0 = L0Chunk(**meta["l0"])

    l1_chunks: list[L1Chunk] = []
    l2_chunks: list[L2Chunk] = []
    l3_chunks: list[L3Chunk] = []

    chapters_dir = doc_dir / "chapters"
    if chapters_dir.exists():
        for ch_path in sorted(chapters_dir.iterdir()):
            if not ch_path.is_dir():
                continue
            ch_meta = _read_json(ch_path / "meta.json")
            l1_chunks.append(L1Chunk(**ch_meta))

            sections_dir = ch_path / "sections"
            if sections_dir.exists():
                for sec_path in sorted(sections_dir.iterdir()):
                    if not sec_path.is_dir():
                        continue
                    sec_meta = _read_json(sec_path / "meta.json")
                    l2_chunks.append(L2Chunk(**sec_meta))

                    chunks_path = sec_path / "chunks"
                    if chunks_path.exists():
                        for chunk_file in sorted(chunks_path.glob("*.json")):
                            chunk_data = _read_json(chunk_file)
                            l3_chunks.append(L3Chunk(**chunk_data))

    # Orphan chunks
    orphan_dir = doc_dir / "chunks"
    if orphan_dir.exists():
        for chunk_file in sorted(orphan_dir.glob("*.json")):
            chunk_data = _read_json(chunk_file)
            l3_chunks.append(L3Chunk(**chunk_data))

    return ChunkSet(
        doc_id=doc_id,
        l0=l0,
        l1_chunks=l1_chunks,
        l2_chunks=l2_chunks,
        l3_chunks=l3_chunks,
    )


def load_structure(doc_dir: Path) -> DocumentStructure:
    """Load structure.json for a document."""
    data = _read_json(doc_dir / "structure.json")
    return DocumentStructure(**data)


def list_documents(settings: Settings) -> list[dict]:
    """List all ingested documents."""
    docs_dir = settings.documents_dir
    if not docs_dir.exists():
        return []
    results = []
    for d in sorted(docs_dir.iterdir()):
        meta_path = d / "meta.json"
        if meta_path.exists():
            results.append(_read_json(meta_path))
    return results


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
