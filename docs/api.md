# REST API Reference

All endpoints are served by `ingest serve` (default: `http://localhost:8081`).

**Authentication:** when `INGEST_API_KEYS` is set, all requests require `Authorization: Bearer <key>`. Health, docs, and metrics endpoints are exempt.

**Rate limiting:** all endpoints are rate-limited. Defaults: ingestion 10/min, search 60/min, others 120/min. Returns `429 Too Many Requests` when exceeded. Configure via `INGEST_RATE_LIMIT_*` env vars.

**Upload limits:** file uploads are capped at 500 MB by default (`INGEST_MAX_UPLOAD_BYTES`). Returns `413` when exceeded.

**Document IDs:** all `{doc_id}` path parameters are validated to prevent path traversal. Only lowercase alphanumeric characters, hyphens, and underscores are allowed.

**Access control:** when `INGEST_ACCESS_CONTROL_ENABLED=true`, search endpoints filter results by the `X-Access-Tags` header (comma-separated tags). Documents tagged during ingestion are only returned to users with matching tags. Untagged documents are public.

**User identity:** extracted from `X-User-ID` header (if set by auth proxy), then bearer token prefix, then `anonymous`. Used for audit logging.

**Interactive docs:** FastAPI auto-generates OpenAPI docs at `/docs` (Swagger UI), `/redoc`, and `/openapi.json`.

---

## Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Ingest a file upload |
| `POST` | `/ingest/url` | Ingest from a URL |
| `POST` | `/ingest/batch` | Ingest multiple files |
| `POST` | `/ingest/stream` | Ingest with SSE progress streaming |
| `POST` | `/ingest/async` | Submit file for background ingestion (returns 202) |

### POST /ingest

Upload a document for ingestion. Supports 25+ file formats (PDF, DOCX, HTML, Markdown, audio, video, spreadsheets, etc.). Runs the full 6-stage pipeline: parse → structure → chunk → enrich → embed → store.

- **Content-Type:** `multipart/form-data`
- **Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | file | *(required)* | Document file to ingest |
| `skip_enrichment` | bool | `false` | Skip LLM enrichment (faster, but no summaries/concepts/questions) |
| `profile` | string | `"auto"` | Extraction profile: `auto`, `fast`, `accurate`, or `economy` |
| `access_tags` | string | `""` | Comma-separated access control tags |
| `weight` | float | `0.0` | Corpus search weight boost (0.0 = neutral) |
| `pinned` | bool | `false` | Pin document to always appear in corpus search results |
| `tags` | string | `""` | Comma-separated metadata tags for filtering |

- **Returns:** `IngestResponse`

```json
{
  "doc_id": "my-document",
  "title": "My Document Title",
  "total_pages": 42,
  "total_chunks": 156,
  "l0_tokens": 1200,
  "enriched": true
}
```

### POST /ingest/url

Ingest a document from a URL. Downloads the resource, detects content type, and runs the full pipeline.

- **Content-Type:** `application/json`
- **Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `url` | string | *(required)* | URL of the document to ingest |
| `skip_enrichment` | bool | `false` | Skip LLM enrichment |
| `profile` | string | `"auto"` | Extraction profile |

- **Returns:** `IngestResponse`

### POST /ingest/batch

Ingest multiple files in a single request. Each file is processed independently with error isolation — one failure does not abort the batch.

- **Content-Type:** `multipart/form-data`
- **Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `files` | file[] | *(required)* | One or more document files |
| `skip_enrichment` | bool | `false` | Skip LLM enrichment for all files |

- **Returns:** `BatchIngestResponse`

```json
{
  "total": 3,
  "succeeded": 2,
  "failed": 1,
  "elapsed_seconds": 45.2,
  "results": [
    { "filename": "doc1.pdf", "doc_id": "doc1", "error": null, "elapsed_seconds": 12.1 },
    { "filename": "doc2.pdf", "doc_id": "doc2", "error": null, "elapsed_seconds": 15.3 },
    { "filename": "bad.pdf", "doc_id": null, "error": "Parsing failed: corrupted PDF", "elapsed_seconds": 0.8 }
  ]
}
```

### POST /ingest/stream

Ingest a document with real-time Server-Sent Events progress streaming.

- **Content-Type:** `multipart/form-data`
- **Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | file | *(required)* | Document file to ingest |
| `skip_enrichment` | bool | `false` | Skip LLM enrichment |

- **Returns:** `text/event-stream` with JSON progress events

```
data: {"stage": "parsing", "step": 1, "total": 6}
data: {"stage": "structuring", "step": 2, "total": 6}
data: {"stage": "chunking", "step": 3, "total": 6}
data: {"stage": "enriching", "step": 4, "total": 6}
data: {"stage": "embedding", "step": 5, "total": 6}
data: {"stage": "storing", "step": 6, "total": 6}
data: {"status": "complete", "doc_id": "my-document"}
```

On error: `data: {"status": "error", "error": "..."}`

---

## Background Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest/async` | Submit file for background ingestion |
| `GET` | `/jobs/{job_id}` | Get job status and progress |
| `GET` | `/jobs` | List all ingestion jobs |

### POST /ingest/async

Submit a document for background ingestion. Returns immediately with a job ID.

- **Content-Type:** `multipart/form-data`
- **Form fields:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `file` | file | *(required)* | Document file to ingest |
| `skip_enrichment` | bool | `false` | Skip LLM enrichment |

- **Returns:** `202 Accepted`

```json
{
  "job_id": "a1b2c3d4",
  "status": "pending"
}
```

### GET /jobs/{job_id}

Poll for job status and progress.

- **Returns:** `JobDetailResponse`

```json
{
  "job_id": "a1b2c3d4",
  "status": "running",
  "doc_id": null,
  "error": null,
  "created_at": 1711500000.0,
  "started_at": 1711500001.0,
  "finished_at": null,
  "progress_stage": "enriching",
  "progress_step": 12,
  "progress_total": 45
}
```

- **Status values:** `pending`, `running`, `complete`, `failed`

### GET /jobs

List all background ingestion jobs (pending, running, complete, and failed).

- **Returns:** `JobDetailResponse[]`

---

## Documents

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/documents` | List all ingested documents |
| `GET` | `/documents/{doc_id}` | Get document overview (L0 + metadata) |
| `PATCH` | `/documents/{doc_id}/meta` | Update mutable metadata |
| `DELETE` | `/documents/{doc_id}` | Delete a document and its indexes |
| `GET` | `/documents/{doc_id}/chunks` | Get full ChunkSet (L0-L3) |
| `GET` | `/documents/{doc_id}/structure` | Get document structure tree |
| `GET` | `/documents/{doc_id}/economics` | Get token economics |
| `GET` | `/documents/{doc_id}/citations` | Get extracted citations |
| `GET` | `/documents/{doc_id}/knowledge-graph` | Get knowledge graph triples and entities |
| `GET` | `/documents/{doc_id}/versions` | List archived versions |
| `GET` | `/documents/{doc_id}/export` | Export document to portable format |
| `POST` | `/documents/{doc_id}/enrich` | Re-enrich without re-parsing |

### GET /documents

List all ingested documents with pagination and optional tag filtering.

- **Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `offset` | int | `0` | Pagination offset (0-based) |
| `limit` | int | `100` | Max documents to return (1-1000) |
| `tags` | string | `""` | Comma-separated metadata tags to filter by |

- **Returns:** `DocumentSummary[]`

```json
[
  {
    "doc_id": "my-document",
    "title": "My Document Title",
    "total_pages": 42,
    "ingestion_date": "2025-01-15T10:30:00"
  }
]
```

### GET /documents/{doc_id}

Get document overview including L0 content, chapter list, and token count.

- **Returns:** `DocumentOverview`

```json
{
  "doc_id": "my-document",
  "title": "My Document Title",
  "total_pages": 42,
  "ingestion_date": "2025-01-15T10:30:00",
  "l0_content": "My Document Title\nAuthor: Jane Doe\nDomain: Machine Learning\n...",
  "l0_tokens": 1200,
  "total_chunks": 156,
  "chapters": ["Introduction", "Methods", "Results", "Discussion"]
}
```

### PATCH /documents/{doc_id}/meta

Update mutable document metadata without re-ingesting. Only included fields are updated; omitted fields are left unchanged.

- **Content-Type:** `application/json`
- **Body:**

| Field | Type | Description |
|-------|------|-------------|
| `weight` | float \| null | Corpus search weight boost (0.0 = neutral) |
| `pinned` | bool \| null | Pin document in corpus search results |
| `tags` | string[] \| null | Replace metadata tags (pass `[]` to clear) |

- **Returns:**

```json
{
  "doc_id": "my-document",
  "weight": 1.5,
  "pinned": true,
  "tags": ["research", "ml"]
}
```

### DELETE /documents/{doc_id}

Delete a document and all its indexes, chunks, and embeddings. **This is irreversible.**

- **Returns:**

```json
{ "deleted": "my-document" }
```

### GET /documents/{doc_id}/chunks

Get the full ChunkSet (L0 through L3) for a document, including all enrichment data (summaries, concepts, hypothetical questions, knowledge graph triples).

- **Returns:** `ChunkSet` — the complete hierarchical chunk tree

### GET /documents/{doc_id}/structure

Get the hierarchical document structure tree (headings, sections, page ranges).

- **Returns:** `DocumentStructure`

### GET /documents/{doc_id}/economics

Get token economics: compares cost of placing the full document in an LLM context window vs. using hierarchical retrieval (L0 overview + top-k passages).

- **Returns:** `TokenEconomics`

```json
{
  "full_document_tokens": 85000,
  "l0_overview_tokens": 1200,
  "avg_query_tokens": 2400,
  "savings_percent": 97.2
}
```

### GET /documents/{doc_id}/citations

Get bibliographic citations extracted during parsing.

- **Returns:**

```json
{
  "doc_id": "my-document",
  "citations": [ ... ]
}
```

### GET /documents/{doc_id}/knowledge-graph

Get knowledge graph triples and entities extracted during enrichment. Requires KG extraction to have been enabled during ingestion. Entities are sorted by occurrence count.

- **Returns:**

```json
{
  "doc_id": "my-document",
  "total_triples": 45,
  "total_entities": 23,
  "triples": [
    { "subject": "GPT-4", "predicate": "outperforms", "object": "GPT-3.5", "subject_type": "Model", "object_type": "Model" }
  ],
  "entities": [
    { "name": "GPT-4", "type": "Model", "count": 12 }
  ]
}
```

### GET /documents/{doc_id}/versions

List all archived versions of a document. When a document is re-ingested, the previous version is archived.

- **Returns:**

```json
{
  "doc_id": "my-document",
  "versions": [ ... ]
}
```

### GET /documents/{doc_id}/export

Export a document's chunks to a portable format. Returns a file download.

- **Query params:**

| Param | Type | Description |
|-------|------|-------------|
| `format` | string | **Required.** One of: `jsonl`, `parquet`, `llamaindex`, `langchain`, `complete` |

- **Formats:**
  - `jsonl` — one chunk per line (NDJSON)
  - `parquet` — columnar format for data tools
  - `llamaindex` — LlamaIndex-compatible nodes JSON
  - `langchain` — LangChain-compatible documents JSON
  - `complete` — full ChunkSet JSON with all metadata

- **Returns:** file download with appropriate content type

### POST /documents/{doc_id}/enrich

Re-enrich a document without re-parsing. Re-runs LLM enrichment (stage 4) and embedding (stage 5) on existing chunks. Useful after changing LLM provider or enrichment settings.

- **Returns:** `IngestResponse`

---

## Search

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/documents/{doc_id}/search` | Hybrid search within a document |
| `POST` | `/search` | Search across all documents |

### POST /documents/{doc_id}/search

Hybrid search within a single document. Fuses vector search (ChromaDB, weight 0.4), BM25 (weight 0.6), and concept index using Reciprocal Rank Fusion.

- **Content-Type:** `application/json`
- **Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *(required)* | Natural language search query |
| `n_results` | int | `5` | Number of results to return (1-20) |
| `hyde` | bool | `false` | Use HyDE query expansion — generates a hypothetical answer passage via LLM for better vector matching |
| `auto_merge` | bool | `false` | Auto-merge L3 results into parent L2/L1 when 3+ passages from the same section match |
| `kg_boost` | bool | `false` | Boost results using knowledge graph entity relationships |

- **Headers:** `X-Access-Tags` (optional, comma-separated) for access control filtering
- **Returns:** `SearchResponse` with ranked results including scores, match sources, content/summaries, page numbers, and timestamps (for audio/video)

### POST /search

Search across all ingested documents. Merges per-document hybrid search results using cross-document Reciprocal Rank Fusion.

- **Content-Type:** `application/json`
- **Body:**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `query` | string | *(required)* | Natural language search query |
| `n_results` | int | `10` | Number of results to return (1-50) |
| `doc_ids` | string[] \| null | `null` | Restrict search to these document IDs (null = all) |
| `tags` | string[] \| null | `null` | Only search documents with these metadata tags |
| `hyde` | bool | `false` | Use HyDE query expansion |
| `auto_merge` | bool | `false` | Auto-merge L3 results into parent L2/L1 |
| `kg_boost` | bool | `false` | Boost results using knowledge graph relationships |

- **Headers:** `X-Access-Tags` (optional) for access control filtering
- **Returns:** `SearchResponse` with cross-document RRF fusion

---

## Evaluation

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/documents/{doc_id}/eval` | Metric-based retrieval evaluation |
| `POST` | `/documents/{doc_id}/eval/judge` | LLM-as-judge retrieval evaluation |

### POST /documents/{doc_id}/eval

Evaluate retrieval quality using synthetic queries generated during enrichment. Returns standard IR metrics.

- **Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `k` | int | `5` | Number of results to retrieve per query (1-50) |

- **Returns:**

```json
{
  "doc_id": "my-document",
  "total_queries": 30,
  "k": 5,
  "hit_rate": 0.93,
  "mrr": 0.87,
  "mean_precision_at_k": 0.76,
  "mean_recall_at_k": 0.82
}
```

### POST /documents/{doc_id}/eval/judge

Evaluate retrieval quality using LLM-as-judge scoring. More accurate than metric-based eval but slower and requires LLM API credits.

- **Query params:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `k` | int | `5` | Number of results to retrieve per query (1-50) |

- **Returns:** Faithfulness, relevance, and completeness scores (0-1 scale) assessed by the configured LLM provider.

---

## Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/cv` | Receive CognitiveVault entry updates |

### POST /webhooks/cv

Receives `entry.updated` events from CognitiveVault. When a CV entry with an `ingest:` sourcePath is edited, this endpoint updates the local chunk content and triggers selective re-enrichment.

- **Requires:** `INGEST_WEBHOOK_SECRET` env var for HMAC-SHA256 signature verification
- **Headers:** `X-Webhook-Signature` — HMAC-SHA256 hex digest of the request body
- **Body:** JSON envelope with `event` and `payload` fields

```json
{
  "event": "entry.updated",
  "payload": {
    "entryId": "...",
    "sourcePath": "ingest:my-document/chunk-abc123",
    "content": "Updated chunk content...",
    "checksum": "sha256hex..."
  }
}
```

- **Returns:**

```json
{
  "status": "ok",
  "doc_id": "my-document",
  "chunk_id": "chunk-abc123",
  "re_enriched": true
}
```

---

## Health & Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check (fast, no deps) |
| `GET` | `/health/ready` | Readiness check (verifies all dependencies) |
| `GET` | `/metrics` | Prometheus metrics |

### GET /health

Fast liveness probe. Returns immediately without checking dependencies.

```json
{ "status": "ok", "documents_count": 12 }
```

### GET /health/ready

Deep readiness check. Verifies data directory is writable, disk space above threshold, embedding model loads, and LLM API is configured.

- **Returns:**

```json
{
  "status": "ready",
  "checks": {
    "data_dir": { "status": "ok", "path": "/app/data" },
    "disk_space": { "status": "ok", "free_mb": 4500 },
    "embedding_model": { "status": "ok", "model": "intfloat/e5-large-v2" },
    "llm_api": { "status": "ok", "provider": "anthropic" },
    "documents": { "status": "ok", "count": 12 }
  }
}
```

- Overall status is `"ready"` when all checks pass, `"degraded"` when any check fails.
- Individual check statuses: `ok`, `warning`, or `error`.

### GET /metrics

Prometheus-format metrics endpoint. Key metrics:

| Metric | Type | Description |
|--------|------|-------------|
| `ingestible_ingest_duration_seconds` | histogram | Ingestion latency by stage |
| `ingestible_active_ingestions` | gauge | Currently running ingestion jobs |
| `ingestible_llm_calls_total` | counter | LLM API calls by provider and status |
| `ingestible_search_duration_seconds` | histogram | Search query latency |

---

## Error Responses

All endpoints return errors as JSON:

```json
{
  "detail": "Human-readable error message"
}
```

| Status | Meaning |
|--------|---------|
| `400` | Bad request (invalid doc ID, unknown format, malformed JSON) |
| `401` | Missing or invalid API key / webhook signature |
| `404` | Document or job not found |
| `413` | File too large (exceeds `INGEST_MAX_UPLOAD_BYTES`) |
| `429` | Rate limit exceeded |
| `500` | Internal server error |
