"""Stage 6 — Storage.

Saves and loads the complete document data as a JSON file hierarchy:
  documents/{doc_id}/
    meta.json
    structure.json
    versions.json
    chapters/{chapter_id}/
      meta.json
      sections/{section_id}/
        meta.json
        chunks/{chunk_id}.json
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ingestible.config import Settings
from ingestible.models.chunks import ChunkSet, L0Chunk, L1Chunk, L2Chunk, L3Chunk
from ingestible.models.document import DocumentStructure
from ingestible.models.enrichment import Citation, KGTriple

logger = logging.getLogger(__name__)


def save_document(
    structure: DocumentStructure,
    chunks: ChunkSet,
    settings: Settings,
    content_hash: str = "",
    extraction_profile: str = "",
) -> Path:
    """Persist a processed document to disk as a JSON file hierarchy."""
    doc_dir = settings.documents_dir / chunks.doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)

    # meta.json
    meta = {
        "schema_version": 2,  # increment when chunk model changes
        "doc_id": chunks.doc_id,
        "title": structure.title,
        "total_pages": chunks.l0.total_pages,
        "total_chapters": chunks.l0.total_chapters,
        "total_sections": chunks.l0.total_sections,
        "total_passages": chunks.l0.total_passages,
        "ingestion_date": datetime.now(timezone.utc).isoformat(),
        "content_hash": content_hash,
        "author": chunks.l0.author,
        "creation_date": chunks.l0.creation_date,
        "source_language": chunks.l0.source_language,
        "version": len(list_versions(doc_dir)) + 1,
        "extraction_profile": extraction_profile,
        "l0": chunks.l0.model_dump(),
    }
    _write_json(doc_dir / "meta.json", meta)

    # citations.json — structured citations from enrichment
    if chunks.citations:
        _write_json(
            doc_dir / "citations.json",
            {"citations": [c.model_dump() for c in chunks.citations]},
        )

    # knowledge_graph.json — entity-relationship triples from enrichment
    if chunks.knowledge_graph:
        _write_json(
            doc_dir / "knowledge_graph.json",
            {"triples": [t.model_dump() for t in chunks.knowledge_graph]},
        )

    # structure.json
    _write_json(doc_dir / "structure.json", structure.model_dump())

    # figures.json — manifest of extracted figures
    figures_dir = doc_dir / "figures"
    if figures_dir.exists() and any(figures_dir.iterdir()):
        figure_files = sorted(f.name for f in figures_dir.iterdir() if f.is_file())
        _write_json(doc_dir / "figures.json", {"figures": figure_files})

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
    meta = _read_json(doc_dir / "meta.json")
    schema_version = meta.get("schema_version", 1)
    if schema_version > 2:
        raise ValueError(
            f"Document {doc_dir.name} uses schema version {schema_version}, "
            f"but this version of Ingestible only supports up to version 2. "
            f"Please upgrade Ingestible."
        )
    return meta


def load_chunks(doc_dir: Path) -> ChunkSet:
    """Reconstruct a ChunkSet from the stored file hierarchy."""
    meta = _read_json(doc_dir / "meta.json")
    schema_version = meta.get("schema_version", 1)
    if schema_version > 2:
        raise ValueError(
            f"Document {doc_dir.name} uses schema version {schema_version}, "
            f"but this version of Ingestible only supports up to version 2. "
            f"Please upgrade Ingestible."
        )
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

    # Citations
    citations: list[Citation] = []
    citations_path = doc_dir / "citations.json"
    if citations_path.exists():
        try:
            cit_data = _read_json(citations_path)
            citations = [Citation(**c) for c in cit_data.get("citations", [])]
        except (json.JSONDecodeError, OSError):
            pass

    # Knowledge graph
    kg_triples: list[KGTriple] = []
    kg_path = doc_dir / "knowledge_graph.json"
    if kg_path.exists():
        try:
            kg_data = _read_json(kg_path)
            kg_triples = [KGTriple(**t) for t in kg_data.get("triples", [])]
        except (json.JSONDecodeError, OSError):
            pass

    return ChunkSet(
        doc_id=doc_id,
        l0=l0,
        l1_chunks=l1_chunks,
        l2_chunks=l2_chunks,
        l3_chunks=l3_chunks,
        citations=citations,
        knowledge_graph=kg_triples,
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


def archive_version(doc_dir: Path) -> int | None:
    """Archive the current version of a document before re-ingestion.

    Copies the doc dir to ``{doc_id}_v{N}`` and records the version in
    ``versions.json``. Returns the version number, or None if there's
    nothing to archive.
    """
    meta_path = doc_dir / "meta.json"
    if not meta_path.exists():
        return None

    meta = _read_json(meta_path)
    versions = list_versions(doc_dir)
    next_version = len(versions) + 1

    # Archive directory
    archive_dir = doc_dir.parent / f"{doc_dir.name}_v{next_version}"
    shutil.copytree(doc_dir, archive_dir, dirs_exist_ok=False)

    # Update versions.json in the main doc dir
    versions.append({
        "version": next_version,
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": meta.get("content_hash", ""),
        "ingestion_date": meta.get("ingestion_date", ""),
        "archive_path": archive_dir.name,
    })
    _write_json(doc_dir / "versions.json", {"versions": versions})

    logger.info("Archived version %d of %s to %s", next_version, doc_dir.name, archive_dir.name)
    return next_version


def list_versions(doc_dir: Path) -> list[dict]:
    """List all archived versions of a document."""
    versions_path = doc_dir / "versions.json"
    if not versions_path.exists():
        return []
    try:
        data = _read_json(versions_path)
        return data.get("versions", [])
    except (json.JSONDecodeError, OSError):
        return []


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
