# Introduction

Ingestible is a document ingestion pipeline that transforms documents into token-efficient, searchable knowledge stores for AI.

Instead of dumping 90,000 tokens into an LLM context window, Ingestible gives your AI a **structured map** of the document and **hybrid search** across three indexes — so each query costs ~1,000-2,000 tokens instead.

```
513-page book:  92,598 tokens full  →  ~1,317 tokens per query  (99% reduction)
55-page paper:   4,975 tokens full  →    ~585 tokens per query  (88% reduction)
```

## Quick Install

### pip (recommended)

```bash
pip install ingestible                # base install (~50MB) — uses API embeddings
```

To use **local embeddings** (no API keys needed, runs fully offline):

```bash
pip install ingestible[local]         # adds torch + sentence-transformers + ChromaDB (~2GB)
```

### Docker

```bash
docker run -d \
  -p 8081:8081 \
  -v ingestible-data:/app/data \
  ghcr.io/simplyliz/ingestible:latest
```

The API and web UI are at `http://localhost:8081`. Data persists via the Docker volume.

## Quickstart

```bash
# Ingest a document (no API keys needed — skips LLM enrichment, builds all search indexes)
ingest add /path/to/document.pdf -v --skip-enrichment

# List ingested documents
ingest list

# Search
ingest search <doc_id> "your query here"

# Parse only — get structured chunks as JSONL, no storage
ingest parse /path/to/document.pdf
```

First run downloads the E5-large-v2 embedding model (~1.3 GB). Runs locally on CPU / Apple Silicon MPS / CUDA.

## With LLM enrichment

Enrichment adds summaries, hypothetical questions, and concept tags to each chunk — significantly improving search precision. One-time cost per document.

```bash
cp .env.example .env   # add your Anthropic or OpenAI API key
ingest add /path/to/document.pdf -v
```

| Document size | Estimated cost (gpt-4o-mini) | Time |
|---------------|------------------------------|------|
| 55 pages | ~$0.01 | ~1 min |
| 500 pages | ~$0.20 | ~5 min |
| 1,000 pages | ~$0.50 | ~10 min |

## How It Works

| Stage | What happens |
|-------|-------------|
| **Parse** | Format-specific extraction to clean markdown. PDF uses IBM Docling for deep layout analysis, PyMuPDF fallback, automatic OCR if text is sparse. |
| **Structure** | Builds hierarchy tree from TOC tables, heading patterns, or page range heuristics. |
| **Chunk** | Splits into 4 levels (L0-L3). Tables and code blocks stay atomic. ~10% overlap. Small trailing chunks get merged. |
| **Enrich** | Bottom-up LLM pass (L3 to L0) generates summaries, concepts, hypothetical questions, entities. Skippable. |
| **Embed** | E5-large-v2 vectors (ChromaDB, auto-detected CUDA/MPS/CPU) + BM25 sparse index + concept-to-chunk mapping. |
| **Store** | JSON file hierarchy under `data/documents/{doc_id}/`. |

## Optional Extras

| Extra | What it adds |
|-------|-------------|
| `local` | Local embeddings — sentence-transformers, ChromaDB, torch |
| `pgvector` | PostgreSQL pgvector backend — psycopg, pgvector |
| `gemini` | Google Gemini LLM + embeddings — google-genai |
| `audio` | Audio/video transcription — faster-whisper |
| `cloud` | S3, GCS, Azure Blob connectors — boto3, google-cloud-storage, azure-storage-blob |
| `mcp` | MCP server for AI agent integration |
| `watch` | File watcher — watchdog |
| `cohere` | Cohere embedding provider |
| `voyage` | Voyage embedding provider |

Combine extras with commas: `pip install ingestible[local,audio,cloud]`
