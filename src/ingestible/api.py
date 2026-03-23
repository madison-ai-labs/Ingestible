"""FastAPI HTTP wrapper for the ingestion pipeline."""

from __future__ import annotations

import hmac
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path

import structlog
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from ingestible.config import get_settings
from ingestible.logging import setup_logging
from ingestible.models.chunks import ChunkSet, L0Chunk
from ingestible.models.document import DocumentStructure
from ingestible.models.search import SearchResponse
from ingestible.pipeline.locking import document_lock
from ingestible.pipeline.orchestrator import ingest
from ingestible.pipeline.stage5_embedding import Embedder
from ingestible.pipeline.stage6_storage import (
    list_documents,
    load_chunks,
    load_document_meta,
    load_structure,
    update_document_meta,
)
from ingestible.pipeline.task_queue import get_task_queue
from ingestible.search.hybrid import load_searcher

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Ingestible API",
    description="PDF ingestion pipeline with hierarchical retrieval",
    version="1.0.0",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# ---------------------------------------------------------------------------
# Boot-time settings (read once for middleware configuration)
# ---------------------------------------------------------------------------

_boot_settings = get_settings()

_RATE_INGEST = _boot_settings.rate_limit_ingest
_RATE_SEARCH = _boot_settings.rate_limit_search
_RATE_DEFAULT = _boot_settings.rate_limit_default


# ---------------------------------------------------------------------------
# Authentication Middleware
# ---------------------------------------------------------------------------

SKIP_AUTH_PATHS = {"/health", "/health/ready", "/docs", "/openapi.json", "/redoc", "/metrics"}


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
    allow_origins=_boot_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)

Instrumentator().instrument(app).expose(app, endpoint="/metrics")


@app.on_event("startup")
async def _startup():
    settings = get_cached_settings()
    setup_logging(json_output=settings.log_json, level=settings.log_level)

    # Clean up stale checkpoints and temp files from previous runs
    from ingestible.pipeline.cleanup import cleanup_stale

    counts = cleanup_stale(settings)
    if any(counts.values()):
        import logging

        logging.getLogger(__name__).info("Startup cleanup: %s", counts)


@app.on_event("shutdown")
async def _shutdown():
    """Drain background ingestion jobs on shutdown."""
    import logging

    logger = logging.getLogger(__name__)
    queue = get_task_queue()
    active = queue.active_count()
    if active > 0:
        logger.info("Shutting down — waiting for %d active ingestion(s)...", active)
    queue.shutdown(wait=True)
    logger.info("Shutdown complete.")


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


_DOC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")


def _validate_doc_id(doc_id: str) -> str:
    """Sanitise and validate a document ID to prevent path traversal."""
    doc_id = doc_id.strip()
    if any(c in doc_id for c in ("/", "\\", "\x00")) or ".." in doc_id:
        raise HTTPException(status_code=400, detail=f"Invalid document ID: {doc_id}")
    if not _DOC_ID_RE.match(doc_id):
        raise HTTPException(status_code=400, detail=f"Invalid document ID: {doc_id}")
    return doc_id


def _check_upload_size(content: bytes, settings) -> None:
    """Raise 413 if *content* exceeds the configured upload limit."""
    if len(content) > settings.max_upload_bytes:
        max_mb = settings.max_upload_bytes / 1_000_000
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size: {max_mb:.0f}MB",
        )


def _get_user(request: Request) -> str:
    """Extract user identity from request headers.

    Priority: X-User-ID header (set by auth proxy) > bearer token prefix > 'anonymous'.
    """
    user_id = request.headers.get("X-User-ID", "")
    if user_id:
        return user_id.strip()
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and len(auth) > 15:
        return auth[7:15]
    return "anonymous"


def _l0_overview_text(l0: L0Chunk) -> str:
    """Compose readable overview text from L0's structured fields."""
    parts = [l0.title]
    if l0.author:
        parts.append(f"Author: {l0.author}")
    if l0.domain:
        parts.append(f"Domain: {l0.domain}")
    if l0.document_type:
        parts.append(f"Type: {l0.document_type}")
    parts.append(
        f"Pages: {l0.total_pages} | Chapters: {l0.total_chapters} | "
        f"Sections: {l0.total_sections} | Passages: {l0.total_passages}"
    )
    if l0.executive_summary:
        parts.append(f"Summary: {l0.executive_summary}")
    if l0.key_findings:
        parts.append("Key findings:")
        for f in l0.key_findings:
            parts.append(f"  - {f}")
    if l0.methodology:
        parts.append(f"Methodology: {l0.methodology}")
    if l0.limitations:
        parts.append(f"Limitations: {l0.limitations}")
    if l0.target_audience:
        parts.append(f"Audience: {l0.target_audience}")
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
    hyde: bool = Field(default=False, description="Use HyDE query expansion for vector search")
    auto_merge: bool = Field(default=False, description="Auto-merge L3 results into parent L2/L1")
    kg_boost: bool = Field(
        default=False, description="Boost results using knowledge graph relationships"
    )


class HealthResponse(BaseModel):
    status: str
    documents_count: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
@limiter.limit(_RATE_DEFAULT)
async def health(request: Request):
    """Health check with document count."""
    settings = get_cached_settings()
    docs = list_documents(settings)
    return HealthResponse(status="ok", documents_count=len(docs))


class ReadinessCheck(BaseModel):
    status: str
    checks: dict[str, dict]


@app.get("/health/ready", response_model=ReadinessCheck)
@limiter.limit(_RATE_DEFAULT)
async def health_ready(request: Request):
    """Deep readiness check — verifies all dependencies are available."""
    settings = get_cached_settings()
    checks: dict[str, dict] = {}
    all_ok = True

    # 1. Data directory writable
    try:
        test_file = settings.data_dir / ".health_check"
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        test_file.write_text("ok")
        test_file.unlink()
        checks["data_dir"] = {"status": "ok", "path": str(settings.data_dir)}
    except Exception as e:
        checks["data_dir"] = {"status": "error", "error": str(e)}
        all_ok = False

    # 2. Disk space
    try:
        usage = shutil.disk_usage(settings.data_dir)
        free_mb = usage.free / (1024 * 1024)
        if free_mb < settings.min_disk_space_mb:
            checks["disk_space"] = {
                "status": "warning",
                "free_mb": round(free_mb),
                "min_mb": settings.min_disk_space_mb,
            }
            all_ok = False
        else:
            checks["disk_space"] = {"status": "ok", "free_mb": round(free_mb)}
    except Exception as e:
        checks["disk_space"] = {"status": "error", "error": str(e)}
        all_ok = False

    # 3. Embedding model
    try:
        embedder = get_cached_embedder()
        # Quick sanity check — embed a single short text
        embedder.model.encode(["health check"], show_progress_bar=False)
        checks["embedding_model"] = {"status": "ok", "model": settings.embedding_model}
    except Exception as e:
        checks["embedding_model"] = {"status": "error", "error": str(e)}
        all_ok = False

    # 4. LLM API configured
    try:
        from ingestible.pipeline.stage4_enrichment import _make_client

        _make_client(settings)  # validates keys exist and client instantiates
        checks["llm_api"] = {"status": "ok", "provider": settings.llm_provider}
    except Exception as e:
        checks["llm_api"] = {"status": "error", "error": str(e)}
        all_ok = False

    # 5. Document count
    docs = list_documents(settings)
    checks["documents"] = {"status": "ok", "count": len(docs)}

    return ReadinessCheck(
        status="ready" if all_ok else "degraded",
        checks=checks,
    )


@app.post("/ingest", response_model=IngestResponse)
@limiter.limit(_RATE_INGEST)
async def ingest_document(
    request: Request,
    file: UploadFile = File(...),
    skip_enrichment: bool = Form(False),
    profile: str = Form("auto"),
    access_tags: str = Form(""),
    weight: float = Form(0.0),
    pinned: bool = Form(False),
    tags: str = Form(""),
):
    """
    Ingest a PDF into the knowledge store.

    Runs the 6-stage pipeline: parse -> structure -> chunk -> enrich -> embed -> store.
    """
    settings = get_cached_settings()

    # Save uploaded file to temp location
    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        if profile != "auto":
            from ingestible.config import get_settings as _gs

            settings = _gs(extraction_profile=profile)

        parsed_access_tags = (
            [t.strip() for t in access_tags.split(",") if t.strip()] if access_tags else None
        )
        parsed_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

        doc_dir = ingest(
            tmp_path,
            settings,
            skip_enrichment=skip_enrichment,
            verbose=False,
            access_tags=parsed_access_tags,
            weight=weight,
            pinned=pinned,
            tags=parsed_tags,
        )

        meta = load_document_meta(doc_dir)
        chunks = load_chunks(doc_dir)

        from ingestible.utils.tokens import count_tokens

        l0_tokens = count_tokens(_l0_overview_text(chunks.l0))

        doc_id = meta.get("doc_id", doc_dir.name)

        if settings.audit_enabled:
            from ingestible.audit import log_ingest

            log_ingest(
                settings.data_dir / "audit.jsonl",
                doc_id=doc_id,
                user=_get_user(request),
                title=meta.get("title", ""),
                source_path=file.filename or "",
                total_chunks=len(chunks.l3_chunks),
                enriched=not skip_enrichment,
            )

        return IngestResponse(
            doc_id=doc_id,
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
    profile: str = "auto"


@app.post("/ingest/url", response_model=IngestResponse)
@limiter.limit(_RATE_INGEST)
async def ingest_url(body: URLIngestRequest, request: Request):
    """
    Ingest a document from a URL.

    Downloads the URL, detects content type, and runs the full pipeline.
    """
    settings = get_cached_settings()

    if body.profile != "auto":
        from ingestible.config import get_settings as _gs

        settings = _gs(extraction_profile=body.profile)

    doc_dir = ingest(
        body.url,
        settings,
        skip_enrichment=body.skip_enrichment,
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
        enriched=not body.skip_enrichment,
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
@limiter.limit(_RATE_INGEST)
async def ingest_batch_endpoint(
    request: Request,
    files: list[UploadFile] = File(...),
    skip_enrichment: bool = Form(False),
):
    """
    Ingest multiple files in a single request.

    Accepts multipart file uploads. Each file is ingested independently with
    error isolation -- one failure doesn't abort the batch.
    """
    from ingestible.pipeline.batch import BatchReport, _ingest_one

    settings = get_cached_settings()
    report = BatchReport(total=len(files))
    results: list[BatchIngestResult] = []

    for upload in files:
        suffix = Path(upload.filename or "upload.pdf").suffix
        content = await upload.read()
        _check_upload_size(content, settings)
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(content)
            tmp_path = Path(tmp.name)

        try:
            result = _ingest_one(tmp_path, settings, skip_enrichment, force=False)
            if result.error:
                report.failed += 1
                results.append(
                    BatchIngestResult(
                        filename=upload.filename or "unknown",
                        error=result.error,
                        elapsed_seconds=result.elapsed_seconds,
                    )
                )
            else:
                report.succeeded += 1
                results.append(
                    BatchIngestResult(
                        filename=upload.filename or "unknown",
                        doc_id=result.doc_id,
                        elapsed_seconds=result.elapsed_seconds,
                    )
                )
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
@limiter.limit(_RATE_DEFAULT)
async def list_docs(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    tags: str = Query(default="", description="Comma-separated tags to filter by"),
):
    """List all ingested documents, optionally filtered by tags."""
    settings = get_cached_settings()
    filter_tags = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    docs = list_documents(settings, tags=filter_tags)
    paginated = docs[offset : offset + limit]
    return [
        DocumentSummary(
            doc_id=d.get("doc_id", "?"),
            title=d.get("title", "Untitled"),
            total_pages=d.get("total_pages", 0),
            ingestion_date=d.get("ingestion_date", ""),
        )
        for d in paginated
    ]


@app.get("/documents/{doc_id}", response_model=DocumentOverview)
@limiter.limit(_RATE_DEFAULT)
async def get_document(doc_id: str, request: Request):
    """Get document overview including L0 content and structure."""
    doc_id = _validate_doc_id(doc_id)
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


class UpdateMetaRequest(BaseModel):
    weight: float | None = None
    pinned: bool | None = None
    tags: list[str] | None = None


@app.patch("/documents/{doc_id}/meta")
@limiter.limit(_RATE_DEFAULT)
async def patch_document_meta(doc_id: str, body: UpdateMetaRequest, request: Request):
    """Update mutable metadata (weight, pinned, tags) without re-ingesting."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    meta = update_document_meta(doc_dir, weight=body.weight, pinned=body.pinned, tags=body.tags)
    return {
        "doc_id": doc_id,
        "weight": meta.get("weight", 0.0),
        "pinned": meta.get("pinned", False),
        "tags": meta.get("tags", []),
    }


class DeleteResponse(BaseModel):
    deleted: str


@app.delete("/documents/{doc_id}", response_model=DeleteResponse)
@limiter.limit(_RATE_DEFAULT)
async def delete_document(doc_id: str, request: Request):
    """Delete an ingested document and all its indexes."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    shutil.rmtree(doc_dir)

    if settings.audit_enabled:
        from ingestible.audit import log_delete

        log_delete(
            settings.data_dir / "audit.jsonl",
            doc_id=doc_id,
            user=_get_user(request),
        )

    return DeleteResponse(deleted=doc_id)


@app.get("/documents/{doc_id}/economics", response_model=TokenEconomics)
@limiter.limit(_RATE_DEFAULT)
async def get_token_economics(doc_id: str, request: Request):
    """
    Get token economics for a document.

    Shows how many tokens the full document would cost vs. hierarchical retrieval.
    """
    doc_id = _validate_doc_id(doc_id)
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

    # Compute actual average passage tokens
    passage_tokens = [count_tokens(c.content) for c in chunks.l3_chunks]
    avg_passage_tokens = sum(passage_tokens) / len(passage_tokens) if passage_tokens else 400
    avg_query_tokens = l0_tokens + (3 * int(avg_passage_tokens))

    savings = ((full_tokens - avg_query_tokens) / full_tokens * 100) if full_tokens > 0 else 0

    return TokenEconomics(
        full_document_tokens=full_tokens,
        l0_overview_tokens=l0_tokens,
        avg_query_tokens=avg_query_tokens,
        savings_percent=round(savings, 1),
    )


@app.post("/documents/{doc_id}/search", response_model=SearchResponse)
@limiter.limit(_RATE_SEARCH)
async def search_document(doc_id: str, body: SearchRequest, request: Request):
    """
    Hybrid search within a document.

    Uses vector search (70%), BM25 (30%), and concept index with RRF fusion.
    """
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    embedder = get_cached_embedder()

    # Apply search overrides
    search_settings = settings
    overrides = {}
    if body.auto_merge:
        overrides["auto_merge_enabled"] = True
    if body.kg_boost:
        overrides["kg_retrieval_enabled"] = True
    if overrides:
        search_settings = settings.model_copy(update=overrides)

    searcher = load_searcher(doc_dir, chunks, embedder, search_settings)

    # Access control
    user_tags = None
    if settings.access_control_enabled:
        tags_header = request.headers.get("X-Access-Tags", "")
        user_tags = (
            [t.strip() for t in tags_header.split(",") if t.strip()] if tags_header else None
        )

    # Audit: identify user from bearer token
    user = _get_user(request) if settings.audit_enabled else ""

    # HyDE query expansion
    hyde_query = None
    if body.hyde:
        try:
            from ingestible.search.query_expansion import HyDEExpander

            expander = HyDEExpander(search_settings)
            hyde_query = await expander.expand(body.query)
        except Exception:
            pass  # fall back to normal search

    response = searcher.search(
        body.query, n_results=body.n_results, user_tags=user_tags, user=user, hyde_query=hyde_query
    )
    return response


@app.get("/documents/{doc_id}/chunks", response_model=ChunkSet)
@limiter.limit(_RATE_DEFAULT)
async def get_chunks(doc_id: str, request: Request):
    """Get the full ChunkSet for a document."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    return load_chunks(doc_dir)


@app.get("/documents/{doc_id}/citations")
@limiter.limit(_RATE_DEFAULT)
async def get_citations(doc_id: str, request: Request):
    """Get extracted citations for a document."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    return {"doc_id": doc_id, "citations": [c.model_dump() for c in chunks.citations]}


@app.get("/documents/{doc_id}/knowledge-graph")
@limiter.limit(_RATE_DEFAULT)
async def get_knowledge_graph(doc_id: str, request: Request):
    """Get extracted knowledge graph triples for a document."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)

    # Build entity index from triples
    entities: dict[str, dict] = {}
    for t in chunks.knowledge_graph:
        for name, etype in [(t.subject, t.subject_type), (t.object, t.object_type)]:
            key = name.lower()
            if key not in entities:
                entities[key] = {"name": name, "type": etype, "count": 0}
            entities[key]["count"] += 1

    return {
        "doc_id": doc_id,
        "total_triples": len(chunks.knowledge_graph),
        "total_entities": len(entities),
        "triples": [t.model_dump() for t in chunks.knowledge_graph],
        "entities": sorted(entities.values(), key=lambda e: e["count"], reverse=True),
    }


@app.get("/documents/{doc_id}/structure", response_model=DocumentStructure)
@limiter.limit(_RATE_DEFAULT)
async def get_structure(doc_id: str, request: Request):
    """Get the document structure tree."""
    doc_id = _validate_doc_id(doc_id)
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
    tags: list[str] | None = None
    hyde: bool = Field(default=False, description="Use HyDE query expansion")
    auto_merge: bool = Field(default=False, description="Auto-merge L3 results into parent L2/L1")
    kg_boost: bool = Field(
        default=False, description="Boost results using knowledge graph relationships"
    )


@app.post("/search")
@limiter.limit(_RATE_SEARCH)
async def corpus_search(body: CorpusSearchRequest, request: Request):
    """Search across all ingested documents with cross-document RRF fusion."""
    from ingestible.search.corpus import CorpusSearcher

    settings = get_cached_settings()

    # Apply search overrides (hyde handled separately at corpus level)
    overrides = {}
    if body.auto_merge:
        overrides["auto_merge_enabled"] = True
    if body.kg_boost:
        overrides["kg_retrieval_enabled"] = True
    if overrides:
        settings = settings.model_copy(update=overrides)

    # Access control
    user_tags = None
    if settings.access_control_enabled:
        tags_header = request.headers.get("X-Access-Tags", "")
        user_tags = (
            [t.strip() for t in tags_header.split(",") if t.strip()] if tags_header else None
        )

    user = _get_user(request) if settings.audit_enabled else ""

    # HyDE: expand once at corpus level
    hyde_query = None
    if body.hyde:
        try:
            from ingestible.search.query_expansion import HyDEExpander

            expander = HyDEExpander(settings)
            hyde_query = await expander.expand(body.query)
        except Exception:
            pass

    searcher = CorpusSearcher(settings, embedder=get_cached_embedder())
    return searcher.search(
        body.query,
        n_results=body.n_results,
        doc_ids=body.doc_ids,
        user_tags=user_tags,
        user=user,
        tags=body.tags,
        hyde_query=hyde_query,
    )


# ---------------------------------------------------------------------------
# Re-enrichment (WP 2.2)
# ---------------------------------------------------------------------------


@app.post("/documents/{doc_id}/enrich", response_model=IngestResponse)
@limiter.limit(_RATE_INGEST)
async def enrich_document(doc_id: str, request: Request):
    """Re-enrich a document without re-parsing. Re-runs enrichment + embedding."""
    doc_id = _validate_doc_id(doc_id)
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

    if settings.audit_enabled:
        from ingestible.audit import log_re_enrich

        log_re_enrich(
            settings.data_dir / "audit.jsonl",
            doc_id=doc_id,
            user=_get_user(request),
        )

    return IngestResponse(
        doc_id=meta.get("doc_id", doc_dir.name),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        total_chunks=len(chunks.l3_chunks),
        l0_tokens=l0_tokens,
        enriched=True,
    )


# ---------------------------------------------------------------------------
# Retrieval Evaluation
# ---------------------------------------------------------------------------


@app.post("/documents/{doc_id}/eval")
@limiter.limit(_RATE_DEFAULT)
async def eval_document(doc_id: str, request: Request, k: int = Query(default=5, ge=1, le=50)):
    """Evaluate retrieval quality using synthetic queries from enrichment."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    from ingestible.eval import evaluate_document

    report = evaluate_document(doc_id, settings, k=k)
    return report.to_dict()


@app.post("/documents/{doc_id}/eval/judge")
@limiter.limit(_RATE_DEFAULT)
async def eval_document_judge(
    doc_id: str, request: Request, k: int = Query(default=5, ge=1, le=50)
):
    """Evaluate retrieval quality using LLM-as-judge scoring.

    Returns faithfulness, relevance, and completeness scores (0-1 scale)
    assessed by the configured LLM provider.
    """
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    from ingestible.eval_llm_judge import evaluate_with_judge

    report = await evaluate_with_judge(
        doc_id, settings, k=k, concurrency=settings.llm_judge_concurrency
    )
    return report.to_dict()


# ---------------------------------------------------------------------------
# Export (WP 2.3)
# ---------------------------------------------------------------------------


@app.get("/documents/{doc_id}/export")
@limiter.limit(_RATE_DEFAULT)
async def export_document_endpoint(
    doc_id: str,
    request: Request,
    format: str = Query(..., description="Export format: jsonl, parquet, llamaindex, langchain"),
):
    """Export a document to a portable format. Returns the file as a download."""
    doc_id = _validate_doc_id(doc_id)
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

    ext_map = {
        "jsonl": ".jsonl",
        "parquet": ".parquet",
        "llamaindex": ".json",
        "langchain": ".json",
    }
    ext = ext_map.get(format, ".json")
    output_path = doc_dir / f"export{ext}"

    export_document(chunks, format, output_path, doc_title=meta.get("title", ""))

    if settings.audit_enabled:
        from ingestible.audit import log_export

        log_export(
            settings.data_dir / "audit.jsonl",
            doc_id=doc_id,
            user=_get_user(request),
            format=format,
        )

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
# Versioning (WP 5.1)
# ---------------------------------------------------------------------------


@app.get("/documents/{doc_id}/versions")
@limiter.limit(_RATE_DEFAULT)
async def get_versions(doc_id: str, request: Request):
    """List all archived versions of a document."""
    doc_id = _validate_doc_id(doc_id)
    from ingestible.pipeline.stage6_storage import list_versions

    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    versions = list_versions(doc_dir)
    return {"doc_id": doc_id, "versions": versions}


# ---------------------------------------------------------------------------
# SSE Streaming Ingest (WP 5.2)
# ---------------------------------------------------------------------------


@app.post("/ingest/stream")
@limiter.limit(_RATE_INGEST)
async def ingest_stream(
    request: Request,
    file: UploadFile = File(...),
    skip_enrichment: bool = Form(False),
):
    """Ingest a document with Server-Sent Events progress streaming."""
    from starlette.responses import StreamingResponse

    from ingestible.pipeline.progress import SSEProgress

    settings = get_cached_settings()

    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    def generate():
        progress = SSEProgress()

        try:
            doc_dir = ingest(
                tmp_path,
                settings,
                skip_enrichment=skip_enrichment,
                verbose=False,
                progress_callback=progress,
            )

            # Yield all progress events
            for evt in progress.events:
                yield f"data: {json.dumps(evt)}\n\n"

            meta = load_document_meta(doc_dir)
            yield f"data: {json.dumps({'status': 'complete', 'doc_id': meta.get('doc_id', doc_dir.name)})}\n\n"
        except Exception as e:
            error_msg = str(e)[:200]  # truncate to avoid leaking internal details
            yield f"data: {json.dumps({'status': 'error', 'error': error_msg})}\n\n"
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Background Jobs (WP 8.1)
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    job_id: str
    status: str


class JobDetailResponse(BaseModel):
    job_id: str
    status: str
    doc_id: str | None = None
    error: str | None = None
    created_at: float
    started_at: float | None = None
    finished_at: float | None = None
    progress_stage: str = ""
    progress_step: int = 0
    progress_total: int = 0


@app.post("/ingest/async", response_model=JobResponse, status_code=202)
@limiter.limit(_RATE_INGEST)
async def ingest_async(
    request: Request,
    file: UploadFile = File(...),
    skip_enrichment: bool = Form(False),
):
    """Submit a document for background ingestion. Returns a job ID immediately."""
    settings = get_cached_settings()

    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)

    # Write to a persistent temp file (not auto-deleted)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(content)
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        queue = get_task_queue(max_workers=settings.max_concurrent_ingestions)
        job = queue.submit_ingestion(
            tmp.name,
            settings,
            skip_enrichment=skip_enrichment,
        )
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return JobResponse(job_id=job.job_id, status=job.status.value)


@app.get("/jobs/{job_id}", response_model=JobDetailResponse)
@limiter.limit(_RATE_DEFAULT)
async def get_job_status(job_id: str, request: Request):
    """Get the status of a background ingestion job."""
    queue = get_task_queue()
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    d = job.to_dict()
    return JobDetailResponse(**d)


@app.get("/jobs", response_model=list[JobDetailResponse])
@limiter.limit(_RATE_DEFAULT)
async def list_jobs(request: Request):
    """List all ingestion jobs."""
    queue = get_task_queue()
    return [JobDetailResponse(**j.to_dict()) for j in queue.list_jobs()]


# ---------------------------------------------------------------------------
# Webhook: CognitiveVault -> Ingestible (P2)
# ---------------------------------------------------------------------------


def _find_chunk_file(doc_dir: Path, chunk_id: str) -> Path | None:
    """Locate a chunk's JSON file in the document directory hierarchy."""
    # Check orphan chunks first
    orphan = doc_dir / "chunks" / f"{chunk_id}.json"
    if orphan.exists():
        return orphan
    # Search within chapter/section hierarchy
    chapters_dir = doc_dir / "chapters"
    if chapters_dir.exists():
        for chunk_file in chapters_dir.rglob(f"{chunk_id}.json"):
            return chunk_file
    return None


class CVWebhookPayload(BaseModel):
    """Payload from CognitiveVault entry.updated webhook."""

    entry_id: str = Field(alias="entryId")
    source_path: str = Field(alias="sourcePath")
    content: str
    checksum: str

    model_config = {"populate_by_name": True}


def _verify_webhook_signature(body: bytes, signature: str, secret: str) -> bool:
    """Verify HMAC-SHA256 webhook signature."""
    import hashlib

    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.post("/webhooks/cv")
@limiter.limit(_RATE_DEFAULT)
async def cv_webhook(request: Request):
    """Receive entry.updated webhooks from CognitiveVault.

    When a CV entry with an ``ingest:`` sourcePath is edited, this endpoint
    updates the local chunk content and triggers selective re-enrichment.
    """
    secret = os.environ.get("INGEST_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(status_code=500, detail="INGEST_WEBHOOK_SECRET not configured")

    # Verify HMAC signature
    signature = request.headers.get("X-Webhook-Signature", "")
    body = await request.body()
    if not _verify_webhook_signature(body, signature, secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    # Parse envelope
    try:
        envelope = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = envelope.get("event")
    if event != "entry.updated":
        return {"status": "ignored", "event": event}

    payload = CVWebhookPayload.model_validate(envelope.get("payload", {}))

    # Parse sourcePath: "ingest:{doc_id}/{chunk_id}"
    if not payload.source_path.startswith("ingest:"):
        return {"status": "ignored", "reason": "not an ingest-sourced entry"}

    path_part = payload.source_path[len("ingest:") :]
    parts = path_part.split("/", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sourcePath format: {payload.source_path}",
        )

    doc_id, chunk_id = parts

    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    # Find and update the chunk file on disk under lock
    import hashlib as _hashlib

    with document_lock(doc_dir):
        chunk_file = _find_chunk_file(doc_dir, chunk_id)
        if chunk_file is None:
            raise HTTPException(status_code=404, detail=f"Chunk not found: {chunk_id}")

        chunk_data = json.loads(chunk_file.read_text(encoding="utf-8"))
        chunk_data["content"] = payload.content
        chunk_data["content_hash"] = _hashlib.sha256(payload.content.encode()).hexdigest()
        chunk_file.write_text(
            json.dumps(chunk_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Store CV checksum so watcher/sync knows this chunk was edited in CV
        meta = load_document_meta(doc_dir)
        cv_checksums = meta.get("cv_checksums", {})
        cv_checksums[chunk_id] = payload.checksum
        meta["cv_checksums"] = cv_checksums
        meta_path = doc_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    # Selective re-enrichment for just this chunk (acquires its own lock)
    from ingestible.pipeline.re_enrich import re_enrich

    re_enrich(doc_id, settings, changed_chunk_ids={chunk_id})

    if settings.audit_enabled:
        from ingestible.audit import log_webhook

        log_webhook(
            settings.data_dir / "audit.jsonl",
            doc_id=doc_id,
            chunk_id=chunk_id,
        )

    return {
        "status": "ok",
        "doc_id": doc_id,
        "chunk_id": chunk_id,
        "re_enriched": True,
    }


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
