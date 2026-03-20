# REST API Reference

All endpoints are served by `ingest serve` (default: `http://localhost:8081`).

Authentication: when `INGEST_API_KEYS` is set, all requests require `Authorization: Bearer <key>`.

## Ingestion

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/ingest` | Ingest a file upload |
| `POST` | `/ingest/url` | Ingest from a URL |
| `POST` | `/ingest/batch` | Ingest multiple files |
| `POST` | `/ingest/stream` | Ingest with SSE progress streaming |

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
| `POST` | `/documents/{doc_id}/search` | Search within a document |

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

## Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
