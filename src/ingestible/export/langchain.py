"""Export to LangChain Document format (JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from ingestible.models.chunks import ChunkSet


def export_langchain(chunks: ChunkSet, output_path: Path, doc_title: str = "") -> Path:
    """Export L3 chunks as LangChain Document-compatible JSON.

    Each document has: page_content, metadata.
    Can be loaded with ``langchain_core.documents.Document(**doc)``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    title = doc_title or chunks.l0.title
    documents = []

    for chunk in chunks.l3_chunks:
        doc = {
            "page_content": chunk.content,
            "metadata": {
                "chunk_id": chunk.chunk_id,
                "doc_id": chunks.doc_id,
                "doc_title": title,
                "chapter": chunk.position.chapter,
                "section": chunk.position.section,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "summary": chunk.summary,
                "concepts": chunk.concepts,
                "keywords": chunk.keywords,
            },
        }
        documents.append(doc)

    output_path.write_text(json.dumps(documents, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
