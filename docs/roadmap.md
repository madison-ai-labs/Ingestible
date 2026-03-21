# Ingestible Roadmap — Complete

> **Status: v1.0.0 released** — all planned phases delivered.

---

## Phase 1: Foundation & Batch Operations (v0.10)

| WP | Feature | Status |
|----|---------|--------|
| 1.1 | Pipeline Checkpoint/Resume | **done** |
| 1.2 | Batch/Directory Ingestion | **done** |
| 1.3 | Document Metadata Extraction | **done** |
| 1.4 | URL Ingestion | **done** |

- **1.1** — Serialize intermediate Pydantic models to `.checkpoint/{stage}.json` after each stage. Resume from latest checkpoint on re-entry. Clear on success.
- **1.2** — `discover_files()`, `ingest_batch()`, `BatchReport`/`FileResult`. CLI dispatches via `_is_batch_input()`. API: `POST /ingest/batch`.
- **1.3** — Extract author, creation date, language, keywords from PDF/DOCX metadata. Populates `L0Chunk.author`, `ParsedDocument.detected_language`.
- **1.4** — URL detection, download to temp file, content-type sniffing, optional readability extraction for HTML.

---

## Phase 2: Cross-Document Search & Export (v0.11)

| WP | Feature | Status |
|----|---------|--------|
| 2.1 | Cross-Document Search | **done** |
| 2.2 | Re-enrichment Without Re-parsing | **done** |
| 2.3 | Export to Portable Formats | **done** |

- **2.1** — `CorpusSearcher` with per-document `HybridSearcher` LRU cache, parallel queries, cross-document RRF fusion.
- **2.2** — Load existing chunks, re-run Stage 3c → 4 → 5 → 6. Skips parse/structure/chunk.
- **2.3** — Export to JSONL, Parquet, LlamaIndex nodes, LangChain documents.

---

## Phase 3: Format Expansion (v0.12)

| WP | Feature | Status |
|----|---------|--------|
| 3.1 | EPUB | **done** |
| 3.2 | CSV/Excel | **done** |
| 3.3 | PowerPoint | **done** |
| 3.4 | RST & AsciiDoc | **done** |
| 3.5 | Image/Figure Extraction from PDFs | **done** |

---

## Phase 4: Embedding & Search Enhancements (v0.13)

| WP | Feature | Status |
|----|---------|--------|
| 4.1 | Configurable Embedding Dimensions / Quantization | **done** |
| 4.2 | Language Detection + Multilingual BM25 | **done** |

---

## Phase 5: Production Hardening (v0.14)

| WP | Feature | Status |
|----|---------|--------|
| 5.1 | Document Versioning | **done** |
| 5.2 | Streaming Progress Callbacks | **done** |
| 5.3 | Chunk-Level Cache Invalidation | **done** |

---

## Phase 6: Integrations & Knowledge Graph (v0.15)

| WP | Feature | Status |
|----|---------|--------|
| 6.1 | Selective Re-enrichment | **done** |
| 6.2 | File Watcher (`ingest watch`) | **done** |
| 6.3 | CV Webhook (`POST /webhooks/cv`) | **done** |
| 6.4 | Knowledge Graph Extraction | **done** |
| 6.5 | Audio & Video Ingestion | **done** |

- **6.1** — Hash-based skip for Stage 4 enrichment. Unchanged L3 chunks copy enrichment from previous version. `re_enrich()` accepts `changed_chunk_ids`.
- **6.2** — `ingest watch <dir>` with watchdog, 2s debounce, optional `--cv-push`.
- **6.3** — HMAC-SHA256 verified webhook. Updates chunk content, stores `cv_checksum`, triggers selective re-enrichment.
- **6.4** — `(subject, predicate, object)` triples from L3 chunks. Auto-enabled for `paper`/`documentation` profiles. Deduplication by highest confidence. API: `GET /documents/{doc_id}/knowledge-graph`.
- **6.5** — Audio (MP3, WAV, FLAC, OGG, M4A, AAC, OPUS) via faster-whisper. Video (MP4, MKV, AVI, MOV, WebM, WMV, FLV) via ffmpeg + whisper. 2-minute pages with `[MM:SS]` timestamps. Keyframe extraction at 60s intervals.

---

## Phase 7: Security & Input Validation (v0.16)

| WP | Feature | Status |
|----|---------|--------|
| 7.1 | Path Traversal Protection | **done** |
| 7.2 | File Upload Size Limits | **done** |
| 7.3 | CORS Lockdown | **done** |
| 7.4 | Rate Limiting | **done** |
| 7.5 | Pydantic Model Constraints | **done** |

- **7.1** — `_validate_doc_id()` rejects `/`, `\`, `..`, null bytes. Regex-enforced `[a-z0-9][a-z0-9_-]*`. Applied to all `{doc_id}` endpoints and the webhook `sourcePath` parser.
- **7.2** — `max_upload_bytes` setting (default 500 MB). HTTP 413 on oversize uploads. Streaming size check in `fetch_url()`.
- **7.3** — `cors_origins` configurable via `INGEST_CORS_ORIGINS` (default `["*"]`).
- **7.4** — slowapi rate limiting. Tiers: ingest (10/min), search (60/min), default (120/min). All configurable.
- **7.5** — `Field(ge=0)` on page numbers, timestamps, counts. `Field(max_length=...)` on list fields. `Field(ge=0, le=1)` on KG confidence.

---

## Phase 8: Async Pipeline & Concurrency (v0.16)

| WP | Feature | Status |
|----|---------|--------|
| 8.1 | Background Task Queue | **done** |
| 8.2 | Document-Level File Locking | **done** |
| 8.3 | LLM Retry with Backoff | **done** |
| 8.4 | LLM Call Timeouts | **done** |
| 8.5 | Parse Timeout | **done** |

- **8.1** — `TaskQueue` backed by `ThreadPoolExecutor`. `POST /ingest/async` returns job ID (202). `GET /jobs/{id}` for polling. `GET /jobs` to list all. Configurable `max_concurrent_ingestions`.
- **8.2** — `document_lock()` context manager using portalocker. Protects version archival + save in orchestrator, save in re-enrich, chunk mutation in webhook.
- **8.3** — `retry_llm_call()` with exponential backoff on 429/500/502/503/529 and connection errors. Applied to all `generate_json` calls in Stage 4 and Stage 3c.
- **8.4** — `llm_timeout` setting (default 120s). Passed to both OpenAI and Anthropic async clients.
- **8.5** — `parse_timeout` setting (default 300s). Wraps PDF, audio, and video parsing in `concurrent.futures` with timeout.

---

## Phase 9: Observability (v0.16)

| WP | Feature | Status |
|----|---------|--------|
| 9.1 | Structured JSON Logging | **done** |
| 9.2 | Request ID Tracing | **done** |
| 9.3 | Prometheus Metrics | **done** |
| 9.4 | Deep Health Check | **done** |

- **9.1** — structlog with JSON renderer (API) or console renderer (CLI). Replaces `logging.basicConfig` in orchestrator. Quiets noisy third-party loggers.
- **9.2** — `RequestIDMiddleware` generates/reads `X-Request-ID`, binds to structlog contextvars, echoes in response.
- **9.3** — prometheus-fastapi-instrumentator on all routes. Custom metrics: `ingestible_ingest_duration_seconds`, `ingestible_llm_calls_total`, `ingestible_active_ingestions`, `ingestible_search_duration_seconds`. Endpoint: `GET /metrics`.
- **9.4** — `GET /health/ready` checks: data dir writable, disk space > threshold, embedding model loadable, LLM API configured, document count. Returns `ready` or `degraded`.

---

## Phase 10: Deployment & Portability (v0.16)

| WP | Feature | Status |
|----|---------|--------|
| 10.1 | Dockerfile + Compose | **done** |
| 10.2 | Multi-Worker Server Config | **done** |
| 10.3 | Configurable Embedding Device | **done** |
| 10.4 | Version Bump | **done** |
| 10.5 | Dependency Pinning | **done** |

- **10.1** — Multi-stage Dockerfile (builder + slim runtime). Non-root user. ffmpeg included. docker-compose with named volume, healthcheck, env_file.
- **10.2** — `gunicorn.conf.py` with UvicornWorker, `cpu_count*2+1` workers (capped at 8), 10-min timeout, preload, max_requests leak protection.
- **10.3** — `embedding_device` setting: `auto` detects CUDA > MPS > CPU. Accepts explicit `cuda`, `mps`, `cpu`.
- **10.4** — Version bumped to 0.16.0 in pyproject.toml and FastAPI app.
- **10.5** — `requirements.lock` with direct dependencies. Header documents `pip-compile` / `uv pip compile` workflow.

---

## Phase 11: Resilience & Cleanup (v0.16)

| WP | Feature | Status |
|----|---------|--------|
| 11.1 | Graceful Shutdown | **done** |
| 11.2 | Stale Checkpoint/Temp Cleanup | **done** |
| 11.3 | Bounded Searcher Cache | **done** |
| 11.4 | Batch Concurrency Guard | **done** |

- **11.1** — `@app.on_event("shutdown")` drains active ingestion jobs via `TaskQueue.shutdown(wait=True)`.
- **11.2** — `cleanup_stale()` removes checkpoint dirs, lock files, and temp uploads older than 24h. Runs on API startup. CLI: `ingest cleanup --max-age 24`.
- **11.3** — `CorpusSearcher` cache replaced with OrderedDict LRU (default maxsize=50). Configurable via `searcher_cache_size`.
- **11.4** — Parallel batch caps per-worker LLM concurrency: `max(1, max_total_llm_concurrency // parallel)`. Default ceiling: 20.

---

## Phase 12: Format Expansion & MCP Server (v0.17)

| WP | Feature | Status |
|----|---------|--------|
| 12.1 | Image Parsing (PNG/JPEG/TIFF) | **done** |
| 12.2 | Email Parsing (EML/MSG) | **done** |
| 12.3 | XML/JSON/JSONL Parsing | **done** |
| 12.4 | MCP Server | **done** |

- **12.1** — Images routed through Docling's VLM pipeline for OCR + layout analysis. Supports PNG, JPEG, TIFF, BMP, WebP.
- **12.2** — EML via stdlib `email` module (headers, body, attachments). MSG via optional `extract-msg` library.
- **12.3** — XML converted to heading/key-value markdown. JSON/JSONL rendered as structured markdown with nested objects and arrays.
- **12.4** — MCP server exposing 7 tools: `ingest_document`, `search`, `list_documents`, `get_document_overview`, `get_chunk`, `get_knowledge_graph`, `delete_document`. Run via `ingest mcp` or `python -m ingestible.mcp_server`. Requires `pip install ingestible[mcp]`.

---

## Phase 13: Docling Chunker & Archive Parsing (v0.17)

| WP | Feature | Status |
|----|---------|--------|
| 13.1 | Docling Chunking Strategy | **done** |
| 13.2 | Notion Export Parsing | **done** |
| 13.3 | Confluence Export Parsing | **done** |
| 13.4 | Generic ZIP Parsing | **done** |

- **13.1** — `INGEST_CHUNKING_STRATEGY=docling`: strict heading-based chunk boundaries, atomic code/table blocks, no overlap (hierarchy provides context). Fourth chunking strategy alongside paragraph, semantic, and recursive.
- **13.2** — Notion Markdown ZIP exports: UUID cleanup from filenames, inter-page link normalization, auto-heading insertion.
- **13.3** — Confluence HTML ZIP exports: auto-detected via `index.html`, HTML-to-markdown conversion, asset directory filtering.
- **13.4** — Generic ZIP fallback: extracts and concatenates supported text files (md, txt, html, rst, csv, json, xml).

---

## Phase 14: Retrieval Evaluation (v0.17)

| WP | Feature | Status |
|----|---------|--------|
| 14.1 | Eval Framework | **done** |
| 14.2 | Synthetic Query Generation | **done** |
| 14.3 | Strategy Comparison | **done** |

- **14.1** — `ingest eval <doc_id>` measures Hit Rate@K, MRR, Precision@K, Recall@K. Supports manual Q&A pairs from JSONL files. API: `POST /documents/{doc_id}/eval`.
- **14.2** — Auto-generates eval queries from enrichment hypothetical questions. Each question should retrieve the chunk it came from (self-consistency check).
- **14.3** — `ingest eval <doc_id> --compare` runs hybrid vs vector-only vs BM25-only side by side.

---

## Phase 15: Cloud Storage Connectors (v0.17)

| WP | Feature | Status |
|----|---------|--------|
| 15.1 | S3 Connector | **done** |
| 15.2 | GCS Connector | **done** |
| 15.3 | Azure Blob Connector | **done** |

- **15.1** — `ingest ingest s3://bucket/key` downloads from AWS S3 via boto3. Size check before download.
- **15.2** — `ingest ingest gs://bucket/key` downloads from Google Cloud Storage via google-cloud-storage.
- **15.3** — `ingest ingest az://container/blob` downloads from Azure Blob Storage via azure-storage-blob. Requires `AZURE_STORAGE_CONNECTION_STRING`.
- All require `pip install ingestible[cloud]`.

---

## Phase 16: Embedding Providers, Access Control, Audit & SPLADE (v1.0.0)

| WP | Feature | Status |
|----|---------|--------|
| 16.1 | API Embedding Providers | **done** |
| 16.2 | Document-Level Access Control | **done** |
| 16.3 | Retrieval Audit Trail | **done** |
| 16.4 | SPLADE Sparse Retrieval | **done** |

- **16.1** — Embedding provider abstraction: `INGEST_EMBEDDING_PROVIDER=local|openai|cohere|voyage`. API providers (OpenAI, Cohere, Voyage) alongside local sentence-transformers. Lazy model import so API-only users don't need sentence-transformers. Provider-specific API keys via config.
- **16.2** — Per-document access tags stored in meta.json and ChromaDB metadata. Search filters by `X-Access-Tags` header. Empty tags = public. CLI: `--access-tags tag1,tag2`. Opt-in via `INGEST_ACCESS_CONTROL_ENABLED`.
- **16.3** — Every search logged to `data/audit.jsonl` with query, user (from bearer token), retrieved chunk IDs, scores, and latency. CLI: `ingest audit`. Opt-in via `INGEST_AUDIT_ENABLED`.
- **16.4** — SPLADE learned sparse retrieval as alternative to BM25. Term expansion activates vocabulary terms not in the original text. JSON serialization (not pickle). Same RRF fusion, backward compatible. Config: `INGEST_SPARSE_RETRIEVAL=bm25|splade`.

---

## Dependency Graph

```
Phase 1 (parallel, no deps):
  WP 1.1 Checkpoint ──┐
  WP 1.2 Batch ────────┤
  WP 1.3 Metadata ─────┤
  WP 1.4 URL ──────────┘
           │
Phase 2 (after Phase 1):
  WP 2.1 Cross-doc search ── needs 1.2
  WP 2.2 Re-enrichment ───── benefits from 1.1
  WP 2.3 Export ───────────── standalone
           │
Phase 3 (can overlap with Phase 2):
  WP 3.1-3.5 ─── all independent
           │
Phase 4 (after Phase 2):
  WP 4.1 Embedding config ── standalone
  WP 4.2 Multilingual BM25 ─ benefits from 1.3
           │
Phase 5 (after Phases 1-2):
  WP 5.1 Versioning ──────── needs 1.1
  WP 5.2 Progress ─────────── needs 1.2
  WP 5.3 Chunk cache ──────── needs 5.1
           │
Phase 6 (after Phase 5):
  WP 6.1 Selective re-enrich ── needs 5.3
  WP 6.2 File watcher ────────── needs 1.2
  WP 6.3 CV webhook ──────────── needs 6.1
  WP 6.4 Knowledge graph ─────── standalone
  WP 6.5 Audio/video ─────────── standalone
           │
Phase 7 (no deps, security):
  WP 7.1-7.5 ─── all independent
           │
Phase 8 (after 7):
  WP 8.1-8.5 ─── all independent
           │
Phase 9 (after 8.1):
  WP 9.1 Structured logging ── standalone
  WP 9.2 Request tracing ───── needs 9.1 + 8.1
  WP 9.3 Prometheus metrics ── needs 8.1
  WP 9.4 Deep health ─────────── standalone
           │
Phase 10 (after 9):
  WP 10.1 Dockerfile ────────── needs 10.2
  WP 10.2 Multi-worker ──────── standalone
  WP 10.3 Embedding device ──── standalone
  WP 10.4 Version bump ──────── after each phase
  WP 10.5 Dep pinning ────────── standalone
           │
Phase 11 (after 8.1 + 9.1):
  WP 11.1 Graceful shutdown ── needs 8.1
  WP 11.2 Temp cleanup ─────── standalone
  WP 11.3 Searcher cache ───── standalone
  WP 11.4 Batch concurrency ── standalone
           │
Phase 12 (after 11):
  WP 12.1-12.3 Formats ────── standalone
  WP 12.4 MCP server ─────── standalone
           │
Phase 13 (after 12):
  WP 13.1 Docling chunker ── standalone
  WP 13.2-13.4 Archives ──── standalone
           │
Phase 14 (after core pipeline):
  WP 14.1-14.3 Eval ────────── needs enrichment (Stage 4)
           │
Phase 15 (standalone):
  WP 15.1-15.3 Cloud ───────── standalone
           │
Phase 16 (v1.0.0):
  WP 16.1 Embedding providers ── standalone
  WP 16.2 Access control ─────── standalone
  WP 16.3 Audit trail ────────── standalone
  WP 16.4 SPLADE ──────────────── standalone
```
