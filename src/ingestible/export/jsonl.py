"""Export to JSONL — one JSON object per line, one line per L3 chunk."""

from __future__ import annotations

import json
from pathlib import Path

from ingestible.models.chunks import ChunkSet


def export_jsonl(chunks: ChunkSet, output_path: Path, doc_title: str = "") -> Path:
    """Export L3 chunks to JSONL format.

    Each line is a JSON object with: id, content, metadata.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for chunk in chunks.l3_chunks:
            record = {
                "id": chunk.chunk_id,
                "doc_id": chunks.doc_id,
                "doc_title": doc_title or chunks.l0.title,
                "content": chunk.content,
                "summary": chunk.summary,
                "chapter": chunk.position.chapter,
                "section": chunk.position.section,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "concepts": chunk.concepts,
                "keywords": chunk.keywords,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    return output_path
