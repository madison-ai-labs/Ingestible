# Ingestible

A document ingestion pipeline that transforms PDFs, Markdown, DOCX, HTML, EPUB, PowerPoint, Excel, CSV, RST, AsciiDoc, and plain text into a hierarchical, searchable knowledge store optimized for AI retrieval.

Instead of dumping 90,000 tokens into an LLM context window, Ingestible gives your AI a **structured map** of the document and **hybrid search** across three indexes — so each query costs ~1,000-2,000 tokens instead.

```
513-page book:  92,598 tokens full  →  ~1,317 tokens per query  (99% reduction)
55-page paper:   4,975 tokens full  →    ~585 tokens per query  (88% reduction)
```

## How It Works

```
Document  →  Parse  →  Structure  →  Chunk  →  Enrich  →  Embed  →  Store
              ↓           ↓            ↓          ↓          ↓
           Docling     Heading      4-level    LLM adds   ChromaDB
           + OCR       detection    hierarchy  summaries  + BM25
           fallback    + TOC        (L0-L3)    concepts   + concepts
                       extraction              questions
```

**The 4-level chunk hierarchy:**

| Level | What | Size | Purpose |
|-------|------|------|---------|
| L0 | Document overview + TOC + executive summary | ~500-800 tokens | Map of the entire document |
| L1 | Chapters | ~300-500 tokens | Browsing units |
| L2 | Sections | ~200-400 tokens | Section summaries |
| L3 | Passages | ~250-500 tokens | Primary search targets |

**Three search indexes, fused with Reciprocal Rank Fusion (RRF):**

- **Vector** (ChromaDB + E5-large-v2) — semantic meaning
- **BM25** (rank-bm25) — keyword matching
- **Concept index** — direct concept-to-chunk lookup

Passages found by multiple indexes rank higher. No score normalization needed.

## Quickstart

```bash
git clone https://github.com/simplyliz/Ingestible.git
cd Ingestible

# Requires Python 3.11-3.12 (ChromaDB incompatible with 3.14)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Ingest without API keys (skips LLM enrichment, still builds all search indexes)
ingest ingest /path/to/document.pdf -v --skip-enrichment

# List ingested documents
ingest list

# Search within a document
ingest search <doc_id> "your query here"

# Search across all documents
ingest corpus-search "your query here"
```

**First run downloads the E5-large-v2 embedding model (~1.3GB). Runs locally on CPU/Apple Silicon MPS.**

### With Docker

```bash
cp .env.example .env
# Add your API keys to .env

docker compose up -d
```

The API and web UI are available at `http://localhost:8081`. Document data is persisted via a Docker volume.

### With LLM Enrichment

Enrichment adds summaries, hypothetical questions, and concept tags to each chunk — significantly improving search precision. One-time cost per document.

```bash
cp .env.example .env
# Add your OpenAI or Anthropic API key

ingest ingest /path/to/document.pdf -v
```

| Document size | Estimated enrichment cost (gpt-4o-mini) | Time |
|---------------|----------------------------------------|------|
| 55 pages | ~$0.01 | ~1 min |
| 500 pages | ~$0.20 | ~5 min |
| 1,000 pages | ~$0.50 | ~10 min |

## Supported Formats

| Format | Extensions | Notes |
|--------|-----------|-------|
| PDF | `.pdf` | Text + scanned/OCR via Docling |
| Markdown | `.md` | |
| DOCX | `.docx` | |
| HTML | `.html`, `.htm` | |
| EPUB | `.epub` | |
| PowerPoint | `.pptx` | |
| Excel | `.xlsx` | |
| CSV | `.csv` | |
| reStructuredText | `.rst` | |
| AsciiDoc | `.adoc` | |
| Plain text | `.txt` | |

## Extraction Profiles

Ingestible auto-detects the document type and applies a tailored extraction profile:

| Profile | Detects via | Extras |
|---------|------------|--------|
| `paper` | Academic headings (Abstract, Methodology, References...) | Citation extraction, methodology, key findings |
| `article` | HTML/Markdown without academic signals | Executive summary |
| `documentation` | Code blocks, API/install headings, `.rst`/`.adoc` format | Code-aware chunking |
| `general` | Fallback | Standard enrichment |

Override with `--profile <name>`, or enable LLM fallback for ambiguous documents with `INGEST_PROFILE_LLM_FALLBACK=true`.

## CLI Reference

```bash
ingest ingest <path>           # Ingest a file or directory
ingest list                    # List all ingested documents
ingest search <doc_id> <query> # Search within a document
ingest corpus-search <query>   # Search across all documents
ingest enrich <doc_id>         # Re-enrich without re-parsing
ingest export <doc_id>         # Export (jsonl, parquet, llamaindex, langchain)
ingest versions <doc_id>       # Show document version history
ingest config                  # Show effective configuration
ingest serve                   # Start web UI + API server
```

### Ingest Options

```bash
ingest ingest /path/to/docs/ \
  --profile auto \              # auto | paper | article | documentation | general
  --chunking paragraph \        # paragraph | semantic | recursive
  --parallel 4 \                # concurrent file processing
  --force \                     # re-ingest even if unchanged
  --skip-enrichment \           # skip LLM enrichment
  --no-checkpoint \             # disable checkpoint/resume
  -v                            # verbose logging
```

## Web UI

```bash
ingest serve
```

Browse documents, view chunk hierarchies, search within and across documents — all from a browser. File upload for ingestion included.

## Configuration

All settings via environment variables (`INGEST_*` prefix) or `.env` file. See [.env.example](.env.example) for the full list.

Key settings:

```bash
# LLM provider
INGEST_LLM_PROVIDER=openai              # or "anthropic"
INGEST_OPENAI_API_KEY=sk-...
INGEST_OPENAI_MODEL=gpt-4o-mini

# Embeddings
INGEST_EMBEDDING_MODEL=intfloat/e5-large-v2
INGEST_EMBEDDING_DIMENSIONS=             # Matryoshka truncation (empty = full)
INGEST_EMBEDDING_QUANTIZATION=none       # "none" or "binary"

# Search tuning
INGEST_VECTOR_WEIGHT=0.7
INGEST_BM25_WEIGHT=0.3
INGEST_RERANKER_MODEL=                   # cross-encoder model (empty = disabled)

# Chunking
INGEST_MAX_CHUNK_TOKENS=500
INGEST_CHUNKING_STRATEGY=paragraph       # paragraph | semantic | recursive
INGEST_CONTEXTUAL_CHUNKING=false

# API auth (empty = no auth)
INGEST_API_KEYS=key1,key2
```

See the [Usage Guide](docs/usage.md) for full configuration options.

## Documentation

- [Architecture Overview](docs/architecture.md) — pipeline stages, data flow, project structure
- [How Search Works](docs/search.md) — vector search, BM25, concept index, RRF fusion
- [Usage Guide](docs/usage.md) — installation, CLI commands, configuration
- [Token Economics](docs/token-economics.md) — why hierarchical retrieval matters, real-world numbers
- [CognitiveVault Integration](docs/cv-integration.md) — export to CognitiveVault
- [Roadmap](docs/roadmap.md)

## Why Not Just Use LlamaIndex / LangChain?

Ingestible is purpose-built for one thing: turning documents into the most token-efficient, highest-precision knowledge stores possible.

- **Hierarchical chunking** (L0-L3) preserves document structure. Most RAG tools flatten everything.
- **Three independent search indexes** fused with RRF. No single point of failure in retrieval.
- **LLM enrichment** generates 5-6 embeddings per passage (content + summary + hypothetical questions). One-time cost, permanent precision gain.
- **Extraction profiles** tailor the pipeline to the document type — papers get citation extraction, docs get code-aware chunking.
- **Cross-document corpus search** with RRF fusion across all ingested documents.
- **Zero cloud dependencies** for core pipeline. Embeddings run locally. LLM enrichment is optional.
- **Checkpoint/resume** for long-running pipelines. Content-hash deduplication. Version tracking.
- **Deterministic and repeatable.** Async-safe, no side effects.

## License

[Apache 2.0](LICENSE)
