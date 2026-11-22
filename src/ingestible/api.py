"""FastAPI HTTP wrapper for the ingestion pipeline."""

from __future__ import annotations

import asyncio
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
from ingestible.pipeline.task_queue import UserConcurrencyExceeded, get_task_queue
from ingestible.search.hybrid import load_searcher

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Ingestible API",
    description=(
        "Document ingestion pipeline with hierarchical chunking and hybrid search. "
        "Supports 25+ file formats including PDF, DOCX, HTML, Markdown, audio, video, "
        "spreadsheets, and more. Documents are parsed, structured, chunked into a 4-level "
        "hierarchy (L0-L3), optionally enriched with LLM-generated metadata, embedded, "
        "and stored for hybrid vector + BM25 retrieval."
    ),
    version="1.1.0",
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
    """Bearer token authentication — checks env-var keys first, then Supabase."""

    async def dispatch(self, request: Request, call_next):
        from ingestible.auth import (
            update_usage_stats,
            validate_supabase_key,
        )

        env_keys = get_api_keys()
        supabase_client = getattr(request.app.state, "supabase_http", None)

        # No auth configured at all = auth disabled
        if not env_keys and supabase_client is None:
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

        # Fast path: env-var keys (constant-time comparison)
        if env_keys and any(hmac.compare_digest(token, k) for k in env_keys):
            return await call_next(request)

        # Slow path: Supabase lookup (with cache)
        if supabase_client is not None:
            valid, key_id = await validate_supabase_key(token, supabase_client)
            if valid:
                request.state.key_id = key_id
                asyncio.create_task(update_usage_stats(key_id, supabase_client))

                # Soft-gate: fetch quotas (failures allow the request through)
                try:
                    from ingestible.auth import get_user_quotas

                    quotas = await get_user_quotas(key_id, supabase_client)
                    if quotas is not None:
                        request.state.quotas = quotas
                        if quotas.suspended:
                            return JSONResponse(
                                status_code=403,
                                content={"detail": "Account suspended"},
                            )
                        if quotas.requests_today >= quotas.requests_per_day:
                            return JSONResponse(
                                status_code=429,
                                content={"detail": "Daily request quota exceeded"},
                            )
                except Exception:
                    pass  # quota fetch failed — allow request through

                return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Missing or invalid API key"},
        )


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
    import logging

    import httpx

    from ingestible.auth import init_supabase_auth

    settings = get_cached_settings()
    setup_logging(json_output=settings.log_json, level=settings.log_level)

    _logger = logging.getLogger(__name__)

    # Supabase key validation
    if init_supabase_auth():
        app.state.supabase_http = httpx.AsyncClient(timeout=5.0)
        _logger.info("Supabase API key validation enabled")
    else:
        app.state.supabase_http = None

    # Clean up stale checkpoints and temp files from previous runs
    from ingestible.pipeline.cleanup import cleanup_stale

    counts = cleanup_stale(settings)
    if any(counts.values()):
        _logger.info("Startup cleanup: %s", counts)


@app.on_event("shutdown")
async def _shutdown():
    """Drain background ingestion jobs and close HTTP clients on shutdown."""
    import logging

    logger = logging.getLogger(__name__)

    # Close Supabase HTTP client
    supabase_http = getattr(app.state, "supabase_http", None)
    if supabase_http is not None:
        await supabase_http.aclose()

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


def _check_ingestion_quotas(request: Request, content_length: int, skip_enrichment: bool) -> bool:
    """Enforce tier-based ingestion quotas from Supabase.

    Raises :class:`HTTPException` if the request violates a quota limit.
    Returns the (possibly updated) *skip_enrichment* flag — free-tier users
    have enrichment silently disabled.

    If no quotas are attached to the request (env-var auth, Supabase down),
    the request is allowed through unchanged.
    """
    quotas = getattr(request.state, "quotas", None)
    if quotas is None:
        return skip_enrichment

    if quotas.documents_ingested >= quotas.max_documents:
        raise HTTPException(
            status_code=403,
            detail="Document limit reached for your plan",
        )

    if content_length > quotas.max_file_size_mb * 1_000_000:
        raise HTTPException(
            status_code=413,
            detail="File exceeds your plan's size limit",
        )

    if not quotas.enrichment_enabled and not skip_enrichment:
        skip_enrichment = True

    return skip_enrichment


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
    """Result of a successful document ingestion."""

    doc_id: str = Field(description="Unique document identifier (slug derived from filename)")
    title: str = Field(description="Extracted or inferred document title")
    total_pages: int = Field(description="Number of pages (or segments for non-paged formats)")
    total_chunks: int = Field(description="Number of L3 (passage-level) chunks created")
    l0_tokens: int = Field(description="Token count of the L0 document overview")
    enriched: bool = Field(description="Whether LLM enrichment was applied")
    enrichment_tokens: int = Field(default=0, description="Total LLM tokens used during enrichment")
    estimated_cost_usd: float = Field(default=0.0, description="Estimated USD cost of ingestion")
    duration_seconds: float = Field(default=0.0, description="Total pipeline duration in seconds")
    storage_bytes: int = Field(default=0, description="Total storage bytes on disk")


class DocumentSummary(BaseModel):
    """Lightweight document listing entry."""

    doc_id: str = Field(description="Unique document identifier")
    title: str = Field(description="Document title")
    total_pages: int = Field(description="Number of pages")
    ingestion_date: str = Field(description="ISO 8601 ingestion timestamp")


class DocumentOverview(BaseModel):
    """Detailed document overview including L0 content and chapter list."""

    doc_id: str = Field(description="Unique document identifier")
    title: str = Field(description="Document title")
    total_pages: int = Field(description="Number of pages")
    ingestion_date: str = Field(description="ISO 8601 ingestion timestamp")
    l0_content: str = Field(
        description="Human-readable L0 overview (title, summary, key findings, TOC)"
    )
    l0_tokens: int = Field(description="Token count of the L0 overview")
    total_chunks: int = Field(description="Number of L3 (passage-level) chunks")
    chapters: list[str] = Field(default_factory=list, description="L1 chapter titles")
    original_filename: str = Field(
        default="", description="Original uploaded filename (empty for older documents)"
    )
    original_media_type: str = Field(
        default="", description="MIME type of the original file (empty for older documents)"
    )
    has_pdf: bool = Field(
        default=False,
        description="True if the original PDF is retained and can be fetched via GET /documents/{doc_id}/pdf",
    )
    pdf_url: str | None = Field(
        default=None,
        description="Relative URL to fetch the original PDF, or null if not available",
    )


class TokenEconomics(BaseModel):
    """Token cost comparison: full document vs. hierarchical retrieval."""

    full_document_tokens: int = Field(
        description="Tokens if the entire document were placed in context"
    )
    l0_overview_tokens: int = Field(
        description="Tokens for the L0 overview (always included in queries)"
    )
    avg_query_tokens: int = Field(description="Average tokens per query (L0 + top-3 passages)")
    savings_percent: float = Field(
        description="Percentage token savings vs. full document in context"
    )


class SearchRequest(BaseModel):
    """Search query with optional enhancement flags."""

    query: str = Field(description="Natural language search query")
    n_results: int = Field(default=5, ge=1, le=20, description="Number of results to return (1-20)")
    hyde: bool = Field(
        default=False,
        description="Use HyDE query expansion — generates a hypothetical answer passage via LLM for better vector matching",
    )
    auto_merge: bool = Field(
        default=False,
        description="Auto-merge L3 results into parent L2/L1 when 3+ passages from the same section match",
    )
    kg_boost: bool = Field(
        default=False, description="Boost results using knowledge graph entity relationships"
    )


class HealthResponse(BaseModel):
    """Liveness probe response."""

    status: str = Field(description="Always 'ok' if the service is running")
    documents_count: int = Field(description="Number of ingested documents")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["Health"])
@limiter.limit(_RATE_DEFAULT)
async def health(request: Request):
    """Fast liveness probe. Returns immediately without checking dependencies."""
    settings = get_cached_settings()
    docs = list_documents(settings)
    return HealthResponse(status="ok", documents_count=len(docs))


class ReadinessCheck(BaseModel):
    """Deep readiness check result with per-dependency status."""

    status: str = Field(description="Overall status: 'ready' or 'degraded'")
    checks: dict[str, dict] = Field(
        description="Per-dependency check results (data_dir, disk_space, embedding_model, llm_api, documents)"
    )


@app.get("/health/ready", response_model=ReadinessCheck, tags=["Health"])
@limiter.limit(_RATE_DEFAULT)
async def health_ready(request: Request):
    """Deep readiness check. Verifies data directory, disk space, embedding model, and LLM API."""
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


@app.post("/ingest", response_model=IngestResponse, tags=["Ingestion"])
@limiter.limit(_RATE_INGEST)
async def ingest_document(
    request: Request,
    file: UploadFile = File(
        ..., description="Document file to ingest (PDF, DOCX, HTML, Markdown, audio, video, etc.)"
    ),
    skip_enrichment: bool = Form(
        False, description="Skip LLM enrichment (faster, but no summaries/concepts/questions)"
    ),
    profile: str = Form(
        "auto", description="Extraction profile: 'auto', 'fast', 'accurate', or 'economy'"
    ),
    access_tags: str = Form(
        "", description="Comma-separated access control tags for this document"
    ),
    weight: float = Form(0.0, description="Corpus search weight boost (0.0 = neutral)"),
    pinned: bool = Form(
        False, description="Pin document to always appear in corpus search results"
    ),
    tags: str = Form("", description="Comma-separated metadata tags for filtering"),
    retain_original: bool = Form(
        False,
        description=(
            "Retain the uploaded file on disk so it can be fetched back via "
            "GET /documents/{doc_id}/pdf. Default false — the raw bytes are "
            "discarded after parsing, which is the safer choice for sensitive "
            "material. Enable for documents you intend to render in a viewer "
            "(e.g. learning material, published standards)."
        ),
    ),
    redact: bool = Form(
        False,
        description=(
            "Enable PII redaction (Stage 1d). Requires pip install 'ingestible[redaction]'. "
            "Scans parsed text for personal data before enrichment and embedding — "
            "LLMs and the vector index never see the original values."
        ),
    ),
    redaction_mode: str = Form(
        "",
        description=(
            "Redaction strategy: 'placeholder' (default) replaces entities with [PERSON] etc.; "
            "'pseudonymize' assigns consistent fictional labels within the document "
            "(Person A, Location 1 …); 'suppress' replaces all entities with [REDACTED]. "
            "Empty string uses the server default (INGEST_REDACTION_MODE)."
        ),
    ),
    redaction_entities: str = Form(
        "",
        description=(
            "Comma-separated Presidio entity types to redact "
            "(e.g. PERSON,EMAIL_ADDRESS,PHONE_NUMBER). "
            "Empty string uses the server default list."
        ),
    ),
    redaction_language: str = Form(
        "",
        description=(
            "ISO 639-1 language code to force for NER redaction (e.g. 'de', 'fr'). "
            "Overrides the language auto-detected from the document. "
            "Useful when langdetect misidentifies short forms or mixed-language PDFs. "
            "Empty string uses the document's detected language."
        ),
    ),
):
    """Ingest a document into the knowledge store.

    Runs the full 6-stage pipeline: parse → structure → chunk → enrich → embed → store.
    Supports 25+ file formats. Returns immediately with document metadata and chunk counts.
    """
    settings = get_cached_settings()

    # Save uploaded file to temp location
    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    skip_enrichment = _check_ingestion_quotas(request, len(content), skip_enrichment)
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

        parsed_redaction_entities = (
            [e.strip() for e in redaction_entities.split(",") if e.strip()]
            if redaction_entities
            else None
        )

        doc_dir = ingest(
            tmp_path,
            settings,
            skip_enrichment=skip_enrichment,
            verbose=False,
            access_tags=parsed_access_tags,
            weight=weight,
            pinned=pinned,
            tags=parsed_tags,
            original_filename=file.filename,
            retain_original=retain_original,
            redact=redact or None,
            redaction_mode=redaction_mode or None,
            redaction_entities=parsed_redaction_entities,
            redaction_language=redaction_language or None,
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

        try:
            from ingestible.models.costs import get_cost_tracker

            _tracker = get_cost_tracker()
            _enrichment_tokens = (
                _tracker.enrichment_llm.input_tokens + _tracker.enrichment_llm.output_tokens
            )
            _estimated_cost = _tracker.estimated_cost_usd
            _duration = _tracker.duration_seconds
            _storage = _tracker.output_storage_bytes
        except Exception:
            _enrichment_tokens = 0
            _estimated_cost = 0.0
            _duration = 0.0
            _storage = 0

        return IngestResponse(
            doc_id=doc_id,
            title=meta.get("title", "Untitled"),
            total_pages=meta.get("total_pages", 0),
            total_chunks=len(chunks.l3_chunks),
            l0_tokens=l0_tokens,
            enriched=not skip_enrichment,
            enrichment_tokens=_enrichment_tokens,
            estimated_cost_usd=_estimated_cost,
            duration_seconds=_duration,
            storage_bytes=_storage,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


class URLIngestRequest(BaseModel):
    """Request body for URL-based ingestion."""

    url: str = Field(description="URL of the document to ingest")
    skip_enrichment: bool = Field(default=False, description="Skip LLM enrichment")
    profile: str = Field(
        default="auto", description="Extraction profile: 'auto', 'fast', 'accurate', or 'economy'"
    )


@app.post("/ingest/url", response_model=IngestResponse, tags=["Ingestion"])
@limiter.limit(_RATE_INGEST)
async def ingest_url(body: URLIngestRequest, request: Request):
    """Ingest a document from a URL.

    Downloads the resource, detects content type, and runs the full 6-stage pipeline.
    """
    skip_enrichment = _check_ingestion_quotas(request, 0, body.skip_enrichment)
    settings = get_cached_settings()

    if body.profile != "auto":
        from ingestible.config import get_settings as _gs

        settings = _gs(extraction_profile=body.profile)

    doc_dir = ingest(
        body.url,
        settings,
        skip_enrichment=skip_enrichment,
        verbose=False,
    )

    meta = load_document_meta(doc_dir)
    chunks = load_chunks(doc_dir)

    from ingestible.utils.tokens import count_tokens

    l0_tokens = count_tokens(_l0_overview_text(chunks.l0))

    try:
        from ingestible.models.costs import get_cost_tracker

        _tracker = get_cost_tracker()
        _enrichment_tokens = (
            _tracker.enrichment_llm.input_tokens + _tracker.enrichment_llm.output_tokens
        )
        _estimated_cost = _tracker.estimated_cost_usd
        _duration = _tracker.duration_seconds
        _storage = _tracker.output_storage_bytes
    except Exception:
        _enrichment_tokens = 0
        _estimated_cost = 0.0
        _duration = 0.0
        _storage = 0

    return IngestResponse(
        doc_id=meta.get("doc_id", doc_dir.name),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        total_chunks=len(chunks.l3_chunks),
        l0_tokens=l0_tokens,
        enriched=not skip_enrichment,
        enrichment_tokens=_enrichment_tokens,
        estimated_cost_usd=_estimated_cost,
        duration_seconds=_duration,
        storage_bytes=_storage,
    )


class BatchIngestResult(BaseModel):
    """Per-file result within a batch ingestion."""

    filename: str = Field(description="Original filename")
    doc_id: str | None = Field(default=None, description="Document ID (null if ingestion failed)")
    error: str | None = Field(default=None, description="Error message (null if successful)")
    elapsed_seconds: float = Field(default=0.0, description="Processing time for this file")


class BatchIngestResponse(BaseModel):
    """Aggregated result of a batch ingestion request."""

    total: int = Field(description="Total number of files submitted")
    succeeded: int = Field(description="Number of files successfully ingested")
    failed: int = Field(description="Number of files that failed")
    elapsed_seconds: float = Field(description="Total elapsed time across all files")
    results: list[BatchIngestResult] = Field(description="Per-file results")


@app.post("/ingest/batch", response_model=BatchIngestResponse, tags=["Ingestion"])
@limiter.limit(_RATE_INGEST)
async def ingest_batch_endpoint(
    request: Request,
    files: list[UploadFile] = File(..., description="One or more document files to ingest"),
    skip_enrichment: bool = Form(False, description="Skip LLM enrichment for all files"),
):
    """Ingest multiple files in a single request.

    Each file is processed independently with error isolation — one failure
    does not abort the batch. Returns per-file results with elapsed time.
    """
    from ingestible.pipeline.batch import BatchReport, _ingest_one

    # Check document-count and enrichment quotas up front (file size checked per-file)
    skip_enrichment = _check_ingestion_quotas(request, 0, skip_enrichment)

    settings = get_cached_settings()
    report = BatchReport(total=len(files))
    results: list[BatchIngestResult] = []

    for upload in files:
        suffix = Path(upload.filename or "upload.pdf").suffix
        content = await upload.read()
        _check_upload_size(content, settings)
        _check_ingestion_quotas(request, len(content), skip_enrichment)
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


@app.get("/documents", response_model=list[DocumentSummary], tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def list_docs(
    request: Request,
    offset: int = Query(default=0, ge=0, description="Pagination offset (0-based)"),
    limit: int = Query(
        default=100, ge=1, le=1000, description="Maximum number of documents to return (1-1000)"
    ),
    tags: str = Query(default="", description="Comma-separated metadata tags to filter by"),
):
    """List all ingested documents with pagination and optional tag filtering."""
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


@app.get("/documents/{doc_id}", response_model=DocumentOverview, tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_document(doc_id: str, request: Request):
    """Get document overview including L0 content, chapter list, and token count."""
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

    original_media_type = meta.get("original_media_type", "")
    has_pdf = bool(
        meta.get("original_stored_name")
        and original_media_type == "application/pdf"
        and (doc_dir / meta["original_stored_name"]).exists()
    )

    return DocumentOverview(
        doc_id=meta.get("doc_id", doc_id),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        ingestion_date=meta.get("ingestion_date", ""),
        l0_content=l0_content,
        l0_tokens=l0_tokens,
        total_chunks=len(chunks.l3_chunks),
        chapters=chapters,
        original_filename=meta.get("original_filename", ""),
        original_media_type=original_media_type,
        has_pdf=has_pdf,
        pdf_url=f"/documents/{doc_id}/pdf" if has_pdf else None,
    )


_PDF_CHUNK_SIZE = 1024 * 1024  # 1 MiB per Range streaming chunk


def _parse_range_header(header: str, file_size: int) -> tuple[int, int] | None:
    """Parse a single-range 'bytes=start-end' header. Returns (start, end_inclusive) or None."""
    if not header or not header.lower().startswith("bytes="):
        return None
    spec = header.split("=", 1)[1].strip()
    # Reject multi-range requests — PDF.js only uses single ranges.
    if "," in spec:
        return None
    start_s, _, end_s = spec.partition("-")
    try:
        if start_s == "":
            # Suffix range: "-N" = last N bytes
            length = int(end_s)
            if length <= 0:
                return None
            start = max(0, file_size - length)
            end = file_size - 1
        else:
            start = int(start_s)
            end = int(end_s) if end_s else file_size - 1
    except ValueError:
        return None
    if start < 0 or end < start or start >= file_size:
        return None
    end = min(end, file_size - 1)
    return start, end


def _check_doc_access(meta: dict, request: Request, settings) -> None:
    """Enforce access-tag intersection between caller and document.

    Mirrors the search endpoint's model: when ``access_control_enabled`` is on
    and the document has ``access_tags``, the caller must present at least one
    matching tag via the ``X-Access-Tags`` header. Documents with no tags are
    open to any authenticated caller.
    """
    if not settings.access_control_enabled:
        return
    doc_tags = set(meta.get("access_tags", []) or [])
    if not doc_tags:
        return
    header = request.headers.get("X-Access-Tags", "")
    user_tags = {t.strip() for t in header.split(",") if t.strip()}
    if not (doc_tags & user_tags):
        raise HTTPException(status_code=403, detail="Access denied for this document")


@app.get("/documents/{doc_id}/pdf", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_document_pdf(doc_id: str, request: Request):
    """Serve the original PDF bytes with HTTP Range support for streaming.

    Returns 200 with the full bytes, or 206 with a byte range when the client
    sends a ``Range: bytes=start-end`` header (required by PDF.js to stream
    large documents progressively). Returns 415 when the ingested original
    was not a PDF, 404 when the document has no retained original (either
    ingested before retention was added or ingested with ``retain_original=false``),
    and 403 when access-tag gating rejects the caller.

    Response sets ``Cache-Control: no-store`` by default: PDFs may carry
    sensitive client data and should not be written to any cache (browser,
    proxy, or CDN).
    """
    from starlette.responses import FileResponse, Response, StreamingResponse

    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    meta = load_document_meta(doc_dir)
    _check_doc_access(meta, request, settings)

    stored_name = meta.get("original_stored_name")
    media_type = meta.get("original_media_type", "")
    display_name = meta.get("original_filename") or stored_name or f"{doc_id}.pdf"

    if not stored_name:
        raise HTTPException(
            status_code=404,
            detail=(
                "Original file not retained for this document. Re-ingest with "
                "retain_original=true to enable PDF serving."
            ),
        )

    if media_type != "application/pdf":
        raise HTTPException(
            status_code=415,
            detail=(
                f"Document is not a PDF (original type: {media_type or 'unknown'}). "
                f"Use /documents/{doc_id}/chunks for content."
            ),
        )

    file_path = doc_dir / stored_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Stored PDF file missing on disk")

    file_size = file_path.stat().st_size
    common_headers = {
        "Accept-Ranges": "bytes",
        "Content-Disposition": f'inline; filename="{display_name}"',
        "Cache-Control": "no-store",
    }

    range_header = request.headers.get("range") or request.headers.get("Range")
    parsed = _parse_range_header(range_header, file_size) if range_header else None

    if range_header and parsed is None:
        return Response(
            status_code=416,
            headers={**common_headers, "Content-Range": f"bytes */{file_size}"},
        )

    # Audit the access (partial or full) before streaming.
    if settings.audit_enabled:
        from ingestible.audit import log_access

        if parsed is not None:
            start, end = parsed
            log_access(
                settings.data_dir / "audit.jsonl",
                doc_id=doc_id,
                resource="pdf",
                user=_get_user(request),
                bytes_served=end - start + 1,
                range_start=start,
                range_end=end,
            )
        else:
            log_access(
                settings.data_dir / "audit.jsonl",
                doc_id=doc_id,
                resource="pdf",
                user=_get_user(request),
                bytes_served=file_size,
            )

    if parsed is not None:
        start, end = parsed
        length = end - start + 1

        def _iter_range():
            with open(file_path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    data = f.read(min(_PDF_CHUNK_SIZE, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data

        headers = {
            **common_headers,
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
        }
        return StreamingResponse(
            _iter_range(),
            status_code=206,
            media_type="application/pdf",
            headers=headers,
        )

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        headers=common_headers,
    )


@app.get("/documents/{doc_id}/redaction-manifest", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_redaction_manifest(doc_id: str, request: Request):
    """Return the redaction manifest for a document.

    The manifest lists every entity that was redacted, its type, replacement
    value, and page number. In pseudonymize mode it also includes the full
    original → pseudonym mapping so privileged callers can de-anonymize.

    Access is gated by ``INGEST_REDACTION_ACCESS_TAG`` when set, otherwise
    falls back to the document's own access_tags. Returns 404 when the
    document was not ingested with redaction enabled.
    """
    from ingestible.pipeline.stage6_storage import load_redaction_manifest

    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    meta = load_document_meta(doc_dir)

    # Honour dedicated redaction access tag if configured, otherwise use doc tags
    if settings.redaction_access_tag:
        header = request.headers.get("X-Access-Tags", "")
        user_tags = {t.strip() for t in header.split(",") if t.strip()}
        if settings.redaction_access_tag not in user_tags:
            raise HTTPException(status_code=403, detail="Access denied: redaction manifest")
    else:
        _check_doc_access(meta, request, settings)

    manifest = load_redaction_manifest(doc_dir)
    if manifest is None:
        raise HTTPException(
            status_code=404,
            detail="No redaction manifest found. Re-ingest with redact=true to enable.",
        )

    return manifest.model_dump()


class UpdateMetaRequest(BaseModel):
    """Mutable metadata fields that can be updated without re-ingestion."""

    weight: float | None = Field(
        default=None,
        description="Corpus search weight boost (0.0 = neutral). Higher values rank this document higher in cross-document search.",
    )
    pinned: bool | None = Field(
        default=None, description="Pin document so it always appears in corpus search results"
    )
    tags: list[str] | None = Field(
        default=None, description="Replace metadata tags (pass empty list to clear)"
    )


@app.patch("/documents/{doc_id}/meta", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def patch_document_meta(doc_id: str, body: UpdateMetaRequest, request: Request):
    """Update mutable document metadata without re-ingesting.

    Only the fields you include in the request body are updated; omitted fields are left unchanged.
    """
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
    deleted: str = Field(description="ID of the deleted document")


@app.delete("/documents/{doc_id}", response_model=DeleteResponse, tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def delete_document(doc_id: str, request: Request):
    """Delete a document and all its indexes, chunks, and embeddings. This is irreversible."""
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


@app.get("/documents/{doc_id}/economics", response_model=TokenEconomics, tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_token_economics(doc_id: str, request: Request):
    """Get token economics for a document.

    Compares the cost of placing the full document in an LLM context window vs.
    using hierarchical retrieval (L0 overview + top-k passages).
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


@app.post("/documents/{doc_id}/search", response_model=SearchResponse, tags=["Search"])
@limiter.limit(_RATE_SEARCH)
async def search_document(doc_id: str, body: SearchRequest, request: Request):
    """Hybrid search within a single document.

    Fuses vector search (ChromaDB, weight 0.4), BM25 (weight 0.6), and concept index
    using Reciprocal Rank Fusion. Optionally enable HyDE query expansion, auto-merge,
    or knowledge graph boosting via request body flags.
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


@app.get("/documents/{doc_id}/chunks", response_model=ChunkSet, tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_chunks(doc_id: str, request: Request):
    """Get the full ChunkSet (L0 through L3) for a document, including all enrichment data."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    return load_chunks(doc_dir)


@app.get("/documents/{doc_id}/citations", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_citations(doc_id: str, request: Request):
    """Get bibliographic citations extracted during parsing."""
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    chunks = load_chunks(doc_dir)
    return {"doc_id": doc_id, "citations": [c.model_dump() for c in chunks.citations]}


@app.get("/documents/{doc_id}/knowledge-graph", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_knowledge_graph(doc_id: str, request: Request):
    """Get knowledge graph triples and entities extracted during enrichment.

    Requires KG extraction to have been enabled during ingestion. Entities are
    sorted by occurrence count (most frequent first).
    """
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


@app.get("/documents/{doc_id}/structure", response_model=DocumentStructure, tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_structure(doc_id: str, request: Request):
    """Get the hierarchical document structure tree (headings, sections, page ranges)."""
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
    """Cross-document search query with optional filters and enhancement flags."""

    query: str = Field(description="Natural language search query")
    n_results: int = Field(
        default=10, ge=1, le=50, description="Number of results to return (1-50)"
    )
    doc_ids: list[str] | None = Field(
        default=None, description="Restrict search to these document IDs (null = all documents)"
    )
    tags: list[str] | None = Field(
        default=None, description="Only search documents with these metadata tags"
    )
    hyde: bool = Field(
        default=False,
        description="Use HyDE query expansion — generates a hypothetical answer passage via LLM for better vector matching",
    )
    auto_merge: bool = Field(
        default=False,
        description="Auto-merge L3 results into parent L2/L1 when 3+ passages from the same section match",
    )
    kg_boost: bool = Field(
        default=False, description="Boost results using knowledge graph entity relationships"
    )


@app.post("/search", tags=["Search"])
@limiter.limit(_RATE_SEARCH)
async def corpus_search(body: CorpusSearchRequest, request: Request):
    """Search across all ingested documents.

    Merges per-document hybrid search results using cross-document Reciprocal Rank
    Fusion. Optionally filter by document IDs or metadata tags.
    """
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


@app.post("/documents/{doc_id}/enrich", response_model=IngestResponse, tags=["Documents"])
@limiter.limit(_RATE_INGEST)
async def enrich_document(doc_id: str, request: Request):
    """Re-enrich a document without re-parsing.

    Re-runs LLM enrichment (stage 4) and embedding (stage 5) on existing chunks.
    Useful after changing LLM provider or enrichment settings.
    """
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

    try:
        from ingestible.models.costs import get_cost_tracker

        _tracker = get_cost_tracker()
        _enrichment_tokens = (
            _tracker.enrichment_llm.input_tokens + _tracker.enrichment_llm.output_tokens
        )
        _estimated_cost = _tracker.estimated_cost_usd
        _duration = _tracker.duration_seconds
        _storage = _tracker.output_storage_bytes
    except Exception:
        _enrichment_tokens = 0
        _estimated_cost = 0.0
        _duration = 0.0
        _storage = 0

    return IngestResponse(
        doc_id=meta.get("doc_id", doc_dir.name),
        title=meta.get("title", "Untitled"),
        total_pages=meta.get("total_pages", 0),
        total_chunks=len(chunks.l3_chunks),
        l0_tokens=l0_tokens,
        enriched=True,
        enrichment_tokens=_enrichment_tokens,
        estimated_cost_usd=_estimated_cost,
        duration_seconds=_duration,
        storage_bytes=_storage,
    )


# ---------------------------------------------------------------------------
# Retrieval Evaluation
# ---------------------------------------------------------------------------


@app.post("/documents/{doc_id}/eval", tags=["Evaluation"])
@limiter.limit(_RATE_DEFAULT)
async def eval_document(
    doc_id: str,
    request: Request,
    k: int = Query(
        default=5, ge=1, le=50, description="Number of results to retrieve per query (1-50)"
    ),
):
    """Evaluate retrieval quality using synthetic queries generated during enrichment.

    Returns hit rate, MRR, precision@k, and recall@k metrics.
    """
    doc_id = _validate_doc_id(doc_id)
    settings = get_cached_settings()
    doc_dir = settings.documents_dir / doc_id

    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")

    from ingestible.eval import evaluate_document

    report = evaluate_document(doc_id, settings, k=k)
    return report.to_dict()


@app.post("/documents/{doc_id}/eval/judge", tags=["Evaluation"])
@limiter.limit(_RATE_DEFAULT)
async def eval_document_judge(
    doc_id: str,
    request: Request,
    k: int = Query(
        default=5, ge=1, le=50, description="Number of results to retrieve per query (1-50)"
    ),
):
    """Evaluate retrieval quality using LLM-as-judge scoring.

    An LLM assesses each query-result pair on faithfulness, relevance, and
    completeness (0-1 scale). More accurate than metric-based eval but slower
    and requires LLM API credits.
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


@app.get("/documents/{doc_id}/export", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def export_document_endpoint(
    doc_id: str,
    request: Request,
    format: str = Query(
        ...,
        description="Export format: 'jsonl', 'parquet', 'llamaindex', 'langchain', or 'complete'",
    ),
):
    """Export a document's chunks to a portable format.

    Returns a file download. Formats: JSONL (one chunk per line), Parquet (columnar),
    LlamaIndex (nodes JSON), LangChain (documents JSON), or complete (full ChunkSet JSON).
    """
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
        "complete": ".json",
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
        "complete": "application/json",
    }

    return FileResponse(
        path=str(output_path),
        filename=f"{doc_id}.{format}{ext}",
        media_type=media_types.get(format, "application/octet-stream"),
    )


# ---------------------------------------------------------------------------
# Versioning (WP 5.1)
# ---------------------------------------------------------------------------


@app.get("/documents/{doc_id}/versions", tags=["Documents"])
@limiter.limit(_RATE_DEFAULT)
async def get_versions(doc_id: str, request: Request):
    """List all archived versions of a document.

    When a document is re-ingested, the previous version is archived.
    Returns version timestamps and metadata.
    """
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


@app.post("/ingest/stream", tags=["Ingestion"])
@limiter.limit(_RATE_INGEST)
async def ingest_stream(
    request: Request,
    file: UploadFile = File(..., description="Document file to ingest"),
    skip_enrichment: bool = Form(False, description="Skip LLM enrichment"),
):
    """Ingest a document with real-time Server-Sent Events progress streaming.

    Returns `text/event-stream` with JSON progress events for each pipeline stage.
    The final event contains `{"status": "complete", "doc_id": "..."}` or
    `{"status": "error", "error": "..."}`.
    """
    from starlette.responses import StreamingResponse

    from ingestible.pipeline.progress import SSEProgress

    settings = get_cached_settings()

    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    skip_enrichment = _check_ingestion_quotas(request, len(content), skip_enrichment)
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
    """Acknowledgement returned when a background job is submitted."""

    job_id: str = Field(description="Unique job identifier for polling status")
    status: str = Field(description="Initial status (always 'pending')")


class JobDetailResponse(BaseModel):
    """Full status of a background ingestion job."""

    job_id: str = Field(description="Unique job identifier")
    status: str = Field(description="Job status: pending, running, complete, or failed")
    doc_id: str | None = Field(
        default=None, description="Document ID (set once ingestion completes)"
    )
    error: str | None = Field(default=None, description="Error message if status is 'failed'")
    created_at: float = Field(description="Unix timestamp when job was submitted")
    started_at: float | None = Field(
        default=None, description="Unix timestamp when processing began"
    )
    finished_at: float | None = Field(
        default=None, description="Unix timestamp when processing ended"
    )
    progress_stage: str = Field(default="", description="Current pipeline stage name")
    progress_step: int = Field(default=0, description="Current step within the stage")
    progress_total: int = Field(default=0, description="Total steps in the current stage")


@app.post("/ingest/async", response_model=JobResponse, status_code=202, tags=["Ingestion"])
@limiter.limit(_RATE_INGEST)
async def ingest_async(
    request: Request,
    file: UploadFile = File(..., description="Document file to ingest"),
    skip_enrichment: bool = Form(False, description="Skip LLM enrichment"),
):
    """Submit a document for background ingestion.

    Returns immediately with a job ID. Poll `GET /jobs/{job_id}` for progress.
    """
    settings = get_cached_settings()

    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    skip_enrichment = _check_ingestion_quotas(request, len(content), skip_enrichment)

    # Write to a persistent temp file (not auto-deleted)
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(content)
    tmp.close()
    tmp_path = Path(tmp.name)

    try:
        queue = get_task_queue(
            max_workers=settings.max_concurrent_ingestions,
            max_jobs_per_user=settings.max_jobs_per_user,
        )
        job = queue.submit_ingestion(
            tmp.name,
            settings,
            skip_enrichment=skip_enrichment,
            user=_get_user(request),
        )
    except UserConcurrencyExceeded as exc:
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    return JobResponse(job_id=job.job_id, status=job.status.value)


@app.get("/jobs/{job_id}", response_model=JobDetailResponse, tags=["Jobs"])
@limiter.limit(_RATE_DEFAULT)
async def get_job_status(job_id: str, request: Request):
    """Get the status and progress of a background ingestion job."""
    queue = get_task_queue()
    job = queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    d = job.to_dict()
    return JobDetailResponse(**d)


@app.get("/jobs", response_model=list[JobDetailResponse], tags=["Jobs"])
@limiter.limit(_RATE_DEFAULT)
async def list_jobs(request: Request):
    """List all background ingestion jobs (pending, running, complete, and failed)."""
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


@app.post("/webhooks/cv", tags=["Webhooks"])
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
# ANCS export — Madison's structured memory store
# ---------------------------------------------------------------------------


class ANCSExportResponse(BaseModel):
    """Result of ingesting a document and pushing it into ANCS."""

    doc_id: str
    trust_class: str = Field(description="Provenance-derived trust tier the doc was routed to")
    can_promote: bool = Field(
        description="Whether this class is ever eligible for human-confirm promotion"
    )
    memory_items_created: int = 0
    entities_created: int = 0
    hyperedges_created: int = 0
    kg_triples_ingested: int = 0


@app.post("/ancs/ingest", response_model=ANCSExportResponse, tags=["ANCS"])
@limiter.limit(_RATE_INGEST)
async def ancs_ingest(
    request: Request,
    file: UploadFile = File(..., description="Document file to ingest into Madison's memory"),
    source_channel: str = Form(
        "unknown",
        description=(
            "OUT-OF-BAND provenance: how Madison obtained this file "
            "('user_authored', 'download', 'mail_attachment', 'unknown'). This — and "
            "ONLY this — decides the trust tier / ANCS tenant. Document content is "
            "never trusted to classify itself. Unknown/forged → most isolated tenant."
        ),
    ),
    source_uri: str = Form(
        "", description="Optional provenance URI; defaults to ingestible://{class}/{doc_id}"
    ),
):
    """Ingest a document and push its structured form into ANCS.

    Runs the full pipeline WITH knowledge-graph extraction (LLM path), then exports
    the L0–L3 hierarchy plus the typed KG triples to ANCS, which materializes them
    as semantic hyperedges (multi-hop-traversable). The document is routed to a
    trust-isolated ANCS tenant chosen purely from `source_channel` provenance.
    """
    from ingestible.adapters.ancs_export import export_to_ancs
    from ingestible.adapters.ancs_trust import classify_trust, resolve_ancs_config

    base_settings = get_cached_settings()
    if not getattr(base_settings, "ancs_url", ""):
        raise HTTPException(status_code=503, detail="ANCS export not configured (INGEST_ANCS_URL)")

    # 1) Classify trust from PROVENANCE only (never from the bytes). Default-deny.
    policy = classify_trust(source_channel)

    # 2) Refuse early if the chosen class's tenant isn't provisioned — don't fall
    #    back to a more-trusted tenant.
    try:
        # (re-resolved after ingest with the real source_uri; this is the guard)
        resolve_ancs_config(policy, base_settings)
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))

    # 3) Ingest with KG extraction enabled (LLM path — kg_spacy stays off; the
    #    spaCy path is measured lossy and we want quality for Madison).
    settings = get_settings(extract_knowledge_graph=True)
    suffix = Path(file.filename or "upload.pdf").suffix
    content = await file.read()
    _check_upload_size(content, settings)
    _check_ingestion_quotas(request, len(content), False)
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # ingest() runs enrichment via asyncio.run() internally; run it in a
        # threadpool so it gets a thread WITHOUT this route's running event loop
        # (otherwise enrichment — and the KG extraction we need — is skipped).
        from starlette.concurrency import run_in_threadpool

        doc_dir = await run_in_threadpool(
            lambda: ingest(
                tmp_path,
                settings,
                skip_enrichment=False,
                verbose=False,
                original_filename=file.filename,
            )
        )
        meta = load_document_meta(doc_dir)
        doc_id = meta.get("doc_id", doc_dir.name)
        chunks = load_chunks(doc_dir)

        # 4) Export to the trust-class tenant. Provenance URI embeds the class.
        uri = source_uri or f"ingestible://{policy.trust_class.value}/{doc_id}"
        cfg = resolve_ancs_config(policy, base_settings, source_uri=uri)
        result = export_to_ancs(chunks, cfg)
        if result.error:
            raise HTTPException(status_code=502, detail=f"ANCS export failed: {result.error}")

        return ANCSExportResponse(
            doc_id=doc_id,
            trust_class=policy.trust_class.value,
            can_promote=policy.can_promote,
            memory_items_created=result.memory_items_created,
            entities_created=result.entities_created,
            hyperedges_created=result.hyperedges_created,
            kg_triples_ingested=result.kg_triples_ingested,
        )
    finally:
        Path(tmp_path).unlink(missing_ok=True)


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
