# Changelog

## v1.2.2 (2026-04-18)

### Security
- **Strict injection gate** — `INGEST_INJECTION_STRICT_MODE=true` blocks L3 chunks from enrichment when high-confidence injection patterns (`role_marker`, `jailbreak`) are detected. Raises `InjectionDetected`; chunk summary is set to `"[enrichment blocked: injection detected]"`. Off by default to avoid false positives on legitimate security content.
- Documents existing cost-routing architecture as a security control: L3/KG/L1 enrichment runs on the bulk model, limiting blast radius for the stages most exposed to raw untrusted content.

## v1.2.1 (2026-04-18)

### Added
- **networkx KG graph analysis** — knowledge graph retrieval uses networkx for multi-hop entity relationship traversal, improving KG-boosted search result coverage.

### Security
- **XML delimiter isolation** — all enrichment prompts (L3, L2, L1, L0, KG extraction) and the eval judge now wrap document content in `<document>…</document>` tags with an explicit instruction to treat contents as data, not instructions.
- **Pre-enrichment injection scanner** (`utils/injection.py`) — scans raw L3 chunk content for injection pattern families (role override, role assumption, role markers, jailbreak keywords) before each LLM call. Logs warnings with chunk ID and matched families.
- **Post-enrichment output validator** — checks enrichment output fields for anomalous values (imperative `summary`, sentence-length concept/keyword entries) that may indicate a successful injection corrupted structured output.
- **Hardened HyDE and decompose system prompts** — explicitly frames the user turn as a search query and instructs the model not to follow embedded instructions.
- Added `docs/security.md` documenting threat model, defences, and remaining gaps.

## v1.2.0 (2026-04-15)

### Added
- **Original-file retention + PDF serving** — `POST /ingest` accepts `retain_original` (default `false`). When enabled, the uploaded file is kept under `{doc_dir}/original{ext}` and served back via `GET /documents/{doc_id}/pdf` with HTTP Range support for streaming PDF.js viewers. Responses set `Cache-Control: no-store`.
- **Access-tag gating on `/pdf`** — parity with search: when `access_control_enabled` is on, `/pdf` requires an intersecting `X-Access-Tags` header against the document's `access_tags`. 403 on mismatch.
- **`log_access` audit event** — every `/pdf` fetch (full or Range) is written to `audit.jsonl` with user, doc_id, bytes served, and byte range.
- **`DocumentOverview` exposes retention state** — new fields `has_pdf`, `original_filename`, `original_media_type`, and `pdf_url` on `GET /documents/{doc_id}`.
- **`docs/privacy.md`** — threat model, retention modes, caching rationale, and audit guarantees.
- **Cost routing for bulk enrichment** — `INGEST_COST_ROUTING_ENABLED=true` (default) routes L3 enrichment, KG extraction, context prefixes, and HyDE to `INGEST_COST_ROUTING_MODEL` (default `gpt-4o-mini`). L0 document digest still uses the primary model for quality. Requires an OpenAI key; falls back to the primary model otherwise.
- **Cloud-first Docker image** — default `EXTRAS=pgvector,gemini` (~200MB RAM, API-based embeddings). The PyTorch + local-embedding build is still available as the `-full` image variant. CI release workflow updated accordingly.
- **Admin cost + storage metrics** — `/api/admin/metrics` reports estimated monthly cost and total uploaded bytes; `/api/admin/users` adds `cost_usd` per user.
- **Pricing page** on the website (`/pricing`) — Free, Pay-as-you-go, and Pro tiers.
- **Supabase migration** `20260328_update_usage_rpc.sql` — usage-stats RPC update.
- **Design doc** `docs/design-content-awareness-and-truth.md` — scoped proposal for content-tier classification (VBC), surprise scoring, version-aware search, and entity resolution. All opt-in, off by default.

### Changed
- **Default embedding provider switched from `local` to `openai`** (`text-embedding-3-small`). Local sentence-transformers still available via the `[local]` extra — recommended for self-hosted deployments with ≥3 GB RAM. Reduces default container footprint from ~3 GB to ~200 MB.
- **Default Gemini model: `gemini-2.0-flash` → `gemini-2.5-flash`**. Gemini 2.0 Flash shuts down 2026-06-01.
- **Contextual chunking (Stage 3c) rewritten as heuristic** — the context prefix is now built from document/chapter/section titles instead of per-chunk LLM calls. Near-identical retrieval quality, zero LLM cost for this stage. Removes the `llm_concurrency` / retry path from Stage 3c.
- **`searcher_cache_size` default: 50 → 10** — better fit for cloud memory budgets (each cached document searcher is ~50–145 MB).
- **LLM pricing tables** in `docs/costpoints.md` updated for March 2026 rates (Claude Haiku 4.5 $1.00/$5.00, Gemini 2.5 Flash $0.30/$2.50) and a new per-document cost-estimate table across providers.
- **`docker-compose.prod.yml`** retuned for the cloud stack — OpenAI embeddings, `INGEST_SEARCHER_CACHE_SIZE=10`, resource limits.

## v1.1.1 (2026-03-25)

### Changed
- CI now publishes two Docker images: `latest` (full, ~3GB) and `latest-slim` (thin API, ~500MB)

## v1.1.0 (2026-03-25)

### Added
- **Gemini LLM + embedding provider** — `INGEST_LLM_PROVIDER=gemini` and `INGEST_EMBEDDING_PROVIDER=gemini` with batch support
- **Ollama LLM provider** — `INGEST_LLM_PROVIDER=ollama` for fully local LLM enrichment, no API keys needed
- **pgvector vector backend** — `INGEST_VECTOR_BACKEND=pgvector` as production alternative to ChromaDB
- **Gemini and pgvector optional dependency groups** — `pip install ingestible[gemini,pgvector]`
- **Code-aware chunking** — preserves code blocks, fenced regions, and inline code during chunk splitting
- **Document weight, pinned, and tags** — per-document metadata for search filtering and prioritization
- **Competitive search enhancements** — improved ranking, filtering, and complete export support
- **Standalone production Docker Compose** (`docker-compose.prod.yml`)
- **Configurable Docker extras** — thin API server (~500MB) vs full ingestion worker (~3GB)
- **Configurable gunicorn workers** via `WEB_CONCURRENCY` env var
- **Configurable preload** via `GUNICORN_PRELOAD` env var for memory-constrained environments

### Changed
- Production deployment moved from Railway to **Fly.io**
- Default Docker image extras changed to `pgvector,gemini` (thin API server)

## v1.0.0 (2026-03-21)

First stable release.

### Core Pipeline
- 25+ input formats (PDF, DOCX, HTML, EPUB, PPTX, XLSX, CSV, Markdown, RST, AsciiDoc, TXT, images, email, XML, JSON, ZIP/Notion/Confluence, audio, video)
- 4-level hierarchical chunking (L0 document → L1 chapter → L2 section → L3 passage)
- 4 chunking strategies: paragraph, semantic, recursive, docling
- Content-tier classification (T0 verbatim → T3 compressible) for smarter chunking and enrichment
- LLM enrichment with summaries, concepts, hypothetical questions, knowledge graph triples, citations
- Extraction profiles: auto-detected paper, article, documentation, general
- Triple hybrid search: vector (ChromaDB) + BM25/SPLADE + concept index with RRF fusion
- Version-aware search: superseded chunks weighted 0.3x
- Cross-document corpus search
- Selective re-enrichment with content-hash caching

### Production
- Rate limiting, CORS config, upload size limits, path traversal protection
- Structured JSON logging (structlog) with request ID tracing
- Prometheus metrics at `/metrics`
- Background ingestion task queue (`POST /ingest/async`)
- Document-level file locking (portalocker)
- LLM retry with exponential backoff + per-call timeouts
- Parse timeouts for PDF/audio/video
- Graceful shutdown with task queue drain
- Stale checkpoint/temp file cleanup
- Docker deployment with gunicorn multi-worker
- Deep readiness probe at `/health/ready`

### Integrations
- MCP server for AI agent integration (7 tools)
- Cloud storage connectors: S3, GCS, Azure Blob
- Embedding providers: local (sentence-transformers), OpenAI, Cohere, Voyage
- Document-level access control with `X-Access-Tags` header
- Retrieval audit trail (JSONL logging)
- SPLADE learned sparse retrieval as BM25 alternative
- Export: JSONL, Parquet, LlamaIndex, LangChain
- File watcher with auto-ingestion
- Retrieval evaluation framework (Hit Rate, MRR, Precision@K, Recall@K)
- CognitiveVault webhook integration

### Interfaces
- CLI with 14 commands
- REST API (FastAPI) with auth, rate limiting, SSE streaming
- Web UI with document browser, chunk viewer, search, file upload
