"""Export to LlamaIndex node format (JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from ingestible.models.chunks import ChunkSet


def export_llamaindex(chunks: ChunkSet, output_path: Path, doc_title: str = "") -> Path:
    """Export L3 chunks as LlamaIndex TextNode-compatible JSON.

    Each node has: id_, text, metadata, and relationships.
    Can be loaded with ``llama_index.core.schema.TextNode.from_dict()``.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    title = doc_title or chunks.l0.title
    nodes = []

    for chunk in chunks.l3_chunks:
        node = {
            "id_": chunk.chunk_id,
            "text": chunk.content,
            "metadata": {
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
            "excluded_embed_metadata_keys": ["summary", "concepts", "keywords"],
            "excluded_llm_metadata_keys": [],
        }
        nodes.append(node)

    output_path.write_text(
        json.dumps(nodes, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return output_path
