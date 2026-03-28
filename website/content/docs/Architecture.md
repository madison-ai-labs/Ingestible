# Architecture Overview

## Pipeline Stages

```
Document → Stage 1 (Parse) → Stage 1b (Clean) → Stage 2 (Structure) → Stage 3 (Chunk)
         → Stage 3b (Validate) → Stage 3c (Contextual) → Stage 4 (Enrich)
         → Stage 5 (Embed & Index) → Stage 6 (Store)
```

### Stage 1 — Document Parsing

**File:** `pipeline/stage1_parsing.py`

Converts a document into structured markdown text. Supports multiple formats:

| Format | Parser | Notes |
|--------|--------|-------|
| PDF | Docling (primary), PyMuPDF4LLM (fallback) | OCR retry when chars/page < 100 |
| DOCX | python-docx + markdownify | |
| HTML | markdownify | |
| EPUB | ebooklib | Chapter-based page splitting |
| PowerPoint | python-pptx | Slide-per-page |
| Excel/CSV | openpyxl / native | Row-based content |
| RST | docutils | |
| AsciiDoc | Native regex parser | |
| Plain text | Native | |
| Audio (MP3, WAV, FLAC, OGG, ...) | faster-whisper ASR | Timestamped transcription, 2-min page windows |
| Video (MP4, MKV, AVI, MOV, ...) | ffmpeg + faster-whisper | Audio extraction → ASR + keyframe extraction |
| Images (PNG, JPG, TIFF, BMP, WebP) | Docling VLM | OCR + layout analysis |
| Email (EML, MSG) | Native | Headers, body, inline attachments |
| XML | Native | Structured-to-markdown conversion |
| JSON / JSONL | Native | Object/array rendering |
| ZIP | Native | Auto-detects Notion, Confluence, or generic archive |

For PDFs, Docling provides deep layout analysis, table detection via TableFormer, heading recognition, and figure extraction. PyMuPDF4LLM is the fallback — faster, simpler markdown extraction with per-page output. If average chars/page < 100 after first pass, parsing retries with OCR enabled.

**Figure extraction:** Docling's `pictures` are extracted as `FigureRef` objects with caption, label, page number, and classification, then attached to their respective pages.

**Audio/video transcription:** Uses faster-whisper (local Whisper model) for ASR. Audio files are transcribed directly; video files have their audio track extracted via ffmpeg first. Transcription segments are grouped into ~2-minute pages with `[MM:SS]` timestamp markers. Video sources also get keyframe extraction at 60-second intervals, stored as figures. Timestamps propagate to L3 chunks for time-based retrieval. Requires `pip install ingestible[audio]` and `ffmpeg` on PATH for video.

**Output:** `ParsedDocument` with title, page count, TOC entries, per-page markdown content (including tables and figures), source format, and optional timestamps.

### Stage 1b — Cleaning

**File:** `pipeline/stage1b_clean.py`

Normalizes whitespace, strips artifacts, and cleans up parser output. Enabled by `INGEST_CLEANING_ENABLED`.

### Stage 2 — Structure Detection

**File:** `pipeline/stage2_structure.py`

Builds a hierarchy tree from the flat document. This is what gives the AI a "map" of the document.

**Strategy (in order of preference):**

1. **Parse embedded TOC tables** — Many documents contain a Table of Contents rendered as markdown tables with page numbers (`| Section Title | 42 |`). These are extracted with page number associations.

2. **Detect headings from markdown** — Falls back to `#`/`##`/`###` heading syntax, numbered section patterns ("1.1 Title", "Chapter 3:"), etc.

3. **Infer hierarchy from page ranges** — When all headings are the same level (common in PDFs where visual hierarchy is lost in conversion), uses page span heuristics:
   - Sections spanning 5+ pages → level 1 (chapter)
   - Sections spanning 2-4 pages → level 2 (section)
   - Sections spanning 1 page → level 3 (subsection)
   - Known patterns: "Risk"/"Mitigations" → always subsections; "Introduction"/"Conclusion" → always top-level

**Output:** `DocumentStructure` — a tree of `StructureNode` objects with titles, levels, page ranges, and content.

### Extraction Profile Resolution

**File:** `profiles.py`

Before chunking, the pipeline auto-detects the document type and selects an extraction profile:

| Profile | Detection | Effect |
|---------|----------|--------|
| `paper` | 3+ academic headings (Abstract, Methodology, etc.) | Citation extraction, methodology, key findings |
| `documentation` | Code blocks + API/install headings, or `.rst`/`.adoc` format | Code-aware enrichment |
| `article` | HTML/Markdown without academic or doc signals | Standard enrichment |
| `general` | Fallback (low-confidence detection) | Standard enrichment |

Heuristic detection is zero-cost. For ambiguous documents (low confidence), an optional LLM fallback classifies the document type (`INGEST_PROFILE_LLM_FALLBACK=true`).

### Stage 3 — Smart Chunking

**File:** `pipeline/stage3_chunking.py`

Produces a 4-level chunk hierarchy from the structure tree:

| Level | What | Size | Purpose |
|-------|------|------|---------|
| L0 | Document | ~500-800 tokens | Title, TOC, executive summary, metadata. Always returned as context. |
| L1 | Chapter | ~300-500 tokens | Chapter title + content preview. For browsing. |
| L2 | Section | ~200-400 tokens | Section title + content preview. Primary browse unit. |
| L3 | Passage | ~250-500 tokens | Actual content chunks. Primary search unit. |

**Chunking strategies** (configurable via `INGEST_CHUNKING_STRATEGY`):
- `paragraph` (default) — split on paragraph boundaries
- `semantic` — split on semantic similarity drops between sentences
- `recursive` — recursive character splitting with overlap

**Chunking rules:**
- Never split mid-paragraph or mid-sentence
- Tables and code blocks are atomic (never split)
- Configurable overlap between adjacent passages (`INGEST_CHUNK_OVERLAP_FRACTION`)
- Small trailing chunks get merged into the previous passage

**Output:** `ChunkSet` with `l0`, `l1_chunks`, `l2_chunks`, `l3_chunks`, and `citations`.

### Stage 3b — Validation

**File:** `pipeline/stage3b_validation.py`

Validates chunk sizes, hierarchy integrity, and content coverage. Catches issues before the expensive enrichment stage.

### Stage 3c — Contextual Chunking

**File:** `pipeline/stage3c_contextual.py`

Adds document-level context to each chunk (parent section title, position in document). Enabled by `INGEST_CONTEXTUAL_CHUNKING`.

### Stage 4 — LLM Enrichment (Optional)

**File:** `pipeline/stage4_enrichment.py`

One-time LLM pass at ingestion that generates metadata for dramatically better retrieval. Runs bottom-up: L3 → L2 → L1 → L0. Enrichment prompts are tailored to the detected extraction profile.

**Per L3 passage, the LLM generates:**
- `summary` — 2-3 sentence summary
- `concepts` — key concepts discussed (extractive)
- `hypothetical_questions` — 3-5 questions this passage answers
- `keywords` — specific terms for BM25 search
- `difficulty_level` — beginner/intermediate/advanced
- `depends_on` — prerequisite concepts
- `cross_references` — related topics

**Per L2 section:** `section_summary`, `key_points`, `concepts_introduced`

**Per L1 chapter:** `chapter_summary`, `main_topics`, `learning_objectives`, `key_takeaways`

**Per L0 document:** `domain`, `document_type`, `target_audience`, `key_concepts`, `executive_summary`, `key_findings`, `methodology`, `limitations`

**For papers:** structured citation extraction with authors, year, title, venue, DOI, and inline reference locations.

**Knowledge graph extraction** (when enabled via `INGEST_EXTRACT_KNOWLEDGE_GRAPH` or auto-enabled for `paper`/`documentation` profiles):
- Extracts `(subject, predicate, object)` triples from each L3 chunk
- Entity types: Person, Concept, Method, Organization, Technology, Dataset, Metric
- Predicates: uses, is_a, part_of, improves, depends_on, authored_by, evaluated_on, etc.
- Confidence scores (1.0 = directly stated, 0.5 = implied)
- Deduplication: same triple across chunks keeps highest confidence
- Stored per-chunk (`kg_triples`) and aggregated on ChunkSet (`knowledge_graph`)
- Persisted as `knowledge_graph.json`
- Accessible via `GET /documents/{doc_id}/knowledge-graph` API endpoint

**Selective re-enrichment:**

When re-ingesting with `--force`, `enrich_chunks()` accepts an optional `previous_chunks` parameter. It builds a lookup of previous L3 chunks by `content_hash`. Unchanged chunks copy all enrichment fields (summary, concepts, questions, KG triples) from the previous version instead of calling the LLM. When **all** L3 chunks are unchanged, L2/L1/L0 enrichment and KG extraction are also skipped. This is automatic during `--force` re-ingestion.

`re_enrich()` also accepts an optional `changed_chunk_ids` parameter for targeted re-enrichment of specific chunks (used by the CV webhook handler).

**LLM Client abstraction:**
- `OpenAIClient` (default) — uses `gpt-4o-mini` with structured JSON output
- `AnthropicClient` (alternative) — uses Claude Haiku
- Async with `Semaphore(N)` for concurrency control (`INGEST_LLM_CONCURRENCY`)
- Swappable via `INGEST_LLM_PROVIDER` env var

**Resilience:** All LLM calls use exponential backoff retry (configurable `INGEST_LLM_MAX_RETRIES`, default 3) on transient errors (429, 500, 502, 503). Per-call timeout is configurable via `INGEST_LLM_TIMEOUT` (default 120s).

The pipeline works without enrichment (`--skip-enrichment`). Validate the full loop before spending API credits.

### Stage 5 — Embedding & Indexing

**File:** `pipeline/stage5_embedding.py`

Builds three search indexes:

**Vector index (ChromaDB):**
- Model: E5-large-v2 via sentence-transformers. Device auto-detected: CUDA > MPS > CPU (configurable via `INGEST_EMBEDDING_DEVICE`)
- Requires `"passage: "` prefix for documents, `"query: "` prefix for queries
- `normalize_embeddings=True` for cosine similarity
- Multiple embeddings per chunk (content, summary, hypothetical questions)
- L0 digest embeddings (executive summary, key findings)
- All point back to the same `chunk_id` — deduplicated at query time
- Configurable dimensions (Matryoshka truncation) and quantization
- Chunk-level cache: unchanged chunks skip re-embedding

**Embedding providers:** Supports local models (sentence-transformers, default E5-large-v2) and API providers (OpenAI, Cohere, Voyage). Provider selected via `INGEST_EMBEDDING_PROVIDER`. API providers don't require sentence-transformers installed.

**BM25 index (rank-bm25):**
- Classic term-frequency search over `content + keywords`
- Language-aware tokenization (detected via `utils/language.py`)
- Persisted as pickle file

**Concept index:**
- Simple `concept → [chunk_ids]` JSON mapping
- For "tell me everything about X" queries
- Populated from enrichment concepts + keywords

### Stage 6 — Storage

**File:** `pipeline/stage6_storage.py`

Persists everything as a JSON file hierarchy:

```
data/documents/{doc_id}/
  meta.json              # title, pages, ingestion date, L0 chunk, metadata
  structure.json         # full hierarchy tree
  chapters/
    {chapter_id}/
      meta.json          # L1 chunk data
      sections/
        {section_id}/
          meta.json      # L2 chunk data
          chunks/
            {chunk_id}.json  # L3 passage data
  chroma/                # ChromaDB vector index
  bm25_index.pkl         # BM25 sparse index
  concept_index.json     # concept → chunk_ids mapping
  knowledge_graph.json   # entity-relationship triples (when KG enabled)
  .checkpoint/           # pipeline stage checkpoints (cleared on success)
  archive/               # previous versions (document versioning)
```

## Project Structure

```
src/ingestible/
  cli.py                 # CLI: ingest, list, search, corpus-search, enrich, export, versions, config, serve, eval, mcp
  eval.py                # Retrieval evaluation framework
  mcp_server.py          # MCP server for AI agents
  config.py              # pydantic-settings, INGEST_ env prefix
  profiles.py            # Extraction profiles (paper, article, documentation, general)
  web.py                 # Web UI (FastAPI + Jinja2 + htmx)
  api.py                 # REST API (FastAPI)
  logging.py             # Structured logging (structlog)
  audit.py               # Retrieval audit trail (JSONL logging)
  metrics.py             # Prometheus metrics definitions
  models/
    document.py          # ParsedDocument, FigureRef, StructureNode, DocumentStructure
    chunks.py            # L0/L1/L2/L3 chunk models, ChunkSet
    enrichment.py        # LLM output schemas
    metadata.py          # DocumentMetadata
    search.py            # SearchResult, SearchResponse
  pipeline/
    orchestrator.py      # Runs stages 1→6 in sequence, profile resolution
    stage1_parsing.py    # Multi-format document parsing
    stage1b_clean.py     # Content cleaning/normalization
    stage2_structure.py  # Heading detection, TOC extraction, hierarchy building
    stage3_chunking.py   # L0-L3 hierarchy chunking
    stage3b_validation.py # Chunk validation
    stage3c_contextual.py # Contextual chunk augmentation
    stage4_enrichment.py # LLM enrichment (OpenAI / Anthropic)
    stage5_embedding.py  # Embedding generation, ChromaDB + BM25 + concept indexing
    stage6_storage.py    # JSON file hierarchy persistence
    batch.py             # Batch/directory ingestion
    checkpoint.py        # Pipeline checkpoint/resume
    fetch.py             # URL download
    metadata.py          # Document metadata extraction
    progress.py          # Progress callbacks
    cloud.py               # Cloud storage connectors (S3, GCS, Azure)
    stage1c_classify.py    # Content-tier classification (T0-T3)
    re_enrich.py         # Re-enrichment without re-parsing
    watcher.py           # Directory file watcher (watchdog)
    task_queue.py        # Background ingestion job queue
    locking.py           # Document-level file locking (portalocker)
    cleanup.py           # Stale checkpoint/temp file cleanup
  search/
    hybrid.py            # RRF-based merge, optional cross-encoder reranking
    vector_store.py      # ChromaDB wrapper
    bm25_store.py        # rank-bm25 wrapper (with language-aware tokenization)
    concept_index.py     # concept → chunk_ids index
    splade_store.py      # SPLADE learned sparse retrieval
    corpus.py            # Cross-document corpus search
  export/
    jsonl.py             # JSONL export
    parquet.py           # Parquet export
    llamaindex.py        # LlamaIndex node export
    langchain.py         # LangChain document export
  adapters/
    cv_export.py         # CognitiveVault export adapter
  utils/
    tokens.py            # tiktoken token counting
    text.py              # paragraph/sentence splitting
    language.py          # Language detection
    retry.py             # LLM retry with exponential backoff
  templates/             # Jinja2 templates for web UI
```

## Web UI

**File:** `web.py`

Jinja2 templates with HTMX for interactivity. Routes: dashboard (list documents), document detail, chunk tree viewer, search (single-doc and corpus), file upload. Templates auto-escape HTML output.

## API Infrastructure

**File:** `api.py`

FastAPI application with layered middleware (bottom to top):
1. CORS (configurable origins)
2. Authentication (Bearer token matching against `INGEST_API_KEYS`)
3. Request ID (generates/reads `X-Request-ID`, binds to structlog)
4. Rate limiting (slowapi, per-IP, three tiers: ingest/search/default)

Prometheus instrumentation via `prometheus-fastapi-instrumentator` exposes `/metrics`.
Background ingestion via `TaskQueue` — `POST /ingest/async` returns 202 with job ID.
Startup: configures structured logging, runs stale file cleanup.
Shutdown: drains active ingestion jobs.

## Production Infrastructure

**Concurrency & locking:**
- Background ingestion via `TaskQueue` (ThreadPoolExecutor) — `POST /ingest/async` returns 202 with a job ID
- Document-level file locking (portalocker) prevents concurrent write corruption during ingestion, re-enrichment, and webhook updates
- Batch processing caps per-worker LLM concurrency to stay under `INGEST_MAX_TOTAL_LLM_CONCURRENCY`

**Observability:**
- Structured JSON logging via structlog (console output for CLI)
- Request ID tracing — `X-Request-ID` header generated/propagated through all log entries
- Prometheus metrics at `/metrics` — ingestion duration, LLM calls, active jobs, search latency
- Readiness probe at `/health/ready` — checks data dir, disk space, embedding model, LLM config

**Security:**
- Path traversal protection on all `{doc_id}` parameters
- File upload size limits (HTTP 413)
- Rate limiting via slowapi (per-IP, configurable tiers)
- CORS origins configurable via `INGEST_CORS_ORIGINS`

**Sparse retrieval:** BM25 (default) or SPLADE (learned sparse vectors with term expansion). SPLADE activates vocabulary terms not in the original text, improving recall on domain-specific queries. Configurable via `INGEST_SPARSE_RETRIEVAL`.

**Access control:** Optional per-document access tags stored in meta.json and ChromaDB metadata. Search filters by user tags at retrieval time (not post-filtering). Enabled via `INGEST_ACCESS_CONTROL_ENABLED`.

**Audit trail:** Optional JSONL logging of every search query with results, user, and latency. Stored at `data/audit.jsonl`. CLI: `ingest audit`.

**Deployment:**
- Dockerfile (multi-stage, non-root, ffmpeg included) + docker-compose
- Gunicorn with UvicornWorker, preload, max_requests leak protection
- Graceful shutdown drains active ingestion jobs
- Stale checkpoint/temp cleanup on startup
