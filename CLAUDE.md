# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run Commands

```bash
# Install (requires Python 3.11-3.12, ChromaDB breaks on 3.14)
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest                              # all tests
pytest tests/test_batch.py          # single file
pytest tests/test_batch.py::test_discover_directory_recursive  # single test
pytest -x -q                        # stop on first failure, quiet

# Lint (CI runs both)
ruff check src/ tests/
ruff format --check src/ tests/

# Auto-fix
ruff check --fix src/ tests/
ruff format src/ tests/

# Run API server
ingest serve                        # dev (uvicorn)
gunicorn ingestible.api:app -c gunicorn.conf.py  # prod

# CLI
ingest ingest /path/to/doc.pdf -v
ingest list
ingest search <doc_id> "query"
ingest eval <doc_id>                # retrieval quality evaluation
ingest mcp                          # MCP server for AI agents
```

Use `.venv/bin/python` to run Python — no system `python` available.

## Architecture

Ingestible is a document ingestion pipeline that transforms documents into a queryable knowledge store with hierarchical chunks and hybrid search.

### Pipeline Flow

```
Document → Stage 1 (Parse) → 1b (Clean) → [1c Classify] → 2 (Structure)
→ 3 (Chunk) → 3b (Validate) → [3c Contextual] → [4 Enrich] → 5 (Embed) → 6 (Store)
```

Stages in brackets are optional. The orchestrator (`pipeline/orchestrator.py`) runs all stages in sequence under a document lock, with checkpoint/resume between stages.

### Key Data Flow

1. **Parse** (`stage1_parsing.py`) — 25+ format-specific parsers all produce `ParsedDocument` (list of `PageContent` with markdown)
2. **Structure** (`stage2_structure.py`) — builds `DocumentStructure` tree from headings/TOC/page heuristics
3. **Chunk** (`stage3_chunking.py`) — produces `ChunkSet` with 4-level hierarchy: L0 (document) → L1 (chapter) → L2 (section) → L3 (passage). Four strategies: paragraph, semantic, recursive, docling.
4. **Enrich** (`stage4_enrichment.py`) — async LLM calls (Anthropic/OpenAI) with retry+backoff. Bottom-up: L3→L2→L1→L0. Adds summaries, concepts, hypothetical questions, KG triples.
5. **Embed** (`stage5_embedding.py`) — E5-large-v2 via sentence-transformers. Builds ChromaDB vector index + BM25 + concept index. Multiple embeddings per chunk (content, summary, questions).
6. **Store** (`stage6_storage.py`) — JSON file hierarchy under `data/documents/{doc_id}/`

### Search

`search/hybrid.py` fuses three indexes with Reciprocal Rank Fusion (RRF):
- Vector (ChromaDB, weight 0.7) + BM25 (rank-bm25, weight 0.3) + concept boost
- Optional cross-encoder reranking
- Version-aware: superseded chunks get 0.3x weight
- Corpus search (`search/corpus.py`) merges results across documents

### Three Entry Points

- **CLI** (`cli.py`) — argparse, all commands
- **API** (`api.py`) — FastAPI with auth middleware, rate limiting, Prometheus metrics
- **MCP** (`mcp_server.py`) — Model Context Protocol server for AI agents

### Content-Tier Classification (VBC)

When `INGEST_CONTENT_CLASSIFICATION=true`, Stage 1c (`stage1c_classify.py`) labels blocks as T0 (verbatim: code/formulas), T1 (structural: tables/JSON), T2 (extractive: dense prose), T3 (compressible: narrative). Tiers affect chunking (T0/T1 = atomic) and enrichment (T0/T1 skip LLM, get heuristic keywords only).

### Concurrency Model

- API ingestion runs in a `ThreadPoolExecutor` background task queue (`pipeline/task_queue.py`)
- LLM calls use async + `Semaphore(N)` for concurrency control
- Document writes protected by `portalocker` file locks (`pipeline/locking.py`)
- Batch processing uses `ProcessPoolExecutor` with per-worker LLM concurrency caps

### Configuration

`config.py` uses pydantic-settings. Priority: init kwargs > env vars (`INGEST_*` prefix) > `.env` file > `ingestible.toml` > defaults. All settings are in the `Settings` class.

## Conventions

- Commit messages: NEVER include co-authored-by, Claude, or the user's name
- License: PolyForm Small Business 1.0.0 (not Apache — `pyproject.toml` reflects this)
- All new `{doc_id}` API endpoints must call `_validate_doc_id(doc_id)` as the first line
- LLM client calls must use `retry_llm_call()` from `utils/retry.py`
- Embedding device must use `_resolve_device()` — never hardcode `"mps"` or `"cuda"`
- Schema changes require bumping `schema_version` in `stage6_storage.py`
- `asyncio_mode = "auto"` in pytest — async test functions work without markers
