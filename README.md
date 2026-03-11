# Ingestible

A document ingestion pipeline that transforms PDFs, Markdown, DOCX, HTML, and plain text into a hierarchical, searchable knowledge store optimized for AI retrieval.

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
| L0 | Document overview + TOC | ~500-800 tokens | Map of the entire document |
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

# Search
ingest search <doc_id> "your query here"
```

**First run downloads the E5-large-v2 embedding model (~1.3GB). Runs locally on CPU/Apple Silicon MPS.**

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

PDF (text + scanned/OCR), Markdown, DOCX, HTML, plain text.

## Configuration

All settings via environment variables (`INGEST_*` prefix) or `.env` file:

```bash
INGEST_LLM_PROVIDER=openai              # or "anthropic"
INGEST_OPENAI_API_KEY=sk-...
INGEST_OPENAI_MODEL=gpt-4o-mini
INGEST_EMBEDDING_MODEL=intfloat/e5-large-v2
INGEST_VECTOR_WEIGHT=0.7
INGEST_BM25_WEIGHT=0.3
INGEST_LLM_CONCURRENCY=10
```

See the [Usage Guide](docs/usage.md) for full configuration options.

## Documentation

- [Architecture Overview](docs/architecture.md) — pipeline stages, data flow, project structure
- [How Search Works](docs/search.md) — vector search, BM25, concept index, RRF fusion
- [Usage Guide](docs/usage.md) — installation, CLI commands, configuration
- [Token Economics](docs/token-economics.md) — why hierarchical retrieval matters, real-world numbers

## Web UI

Ingestible includes a built-in web interface for browsing documents and searching:

```bash
ingest serve
```

## Why Not Just Use LlamaIndex / LangChain?

Ingestible is purpose-built for one thing: turning documents into the most token-efficient, highest-precision knowledge stores possible.

- **Hierarchical chunking** (L0-L3) preserves document structure. Most RAG tools flatten everything.
- **Three independent search indexes** fused with RRF. No single point of failure in retrieval.
- **LLM enrichment** generates 5-6 embeddings per passage (content + summary + hypothetical questions). One-time cost, permanent precision gain.
- **Zero cloud dependencies** for core pipeline. Embeddings run locally. LLM enrichment is optional.
- **Deterministic and repeatable.** Content-hash deduplication, async-safe, no side effects.

## License

[Apache 2.0](LICENSE)
