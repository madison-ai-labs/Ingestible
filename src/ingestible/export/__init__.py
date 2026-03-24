"""Export adapters — convert stored documents to portable formats."""

from __future__ import annotations

from pathlib import Path

from ingestible.models.chunks import ChunkSet

EXPORT_FORMATS = {"jsonl", "parquet", "llamaindex", "langchain", "complete"}


def export_document(
    chunks: ChunkSet,
    format: str,
    output_path: Path,
    doc_title: str = "",
) -> Path:
    """Export a ChunkSet to the given format. Returns the output path."""
    if format not in EXPORT_FORMATS:
        raise ValueError(f"Unknown export format '{format}'. Supported: {sorted(EXPORT_FORMATS)}")

    if format == "jsonl":
        from ingestible.export.jsonl import export_jsonl

        return export_jsonl(chunks, output_path, doc_title=doc_title)
    elif format == "parquet":
        from ingestible.export.parquet import export_parquet

        return export_parquet(chunks, output_path, doc_title=doc_title)
    elif format == "llamaindex":
        from ingestible.export.llamaindex import export_llamaindex

        return export_llamaindex(chunks, output_path, doc_title=doc_title)
    elif format == "langchain":
        from ingestible.export.langchain import export_langchain

        return export_langchain(chunks, output_path, doc_title=doc_title)
    elif format == "complete":
        from ingestible.export.complete import export_complete

        return export_complete(chunks, output_path, doc_title=doc_title)

    raise ValueError(f"Unsupported format: {format}")  # unreachable
