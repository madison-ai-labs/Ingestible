# Usage Guide

## Installation

```bash
cd Ingestible

# Create virtual environment (requires Python 3.12, not 3.14 — ChromaDB incompatible)
python3.12 -m venv .venv
source .venv/bin/activate

# Install
pip install -e ".[dev]"
```

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

**Optional:**
```
INGEST_EMBEDDING_MODEL=intfloat/e5-large-v2  # default
INGEST_DATA_DIR=data                          # where documents are stored
INGEST_LLM_CONCURRENCY=10                    # parallel LLM calls
INGEST_MAX_CHUNK_TOKENS=500                   # max L3 passage size
INGEST_VECTOR_WEIGHT=0.7                      # vector vs BM25 balance
INGEST_BM25_WEIGHT=0.3
```

No API keys are needed if you use `--skip-enrichment`. The embedding model (E5-large-v2) runs locally.

## CLI Commands

### Ingest a PDF

```bash
ingest ingest /path/to/document.pdf -v
```

**Flags:**
- `-v` / `--verbose` — show progress for each stage
- `--skip-enrichment` — skip the LLM enrichment stage (no API cost, still builds search indexes)
- `--data-dir /custom/path` — override the data directory

**What happens:**
1. PDF is parsed (Docling primary, PyMuPDF4LLM fallback)
2. Document structure is detected (TOC tables, heading patterns, page range heuristics)
3. Content is chunked into L0/L1/L2/L3 hierarchy
4. LLM enrichment generates summaries, concepts, questions (unless `--skip-enrichment`)
5. Embeddings are generated and indexed (ChromaDB + BM25 + concept index)
6. Everything is saved to `data/documents/{doc_id}/`

**First run downloads the E5-large-v2 model (~1.3GB). Subsequent runs use the cache.**

### List Ingested Documents

```bash
ingest list
```

Shows all ingested documents with their IDs, titles, page counts, and ingestion dates.

### Search a Document

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

## Typical Workflow

```bash
# 1. Validate the pipeline without API cost
ingest ingest mybook.pdf -v --skip-enrichment

# 2. Check it worked
ingest list
ingest search <doc_id> "test query"

# 3. Re-ingest with enrichment for better search quality
#    (delete the old data first)
rm -rf data/documents/<doc_id>
ingest ingest mybook.pdf -v
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
```

To delete a document, remove its directory:
```bash
rm -rf data/documents/<doc_id>
```

## Supported PDFs

- Text-based PDFs (native text layer)
- Scanned PDFs (triggers OCR retry when chars/page < 100)
- Mixed text + tables + figures
- Multi-language (E5-large-v2 handles many languages)
- Any size — tested with 500+ page books

**Known limitations:**
- PDFs with non-standard page dimension metadata may fail Docling parsing (PyMuPDF4LLM fallback handles these)
- Visual-only hierarchy (same font size for all headings) requires TOC table extraction or page-range heuristics
- ChromaDB requires Python 3.12 (incompatible with 3.14)
