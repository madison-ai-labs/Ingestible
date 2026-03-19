# CV Integration Plan — Ingestible Side

## Context

CognitiveVault needs a document ingestion pipeline. Ingestible already has the right architecture (L0–L3 chunking, RRF hybrid search, LLM enrichment). Instead of rebuilding, we evolve Ingestible to serve as CV's ingestor by swapping storage/inference layers and adding a CV integration mode.

The CV-side plan lives at `~/Work/Projects/CognitiveVault/docs/plans/ingestor.md`.

## Current Stack

```
Parsing:      Docling + PyMuPDF4LLM
Chunking:     L0–L3 hierarchy (heading-based)
Enrichment:   OpenAI (default) / Anthropic (system prompt hack for JSON)
Embeddings:   sentence-transformers E5-large-v2 (local, CPU/MPS)
Vector store: ChromaDB (local, per-document collection)
BM25:         rank-bm25 (in-memory, serialized to pickle)
Reranking:    cross-encoder (local, optional)
Storage:      Local filesystem (JSON + pickle + ChromaDB dirs)
API:          FastAPI (browse + search UI)
```

## Target Stack

```
Parsing:      marker (PDF) + Docling fallback (DOCX/HTML) + PyMuPDF4LLM (OCR fallback)
Chunking:     L0–L3 hierarchy (kept) + domain-specific strategies (new)
Enrichment:   Claude API via tool_use (structured output, replaces prompt hack)
Embeddings:   Voyage AI API (production) / local E5-large-v2 (dev/offline)
Vector store: PostgreSQL pgvector (CV's Supabase DB) / ChromaDB (standalone mode)
BM25:         PostgreSQL tsvector (CV mode) / rank-bm25 (standalone mode)
Reranking:    Cohere Rerank API (production) / local cross-encoder (dev)
Storage:      PostgreSQL direct (CV mode) / local filesystem (standalone mode)
Queue:        pg-boss (CV mode) / synchronous (standalone mode)
API:          FastAPI (kept, extended with /ingest webhook endpoint)
```

**Key principle**: Ingestible keeps working as a standalone tool. CV integration is an additional storage/search backend, not a replacement.

---

## Library Swaps

### 1. PDF Parsing: Docling → marker (primary)

**Why**: marker is purpose-built for PDF→Markdown for LLM consumption. Better layout analysis, table detection, and heading extraction than Docling for this specific use case.

**Change**: Replace `stage1_parsing.py`'s Docling PDF path with marker. Keep Docling as fallback for DOCX/HTML (marker doesn't handle those).

```python
# Before
from docling.document_converter import DocumentConverter

# After
import marker
from docling.document_converter import DocumentConverter  # fallback for DOCX/HTML
```

**Risk**: marker is single-maintainer (VikParuchuri). Docling is IBM-backed. Keep Docling as a fallback, test both paths, switch if marker quality regresses.

### 2. Enrichment: OpenAI structured output / Anthropic prompt hack → Claude tool_use

**Why**: The current `AnthropicClient` uses a system prompt asking for JSON, which can fail. Claude's `tool_use` with a JSON schema gives native structured output enforcement — no parsing failures.

**Change**: Rewrite `stage4_enrichment.py`'s `AnthropicClient`:

```python
class AnthropicClient:
    async def generate_json(self, prompt: str, output_type: type[T]) -> T:
        schema = output_type.model_json_schema()
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
            tools=[{
                "name": "output",
                "description": "Structured output",
                "input_schema": schema,
            }],
            tool_choice={"type": "tool", "name": "output"},
        )
        tool_block = next(b for b in response.content if b.type == "tool_use")
        return output_type.model_validate(tool_block.input)
```

Make Claude the default provider. Keep OpenAI as alternative.

### 3. Embeddings: local E5-large-v2 → Voyage AI API (production)

**Why**: E5-large-v2 needs ~1.3GB RAM and CPU/MPS time. Voyage `voyage-3` beats it on retrieval benchmarks (especially `voyage-code-3` for code). At CV's scale, API cost is negligible (~$0.02/1M tokens).

**Change**: Add a `VoyageEmbedder` alongside the existing `Embedder` in `stage5_embedding.py`:

```python
class VoyageEmbedder:
    def __init__(self, api_key: str, model: str = "voyage-3"):
        import voyageai
        self._client = voyageai.Client(api_key=api_key)
        self._model = model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        result = self._client.embed(texts, model=self._model)
        return result.embeddings

    def embed_query(self, query: str) -> list[float]:
        result = self._client.embed([query], model=self._model, input_type="query")
        return result.embeddings[0]
```

Selection via config: `INGEST_EMBEDDING_PROVIDER=voyage|local`. Default: `voyage` when API key is set, `local` otherwise.

### 4. Vector Store: ChromaDB → pgvector (CV mode)

**Why**: CV uses PostgreSQL (Supabase). Storing embeddings in ChromaDB means a second data store that CV can't query. pgvector puts everything in one database.

**Change**: Add `search/pgvector_store.py` alongside existing `search/vector_store.py`:

```python
class PgVectorStore:
    def __init__(self, dsn: str):
        import asyncpg
        self._dsn = dsn

    async def upsert(self, entry_id: str, embedding: list[float], model: str):
        conn = await asyncpg.connect(self._dsn)
        await conn.execute("""
            INSERT INTO entry_embeddings (id, entry_id, embedding_vec, model, updated_at)
            VALUES (gen_random_uuid(), $1, $2::vector, $3, NOW())
            ON CONFLICT (entry_id) DO UPDATE
            SET embedding_vec = EXCLUDED.embedding_vec, model = EXCLUDED.model, updated_at = NOW()
        """, entry_id, embedding, model)

    async def query(self, embedding: list[float], vault_id: str, n: int = 10):
        conn = await asyncpg.connect(self._dsn)
        return await conn.fetch("""
            SELECT ve.id, ee.embedding_vec <=> $1::vector AS distance
            FROM vault_entries ve
            JOIN entry_embeddings ee ON ee.entry_id = ve.id
            WHERE ve.vault_id = $2
            ORDER BY distance
            LIMIT $3
        """, embedding, vault_id, n)
```

ChromaDB stays as the default for standalone mode. pgvector activates when `INGEST_STORAGE=pgvector` + `DATABASE_URL` is set.

### 5. BM25: rank-bm25 → PostgreSQL tsvector (CV mode)

**Why**: rank-bm25 builds an in-memory index serialized to pickle. PostgreSQL tsvector is built-in, GIN-indexed, supports language-aware tokenization, and doesn't need a separate file.

**Change**: In CV mode, skip `bm25_store.py` entirely. The tsvector column on `vault_entries` is maintained by a PostgreSQL trigger — the ingestor doesn't need to manage it. Search queries use `ts_rank_cd` directly.

rank-bm25 stays for standalone mode.

### 6. Reranking: local cross-encoder → Cohere Rerank API (production)

**Why**: Local cross-encoder needs model loading (slow cold start) and MPS/GPU. Cohere Rerank API is fast, no model management, better models.

**Change**: Add API-based reranker in `search/hybrid.py`:

```python
class CohereReranker:
    def __init__(self, api_key: str, model: str = "rerank-v3.5"):
        import cohere
        self._client = cohere.Client(api_key=api_key)
        self._model = model

    def rerank(self, query: str, documents: list[str], top_n: int = 10):
        result = self._client.rerank(query=query, documents=documents, model=self._model, top_n=top_n)
        return [(r.index, r.relevance_score) for r in result.results]
```

Selection: `INGEST_RERANKER=cohere|local|none`. Default: `cohere` when API key is set, `local` if sentence-transformers available, `none` otherwise.

### 7. Queue: synchronous → pg-boss (CV mode)

**Why**: Synchronous `asyncio.run()` blocks on each document. For CV, ingestion is triggered by webhooks and needs retry logic, concurrency limits, and job status tracking.

**Change**: Add `queue/pgboss.py`:

```python
class PgBossQueue:
    """Job queue using pg-boss (PostgreSQL-native)."""

    async def submit(self, entry_id: str, vault_id: str, content: str, domain_profile: str):
        # Insert job into pgboss queue table
        ...

    async def process(self, handler):
        # Poll and process jobs with concurrency limit
        ...
```

Standalone mode keeps synchronous pipeline. CV mode uses pg-boss.

---

## New Features

### Domain-Specific Chunking

CV vaults have `domainProfile` (CODE, RESEARCH, LEGAL, DOCUMENTATION, NARRATIVE, POETRY, GENERAL). The ingestor should chunk differently per domain.

Add to `stage3_chunking.py`:

| Domain | Strategy |
|--------|----------|
| CODE | Split by function/class boundaries (tree-sitter), not headings |
| LEGAL | Split by clause/section numbers, preserve cross-references |
| RESEARCH | Split by methodology sections (Abstract, Methods, Results, Discussion) |
| DOCUMENTATION | Current heading-based strategy (default) |
| NARRATIVE/POETRY | Split by scene/stanza, preserve paragraph flow |
| GENERAL | Current heading-based strategy |

Implementation: `domainProfile` comes in the webhook payload. The orchestrator selects the chunking strategy based on it.

### Multi-Vault Storage

Add `vault_id` as a required parameter in CV mode. All chunks and embeddings are scoped to a vault.

```python
class CVStorageBackend:
    async def store_chunks(self, chunks: ChunkSet, vault_id: str, source_entry_id: str):
        """Write L1-L3 chunks as child VaultEntries in CV's database."""
        async with asyncpg.connect(self._dsn) as conn:
            for chunk in chunks.l3_chunks:
                await conn.execute("""
                    INSERT INTO vault_entries (id, vault_id, parent_id, title, content,
                      entry_type, chunk_level, chunk_order, source, tags)
                    VALUES ($1, $2, $3, $4, $5, 'DOCUMENT', 3, $6, 'INGESTOR', $7)
                """, ...)
```

### Incremental Re-ingestion

Currently, `_check_existing()` compares content hashes at the document level. For CV, we need chunk-level diffing:

1. Hash each L1/L2/L3 chunk's content
2. On re-ingestion, compare chunk hashes against existing chunks in the DB
3. Only re-embed and re-enrich chunks that changed
4. Update parent summaries (L2→L1→L0) bottom-up for changed branches only

### Provenance

Track what produced each enrichment:

```python
@dataclass
class EnrichmentProvenance:
    model: str           # "claude-sonnet-4-6"
    prompt_version: str  # hash of the prompt template
    timestamp: datetime
    source_hash: str     # SHA-256 of the input content
```

Store in `EntryMetrics` alongside the enrichment data. Enables re-enrichment with a newer model without re-parsing.

---

## CV Webhook Endpoint

Add `POST /ingest` to the FastAPI app:

```python
@app.post("/ingest")
async def ingest_from_cv(request: IngestRequest, api_key: str = Depends(verify_api_key)):
    """Webhook receiver — CV calls this when an entry is created/updated."""
    job_id = await queue.submit(
        entry_id=request.entry_id,
        vault_id=request.vault_id,
        content=request.content,
        title=request.title,
        domain_profile=request.domain_profile,
    )
    return {"job_id": job_id, "status": "queued"}

@app.get("/jobs/{job_id}")
async def job_status(job_id: str):
    return await queue.get_status(job_id)
```

---

## Dual-Mode Architecture

Ingestible must keep working standalone. CV integration is additive.

```
┌─────────────────────────────────────────────────┐
│                  Ingestible                   │
│                                                  │
│  Pipeline (always the same):                     │
│    Parse → Structure → Chunk → Validate →        │
│    Enrich → Embed → Store                        │
│                                                  │
│  ┌──────────────┐    ┌──────────────────────┐   │
│  │ Standalone    │    │ CV Mode              │   │
│  │               │    │                      │   │
│  │ ChromaDB      │    │ pgvector             │   │
│  │ rank-bm25     │    │ tsvector             │   │
│  │ local E5      │    │ Voyage API           │   │
│  │ local reranker│    │ Cohere Rerank API    │   │
│  │ filesystem    │    │ PostgreSQL direct     │   │
│  │ sync pipeline │    │ pg-boss queue         │   │
│  │               │    │ webhook receiver      │   │
│  └──────────────┘    └──────────────────────┘   │
│                                                  │
│  Mode selected by: INGEST_MODE=standalone|cv     │
└─────────────────────────────────────────────────┘
```

---

## Config Changes

New env vars (all optional, standalone mode uses existing defaults):

```bash
# Mode
INGEST_MODE=standalone              # or "cv"

# CV mode settings
DATABASE_URL=postgresql://...       # CV's Supabase pooler
INGEST_CV_API_KEY=cvk_...          # for writing back to CV API (if needed)
INGEST_WEBHOOK_SECRET=...          # verify incoming webhooks from CV

# Embedding provider
INGEST_EMBEDDING_PROVIDER=voyage    # or "local" (default when no API key)
INGEST_VOYAGE_API_KEY=...
INGEST_VOYAGE_MODEL=voyage-3

# Enrichment (Claude becomes default)
INGEST_LLM_PROVIDER=anthropic      # or "openai"
INGEST_ANTHROPIC_API_KEY=...
INGEST_ANTHROPIC_MODEL=claude-sonnet-4-6

# Reranking
INGEST_RERANKER=cohere              # or "local" or "none"
INGEST_COHERE_API_KEY=...

# Parsing
INGEST_PDF_PARSER=marker            # or "docling"
```

---

## CV Export Adapter (Implemented)

The first integration path is now live: an API-based adapter that exports
ChunkSets to CognitiveVault's bulk entries endpoint. This is the simpler
alternative to direct DB writes — no asyncpg, no shared database credentials.

### How it works

```
Ingestible                          CognitiveVault
─────────────                          ───────────────
ingest file.pdf
  → Parse → Structure → Chunk
  → Enrich → Embed → Store (local)

ingest export-cv                       POST /api/v1/vaults/:id/entries/bulk
  → Load ChunkSet from disk            ← Receives entries with:
  → Transform L0-L3 → CV entries          chunkLevel (0-3)
  → POST to CV bulk API                   chunkOrder
                                          parentSourcePath (for hierarchy)
                                          checksum (for upsert)
                                       → Creates parent → child entries
                                       → Embeds via Voyage AI
                                       → Indexes with pgvector + tsvector
```

### Hierarchy mapping

Each chunk gets a deterministic `sourcePath` like `ingest:{doc_id}/{chunk_id}`.
Parent-child relationships use `parentSourcePath` — CV's bulk endpoint resolves
these to internal entry IDs. Entries are sorted by `chunkLevel` (0→3) in the
payload so parents are always created before children.

| Ingestible | CV VaultEntry |
|---------------|---------------|
| L0 (document) | chunkLevel=0, no parent |
| L1 (chapter)  | chunkLevel=1, parent=L0 |
| L2 (section)  | chunkLevel=2, parent=L1 |
| L3 (passage)  | chunkLevel=3, parent=L2 |

Enrichment fields from Stage 4 map to CV's `EntryMetrics`:

| Ingestible L3 field | CV EntryMetrics field |
|------------------------|----------------------|
| summary | summary |
| hypothetical_questions | hypotheticalQuestions |
| concepts + keywords | conceptTags |

### CLI usage

```bash
# Export a specific document
ingest export-cv my-doc-id --cv-url https://cv.example.com \
  --cv-api-key cvk_... --cv-vault-id vault-abc

# Export all ingested documents
ingest export-cv --cv-url https://cv.example.com \
  --cv-api-key cvk_... --cv-vault-id vault-abc

# Or use environment variables
export CV_URL=https://cv.example.com
export CV_API_KEY=cvk_...
export CV_VAULT_ID=vault-abc
ingest export-cv
```

### Programmatic usage

```python
from ingestible.adapters.cv_export import CVConfig, export_to_cv
from ingestible.pipeline.stage6_storage import load_chunks

config = CVConfig(
    base_url="https://cv.example.com",
    api_key="cvk_...",
    vault_id="vault-abc",
)

chunks = load_chunks(doc_dir)
result = export_to_cv(chunks, config)
print(f"Created: {result.created}, Updated: {result.updated}")
```

### Re-sync behavior

The adapter uses `sourcePath` + `checksum` for upsert semantics:

- **New chunks**: created in CV
- **Changed chunks**: content updated, re-embedded by CV
- **Unchanged chunks**: skipped (checksum match)
- **Removed chunks**: optionally deleted with `--delete-removed`

This means re-running `ingest export-cv` after re-ingesting a document is
safe and incremental — only changed chunks are updated.

### CV-side requirements

The adapter depends on these CognitiveVault features (all implemented):

| CV component | What it does | Status |
|---|---|---|
| Bulk endpoint chunk fields | Accepts `chunkLevel`, `chunkOrder`, `parentSourcePath`, `language` | Done (`ae851f4`) |
| Parent resolution in bulk | Sorts by chunkLevel, maps `parentSourcePath` → internal IDs | Done (`ae851f4`) |
| Post-bulk embedding | Calls `embedEntry()` for each created/updated entry | Done |
| Post-bulk metrics | Calls `recomputeEntryMetrics()` for each touched entry | Done |
| Enrichment passthrough | Writes `enrichment.summary`, `hypotheticalQuestions`, `conceptTags` to EntryMetrics | Done |
| Schema: VaultEntry chunk fields | `parentId`, `chunkLevel`, `chunkOrder`, `language` | Done (`1e38485`) |
| Schema: EntryMetrics enrichment | `summary`, `hypotheticalQuestions`, `conceptTags` | Done (`1e38485`) |
| Default chunkLevel filter | `GET /entries` excludes chunked entries by default | Done (`1e38485`) |
| Chunks endpoint | `GET /entries/:id/chunks` returns chunk tree via recursive CTE | Done (`1e38485`) |

### Adapter scope — this is CV-specific, not generic

The adapter (`cv_export.py`) is purpose-built for CognitiveVault's bulk API
contract. It is **not** a generic "export ChunkSet to any system" abstraction.

The generic part is `chunkset_to_entries()` — the pure transformation from
ChunkSet to a list of flat dicts with `sourcePath`, `parentSourcePath`,
`chunkLevel`, `chunkOrder`, and `enrichment`. Any system that accepts entries
with those fields could reuse the transformation logic.

The CV-specific parts are:
- HTTP transport (`export_to_cv`) targeting CV's `/entries/bulk` endpoint
- Auth header format (`Bearer` token)
- Response shape (`{created, updated, unchanged, deleted}`)
- `sourcePath` prefix convention (`ingest:{doc_id}/{chunk_id}`)

To add a different export target (e.g., Qdrant, Pinecone, Notion), create a
new adapter in `adapters/` that imports `chunkset_to_entries()` and handles
its own transport. Do not generalize `cv_export.py` — keep adapters simple
and single-purpose.

### When to use direct DB writes instead

The API-based adapter is right for:
- Low-to-medium volume (hundreds of documents)
- Standard deployment (Ingestible and CV on separate infrastructure)
- No shared database credentials needed

For high-volume production (thousands of documents, continuous ingestion),
the direct DB write path described in Phase 2 of CV's ingestor plan is
more efficient. That path uses asyncpg to batch-insert directly into CV's
PostgreSQL, skipping HTTP overhead.

---

## Selective Re-enrichment (Implemented)

When re-ingesting a document with `--force`, unchanged chunks skip LLM
enrichment entirely. The hash-based skip that already existed at Stage 5
(embedding) now extends to Stage 4 (enrichment).

### How it works

`enrich_chunks()` accepts an optional `previous_chunks` parameter. When
provided, it builds a lookup of previous L3 chunks by `content_hash`. For
each current L3 chunk with a matching hash, enrichment fields (summary,
concepts, questions, etc.) are copied from the previous version instead of
calling the LLM.

When **all** L3 chunks are unchanged, L2/L1/L0 enrichment is also skipped
(their results would be identical since they aggregate from children).

The orchestrator passes `previous_chunks` automatically during `--force`
re-ingestion — no user action needed.

### Targeted re-enrichment

`re_enrich()` accepts an optional `changed_chunk_ids` parameter. When
provided, only those specific L3 chunks are re-enriched. This is used by
the webhook handler to selectively re-enrich chunks edited in CV's web UI.

---

## Sync Loop / Watch (Implemented)

`ingest watch <dir>` monitors a directory for file changes and auto-ingests.

### Architecture

```
┌─────────────────────────────────────────┐
│  FileWatcher                            │
│                                         │
│  watchdog.Observer (OS-native events)   │
│        │                                │
│        ▼                                │
│  Debounce (2s, directory-level)         │
│  Collects changed files into batch      │
│        │                                │
│        ▼                                │
│  For each file: ingest(force=True)      │
│  (dedup via content_hash)               │
│        │                                │
│        ▼ (if --cv-push)                 │
│  export_to_cv() — single bulk call      │
│  for entire batch                       │
└─────────────────────────────────────────┘
```

- **Debounce**: 2-second window at directory level. Rapid writes (git
  checkout, editor batch-saves) are collected and processed as one batch.
- **File filter**: Only supported formats (pdf, md, txt, html, docx, etc.)
- **CV push**: Optional `--cv-push` flag triggers `export_to_cv()` after
  the entire batch completes (single bulk call, not per-file).
- **Enrichment skip**: Benefits from selective re-enrichment — unchanged
  chunks skip LLM calls automatically.

### Installation

```bash
pip install -e ".[watch]"  # adds watchdog dependency
```

---

## Webhook: CV → Ingestible (Implemented)

When entries are edited in CV's web UI, a webhook notifies Ingestible to
update the local chunk and re-enrich.

### Ingestible side

`POST /webhooks/cv` endpoint in `api.py`:

1. Verifies HMAC-SHA256 signature (shared secret via `INGEST_WEBHOOK_SECRET`)
2. Parses `sourcePath` → extracts `doc_id` + `chunk_id`
3. Updates the chunk's content on disk
4. Stores the CV checksum in `meta.json` (`cv_checksums` dict)
5. Triggers selective re-enrichment for just that chunk

### Conflict resolution (last-writer-wins guard)

When the watcher or `export-cv` pushes a document to CV, each chunk's
`cv_checksum` (stored in `meta.json`) tracks what CV last reported. If a
chunk was edited in CV (checksum differs from what Ingestible last pushed),
the push should skip that chunk to avoid reverting manual CV edits.

To overwrite CV's edit, re-ingest the source file with `--force`.

### Configuration

```bash
INGEST_WEBHOOK_SECRET=your-shared-secret  # required for webhook verification
```

### CognitiveVault side (not in this repo)

CV needs to emit webhooks on entry PATCH:

- `apps/web/src/lib/webhooks.ts` — `fireWebhook(event, payload)` utility
  with HMAC-SHA256 signing
- Route handler: after PATCH succeeds on an `ingest:`-sourced entry, call
  `fireWebhook("entry.updated", { entryId, sourcePath, content, checksum })`

---

## Implementation Order

### Step 1 — Library swaps (no CV integration yet)

These improve Ingestible standalone, independent of CV:

1. **marker for PDF parsing** — swap in `stage1_parsing.py`, keep Docling for DOCX/HTML
2. **Claude tool_use for enrichment** — rewrite `AnthropicClient` in `stage4_enrichment.py`, make it default
3. **Voyage API embedder** — add `VoyageEmbedder` in `stage5_embedding.py`, select via config
4. **Cohere reranker** — add `CohereReranker` in `search/hybrid.py`, select via config

Each is an independent PR. Ingestible stays standalone, just with better libraries.

### Step 2 — pgvector storage backend

1. Add `search/pgvector_store.py` — vector upsert/query against PostgreSQL
2. Add `pipeline/stage6_pgvector.py` — write chunks + embeddings to CV's schema
3. Add `INGEST_MODE=cv` config path in orchestrator
4. Test against a local PostgreSQL with pgvector extension

### Step 3 — CV webhook integration

1. Add `POST /ingest` endpoint to FastAPI app
2. Add pg-boss queue (or simple `asyncio.Queue` for v1)
3. Add job status tracking
4. Dockerfile for containerized deployment

### Step 4 — Domain-specific chunking + incremental

1. Add domain-aware chunking strategies in `stage3_chunking.py`
2. Add chunk-level content hashing for incremental re-ingestion
3. Add provenance tracking to enrichment output

---

## Deployment

```
Docker container (Fly.io / Railway)
├── FastAPI on port 8000
├── pg-boss worker (same process, background task)
├── /health endpoint
├── /ingest webhook endpoint
└── Connects to CV's Supabase PostgreSQL
```

No local model loading in production — all inference is API-based (Voyage, Claude, Cohere). Container stays small and cold-starts fast.

Local dev: `INGEST_MODE=standalone` uses local models, ChromaDB, filesystem storage. Same `ingest` CLI as today.

---

## Dependencies Changes

```toml
# Remove (CV mode doesn't need these at runtime)
# chromadb — still optional for standalone mode
# rank-bm25 — still optional for standalone mode
# sentence-transformers — still optional for local embeddings

# Add
voyageai = ">=0.3"           # API embeddings
cohere = ">=5.0"             # API reranking
asyncpg = ">=0.29"           # PostgreSQL async driver (CV mode)
marker-pdf = ">=1.0"         # PDF parsing (replaces Docling for PDFs)
# pg-boss has no Python client — use raw SQL or pgqueuer

# Keep
anthropic = ">=0.40"         # enrichment (now default)
openai = ">=1.0"             # enrichment (alternative)
docling = ">=2.0"            # DOCX/HTML parsing (PDF fallback)
fastapi = ">=0.115"          # API
pydantic = ">=2.0"           # models
```

Make heavy deps optional:
```toml
[project.optional-dependencies]
standalone = ["chromadb>=0.5", "rank-bm25>=0.2", "sentence-transformers>=3.0"]
cv = ["asyncpg>=0.29", "voyageai>=0.3", "cohere>=5.0"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23"]
```
