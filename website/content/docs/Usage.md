# Usage Guide

## Installation

```bash
cd Ingestible

# Create virtual environment (requires Python 3.11-3.13, ChromaDB incompatible with 3.14)
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
INGEST_LLM_PROVIDER=anthropic        # or "openai"
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

**Content classification:**
```
INGEST_CONTENT_CLASSIFICATION=false            # classify blocks into tiers (T0-T3)
INGEST_PROFILE_LLM_FALLBACK=false              # LLM fallback for ambiguous profile detection
```

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
INGEST_SEARCHER_CACHE_SIZE=50                  # max cached document searchers in memory
```

**Embedding providers:**
```
INGEST_EMBEDDING_PROVIDER=local                # local | openai | cohere | voyage
INGEST_OPENAI_EMBEDDING_API_KEY=               # falls back to INGEST_OPENAI_API_KEY
INGEST_COHERE_API_KEY=                         # for Cohere Embed v3/v4
INGEST_VOYAGE_API_KEY=                         # for Voyage-3
```

When using API providers, set `INGEST_EMBEDDING_MODEL` to the provider-specific model name (e.g., `text-embedding-3-large` for OpenAI).

**Access control:**
```
INGEST_ACCESS_CONTROL_ENABLED=false            # enable per-document access filtering
```

Tag documents during ingestion with `--access-tags admin,engineering`. Filter at search time with the `X-Access-Tags: admin` header. Empty tags = public (accessible to all).

**Audit trail:**
```
INGEST_AUDIT_ENABLED=false                     # log every search to data/audit.jsonl
```

**Sparse retrieval:**
```
INGEST_SPARSE_RETRIEVAL=bm25                   # bm25 or splade
INGEST_SPLADE_MODEL=naver/splade-cocondenser-ensembledistil
```

SPLADE uses learned sparse vectors with term expansion. Requires `pip install transformers torch`.

No API keys are needed if you use `--skip-enrichment`. The embedding model (E5-large-v2) runs locally.

See [.env.example](../.env.example) for the complete list with comments.

## CLI Commands

### Ingest a document

```bash
ingest add /path/to/document.pdf -v
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

**Cloud storage:**
```bash
ingest add s3://my-bucket/docs/report.pdf -v
ingest add gs://my-bucket/docs/paper.pdf -v
ingest add az://my-container/docs/spec.pdf -v
```

Requires `pip install ingestible[cloud]`.

**First run downloads the E5-large-v2 model (~1.3GB). Subsequent runs use the cache.**

### Batch ingestion

```bash
# Ingest all supported files in a directory
ingest add /path/to/docs/ -v

# Process files concurrently
ingest add /path/to/docs/ --parallel 4
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

### View audit trail

```bash
ingest audit                     # show last 20 entries
ingest audit -n 50               # show last 50
ingest audit --query "machine"   # filter by query text
```

Requires `INGEST_AUDIT_ENABLED=true`. Logs are stored in `data/audit.jsonl`.

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

### Evaluate retrieval quality

```bash
# Auto-generate queries from enrichment hypothetical questions
ingest eval <doc_id>

# Use manual Q&A pairs
ingest eval <doc_id> --queries eval_queries.jsonl

# Compare hybrid vs vector-only vs BM25-only
ingest eval <doc_id> --compare

# Save detailed results
ingest eval <doc_id> -k 10 --output results.json
```

Metrics: Hit Rate@K, MRR (Mean Reciprocal Rank), Precision@K, Recall@K.

Synthetic mode uses the hypothetical questions generated during enrichment as queries — each question should retrieve the chunk it came from (self-consistency check).

### Start MCP server

```bash
ingest mcp
```

Exposes Ingestible as an MCP (Model Context Protocol) server. AI agents can ingest documents, search the corpus, and retrieve chunk details directly.

**Tools:** `ingest_document`, `search`, `list_documents`, `get_document_overview`, `get_chunk`, `get_knowledge_graph`, `delete_document`.

**Requires:** `pip install ingestible[mcp]`

**Claude Desktop config:**
```json
{
    "mcpServers": {
        "ingestible": {
            "command": "python",
            "args": ["-m", "ingestible.mcp_server"]
        }
    }
}
```

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
| Images | `.png`, `.jpg`, `.jpeg`, `.tiff`, `.bmp`, `.webp` | OCR + layout via Docling VLM |
| Email | `.eml`, `.msg` | Headers, body, attachments |
| XML | `.xml` | Structured to markdown |
| JSON | `.json`, `.jsonl` | Object/array rendering |
| ZIP | `.zip` | Auto-detects Notion, Confluence, or generic |

PDF figure extraction: figures are extracted with captions, labels, page numbers, and classifications when using the Docling parser.

## Typical Workflow

```bash
# 1. Validate the pipeline without API cost
ingest add mybook.pdf -v --skip-enrichment

# 2. Check it worked
ingest list
ingest search <doc_id> "test query"

# 3. Re-ingest with enrichment for better search quality
ingest add mybook.pdf -v --force

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

- ChromaDB requires Python 3.11-3.13 (incompatible with 3.14)
- PDFs with non-standard page dimension metadata may fail Docling parsing (PyMuPDF4LLM fallback handles these)
- Visual-only hierarchy (same font size for all headings) requires TOC table extraction or page-range heuristics
- Figure extraction only works with the Docling parser (not PyMuPDF4LLM fallback)
