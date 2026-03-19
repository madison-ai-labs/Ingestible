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

**Other:**
```
INGEST_DATA_DIR=data                            # where documents are stored
INGEST_LLM_CONCURRENCY=10                       # parallel LLM calls
INGEST_CLEANING_ENABLED=true
INGEST_DEDUP_ENABLED=true
INGEST_CHECKPOINT_ENABLED=true
INGEST_API_KEYS=key1,key2                       # API auth (empty = no auth)
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

### Re-enrich a document

```bash
ingest enrich <doc_id>
```

Re-runs enrichment (Stage 4) without re-parsing or re-chunking. Useful when you want to update summaries and concepts after changing LLM settings or prompt templates.

### Export

```bash
ingest export <doc_id> --format jsonl -o output.jsonl
```

**Supported formats:** `jsonl`, `parquet`, `llamaindex`, `langchain`

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
