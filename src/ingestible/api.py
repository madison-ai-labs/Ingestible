"""FastAPI HTTP wrapper for the ingestion pipeline."""

from __future__ import annotations

import hmac
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ingestible.config import get_settings
from ingestible.models.chunks import ChunkSet, L0Chunk
from ingestible.models.document import DocumentStructure
from ingestible.models.search import SearchResponse, SearchResult
from ingestible.pipeline.orchestrator import ingest
from ingestible.pipeline.stage5_embedding import Embedder
from ingestible.pipeline.stage6_storage import (
    list_documents,
    load_chunks,
    load_document_meta,
    load_structure,
)
from ingestible.search.hybrid import load_searcher

app = FastAPI(
    title="Ingestible API",
    description="PDF ingestion pipeline with hierarchical retrieval",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Authentication Middleware
# ---------------------------------------------------------------------------

SKIP_AUTH_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


def get_api_keys() -> list[str]:
    """Parse comma-separated API keys from INGEST_API_KEYS env var."""
    raw = os.environ.get("INGEST_API_KEYS", "")
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]


class AuthMiddleware(BaseHTTPMiddleware):
    """Bearer token authentication matching AILang proxy pattern."""

    async def dispatch(self, request: Request, call_next):
        keys = get_api_keys()

        # No keys configured = auth disabled
        if not keys:
            return await call_next(request)

        # Skip auth for public paths
        if request.url.path in SKIP_AUTH_PATHS:
            return await call_next(request)

        # Extract bearer token
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid API key"},
            )

        token = auth[7:]  # Strip "Bearer "

        # Constant-time comparison to prevent timing attacks
        valid = any(hmac.compare_digest(token, k) for k in keys)
        if not valid:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing or invalid API key"},
            )

        return await call_next(request)


# Add middleware (order matters: auth runs before CORS)
app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-loaded singletons
_settings = None
_embedder = None


def get_cached_settings():
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def get_cached_embedder():
    global _embedder
    if _embedder is None:
        _embedder = Embedder(get_cached_settings())
    return _embedder


def _l0_overview_text(l0: L0Chunk) -> str:
    """Compose readable overview text from L0's structured fields."""
    parts = [l0.title]
    if l0.author:
        parts.append(f"Author: {l0.author}")
    if l0.domain:
        parts.append(f"Domain: {l0.domain}")
    parts.append(
        f"Pages: {l0.total_pages} | Chapters: {l0.total_chapters} | "
        f"Sections: {l0.total_sections} | Passages: {l0.total_passages}"
    )
    if l0.toc_summary:
        parts.append(f"TOC: {l0.toc_summary}")
    if l0.key_concepts:
        parts.append(f"Key concepts: {', '.join(l0.key_concepts)}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class IngestResponse(BaseModel):
    doc_id: str
    title: str
    total_pages: int
    total_chunks: int
    l0_tokens: int = Field(description="Token count of L0 (document overview)")
    enriched: bool


class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    total_pages: int
    ingestion_date: str


class DocumentOverview(BaseModel):
    doc_id: str
    title: str
    total_pages: int
    ingestion_date: str
    l0_content: str = Field(description="Document overview (L0 chunk)")
    l0_tokens: int
    total_chunks: int
    chapters: list[str] = Field(default_factory=list)


class TokenEconomics(BaseModel):
    full_document_tokens: int = Field(description="Tokens if entire document were in context")
    l0_overview_tokens: int = Field(description="Tokens for L0 overview (always included)")
    avg_query_tokens: int = Field(description="Average tokens per query (L0 + top passages)")
    savings_percent: float = Field(description="Token savings vs. full document")


class SearchRequest(BaseModel):
    query: str
    n_results: int = Field(default=5, ge=1, le=20)


class HealthResponse(BaseModel):
    status: str
    documents_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check with document count."""
    settings = get_cached_settings()
    docs = list_documents(settings)
    return HealthResponse(status="ok", documents_count=len(docs))


@app.post("/ingest", response_model=IngestResponse)
async def ingest_document(
    file: UploadFile = File(...),
    skip_enrichment: bool = Form(False),
):
    """
    Ingest a PDF into the knowledge store.

    Runs the 6-stage pipeline: parse → structure → chunk → enrich → embed → store.
    """
    settings = get_cached_settings()

    # Save uploaded file to temp location
    suffix = Path(file.filename or "upload.pdf").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        doc_dir = ingest(
            tmp_path,
            settings,
            skip_enrichment=skip_enrichment,
            verbose=False,
        )

        meta = load_document_meta(doc_dir)
        chunks = load_chunks(doc_dir)

        from ingestible.utils.tokens import count_tokens
        l0_tokens = count_tokens(_l0_overview_text(chunks.l0))

        return IngestResponse(
            doc_id=meta.get("doc_id", doc_dir.name),
            title=meta.get("title", "Untitled"),
            total_pages=meta.get("total_pages", 0),
            total_chunks=len(chunks.l3_chunks),
            l0_tokens=l0_tokens,
            enriched=not skip_enrichment,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


class URLIngestRequest(BaseModel):
    url: str
    skip_enrichment: bool = False


@app.post("/ingest/url", response_model=IngestResponse)
async def ingest_url(request: URLIngestRequest):
    """
    Ingest a document from a URL.

    Downloads the URL, detects content type, and runs the full pipeline.
    """
    settings = get_cached_settings()

    doc_dir = ingest(
        request.url,
        settings,
        skip_enrichment=request.skip_enrichment,
        verbose=False,
    )

    meta = load_document_meta(doc_dir)
    chunks = load_chunks(doc_dir)

    from ingestible.utils.tokens import count_tokens
    l0_tokens = count_tokens(_l0_overview_text(chunks.l0))

    return IngestResponse(
        doc_id=meta.get("doc_id", doc_dir.name),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        total_chunks=len(chunks.l3_chunks),
        l0_tokens=l0_tokens,
        enriched=not request.skip_enrichment,
    )


class BatchIngestResult(BaseModel):
    filename: str
    doc_id: str | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0


class BatchIngestResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    elapsed_seconds: float
    results: list[BatchIngestResult]


@app.post("/ingest/batch", response_model=BatchIngestResponse)
async def ingest_batch_endpoint(
    files: list[UploadFile] = File(...),
    skip_enrichment: bool = Form(False),
):
    """
    Ingest multiple files in a single request.

    Accepts multipart file uploads. Each file is ingested independently with
    error isolation — one failure doesn't abort the batch.
    """
    from ingestible.pipeline.batch import BatchReport, FileResult, _ingest_one
    from ingestible.pipeline.orchestrator import generate_doc_id

    settings = get_cached_settings()
    report = BatchReport(total=len(files))
    results: list[BatchIngestResult] = []

    for upload in files:
        suffix = Path(upload.filename or "upload.pdf").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await upload.read()
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            result = _ingest_one(tmp_path, settings, skip_enrichment, force=False)
            if result.error:
                report.failed += 1
                results.append(BatchIngestResult(
                    filename=upload.filename or "unknown",
                    error=result.error,
                    elapsed_seconds=result.elapsed_seconds,
                ))
            else:
                report.succeeded += 1
                results.append(BatchIngestResult(
                    filename=upload.filename or "unknown",
                    doc_id=result.doc_id,
                    elapsed_seconds=result.elapsed_seconds,
                ))
        finally:
            tmp_path.unlink(missing_ok=True)

    return BatchIngestResponse(
        total=report.total,
        succeeded=report.succeeded,
        failed=report.failed,
        elapsed_seconds=sum(r.elapsed_seconds for r in results),
        results=results,
    )


@app.get("/documents", response_model=list[DocumentSummary])
async def list_docs():
    """List all ingested documents."""
    settings = get_cached_settings()
    docs = list_documents(settings)
    return [
        DocumentSummary(
            doc_id=d.get("doc_id", "?"),
            title=d.get("title", "Untitled"),
            total_pages=d.get("total_pages", 0),
            ingestion_date=d.get("ingestion_date", ""),
        )
        for d in docs
    ]


@app.get("/documents/{doc_id}", response_model=DocumentOverview)
async def get_document(doc_id: str):
    """Get document overview including L0 content and structure."""
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    meta = load_document_meta(doc_dir)
    chunks = load_chunks(doc_dir)

    l0_content = _l0_overview_text(chunks.l0)

    from ingestible.utils.tokens import count_tokens
    l0_tokens = count_tokens(l0_content)

    chapters = [c.title for c in chunks.l1_chunks]

    return DocumentOverview(
        doc_id=meta.get("doc_id", doc_id),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        ingestion_date=meta.get("ingestion_date", ""),
        l0_content=l0_content,
        l0_tokens=l0_tokens,
        total_chunks=len(chunks.l3_chunks),
        chapters=chapters,
    )


class DeleteResponse(BaseModel):
    deleted: str


@app.delete("/documents/{doc_id}", response_model=DeleteResponse)
async def delete_document(doc_id: str):
    """Delete an ingested document and all its indexes."""
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    shutil.rmtree(doc_dir)

    return DeleteResponse(deleted=doc_id)


@app.get("/documents/{doc_id}/economics", response_model=TokenEconomics)
async def get_token_economics(doc_id: str):
    """
    Get token economics for a document.

    Shows how many tokens the full document would cost vs. hierarchical retrieval.
    """
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)

    from ingestible.utils.tokens import count_tokens

    # Calculate full document tokens (sum of all L3 chunks)
    full_tokens = 0
    for chunk in chunks.l3_chunks:
        full_tokens += count_tokens(chunk.content)

    # L0 overview tokens
    l0_tokens = count_tokens(_l0_overview_text(chunks.l0))

    # Average query: L0 + ~3 passages (~400 tokens each)
    avg_passage_tokens = 400
    avg_query_tokens = l0_tokens + (3 * avg_passage_tokens)

    savings = ((full_tokens - avg_query_tokens) / full_tokens * 100) if full_tokens > 0 else 0

    return TokenEconomics(
        full_document_tokens=full_tokens,
        l0_overview_tokens=l0_tokens,
        avg_query_tokens=avg_query_tokens,
        savings_percent=round(savings, 1),
    )


@app.post("/documents/{doc_id}/search", response_model=SearchResponse)
async def search_document(doc_id: str, request: SearchRequest):
    """
    Hybrid search within a document.

    Uses vector search (70%), BM25 (30%), and concept index with RRF fusion.
    """
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    embedder = get_cached_embedder()
    searcher = load_searcher(doc_dir, chunks, embedder, settings)

    response = searcher.search(request.query, n_results=request.n_results)
    return response


@app.get("/documents/{doc_id}/chunks", response_model=ChunkSet)
async def get_chunks(doc_id: str):
    """Get the full ChunkSet for a document."""
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    return load_chunks(doc_dir)


@app.get("/documents/{doc_id}/structure", response_model=DocumentStructure)
async def get_structure(doc_id: str):
    """Get the document structure tree."""
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    return load_structure(doc_dir)


# ---------------------------------------------------------------------------
# Corpus search (WP 2.1)
# ---------------------------------------------------------------------------


class CorpusSearchRequest(BaseModel):
    query: str
    n_results: int = Field(default=10, ge=1, le=50)
    doc_ids: list[str] | None = None


@app.post("/search")
async def corpus_search(request: CorpusSearchRequest):
    """Search across all ingested documents with cross-document RRF fusion."""
    from ingestible.search.corpus import CorpusSearcher

    settings = get_cached_settings()
    searcher = CorpusSearcher(settings, embedder=get_cached_embedder())
    return searcher.search(
        request.query, n_results=request.n_results, doc_ids=request.doc_ids
    )


# ---------------------------------------------------------------------------
# Re-enrichment (WP 2.2)
# ---------------------------------------------------------------------------


@app.post("/documents/{doc_id}/enrich", response_model=IngestResponse)
async def enrich_document(doc_id: str):
    """Re-enrich a document without re-parsing. Re-runs enrichment + embedding."""
    from ingestible.pipeline.re_enrich import re_enrich

    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    doc_dir = re_enrich(doc_id, settings)

    meta = load_document_meta(doc_dir)
    chunks = load_chunks(doc_dir)
    from ingestible.utils.tokens import count_tokens
    l0_tokens = count_tokens(_l0_overview_text(chunks.l0))

    return IngestResponse(
        doc_id=meta.get("doc_id", doc_dir.name),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        total_chunks=len(chunks.l3_chunks),
        l0_tokens=l0_tokens,
        enriched=True,
    )


# ---------------------------------------------------------------------------
# Export (WP 2.3)
# ---------------------------------------------------------------------------


@app.get("/documents/{doc_id}/export")
async def export_document_endpoint(
    doc_id: str,
    format: str = Query(..., description="Export format: jsonl, parquet, llamaindex, langchain"),
):
    """Export a document to a portable format. Returns the file as a download."""
    from starlette.responses import FileResponse

    from ingestible.export import EXPORT_FORMATS, export_document

    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    if format not in EXPORT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown format '{format}'. Supported: {sorted(EXPORT_FORMATS)}",
        )

    chunks = load_chunks(doc_dir)
    meta = load_document_meta(doc_dir)

    ext_map = {"jsonl": ".jsonl", "parquet": ".parquet", "llamaindex": ".json", "langchain": ".json"}
    ext = ext_map.get(format, ".json")
    output_path = doc_dir / f"export{ext}"

    export_document(chunks, format, output_path, doc_title=meta.get("title", ""))

    media_types = {
        "jsonl": "application/x-ndjson",
        "parquet": "application/octet-stream",
        "llamaindex": "application/json",
        "langchain": "application/json",
    }

    return FileResponse(
        path=str(output_path),
        filename=f"{doc_id}.{format}{ext}",
        media_type=media_types.get(format, "application/octet-stream"),
    )


# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

from ingestible.web import router as web_router  # noqa: E402

app.include_router(web_router)
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


# ---------------------------------------------------------------------------
# Run with: uvicorn ingestible.api:app --port 8081
# ---------------------------------------------------------------------------
