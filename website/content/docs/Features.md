# Features

## Core

- **25+ input formats** — PDF, DOCX, HTML, EPUB, PPTX, XLSX, CSV, Markdown, RST, AsciiDoc, plain text, audio, video, images, email, XML, JSON/JSONL, ZIP (Notion, Confluence, generic)
- **4-level chunk hierarchy** — L0 overview, L1 chapters, L2 sections, L3 passages. No mid-paragraph splits
- **Chunking strategies** — paragraph, semantic, recursive, docling
- **LLM enrichment** — summaries, concepts, hypothetical questions, entities, cross-references (one-time cost, skippable)
- **Hybrid search** — vector + BM25 + concept index, fused with RRF. Optional cross-encoder reranking, SPLADE sparse retrieval
- **Cross-document corpus search** — query across all ingested documents at once
- **Extraction profiles** — auto-detected (paper, article, documentation, general) with tailored enrichment
- **Knowledge graph extraction** — entity-relationship triples from enrichment

## Production

- **Rate limiting** per endpoint tier, configurable
- **Structured JSON logging** and Prometheus metrics (`/metrics`)
- **Docker-ready** — gunicorn with multiple workers, persistent volumes, health checks (`/health/ready`)
- **API auth** — key-based authentication
- **Background ingestion** with checkpoint/resume and file locking
- **Smart re-ingestion** — content-hash dedup, selective re-enrichment (unchanged chunks skip LLM), version archival

## Integrations

- **MCP server** — AI agents (Claude, GPT) can ingest and search directly via Model Context Protocol
- **Cloud storage** — ingest from S3, GCS, Azure Blob (`s3://`, `gs://`, `az://`)
- **Parse mode** — `ingest parse` outputs structured chunks as JSONL without storing. Feed directly to external systems
- **Export** — JSONL, Parquet, LlamaIndex, LangChain formats
- **File watcher** — `ingest watch` monitors a directory and auto-ingests on changes
- **Retrieval evaluation** — Hit Rate, MRR, Precision@K with synthetic or manual queries
- **Document access control** — per-document access tags, filtered at retrieval time

## The 4-Level Chunk Hierarchy

| Level | What | Size | Purpose |
|-------|------|------|---------|
| L0 | Document overview + TOC + executive summary | ~500-800 tokens | Map of the entire document |
| L1 | Chapters | ~300-500 tokens | Browsing units |
| L2 | Sections | ~200-400 tokens | Section summaries |
| L3 | Passages | ~250-500 tokens | Primary search targets |

## Three Search Indexes

All three run in parallel and results are fused with Reciprocal Rank Fusion (RRF):

- **Vector** (ChromaDB + E5-large-v2) — semantic meaning
- **BM25** (rank-bm25) — keyword matching
- **Concept index** — direct concept-to-chunk lookup

Passages found by multiple indexes rank higher. No score normalization needed.

## Pluggable Vector Backends

Abstract `VectorBackend` interface with three implementations:

- **ChromaDB** (default) — embedded, zero-config
- **pgvector** — PostgreSQL with vector extension
- **Qdrant** — dedicated vector database

Configure via `INGEST_VECTOR_BACKEND=pgvector` environment variable.

## Embedding Providers

- **Local** (default) — E5-large-v2 via sentence-transformers, runs on CPU/MPS/CUDA
- **OpenAI** — text-embedding-3-small/large
- **Cohere** — embed-english-v3.0
- **Voyage** — voyage-large-2
- **Gemini** — text-embedding-004

Configure via `INGEST_EMBEDDING_PROVIDER` and related environment variables.

## LLM Providers

- **Anthropic** — Claude models for enrichment
- **OpenAI** — GPT models for enrichment
- **Gemini** — Google Gemini models
- **Ollama** — Local LLM inference

Configure via `INGEST_LLM_PROVIDER` environment variable.
