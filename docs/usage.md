# Usage Guide

## Installation

```bash
cd Ingestible

# Create virtual environment (requires Python 3.11-3.12, ChromaDB incompatible with 3.14)
python3.12 -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"
```

### Docker

```bash
cp .env.example .env
# Edit .env with your API keys

docker compose up -d
```

The API and web UI are available at `http://localhost:8081`. Data is persisted via a Docker volume.

The API runs behind gunicorn with multiple workers for production use. For development, use `ingest serve` directly.

## Configuration

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
```

**Required for enrichment (Stage 4):**
```
INGEST_LLM_PROVIDER=openai           # or "anthropic"
INGEST_OPENAI_API_KEY=sk-...         # needed if provider=openai
INGEST_OPENAI_MODEL=gpt-4o-mini
INGEST_ANTHROPIC_API_KEY=sk-ant-...  # needed if provider=anthropic
INGEST_ANTHROPIC_MODEL=claude-haiku-4-5-20251001
```

**Embedding:**
```
INGEST_EMBEDDING_MODEL=intfloat/e5-large-v2    # default
INGEST_EMBEDDING_DIMENSIONS=                    # Matryoshka truncation (empty = full)
INGEST_EMBEDDING_QUANTIZATION=none              # "none" or "binary"
```

**Chunking:**
```
INGEST_MAX_CHUNK_TOKENS=500                     # max L3 passage size
INGEST_MIN_CHUNK_TOKENS=100
INGEST_CHUNK_OVERLAP_FRACTION=0.1
INGEST_CHUNKING_STRATEGY=paragraph              # "paragraph", "semantic", or "recursive"
INGEST_SEMANTIC_THRESHOLD_PERCENTILE=10
INGEST_CONTEXTUAL_CHUNKING=false
```

**Search tuning:**
```
INGEST_VECTOR_WEIGHT=0.7                        # vector vs BM25 balance
INGEST_BM25_WEIGHT=0.3
INGEST_DEFAULT_SEARCH_RESULTS=5
INGEST_RERANKER_MODEL=                          # cross-encoder model (empty = disabled)
INGEST_RERANKER_TOP_K=50
INGEST_RERANKER_WEIGHT=0.5
```

**Audio/video transcription:**
```
INGEST_WHISPER_MODEL=base                       # faster-whisper model: tiny, base, small, medium, large-v3
```

Requires `pip install ingestible[audio]`. Video also requires `ffmpeg` on PATH.

**Knowledge graph:**
```
INGEST_EXTRACT_KNOWLEDGE_GRAPH=false            # extract entity-relationship triples
```

Enabled by default for `paper` and `documentation` profiles regardless of this setting.

**Other:**
```
INGEST_DATA_DIR=data                            # where documents are stored
INGEST_LLM_CONCURRENCY=10                       # parallel LLM calls
INGEST_CLEANING_ENABLED=true
INGEST_DEDUP_ENABLED=true
INGEST_CHECKPOINT_ENABLED=true
INGEST_API_KEYS=key1,key2                       # API auth (empty = no auth)
```

**Production / deployment:**
```
INGEST_CORS_ORIGINS=*                          # comma-separated allowed origins
INGEST_RATE_LIMIT_INGEST=10/minute             # rate limit for ingestion endpoints
INGEST_RATE_LIMIT_SEARCH=60/minute             # rate limit for search endpoints
INGEST_RATE_LIMIT_DEFAULT=120/minute           # rate limit for other endpoints
INGEST_MAX_UPLOAD_BYTES=500000000              # max file upload size (500 MB)
INGEST_MAX_CONCURRENT_INGESTIONS=2             # background ingestion workers
INGEST_PARSE_TIMEOUT=300                       # seconds before parsing is aborted
INGEST_LLM_TIMEOUT=120                        # seconds per LLM API call
INGEST_LLM_MAX_RETRIES=3                      # retries on transient LLM errors
INGEST_EMBEDDING_DEVICE=auto                  # auto | cuda | mps | cpu
INGEST_LOG_JSON=true                          # JSON structured logging
INGEST_LOG_LEVEL=INFO                         # DEBUG, INFO, WARNING, ERROR
INGEST_MIN_DISK_SPACE_MB=500                  # readiness check threshold
```

No API keys are needed if you use `--skip-enrichment`. The embedding model (E5-large-v2) runs locally.

See [.env.example](../.env.example) for the complete list with comments.

## CLI Commands

### Ingest a document

```bash
ingest ingest /path/to/document.pdf -v
```

**Flags:**
- `-v` / `--verbose` — show progress for each stage
- `--skip-enrichment` — skip LLM enrichment (no API cost, still builds search indexes)
- `--profile auto|paper|article|documentation|general` — extraction profile (default: `auto`)
- `--chunking paragraph|semantic|recursive` — chunking strategy override
- `--force` — force re-ingestion even if document is unchanged
- `--no-checkpoint` — disable pipeline checkpoint/resume
- `--data-dir /custom/path` — override the data directory

**What happens:**
1. Document is parsed (Docling for PDFs with PyMuPDF4LLM fallback; native parsers for other formats)
2. Extraction profile is auto-detected (paper, article, documentation, or general)
3. Document structure is detected (TOC tables, heading patterns, page range heuristics)
4. Content is chunked into L0/L1/L2/L3 hierarchy
5. LLM enrichment generates summaries, concepts, questions (unless `--skip-enrichment`)
6. Embeddings are generated and indexed (ChromaDB + BM25 + concept index)
7. Everything is saved to `data/documents/{doc_id}/`

**First run downloads the E5-large-v2 model (~1.3GB). Subsequent runs use the cache.**

### Batch ingestion

```bash
# Ingest all supported files in a directory
ingest ingest /path/to/docs/ -v

# Process files concurrently
ingest ingest /path/to/docs/ --parallel 4
```

### List ingested documents

```bash
ingest list
```

Shows all ingested documents with their IDs, titles, page counts, and ingestion dates.

### Search within a document

```bash
ingest search <doc_id> "your query here"
```

**Flags:**
- `-n N` — number of results (default: 5)

**Example:**
```bash
ingest search so-ticke-ich-buch-f7fbdddde343 "Wie geht man mit Reizüberflutung um?" -n 10
```

Returns ranked results with scores, match sources (vector/bm25/concept), and content snippets.

### Search across all documents

```bash
ingest corpus-search "your query here"
```

Searches all ingested documents simultaneously with cross-document RRF fusion. Results include the source document title.

**Flags:**
- `-n N` — number of results (default: 10)
- `--doc-ids ID1 ID2 ...` — limit search to specific document IDs

### Re-enrich a document

```bash
ingest enrich <doc_id>
```

Re-runs enrichment (Stage 4) without re-parsing or re-chunking. Useful when you want to update summaries and concepts after changing LLM settings or prompt templates.

**Selective re-enrichment:** When re-ingesting with `--force`, unchanged chunks (same content hash) automatically skip LLM enrichment — their summaries, concepts, and questions are copied from the previous version. When all L3 chunks are unchanged, L2/L1/L0 enrichment is also skipped. This happens automatically; no flags needed.

### Export

```bash
ingest export <doc_id> --format jsonl -o output.jsonl
```

**Supported formats:** `jsonl`, `parquet`, `llamaindex`, `langchain`

### Watch a directory for changes

```bash
ingest watch /path/to/docs/ -v
```

Watches a directory for file changes and auto-ingests on create/modify. Uses OS-native filesystem events with a 2-second debounce window to batch rapid writes (e.g. `git checkout`, editor batch-saves).

**Flags:**
- `-v` / `--verbose` — show ingestion progress
- `--skip-enrichment` — skip LLM enrichment for auto-ingested documents
- `--data-dir /custom/path` — override the data directory
- `--cv-push` — auto-push to CognitiveVault after each batch completes
- `--cv-url`, `--cv-api-key`, `--cv-vault-id` — CognitiveVault connection (or use env vars)

**Requires the `watch` extra:**
```bash
pip install -e ".[watch]"
```

**Example with CV auto-push:**
```bash
export CV_URL=https://cv.example.com
export CV_API_KEY=cvk_...
export CV_VAULT_ID=vault-abc
ingest watch ./docs/ -v --cv-push
```

### Export to CognitiveVault

```bash
ingest export-cv [doc_id] --cv-url https://cv.example.com \
  --cv-api-key cvk_... --cv-vault-id vault-abc
```

See [CognitiveVault Integration](cv-integration.md) for details.

### Document versions

```bash
ingest versions <doc_id>
```

Shows version history when a document has been re-ingested.

### Clean up stale files

```bash
ingest cleanup --max-age 24
```

Removes stale checkpoint directories, lock files, and temp uploads older than the specified hours. Also runs automatically on API startup.

### Show configuration

```bash
ingest config
```

Displays the effective configuration from all sources (defaults, env vars, `.env` file).

### Web UI

```bash
ingest serve
```

Starts the web server with document browsing, hierarchical chunk viewer, search, and file upload.

## Extraction Profiles

Ingestible auto-detects the document type and applies a tailored extraction profile:

| Profile | Detects via | Extras |
|---------|------------|--------|
| `paper` | Academic headings (Abstract, Methodology, References...) | Citation extraction, methodology, key findings |
| `article` | HTML/Markdown without academic signals | Executive summary |
| `documentation` | Code blocks, API/install headings, `.rst`/`.adoc` format | Code-aware chunking |
| `general` | Fallback | Standard enrichment |

Override with `--profile <name>`. For ambiguous documents, enable LLM-based classification with `INGEST_PROFILE_LLM_FALLBACK=true`.

## Supported Formats

| Format | Extensions | Parser |
|--------|-----------|--------|
| PDF | `.pdf` | Docling (primary), PyMuPDF4LLM (fallback), OCR retry |
| Markdown | `.md` | Native |
| DOCX | `.docx` | python-docx + markdownify |
| HTML | `.html`, `.htm` | markdownify |
| EPUB | `.epub` | ebooklib |
| PowerPoint | `.pptx` | python-pptx |
| Excel | `.xlsx`, `.xls` | openpyxl |
| CSV | `.csv` | Native |
| reStructuredText | `.rst` | docutils |
| AsciiDoc | `.adoc`, `.asciidoc` | Native |
| Plain text | `.txt` | Native |
| Audio | `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.aac`, `.opus` | faster-whisper ASR (requires `pip install ingestible[audio]`) |
| Video | `.mp4`, `.mkv`, `.avi`, `.mov`, `.webm`, `.wmv`, `.flv` | ffmpeg + faster-whisper (requires `ffmpeg` on PATH) |

PDF figure extraction: figures are extracted with captions, labels, page numbers, and classifications when using the Docling parser.

## Typical Workflow

```bash
# 1. Validate the pipeline without API cost
ingest ingest mybook.pdf -v --skip-enrichment

# 2. Check it worked
ingest list
ingest search <doc_id> "test query"

# 3. Re-ingest with enrichment for better search quality
ingest ingest mybook.pdf -v --force

# 4. Search across all documents
ingest corpus-search "my query"
```

## Data Storage

All data lives under `data/documents/{doc_id}/`:

```
data/documents/{doc_id}/
  meta.json           # document metadata + L0 chunk
  structure.json      # hierarchy tree
  chapters/           # L1/L2/L3 JSON files
  chroma/             # ChromaDB vector index (persistent)
  bm25_index.pkl      # BM25 sparse index
  concept_index.json  # concept → chunk_ids mapping
  knowledge_graph.json # entity-relationship triples (when KG extraction is enabled)
  .checkpoint/        # pipeline checkpoint files (cleared on success)
  archive/            # previous versions (when re-ingested)
```

To delete a document, remove its directory:
```bash
rm -rf data/documents/<doc_id>
```

## Known Limitations

- ChromaDB requires Python 3.11-3.12 (incompatible with 3.14)
- PDFs with non-standard page dimension metadata may fail Docling parsing (PyMuPDF4LLM fallback handles these)
- Visual-only hierarchy (same font size for all headings) requires TOC table extraction or page-range heuristics
- Figure extraction only works with the Docling parser (not PyMuPDF4LLM fallback)
