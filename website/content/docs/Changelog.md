# Changelog

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
