"""Export to Parquet via pyarrow."""

from __future__ import annotations

from pathlib import Path

from ingestible.models.chunks import ChunkSet


def export_parquet(chunks: ChunkSet, output_path: Path, doc_title: str = "") -> Path:
    """Export L3 chunks to Parquet format.

    Requires ``pyarrow`` (optional dependency).
    """
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        raise ImportError(
            "pyarrow is required for Parquet export. "
            "Install with: pip install 'ingestible[export]'"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    ids = []
    doc_ids = []
    titles = []
    contents = []
    summaries = []
    chapters = []
    sections = []
    page_starts = []
    page_ends = []
    concepts_list = []
    keywords_list = []

    title = doc_title or chunks.l0.title
    for chunk in chunks.l3_chunks:
        ids.append(chunk.chunk_id)
        doc_ids.append(chunks.doc_id)
        titles.append(title)
        contents.append(chunk.content)
        summaries.append(chunk.summary)
        chapters.append(chunk.position.chapter)
        sections.append(chunk.position.section)
        page_starts.append(chunk.page_start)
        page_ends.append(chunk.page_end)
        concepts_list.append(", ".join(chunk.concepts))
        keywords_list.append(", ".join(chunk.keywords))

    table = pa.table(
        {
            "id": ids,
            "doc_id": doc_ids,
            "doc_title": titles,
            "content": contents,
            "summary": summaries,
            "chapter": chapters,
            "section": sections,
            "page_start": pa.array(page_starts, type=pa.int32()),
            "page_end": pa.array(page_ends, type=pa.int32()),
            "concepts": concepts_list,
            "keywords": keywords_list,
        }
    )

    pq.write_table(table, str(output_path))
    return output_path
