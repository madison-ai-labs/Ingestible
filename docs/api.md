# REST API Reference

All endpoints are served by `ingest serve` (default: `http://localhost:8081`).

Authentication: when `INGEST_API_KEYS` is set, all requests require `Authorization: Bearer <key>`.

Rate limiting: all endpoints are rate-limited. Defaults: ingestion 10/min, search 60/min, others 120/min. Returns `429 Too Many Requests` when exceeded. Configure via `INGEST_RATE_LIMIT_*` env vars.

Upload limits: file uploads are capped at 500 MB by default (`INGEST_MAX_UPLOAD_BYTES`). Returns `413` when exceeded.

Document IDs: all `{doc_id}` path parameters are validated to prevent path traversal. Only lowercase alphanumeric characters, hyphens, and underscores are allowed.

## Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Ingest a file upload |
| `POST` | `/ingest/url` | Ingest from a URL |
| `POST` | `/ingest/batch` | Ingest multiple files |
| `POST` | `/ingest/stream` | Ingest with SSE progress streaming |
| `POST` | `/ingest/async` | Submit file for background ingestion (returns 202) |

### POST /ingest

Upload a file for ingestion.

- **Body:** `multipart/form-data` with `file` (required), `skip_enrichment` (bool, default: false), `profile` (string, default: "auto")
- **Returns:** `IngestResponse` with `doc_id`, `title`, `total_pages`, `total_chunks`, `l0_tokens`, `enriched`

### POST /ingest/url

Ingest a document from a URL.

- **Body:** JSON `{ "url": "https://...", "skip_enrichment": false }`
- **Returns:** `IngestResponse`

### POST /ingest/batch

Ingest multiple files at once.

- **Body:** `multipart/form-data` with multiple `files`, `skip_enrichment` (bool)
- **Returns:** `BatchIngestResponse` with per-file results

### POST /ingest/stream

Ingest with real-time progress via Server-Sent Events.

- **Body:** `multipart/form-data` with `file`, `skip_enrichment` (bool)
- **Returns:** `text/event-stream` with JSON progress events, ending with `{ "status": "complete", "doc_id": "..." }`

## Background Jobs

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest/async` | Submit file for background ingestion (returns 202) |
| `GET` | `/jobs/{job_id}` | Get job status and progress |
| `GET` | `/jobs` | List all ingestion jobs |

### POST /ingest/async

Submit a document for background ingestion. Returns immediately with a job ID.

- **Body:** `multipart/form-data` with `file` (required), `skip_enrichment` (bool, default: false)
- **Returns:** `202 Accepted` with `{ "job_id": "...", "status": "pending" }`

### GET /jobs/{job_id}

Poll for job status.

- **Returns:** `{ "job_id", "status", "doc_id", "error", "progress_stage", "progress_step", "progress_total", "created_at", "started_at", "finished_at" }`
- Status: `pending`, `running`, `complete`, `failed`

## Documents

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/documents` | List all ingested documents |
| `GET` | `/documents/{doc_id}` | Get document overview (L0 + metadata) |
| `DELETE` | `/documents/{doc_id}` | Delete a document and its indexes |
| `GET` | `/documents/{doc_id}/chunks` | Get full ChunkSet (L0-L3) |
| `GET` | `/documents/{doc_id}/structure` | Get document structure tree |
| `GET` | `/documents/{doc_id}/economics` | Get token economics (full vs. query cost) |
| `GET` | `/documents/{doc_id}/citations` | Get extracted citations |
| `GET` | `/documents/{doc_id}/knowledge-graph` | Get knowledge graph triples and entities |
| `GET` | `/documents/{doc_id}/versions` | List archived versions |
| `GET` | `/documents/{doc_id}/export?format=jsonl` | Export document (jsonl, parquet, llamaindex, langchain) |
| `POST` | `/documents/{doc_id}/enrich` | Re-enrich without re-parsing |
| `POST` | `/documents/{doc_id}/eval` | Evaluate retrieval quality |
| `POST` | `/documents/{doc_id}/search` | Search within a document |

### POST /documents/{doc_id}/eval

Evaluate retrieval quality using synthetic queries from enrichment.

- **Query params:** `k` (int, default: 5)
- **Returns:** `{ "doc_id", "total_queries", "k", "hit_rate", "mrr", "mean_precision_at_k", "mean_recall_at_k" }`

### POST /documents/{doc_id}/search

- **Body:** JSON `{ "query": "...", "n_results": 5 }`
- **Returns:** `SearchResponse` with ranked results including scores, match sources, content/summaries, page numbers, and timestamps (for audio/video sources)

### GET /documents/{doc_id}/knowledge-graph

Returns extracted entity-relationship triples (requires KG extraction to be enabled).

- **Returns:** `{ "doc_id", "total_triples", "total_entities", "triples": [...], "entities": [...] }`
- Entities are sorted by occurrence count

## Cross-Document Search

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/search` | Search across all documents |

### POST /search

- **Body:** JSON `{ "query": "...", "n_results": 10, "doc_ids": null }`
- **Returns:** `SearchResponse` with cross-document RRF fusion. Set `doc_ids` to limit search scope.

## Webhooks

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/webhooks/cv` | Receive CognitiveVault entry updates |

### POST /webhooks/cv

Receives `entry.updated` events from CognitiveVault. Requires `INGEST_WEBHOOK_SECRET` for HMAC-SHA256 signature verification. See [CognitiveVault Integration](cv-integration.md) for details.

## Health & Observability

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness check (fast, no deps) |
| `GET` | `/health/ready` | Readiness check (verifies all dependencies) |
| `GET` | `/metrics` | Prometheus metrics |

### GET /health

Fast liveness probe. Returns `{ "status": "ok", "documents_count": N }`.

### GET /health/ready

Deep readiness check. Verifies data directory is writable, disk space above threshold, embedding model loads, and LLM API is configured.

- **Returns:** `{ "status": "ready"|"degraded", "checks": { ... } }`
- Each check returns `{ "status": "ok"|"error"|"warning", ... }`

### GET /metrics

Prometheus-format metrics. Key metrics:
- `ingestible_ingest_duration_seconds` -- ingestion latency by stage
- `ingestible_active_ingestions` -- currently running ingestion jobs
- `ingestible_llm_calls_total` -- LLM API calls by provider and status
- `ingestible_search_duration_seconds` -- search query latency
