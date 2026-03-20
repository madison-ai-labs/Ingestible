"""MCP server for Ingestible — lets AI agents ingest and search documents.

Run with:
    python -m ingestible.mcp_server

Or configure in Claude Desktop / claude_desktop_config.json:
    {
        "mcpServers": {
            "ingestible": {
                "command": "python",
                "args": ["-m", "ingestible.mcp_server"]
            }
        }
    }
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ingestible.config import get_settings

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Ingestible",
    description="Document ingestion pipeline — parse, enrich, embed, and search documents",
)


def _get_settings():
    return get_settings()


@mcp.tool()
def ingest_document(
    file_path: str,
    skip_enrichment: bool = False,
    profile: str = "auto",
) -> str:
    """Ingest a document into the knowledge store.

    Runs the full pipeline: parse -> structure -> chunk -> enrich -> embed -> store.
    Supports PDF, DOCX, HTML, EPUB, PPTX, XLSX, CSV, Markdown, RST, AsciiDoc,
    plain text, images (PNG/JPEG/TIFF), email (EML/MSG), XML, JSON, audio, and video.

    Args:
        file_path: Local path, HTTP(S) URL, or cloud URL (s3://, gs://, az://)
        skip_enrichment: Skip LLM enrichment (saves cost, still builds search indexes)
        profile: Extraction profile: "auto", "paper", "article", "documentation", "general"

    Returns:
        JSON with doc_id, title, total_pages, total_chunks
    """
    from ingestible.pipeline.orchestrator import ingest
    from ingestible.pipeline.stage6_storage import load_chunks, load_document_meta

    settings = _get_settings()
    if profile != "auto":
        settings = settings.model_copy(update={"extraction_profile": profile})

    doc_dir = ingest(file_path, settings, skip_enrichment=skip_enrichment, verbose=False)
    meta = load_document_meta(doc_dir)
    chunks = load_chunks(doc_dir)

    return json.dumps({
        "doc_id": meta.get("doc_id", doc_dir.name),
        "title": meta.get("title", "Untitled"),
        "total_pages": meta.get("total_pages", 0),
        "total_chunks": len(chunks.l3_chunks),
        "enriched": not skip_enrichment,
    })


@mcp.tool()
def search(
    query: str,
    doc_id: str | None = None,
    n_results: int = 5,
) -> str:
    """Search across ingested documents.

    If doc_id is provided, searches within that document only.
    Otherwise, searches across all documents (corpus search).

    Args:
        query: The search query
        doc_id: Optional document ID to search within (omit for corpus-wide search)
        n_results: Number of results to return (default: 5)

    Returns:
        JSON with ranked search results including content, scores, and metadata
    """
    from ingestible.pipeline.stage5_embedding import Embedder
    from ingestible.pipeline.stage6_storage import load_chunks
    from ingestible.search.hybrid import load_searcher

    settings = _get_settings()
    embedder = Embedder(settings)

    if doc_id:
        doc_dir = settings.documents_dir / doc_id
        if not doc_dir.exists():
            return json.dumps({"error": f"Document not found: {doc_id}"})

        chunks = load_chunks(doc_dir)
        searcher = load_searcher(doc_dir, chunks, embedder, settings)
        response = searcher.search(query, n_results=n_results)
    else:
        from ingestible.search.corpus import CorpusSearcher

        searcher = CorpusSearcher(settings, embedder=embedder)
        response = searcher.search(query, n_results=n_results)

    return response.model_dump_json()


@mcp.tool()
def list_documents() -> str:
    """List all ingested documents in the knowledge store.

    Returns:
        JSON array of documents with doc_id, title, total_pages, ingestion_date
    """
    from ingestible.pipeline.stage6_storage import list_documents as _list_docs

    settings = _get_settings()
    docs = _list_docs(settings)
    return json.dumps([
        {
            "doc_id": d.get("doc_id", "?"),
            "title": d.get("title", "Untitled"),
            "total_pages": d.get("total_pages", 0),
            "ingestion_date": d.get("ingestion_date", ""),
        }
        for d in docs
    ])


@mcp.tool()
def get_document_overview(doc_id: str) -> str:
    """Get the L0 document overview — a structured map of the entire document.

    Includes title, executive summary, key findings, table of contents,
    key concepts, and chapter list. This is the "map" that lets you understand
    the document's structure before diving into specific passages.

    Args:
        doc_id: The document ID

    Returns:
        JSON with full L0 overview including executive_summary, key_findings,
        key_concepts, chapters, methodology, limitations, etc.
    """
    from ingestible.pipeline.stage6_storage import load_chunks

    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        return json.dumps({"error": f"Document not found: {doc_id}"})

    chunks = load_chunks(doc_dir)
    l0 = chunks.l0

    chapters = [{"id": c.chunk_id, "title": c.title} for c in chunks.l1_chunks]

    return json.dumps({
        "doc_id": doc_id,
        "title": l0.title,
        "author": l0.author,
        "domain": l0.domain,
        "document_type": l0.document_type,
        "target_audience": l0.target_audience,
        "executive_summary": l0.executive_summary,
        "key_findings": l0.key_findings,
        "key_concepts": l0.key_concepts,
        "methodology": l0.methodology,
        "limitations": l0.limitations,
        "toc_summary": l0.toc_summary,
        "total_pages": l0.total_pages,
        "total_chapters": l0.total_chapters,
        "total_sections": l0.total_sections,
        "total_passages": l0.total_passages,
        "chapters": chapters,
    })


@mcp.tool()
def get_chunk(chunk_id: str, doc_id: str) -> str:
    """Get the full content of a specific chunk by ID.

    Use this to drill into a passage found via search, or to read
    a specific chapter/section.

    Args:
        chunk_id: The chunk ID (from search results or document overview)
        doc_id: The document ID containing the chunk

    Returns:
        JSON with chunk content, summary, concepts, and metadata
    """
    from ingestible.pipeline.stage6_storage import load_chunks

    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        return json.dumps({"error": f"Document not found: {doc_id}"})

    chunks = load_chunks(doc_dir)

    # Search all chunk levels
    for c in chunks.l3_chunks:
        if c.chunk_id == chunk_id:
            return c.model_dump_json()
    for c in chunks.l2_chunks:
        if c.chunk_id == chunk_id:
            return c.model_dump_json()
    for c in chunks.l1_chunks:
        if c.chunk_id == chunk_id:
            return c.model_dump_json()
    if chunks.l0.chunk_id == chunk_id:
        return chunks.l0.model_dump_json()

    return json.dumps({"error": f"Chunk not found: {chunk_id}"})


@mcp.tool()
def get_knowledge_graph(doc_id: str) -> str:
    """Get the knowledge graph triples extracted from a document.

    Returns entity-relationship triples like (subject, predicate, object)
    with confidence scores. Only available when knowledge graph extraction
    is enabled during ingestion.

    Args:
        doc_id: The document ID

    Returns:
        JSON with triples and entity summary
    """
    from ingestible.pipeline.stage6_storage import load_chunks

    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        return json.dumps({"error": f"Document not found: {doc_id}"})

    chunks = load_chunks(doc_dir)

    if not chunks.knowledge_graph:
        return json.dumps({"doc_id": doc_id, "total_triples": 0, "triples": []})

    # Build entity index
    entities: dict[str, dict] = {}
    for t in chunks.knowledge_graph:
        for name, etype in [(t.subject, t.subject_type), (t.object, t.object_type)]:
            key = name.lower()
            if key not in entities:
                entities[key] = {"name": name, "type": etype, "count": 0}
            entities[key]["count"] += 1

    return json.dumps({
        "doc_id": doc_id,
        "total_triples": len(chunks.knowledge_graph),
        "total_entities": len(entities),
        "triples": [t.model_dump() for t in chunks.knowledge_graph[:100]],  # cap at 100
        "top_entities": sorted(entities.values(), key=lambda e: e["count"], reverse=True)[:20],
    })


@mcp.tool()
def delete_document(doc_id: str) -> str:
    """Delete an ingested document and all its indexes.

    Args:
        doc_id: The document ID to delete

    Returns:
        JSON confirmation
    """
    import shutil

    settings = _get_settings()
    doc_dir = settings.documents_dir / doc_id
    if not doc_dir.exists():
        return json.dumps({"error": f"Document not found: {doc_id}"})

    shutil.rmtree(doc_dir)
    return json.dumps({"deleted": doc_id})


if __name__ == "__main__":
    mcp.run()
